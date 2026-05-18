"""Fetch authors + institutions for papers with DOIs from OpenAlex.

For each paper with a DOI, batch-queries OpenAlex /works selecting
`doi,authorships`. Replaces `au` with OpenAlex's authors (in author_position
order) and adds an `ins` list of deduped institution names. Each entry in
`au` is [display_name, inst_index_or_null] where inst_index points into
`ins` (0-based, the FIRST listed institution for that author).

Papers OpenAlex doesn't have are left untouched (existing `au` preserved,
no `ins`). Existing fields (`g`, `a`, `d`, `t`, etc.) are never modified.

Usage:
  python scripts/fetch_authors_inst.py --conf kdd2026 --max 50  # preview
  python scripts/fetch_authors_inst.py --conf kdd2026           # full
  python scripts/fetch_authors_inst.py --conf www2026
  python scripts/fetch_authors_inst.py --conf kdd2026 --overwrite  # re-fetch
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENALEX_BATCH = 50
OPENALEX_BASE = "https://api.openalex.org/works"
USER_AGENT = "conference-paper-list/1.0 (mailto:chunxiwang12@gmail.com)"
THROTTLE_SEC = 0.15


def doi_from_url(url: str | None) -> str | None:
    if not url:
        return None
    marker = "doi.org/"
    idx = url.find(marker)
    if idx == -1:
        return None
    return url[idx + len(marker):].strip().rstrip("/")


def http_get_json(url: str, timeout: float = 30) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


POSITION_ORDER = {"first": 0, "middle": 1, "last": 2}


def parse_authorships(authorships: list[dict]) -> tuple[list[list], list[str]] | None:
    """Given OpenAlex authorships, return (au_list, ins_list).

    au_list: [[display_name, inst_index_or_null], ...] in author_position order.
    ins_list: deduped institution display_names in order of first appearance.
    Returns None if authorships is missing/empty.
    """
    if not authorships:
        return None

    # Sort by author_position: first, middle, last. Within middle, preserve
    # original order from OpenAlex (stable sort).
    indexed = list(enumerate(authorships))
    indexed.sort(key=lambda kv: (POSITION_ORDER.get(kv[1].get("author_position") or "middle", 1), kv[0]))

    ins_list: list[str] = []
    ins_index: dict[str, int] = {}
    au_list: list[list] = []

    for _, a in indexed:
        author = a.get("author") or {}
        name = a.get("raw_author_name") or author.get("display_name")
        if not name:
            continue
        institutions = a.get("institutions") or []
        author_indices: list[int] = []
        for inst in institutions:
            inst_name = (inst or {}).get("display_name")
            if not inst_name:
                continue
            if inst_name not in ins_index:
                ins_index[inst_name] = len(ins_list)
                ins_list.append(inst_name)
            i = ins_index[inst_name]
            if i not in author_indices:
                author_indices.append(i)
        # Encoding: None / int (single) / list (multi). Single-int preserves
        # backwards compat with older JSON; list signals multi-affiliation.
        if not author_indices:
            aff_value: int | list[int] | None = None
        elif len(author_indices) == 1:
            aff_value = author_indices[0]
        else:
            aff_value = author_indices
        au_list.append([name, aff_value])

    if not au_list:
        return None
    return au_list, ins_list


def openalex_batch(dois: list[str]) -> dict[str, dict]:
    """Return {doi_lower: work_dict} for indexed papers. Missing = not indexed."""
    if not dois:
        return {}
    filter_val = "|".join(f"https://doi.org/{d}" for d in dois)
    url = (
        f"{OPENALEX_BASE}?"
        f"filter=doi:{urllib.parse.quote(filter_val, safe='|')}&"
        f"per-page={min(len(dois), 200)}&"
        "select=doi,authorships"
    )
    try:
        data = http_get_json(url)
    except Exception as e:
        print(f"  openalex batch error: {type(e).__name__}: {e}", file=sys.stderr)
        return {}
    out: dict[str, dict] = {}
    for w in data.get("results", []):
        doi_raw = (w.get("doi") or "").replace("https://doi.org/", "")
        if not doi_raw:
            continue
        out[doi_raw.lower()] = w
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--conf", required=True)
    p.add_argument("--max", type=int, help="Only process first N papers")
    p.add_argument("--overwrite", action="store_true",
                   help="Re-fetch papers that already have `ins`")
    args = p.parse_args()

    conf_path = ROOT / "conferences" / f"{args.conf}.json"
    with conf_path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)

    papers = data["papers"]
    pool = papers[: args.max] if args.max else papers

    to_fetch: list[tuple[dict, str]] = []
    for paper in pool:
        if not args.overwrite and paper.get("ins"):
            continue
        doi = doi_from_url(paper.get("u"))
        if doi:
            to_fetch.append((paper, doi.lower()))

    print(f"{args.conf}: pool={len(pool)}, will fetch={len(to_fetch)}")
    if not to_fetch:
        return

    # OpenAlex batch
    doi_to_work: dict[str, dict] = {}
    n_batches = (len(to_fetch) + OPENALEX_BATCH - 1) // OPENALEX_BATCH
    for i in range(0, len(to_fetch), OPENALEX_BATCH):
        batch_dois = [d for _, d in to_fetch[i:i + OPENALEX_BATCH]]
        batch_num = i // OPENALEX_BATCH + 1
        print(f"  openalex batch {batch_num}/{n_batches}: {len(batch_dois)} DOIs", flush=True)
        doi_to_work.update(openalex_batch(batch_dois))
        time.sleep(THROTTLE_SEC)

    indexed_oa = sum(1 for _, d in to_fetch if d in doi_to_work)
    print(f"  openalex: {indexed_oa}/{len(to_fetch)} indexed "
          f"({100 * indexed_oa / len(to_fetch):.1f}%)")

    # Apply to papers
    applied = 0
    no_authorships = 0
    missing_dois: list[str] = []
    for paper, doi in to_fetch:
        work = doi_to_work.get(doi)
        if not work:
            missing_dois.append(doi)
            continue
        parsed = parse_authorships(work.get("authorships") or [])
        if not parsed:
            no_authorships += 1
            continue
        au_list, ins_list = parsed
        paper["au"] = au_list
        if ins_list:
            paper["ins"] = ins_list
        elif "ins" in paper:
            # cleanup if overwrite mode produces no institutions
            del paper["ins"]
        applied += 1

    # Update fields_present if at least one paper got institutional data
    any_ins = any(p.get("ins") for p in data["papers"])
    if any_ins:
        fields = set(data.get("fields_present") or [])
        fields.add("ins")
        data["fields_present"] = sorted(fields)

    with conf_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    # Summary stats
    papers_with_ins = sum(1 for p in data["papers"] if p.get("ins"))
    all_institutions: set[str] = set()
    for p in data["papers"]:
        for inst in (p.get("ins") or []):
            all_institutions.add(inst)
    avg_ins_per_paper = (
        sum(len(p.get("ins") or []) for p in data["papers"]) / max(papers_with_ins, 1)
    )

    print(f"\napplied authors+institutions to {applied}/{len(to_fetch)} papers")
    print(f"  no-authorships in OpenAlex: {no_authorships}")
    print(f"  missing from OpenAlex: {len(missing_dois)}")
    if missing_dois[:10]:
        print(f"  sample missing DOIs: {missing_dois[:10]}")
    print(f"saved -> {conf_path}")
    print(f"\ncoverage: {papers_with_ins}/{len(data['papers'])} "
          f"({100 * papers_with_ins / len(data['papers']):.1f}%) papers have `ins`")
    print(f"distinct institutions: {len(all_institutions)}")
    print(f"avg institutions per paper (with ins): {avg_ins_per_paper:.2f}")


if __name__ == "__main__":
    main()
