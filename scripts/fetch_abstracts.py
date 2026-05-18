"""Fetch abstracts for papers with DOIs (e.g. ACM-published KDD/WWW).

Strategy:
  1. OpenAlex batch query (50 DOIs / request, fast).
  2. Fall back to Semantic Scholar for papers OpenAlex doesn't have indexed yet
     (throttled to ~1 req/sec since no API key).

Idempotent by default: papers that already have `a` populated are skipped.
After applying, sets `fields_present` to include "a" and the browser will start
showing the abstract toggle automatically on the next build_browser run.

Usage:
  python scripts/fetch_abstracts.py --conf www2026 --max 50    # preview run
  python scripts/fetch_abstracts.py --conf www2026             # full run
  python scripts/fetch_abstracts.py --conf kdd2026             # KDD too
  python scripts/fetch_abstracts.py --conf www2026 --no-ss     # OpenAlex only (fast)
  python scripts/fetch_abstracts.py --conf www2026 --overwrite # re-fetch
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENALEX_BATCH = 50
OPENALEX_BASE = "https://api.openalex.org/works"
SS_BASE = "https://api.semanticscholar.org/graph/v1/paper"
SS_THROTTLE_SEC = 1.5  # no-key polite delay
USER_AGENT = "conference-paper-list/1.0 (mailto:chunxiwang12@gmail.com)"


def reconstruct_abstract(inv: dict | None) -> str | None:
    """OpenAlex stores abstracts as {word: [positions]}. Reverse to text."""
    if not inv:
        return None
    pos_word: dict[int, str] = {}
    for word, positions in inv.items():
        for p in positions:
            pos_word[p] = word
    if not pos_word:
        return None
    return " ".join(pos_word[i] for i in sorted(pos_word.keys()))


def doi_from_url(url: str | None) -> str | None:
    if not url:
        return None
    marker = "doi.org/"
    idx = url.find(marker)
    if idx == -1:
        return None
    return url[idx + len(marker):].strip().rstrip("/")


def http_get_json(url: str, timeout: float = 20) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def openalex_batch(dois: list[str]) -> dict[str, str]:
    """Return {doi_lower: abstract_or_empty_string}. Empty string = indexed but
    no abstract in OpenAlex. Missing key = not indexed at all."""
    if not dois:
        return {}
    filter_val = "|".join(f"https://doi.org/{d}" for d in dois)
    url = (
        f"{OPENALEX_BASE}?"
        f"filter=doi:{urllib.parse.quote(filter_val, safe='|')}&"
        f"per-page={min(len(dois), 200)}&"
        "select=doi,abstract_inverted_index"
    )
    try:
        data = http_get_json(url)
    except Exception as e:
        print(f"  openalex batch error: {type(e).__name__}: {e}", file=sys.stderr)
        return {}
    out: dict[str, str] = {}
    for w in data.get("results", []):
        doi_raw = (w.get("doi") or "").replace("https://doi.org/", "")
        if not doi_raw:
            continue
        abstract = reconstruct_abstract(w.get("abstract_inverted_index")) or ""
        out[doi_raw.lower()] = abstract
    return out


def semantic_scholar_one(doi: str) -> str | None:
    url = f"{SS_BASE}/DOI:{urllib.parse.quote(doi, safe='')}?fields=abstract"
    try:
        data = http_get_json(url, timeout=15)
        return data.get("abstract")
    except urllib.error.HTTPError as e:
        if e.code in (404, 429):
            return None
        print(f"  ss {doi}: HTTP {e.code}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  ss {doi}: {type(e).__name__}", file=sys.stderr)
        return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--conf", required=True)
    p.add_argument("--max", type=int, help="Only process first N papers")
    p.add_argument("--overwrite", action="store_true",
                   help="Re-fetch papers that already have an abstract")
    p.add_argument("--no-ss", action="store_true",
                   help="Skip Semantic Scholar fallback (faster, less coverage)")
    p.add_argument("--save-every", type=int, default=200,
                   help="Save partial progress every N successful fetches")
    args = p.parse_args()

    conf_path = ROOT / "conferences" / f"{args.conf}.json"
    with conf_path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)

    papers = data["papers"]
    pool = papers[: args.max] if args.max else papers

    to_fetch: list[tuple[dict, str]] = []
    for paper in pool:
        if not args.overwrite and paper.get("a"):
            continue
        doi = doi_from_url(paper.get("u"))
        if doi:
            to_fetch.append((paper, doi.lower()))

    print(f"{args.conf}: pool={len(pool)}, will fetch={len(to_fetch)}")
    if not to_fetch:
        return

    # Phase 1: OpenAlex batch
    doi_to_abs: dict[str, str] = {}
    n_batches = (len(to_fetch) + OPENALEX_BATCH - 1) // OPENALEX_BATCH
    for i in range(0, len(to_fetch), OPENALEX_BATCH):
        batch_dois = [d for _, d in to_fetch[i:i + OPENALEX_BATCH]]
        batch_num = i // OPENALEX_BATCH + 1
        print(f"  openalex batch {batch_num}/{n_batches}: {len(batch_dois)} DOIs", flush=True)
        doi_to_abs.update(openalex_batch(batch_dois))
        time.sleep(0.15)

    with_abs_oa = sum(1 for _, d in to_fetch if doi_to_abs.get(d))
    indexed_oa = sum(1 for _, d in to_fetch if d in doi_to_abs)
    print(f"  openalex: {indexed_oa}/{len(to_fetch)} indexed, "
          f"{with_abs_oa} with abstract ({100 * with_abs_oa / len(to_fetch):.1f}%)")

    # Phase 2: Semantic Scholar fallback
    if not args.no_ss:
        ss_targets = [d for _, d in to_fetch if not doi_to_abs.get(d)]
        if ss_targets:
            print(f"  semantic-scholar fallback: {len(ss_targets)} DOIs "
                  f"(~{len(ss_targets) * SS_THROTTLE_SEC / 60:.1f} min)")
            success = 0
            for j, doi in enumerate(ss_targets):
                abs_text = semantic_scholar_one(doi)
                if abs_text:
                    doi_to_abs[doi] = abs_text
                    success += 1
                if (j + 1) % 25 == 0:
                    print(f"    ss {j + 1}/{len(ss_targets)}, recovered: {success}", flush=True)
                time.sleep(SS_THROTTLE_SEC)
            print(f"  semantic-scholar: recovered {success} extra abstracts")

    # Apply to papers
    applied = 0
    for paper, doi in to_fetch:
        abs_text = doi_to_abs.get(doi)
        if abs_text:
            paper["a"] = abs_text
            applied += 1

    if applied > 0:
        fields = set(data.get("fields_present") or [])
        fields.add("a")
        data["fields_present"] = sorted(fields)

    with conf_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    have_any = sum(1 for p in data["papers"] if p.get("a"))
    print(f"\napplied {applied}/{len(to_fetch)} new abstracts to {conf_path}")
    print(f"total papers with abstract now: {have_any}/{len(data['papers'])} "
          f"({100 * have_any / len(data['papers']):.1f}%)")


if __name__ == "__main__":
    main()
