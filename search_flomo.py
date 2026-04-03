#!/usr/bin/env python3
import argparse, json
from pathlib import Path

def main():
    p = argparse.ArgumentParser(description="Search local flomo index")
    p.add_argument("--q", default="", help="keyword query")
    p.add_argument("--tag", action="append", default=[], help="tag filter, can repeat")
    p.add_argument("--from-date", dest="from_date", default="", help="YYYY-MM-DD")
    p.add_argument("--to-date", dest="to_date", default="", help="YYYY-MM-DD")
    p.add_argument("--limit", type=int, default=20)
    args = p.parse_args()

    # When running from the openclaw skill dir, resolve to the canonical flomo_kb root
    _script_root = Path(__file__).resolve().parents[1]
    _candidate = _script_root / "parsed" / "indexes" / "flomo_notes.json"
    if _candidate.exists():
        idx_path = _candidate
    else:
        idx_path = Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "Obsidian Vault" / "00-OS" / "runtime" / "flomo_kb" / "parsed" / "indexes" / "flomo_notes.json"
    data = json.loads(idx_path.read_text(encoding="utf-8"))

    q = args.q.lower().strip()
    tags = [t.strip() for t in args.tag if t.strip()]
    out = []
    for item in data:
        if args.from_date and item["date"] < args.from_date:
            continue
        if args.to_date and item["date"] > args.to_date:
            continue
        if tags and not all(t in item.get("tags", []) for t in tags):
            continue
        hay = (item.get("text_preview","") + " " + " ".join(item.get("tags", []))).lower()
        if q and q not in hay:
            continue
        out.append(item)

    out.sort(key=lambda x: x["created"], reverse=True)
    for item in out[:args.limit]:
        print(f'[{item["created"]}] {item["id"]}')
        print(f'  tags: {", ".join(item.get("tags", [])) or "-"}')
        print(f'  path: {item["path"]}')
        print(f'  text: {item.get("text_preview","")}')
        print()

    print(f"matched: {len(out)}")

if __name__ == "__main__":
    main()
