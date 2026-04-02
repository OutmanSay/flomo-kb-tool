#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOTION_API_KEY = os.getenv("NOTION_API_KEY", "").strip()
NOTION_VERSION = os.getenv("NOTION_VERSION", "2026-03-11").strip()
NOTION_DATA_SOURCE_ID = os.getenv("NOTION_DATA_SOURCE_ID", "").strip()
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "").strip()

OUT_DIR = Path(os.getenv("FLOMO_INBOX_DIR", str(Path(__file__).parent / "inbox_capture")))
SYNC_HOURS = int(os.getenv("FLOMO_SYNC_HOURS", "30"))
PAGE_SIZE = int(os.getenv("FLOMO_SYNC_PAGE_SIZE", "30"))
MAX_ITEMS = int(os.getenv("FLOMO_SYNC_MAX_ITEMS", "50"))

def notion_request(method: str, path: str, payload: dict | None = None) -> dict:
    if not NOTION_API_KEY:
        raise RuntimeError("missing NOTION_API_KEY")
    url = "https://api.notion.com/v1" + path
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
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
        raise RuntimeError(f"{method} {path} failed: HTTP {e.code} {body[:400]}")
    except Exception as e:
        raise RuntimeError(f"{method} {path} failed: {e}")

def discover_data_source_id() -> str:
    if NOTION_DATA_SOURCE_ID:
        return NOTION_DATA_SOURCE_ID

    if not NOTION_DATABASE_ID:
        raise RuntimeError("set NOTION_DATA_SOURCE_ID or NOTION_DATABASE_ID")

    data = notion_request("GET", f"/databases/{NOTION_DATABASE_ID}")
    ds = data.get("data_sources") or []
    if not ds:
        raise RuntimeError(
            f"database {NOTION_DATABASE_ID} has no data_sources — "
            "set NOTION_DATA_SOURCE_ID manually in .env.local"
        )
    dsid = ds[0]["id"]
    print(f"[flomo] discovered data_source_id: {dsid} ({ds[0].get('name', '')})", flush=True)
    return dsid


def query_recent_pages(data_source_id: str) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=SYNC_HOURS)).isoformat()
    payload = {
        "page_size": PAGE_SIZE,
        "filter": {
            "timestamp": "last_edited_time",
            "last_edited_time": {
                "on_or_after": cutoff
            }
        },
        "sorts": [
            {"timestamp": "last_edited_time", "direction": "descending"}
        ]
    }

    pages = []
    cursor = None

    while True:
        body = dict(payload)
        if cursor:
            body["start_cursor"] = cursor
        data = notion_request("POST", f"/data_sources/{data_source_id}/query", body)
        batch = data.get("results", [])
        print(f"[flomo] page batch: {len(batch)} result(s)", flush=True)
        pages.extend(batch)
        if len(pages) >= MAX_ITEMS:
            return pages[:MAX_ITEMS]
        if not data.get("has_more"):
            return pages[:MAX_ITEMS]
        cursor = data.get("next_cursor")

def plain_rich_text(arr) -> str:
    out = []
    for x in arr or []:
        t = x.get("plain_text") or ""
        if t:
            out.append(t)
    return "".join(out).strip()

def page_title(page: dict) -> str:
    props = page.get("properties", {})
    # auto-detect title property
    for _, v in props.items():
        if v.get("type") == "title":
            txt = plain_rich_text(v.get("title"))
            if txt:
                return txt
    return page.get("id", "Untitled")

def extract_property_tags(page: dict) -> list[str]:
    props = page.get("properties", {})
    tags = []

    for name, v in props.items():
        t = v.get("type")
        if t == "select" and v.get("select"):
            tags.append(f"{name}:{v['select'].get('name','')}")
        elif t == "multi_select":
            vals = [x.get("name","") for x in v.get("multi_select", []) if x.get("name")]
            if vals:
                tags.append(f"{name}:{','.join(vals)}")
        elif t == "status" and v.get("status"):
            tags.append(f"{name}:{v['status'].get('name','')}")
    return tags

