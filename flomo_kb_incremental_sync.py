#!/usr/bin/env python3
"""Incremental sync: Notion → local flomo knowledge base.

Fetches recent Notion pages and merges new entries into flomo_kb:
  - parsed/notes_md/{YYYY}/{MM}/*.md
  - parsed/indexes/flomo_notes.json
  - parsed/indexes/tag_index.json
  - parsed/indexes/month_counts.json

Deduplicates by matching (date, text_preview[:80]).
Assigns sequential IDs continuing from the existing max.

Usage:
    python3 flomo_kb_incremental_sync.py [--hours 48] [--dry-run] [--limit 100]

Environment:
    NOTION_API_KEY          required
    NOTION_DATA_SOURCE_ID   or NOTION_DATABASE_ID (one required)
    NOTION_VERSION          optional (default: 2026-03-11)

Exit codes:
    0  success (or no new items)
    1  error
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---- paths ----
FLOMO_KB = Path(
    os.getenv("FLOMO_KB_DIR", str(Path(__file__).parent / "flomo_kb"))
)
NOTES_DIR = FLOMO_KB / "parsed" / "notes_md"
INDEX_DIR = FLOMO_KB / "parsed" / "indexes"
INDEX_FILE = INDEX_DIR / "flomo_notes.json"
TAG_INDEX_FILE = INDEX_DIR / "tag_index.json"
MONTH_COUNTS_FILE = INDEX_DIR / "month_counts.json"
STATE_FILE = INDEX_DIR / ".sync_state.json"

# ---- Notion API (reused from flomo_sync_to_inbox.py) ----
NOTION_API_KEY = os.getenv("NOTION_API_KEY", "").strip()
NOTION_VERSION = os.getenv("NOTION_VERSION", "2026-03-11").strip()
NOTION_DATA_SOURCE_ID = os.getenv("NOTION_DATA_SOURCE_ID", "").strip()
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "").strip()

import urllib.request
import urllib.error


def notion_request(method: str, path: str, payload: dict | None = None) -> dict:
    if not NOTION_API_KEY:
        raise RuntimeError("missing NOTION_API_KEY")
    url = "https://api.notion.com/v1" + path
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"{method} {path}: HTTP {e.code} {body[:400]}")


def discover_data_source_id() -> str:
    if NOTION_DATA_SOURCE_ID:
        return NOTION_DATA_SOURCE_ID
    if not NOTION_DATABASE_ID:
        raise RuntimeError("set NOTION_DATA_SOURCE_ID or NOTION_DATABASE_ID")
    data = notion_request("GET", f"/databases/{NOTION_DATABASE_ID}")
    ds = data.get("data_sources") or []
    if not ds:
        raise RuntimeError(f"database {NOTION_DATABASE_ID} has no data_sources")
    return ds[0]["id"]


def query_recent_pages(ds_id: str, hours: int, limit: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    payload = {
        "page_size": min(limit, 100),
        "filter": {"timestamp": "last_edited_time",
                   "last_edited_time": {"on_or_after": cutoff}},
        "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
    }
    pages: list[dict] = []
    cursor = None
    while True:
        body = dict(payload)
        if cursor:
            body["start_cursor"] = cursor
        data = notion_request("POST", f"/data_sources/{ds_id}/query", body)
        pages.extend(data.get("results", []))
        if len(pages) >= limit or not data.get("has_more"):
            return pages[:limit]
        cursor = data.get("next_cursor")


# ---- text extraction ----

def plain_rich_text(arr) -> str:
    return "".join((x.get("plain_text") or "") for x in (arr or [])).strip()


def block_to_text(block: dict) -> str:
    t = block.get("type", "")
    obj = block.get(t, {})
    if t in {"paragraph", "heading_1", "heading_2", "heading_3",
             "quote", "callout", "toggle"}:
        return plain_rich_text(obj.get("rich_text"))
    if t in {"bulleted_list_item", "numbered_list_item", "to_do"}:
        txt = plain_rich_text(obj.get("rich_text"))
        return f"- {txt}" if txt else ""
    if t == "code":
        txt = plain_rich_text(obj.get("rich_text"))
        lang = obj.get("language", "")
        return f"```{lang}\n{txt}\n```" if txt else ""
    if t in {"bookmark", "link_preview"}:
        return obj.get("url", "") or ""
    if t == "divider":
        return "---"
    return ""


def fetch_page_text(page_id: str, max_blocks: int = 200) -> str:
    blocks = notion_request("GET", f"/blocks/{page_id}/children").get("results", [])
    lines = []
    count = 0
    for b in blocks:
        if count >= max_blocks:
            break
        txt = block_to_text(b)
        if txt:
            lines.append(txt)
            count += 1
        if b.get("has_children"):
            children = notion_request("GET", f"/blocks/{b['id']}/children").get("results", [])
            for child in children:
                if count >= max_blocks:
                    break
                txt2 = block_to_text(child)
                if txt2:
                    lines.append(txt2)
                    count += 1
    text = "\n".join(lines)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_tags(page: dict) -> list[str]:
    """Extract tags from Notion page properties."""
    props = page.get("properties", {})
    tags = []
    for name, v in props.items():
        t = v.get("type")
        if t == "multi_select":
            for x in v.get("multi_select", []):
                tag = x.get("name", "").strip()
                if tag:
                    tags.append(tag)
        elif t == "select" and v.get("select"):
            tag = v["select"].get("name", "").strip()
            if tag:
                tags.append(tag)
    return tags


def page_created_time(page: dict) -> str:
    """Get created_time from page, format as YYYY-MM-DD HH:MM:SS in local tz."""
    raw = page.get("created_time", "")
    if not raw:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Parse ISO format, convert to local
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    # Convert to Asia/Shanghai (UTC+8)
    from zoneinfo import ZoneInfo
    dt_local = dt.astimezone(ZoneInfo("Asia/Shanghai"))
    return dt_local.strftime("%Y-%m-%d %H:%M:%S")


def page_title(page: dict) -> str:
    props = page.get("properties", {})
    for _, v in props.items():
        if v.get("type") == "title":
            txt = plain_rich_text(v.get("title"))
            if txt:
                return txt
    return ""


# ---- index management ----

def load_index() -> list[dict]:
    if INDEX_FILE.exists():
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_index(entries: list[dict]):
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def rebuild_tag_index(entries: list[dict]):
    tag_map: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        for tag in e.get("tags", []):
            tag_map[tag].append(e["id"])
    with open(TAG_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(tag_map), f, ensure_ascii=False, indent=2)


def rebuild_month_counts(entries: list[dict]):
    counts: dict[str, int] = defaultdict(int)
    for e in entries:
        key = f"{e['year']}-{e['month']:02d}"
        counts[key] += 1
    # Sort by key
    sorted_counts = dict(sorted(counts.items()))
    with open(MONTH_COUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted_counts, f, ensure_ascii=False, indent=2)


def next_id_num(entries: list[dict]) -> int:
    if not entries:
        return 1
    max_num = 0
    for e in entries:
        try:
            num = int(e["id"].split("-")[1])
            if num > max_num:
                max_num = num
        except (IndexError, ValueError):
            pass
    return max_num + 1


def build_dedup_set(entries: list[dict]) -> set[str]:
    """Build dedup keys from existing entries: (date, first 80 chars of preview)."""
    keys = set()
    for e in entries:
        preview = (e.get("text_preview") or "")[:80].strip()
        keys.add(f"{e['date']}|{preview}")
    return keys


# ---- note file generation ----

def write_note_file(entry: dict, text: str) -> Path:
    """Write a markdown note file matching flomo_kb format."""
    created = entry["created"]  # "YYYY-MM-DD HH:MM:SS"
    dt = datetime.strptime(created, "%Y-%m-%d %H:%M:%S")
    id_num = int(entry["id"].split("-")[1])

    # Directory: parsed/notes_md/YYYY/MM/
    note_dir = NOTES_DIR / f"{dt.year}" / f"{dt.month:02d}"
    note_dir.mkdir(parents=True, exist_ok=True)

    # Filename: YYYY-MM-DD_HHMMSS_XXXX.md
    fname = f"{dt.strftime('%Y-%m-%d_%H%M%S')}_{id_num:04d}.md"
    fpath = note_dir / fname

    # Build frontmatter
    tags_yaml = ""
    if entry.get("tags"):
        tag_lines = "\n".join(f"  - {t}" for t in entry["tags"])
        tags_yaml = f"tags:\n{tag_lines}"
    else:
        tags_yaml = "tags: []"

    content = f"""---
