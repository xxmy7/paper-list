"""Scan conferences/*.json and emit conferences/index.json.

The index is read by the browser HTML to populate the conference switcher.

Usage: python scripts/build_index.py
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    confs_dir = ROOT / "conferences"
    out = confs_dir / "index.json"

    entries = []
    for path in sorted(confs_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        # Skip auxiliary dicts (e.g. <conf>_tags.json from the LLM tagger).
        # Real conference JSONs always have a top-level "papers" array.
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "papers" not in data:
            continue
        entries.append({
            "id": data.get("id"),
            "name": data.get("name"),
            "venue": data.get("venue"),
            "year": data.get("year"),
            "source": data.get("source"),
            "paper_count": len(data.get("papers") or []),
            "data_path": f"conferences/{path.name}",
            "browser_path": f"browsers/{data.get('id')}.html",
        })

    entries.sort(key=lambda e: (-(e.get("year") or 0), (e.get("venue") or "")))

    with out.open("w", encoding="utf-8") as f:
        json.dump({"conferences": entries}, f, ensure_ascii=False, indent=2)
    print(f"wrote {out} ({len(entries)} conferences)")
    for e in entries:
        print(f"  {e['id']:<16} {e['paper_count']:>5}  {e['source']}")


if __name__ == "__main__":
    main()