def normalize_text(s: str) -> str:
    s = s.replace("\xa0", " ")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def block_to_text(block: dict) -> str:
    t = block.get("type", "")
    obj = block.get(t, {})
    if t in {"paragraph", "heading_1", "heading_2", "heading_3", "quote", "callout", "toggle"}:
        txt = plain_rich_text(obj.get("rich_text"))
        return txt
    if t in {"bulleted_list_item", "numbered_list_item", "to_do"}:
        txt = plain_rich_text(obj.get("rich_text"))
        if txt:
            return f"- {txt}"
        return ""
    if t == "code":
        txt = plain_rich_text(obj.get("rich_text"))
        lang = obj.get("language", "")
        return f"```{lang}\n{txt}\n```" if txt else ""
    if t == "bookmark":
        return obj.get("url", "") or ""
    if t == "link_preview":
        return obj.get("url", "") or ""
    if t == "child_page":
        return obj.get("title", "") or ""
    if t == "divider":
        return "---"
    return ""

def fetch_block_children(block_id: str) -> list[dict]:
    items = []
    cursor = None
    while True:
        path = f"/blocks/{block_id}/children"
        if cursor:
            path += f"?start_cursor={cursor}"
        data = notion_request("GET", path)
        items.extend(data.get("results", []))
        if not data.get("has_more"):
            return items
        cursor = data.get("next_cursor")

def fetch_page_text(page_id: str, max_blocks: int = 200) -> str:
    blocks = fetch_block_children(page_id)
    lines = []
    count = 0

    for b in blocks:
        if count >= max_blocks:
            break
        text = block_to_text(b)
        if text:
            lines.append(text)
            count += 1
        if b.get("has_children"):
            for child in fetch_block_children(b["id"]):
                if count >= max_blocks:
                    break
                text2 = block_to_text(child)
                if text2:
                    lines.append(text2)
                    count += 1

    return normalize_text("\n".join(lines))

def render_note(page: dict, body: str) -> str:
    title = page_title(page)
    page_id = page.get("id", "")
    url = page.get("url", "")
    edited = page.get("last_edited_time", "")
    created = page.get("created_time", "")
    tags = extract_property_tags(page)

    meta = [
        "---",
        "source: notion-flomo",
        f"page_id: {page_id}",
        f"url: {url}",
        f"created_time: {created}",
        f"last_edited_time: {edited}",
        f"tags: [{'; '.join(tags)}]",
        "---",
        "",
        f"# {title}",
        "",
    ]
    if body:
        meta.append(body)
    # 若无块内容，标题本身即是 flomo 笔记内容，无需额外占位符
    meta.append("")
    return "\n".join(meta)

def already_synced_today() -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    return any(f.name.startswith(today) and "Flomo" in f.name and f.name.endswith(".md") for f in OUT_DIR.iterdir() if f.is_file())


def _safe_filename(title: str, max_len: int = 60) -> str:
    """将标题转为安全文件名片段。"""
    s = re.sub(r'[/\\:*?"<>|\n\r]', '', title).strip()
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    return s if s else "Flomo笔记"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if already_synced_today():
        print(f"[flomo] already synced today, skipping")
        return 0

    dsid = discover_data_source_id()
    pages = query_recent_pages(dsid)

    if not pages:
        print("no recent notion pages")
        return 0

    ts = datetime.now().strftime("%Y-%m-%d %H_%M")
    written = 0
    for i, page in enumerate(pages, 1):
        title = page_title(page)
        print(f"[{i}/{len(pages)}] {title}", flush=True)
        body = fetch_page_text(page["id"])
        content = render_note(page, body)
        safe_title = _safe_filename(title)
        out_path = OUT_DIR / f"{ts} Flomo-{i:02d} {safe_title}.md"
        out_path.write_text(content.strip() + "\n", encoding="utf-8")
        print(f"  → {out_path.name}")
        written += 1

    print(f"[flomo] wrote {written} file(s)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