id: {entry['id']}
created: {created}
source: notion_incremental_sync
{tags_yaml}
has_audio: false
has_image: false
audio_count: 0
image_count: 0
---

## 笔记

{text}
"""

    fpath.write_text(content.strip() + "\n", encoding="utf-8")

    # Return relative path for index
    return Path("parsed/notes_md") / f"{dt.year}" / f"{dt.month:02d}" / fname


# ---- sync state ----

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---- main ----

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Incremental sync Notion → flomo_kb")
    parser.add_argument("--hours", type=int, default=48,
                        help="Look back window in hours (default: 48)")
    parser.add_argument("--limit", type=int, default=100,
                        help="Max pages to fetch from Notion (default: 100)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be added without writing")
    args = parser.parse_args()

    print(f"[flomo-kb-sync] start: hours={args.hours}, limit={args.limit}", flush=True)

    # Load existing index
    entries = load_index()
    dedup_keys = build_dedup_set(entries)
    id_counter = next_id_num(entries)
    print(f"[flomo-kb-sync] existing: {len(entries)} entries, next id: flomo-{id_counter:05d}", flush=True)

    # Fetch from Notion
    try:
        ds_id = discover_data_source_id()
        pages = query_recent_pages(ds_id, args.hours, args.limit)
    except Exception as exc:
        print(f"[flomo-kb-sync] Notion fetch failed: {exc}", file=sys.stderr, flush=True)
        return 1

    print(f"[flomo-kb-sync] fetched {len(pages)} pages from Notion", flush=True)

    # Process each page
    new_entries: list[dict] = []
    skipped = 0

    for page in pages:
        created_str = page_created_time(page)
        date_str = created_str[:10]  # YYYY-MM-DD

        # Fetch full text
        try:
            text = fetch_page_text(page["id"])
        except Exception as exc:
            print(f"[flomo-kb-sync] skip page {page['id']}: {exc}", flush=True)
            skipped += 1
            continue

        if not text or len(text) < 5:
            skipped += 1
            continue

        # Dedup check
        preview = text[:200].strip()
        dedup_key = f"{date_str}|{preview[:80].strip()}"
        if dedup_key in dedup_keys:
            skipped += 1
            continue

        # Extract metadata
        tags = extract_tags(page)
        dt = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S")

        entry = {
            "id": f"flomo-{id_counter:05d}",
            "created": created_str,
            "date": date_str,
            "year": dt.year,
            "month": dt.month,
            "day": dt.day,
            "tags": tags,
            "has_audio": False,
            "has_image": False,
            "text_preview": preview,
            "path": "",  # filled after write
            "audio_refs": [],
            "image_refs": [],
        }

        if args.dry_run:
            print(f"  [dry-run] would add {entry['id']}: {date_str} | {preview[:60]}...", flush=True)
        else:
            rel_path = write_note_file(entry, text)
            entry["path"] = str(rel_path)

        new_entries.append(entry)
        dedup_keys.add(dedup_key)
        id_counter += 1

    print(f"[flomo-kb-sync] new: {len(new_entries)}, skipped: {skipped}", flush=True)

    if not new_entries:
        print("[flomo-kb-sync] nothing to add", flush=True)
        return 0

    if args.dry_run:
        print("[flomo-kb-sync] dry-run complete, no files written", flush=True)
        return 0

    # Merge and save
    all_entries = entries + new_entries
    # Sort by created descending (newest first, matching original order)
    all_entries.sort(key=lambda e: e["created"], reverse=True)

    save_index(all_entries)
    rebuild_tag_index(all_entries)
    rebuild_month_counts(all_entries)

    # Save sync state
    save_state({
        "last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_sync_hours": args.hours,
        "entries_before": len(entries),
        "entries_after": len(all_entries),
        "added": len(new_entries),
        "skipped": skipped,
    })

    print(f"[flomo-kb-sync] done: {len(entries)} → {len(all_entries)} entries", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
