"""Render a self-contained HTML browser for one conference.

Reads templates/browser.html.tmpl, substitutes {{CONF_JSON}} and {{INDEX_JSON}}
with embedded JSON, writes browsers/<conf>.html.

Usage:
  python scripts/build_browser.py --conf icml2026
  python scripts/build_browser.py --all          # build every conference in index
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _safe_for_script(s: str) -> str:
    """Escape so that the JSON can safely sit inside <script>...</script>.

    JSON characters are already valid JS literals, but `</script>` substrings
    or HTML comment openers would break out of the script tag.
    """
    return (s
            .replace("</", "<\\/")
            .replace("<!--", "<\\!--"))


def _load_favorites_inline() -> str:
    """Snapshot of favorites.js, inlined into each browser as a fallback.

    Lets file:// users still bootstrap their localStorage even when the
    browser blocks the external <script src="../favorites.js">. The external
    tag still runs and overrides this when it loads successfully.
    """
    fav_path = ROOT / "favorites.js"
    if not fav_path.exists():
        return "window.FAVORITES_SYNCED = window.FAVORITES_SYNCED || {version:1};"
    with fav_path.open("r", encoding="utf-8") as f:
        return f.read()


def _render(template: str, conf_json: str, index_json: str, out_path: Path) -> Path:
    fav_inline = _load_favorites_inline()
    html = (template
            .replace("{{CONF_JSON}}", _safe_for_script(conf_json))
            .replace("{{INDEX_JSON}}", _safe_for_script(index_json))
            .replace("{{FAVORITES_INLINE}}", _safe_for_script(fav_inline)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write(html)
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"wrote {out_path} ({size_mb:.1f} MB)")
    return out_path


def render_one(conf_id: str, index_json: str) -> Path:
    src = ROOT / "conferences" / f"{conf_id}.json"
    tmpl = ROOT / "templates" / "browser.html.tmpl"
    out = ROOT / "browsers" / f"{conf_id}.html"

    with tmpl.open("r", encoding="utf-8") as f:
        template = f.read()
    with src.open("r", encoding="utf-8-sig") as f:
        conf_data = f.read()

    # Re-serialize to compact JSON to drop whitespace and ensure no BOM.
    conf_json = json.dumps(json.loads(conf_data), ensure_ascii=False, separators=(",", ":"))
    return _render(template, conf_json, index_json, out)


# Map venue → track-* CSS class. Add new venues here as more are imported.
# The class controls the per-card badge color in the merged view.
VENUE_BADGE_CLASS = {
    "icml": "track-amber",
    "kdd": "track-blue",
    "www": "track-purple",
    "cvpr": "track-red",
    "neurips": "track-red",
    "iclr": "track-neutral",
    "cikm": "track-neutral",
}


def render_favorites(index: dict, index_json: str) -> Path:
    """Render browsers/favorites.html — cross-conference unified view.

    All conferences listed in index.json are merged into a single virtual
    conference. Each paper carries `_conf` = its source conf id so the
    runtime knows which favorites bucket to read.

    The wrapper sets `is_favorites_view: true`, which makes the browser
    force-enable the favorites-only filter (and hide its toggle).
    """
    tmpl = ROOT / "templates" / "browser.html.tmpl"
    out = ROOT / "browsers" / "favorites.html"

    with tmpl.open("r", encoding="utf-8") as f:
        template = f.read()

    confs = index.get("conferences", [])
    papers: list = []
    tabs: list = []
    fields_present: set[str] = {"_conf", "i", "t", "u"}

    for entry in confs:
        cid = entry["id"]
        cpath = ROOT / "conferences" / f"{cid}.json"
        if not cpath.exists():
            print(f"  skipping {cid}: {cpath} not found")
            continue
        with cpath.open("r", encoding="utf-8-sig") as f:
            cdata = json.load(f)
        for p in cdata.get("papers", []):
            p2 = dict(p)
            p2["_conf"] = cid
            papers.append(p2)
        for fkey in cdata.get("fields_present", []):
            fields_present.add(fkey)
        venue_key = (entry.get("venue") or "").lower()
        tabs.append({
            "key": cid,
            "label": entry["name"],
            "badge_class": VENUE_BADGE_CLASS.get(venue_key, "track-neutral"),
            "badge_text": entry.get("venue") or entry["name"],
        })

    merged = {
        "id": "_favorites",
        "name": "★ Favorites",
        "venue": "",
        "year": None,
        "source": "merged",
        "is_favorites_view": True,
        "fields_present": sorted(fields_present),
        "topic_field": None,
        "keyword_field": "g",
        "links": [
            {"label": "Virtual", "field": "v", "url_template": "https://icml.cc{v}"},
            {"label": "Page", "field": "u", "url_template": "{u}"},
            {"label": "ACM", "field": "acm", "url_template": "{acm}"},
            {"label": "DBLP", "field": "dblp", "url_template": "{dblp}"},
        ],
        "designations": {
            "field": "_conf",
            "tabs": tabs,
        },
        "papers": papers,
    }
    conf_json = json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
    out_path = _render(template, conf_json, index_json, out)
    print(f"  merged {len(papers)} papers from {len(tabs)} conferences")
    return out_path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--conf", help="Conference id (e.g. icml2026). Omit with --all.")
    p.add_argument("--all", action="store_true", help="Build every conference listed in index.json (plus the merged favorites view)")
    p.add_argument("--favorites", action="store_true", help="Only build the merged favorites view")
    args = p.parse_args()

    idx_path = ROOT / "conferences" / "index.json"
    if idx_path.exists():
        with idx_path.open("r", encoding="utf-8-sig") as f:
            index_json = f.read()
    else:
        index_json = json.dumps({"conferences": []})

    # Re-serialize compactly.
    index_compact = json.dumps(json.loads(index_json), ensure_ascii=False, separators=(",", ":"))
    idx_parsed = json.loads(index_compact)

    if args.all:
        for entry in idx_parsed.get("conferences", []):
            render_one(entry["id"], index_compact)
        render_favorites(idx_parsed, index_compact)
    elif args.favorites:
        render_favorites(idx_parsed, index_compact)
    elif args.conf:
        render_one(args.conf, index_compact)
    else:
        p.error("either --conf <id>, --favorites, or --all is required")


if __name__ == "__main__":
    main()
