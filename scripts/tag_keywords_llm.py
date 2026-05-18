"""Tag papers in a conference JSON using Claude (LLM-based).

Reads tag names + descriptions from shared/keyword_patterns.json (same
catalogue as the regex tagger) and asks Claude to assign each paper the
most appropriate tags from that fixed list, given its title and abstract.

Defaults to claude-opus-4-7 with adaptive thinking, low effort, structured
JSON output (enum-constrained), and prompt caching on the system prompt so
the catalogue is paid for only on the first request.

Idempotent: papers with `g_source == "llm"` are skipped unless --overwrite.
Papers with `g_source == "openreview"` (ICML's source-of-truth) are always
left alone unless --overwrite.

Usage:
  export ANTHROPIC_API_KEY=sk-ant-...
  python scripts/tag_keywords_llm.py --conf kdd2026 --dry-run        # 3-paper preview
  python scripts/tag_keywords_llm.py --conf kdd2026                  # full run
  python scripts/tag_keywords_llm.py --conf www2026 --max 50         # try 50 papers first
  python scripts/tag_keywords_llm.py --conf kdd2026 --overwrite      # re-tag everything
  python scripts/tag_keywords_llm.py --conf kdd2026 --model claude-haiku-4-5  # cheap mode

Cost (rough, for ~1200 papers with prompt caching, no thinking-heavy responses):
  claude-opus-4-7:   ~$2-3      (smartest; takes ~5 min @ concurrency 10)
  claude-haiku-4-5:  ~$0.50     (fast & cheap; usually plenty for classification)
"""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_CONCURRENCY = 10
MAX_ABSTRACT_CHARS = 2000  # keep input tokens predictable


def load_tag_catalogue():
    with (ROOT / "shared" / "keyword_patterns.json").open("r", encoding="utf-8-sig") as f:
        cfg = json.load(f)
    names = [t["name"] for t in cfg["tags"]]
    fallback = cfg.get("fallback", "Other")
    if fallback not in names:
        names.append(fallback)
    catalogue_text = "\n".join(f"- {t['name']}: {t.get('description', '')}" for t in cfg["tags"])
    catalogue_text += f"\n- {fallback}: Use only when no other tag is applicable."
    return names, catalogue_text, fallback


def build_system_prompt(catalogue_text: str) -> str:
    return f"""You are categorising academic conference papers by topic. Given a paper's title and (when available) abstract, return the topic tags that genuinely apply.

The fixed tag catalogue is:

{catalogue_text}

Rules:
- Return only tag names exactly as written above (case-sensitive).
- A typical paper gets 1-3 tags; assign more only when the paper truly spans them.
- Apply broad / methodological tags (e.g. LLM, Graph/GNN, Diffusion/Generation) when the paper's *primary method* fits, not when the method is merely mentioned.
- Apply domain tags (Healthcare/Bio, Spatiotemporal/Urban, etc.) when the paper's *primary domain* fits.
- Do NOT invent tags. Do NOT include explanations.
- Return "Other" only when no listed tag genuinely applies."""


def build_schema(tag_names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "tags": {
                "type": "array",
                "items": {"type": "string", "enum": tag_names},
                "minItems": 1,
            }
        },
        "required": ["tags"],
        "additionalProperties": False,
    }


def build_user_content(paper: dict) -> str:
    title = paper.get("t") or ""
    abstract = paper.get("a") or ""
    if abstract and len(abstract) > MAX_ABSTRACT_CHARS:
        abstract = abstract[:MAX_ABSTRACT_CHARS] + " [...]"
    parts = [f"Title: {title}"]
    if abstract:
        parts.append(f"Abstract: {abstract}")
    return "\n\n".join(parts)


async def tag_one(client, sem, model: str, system_prompt: str, schema: dict, paper: dict):
    """Tag a single paper. Returns list[str] of tag names, or None on failure."""
    async with sem:
        for attempt in range(4):
            try:
                resp = await client.messages.create(
                    model=model,
                    max_tokens=256,
                    system=[{
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }],
                    messages=[{"role": "user", "content": build_user_content(paper)}],
                    thinking={"type": "adaptive"},
                    output_config={
                        "effort": "low",
                        "format": {"type": "json_schema", "schema": schema},
                    },
                )
                text = next((b.text for b in resp.content if b.type == "text"), None)
                if text is None:
                    return None
                data = json.loads(text)
                tags = data.get("tags") or []
                return tags if tags else None
            except anthropic.RateLimitError:
                await asyncio.sleep(min(2 ** attempt, 30))
            except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
                if getattr(e, "status_code", 500) < 500 and attempt > 0:
                    print(f"  [paper {paper.get('i')}] non-retryable: {e}", file=sys.stderr)
                    return None
                await asyncio.sleep(min(2 ** attempt, 30))
            except Exception as e:
                print(f"  [paper {paper.get('i')}] error: {type(e).__name__}: {e}", file=sys.stderr)
                return None
        print(f"  [paper {paper.get('i')}] gave up after retries", file=sys.stderr)
        return None


async def run(args) -> None:
    tag_names, catalogue_text, fallback = load_tag_catalogue()
    system_prompt = build_system_prompt(catalogue_text)
    schema = build_schema(tag_names)

    conf_path = ROOT / "conferences" / f"{args.conf}.json"
    with conf_path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)

    papers = data["papers"]
    pool = papers[: args.max] if args.max else papers

    def should_tag(p):
        if args.overwrite:
            return True
        src = p.get("g_source")
        return src not in ("llm", "openreview")

    to_tag = [p for p in pool if should_tag(p)]
    print(f"{args.conf}: model={args.model}, concurrency={args.concurrency}")
    print(f"  candidate papers: {len(pool)}, will tag: {len(to_tag)}, skipped: {len(pool) - len(to_tag)}")

    if args.dry_run:
        to_tag = to_tag[:3]
        print(f"  dry-run: tagging only {len(to_tag)} papers, NOT saving")

    if not to_tag:
        print("  nothing to do")
        return

    client = anthropic.AsyncAnthropic()
    sem = asyncio.Semaphore(args.concurrency)

    progress = {"done": 0, "total": len(to_tag), "fail": 0}

    async def task(paper):
        tags = await tag_one(client, sem, args.model, system_prompt, schema, paper)
        progress["done"] += 1
        if tags is None:
            progress["fail"] += 1
        if progress["done"] % 25 == 0 or progress["done"] == progress["total"]:
            print(f"  {progress['done']}/{progress['total']} (failures: {progress['fail']})")
        return paper["i"], tags

    pairs = await asyncio.gather(*(task(p) for p in to_tag))
    results = {pid: tags for pid, tags in pairs if tags}

    if args.dry_run:
        print("\nDry-run results:")
        for pid, tags in results.items():
            paper = next(p for p in to_tag if p["i"] == pid)
            title = (paper.get("t") or "")[:90]
            print(f"  {title!r}\n    -> {tags}")
        return

    # Persist
    pid_to_paper = {p["i"]: p for p in data["papers"]}
    for pid, tags in results.items():
        p = pid_to_paper.get(pid)
        if p is not None:
            p["g"] = tags
            p["g_source"] = "llm"

    fields = set(data.get("fields_present") or [])
    fields.add("g")
    data["fields_present"] = sorted(fields)
    data["keyword_field"] = "g"

    with conf_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nsaved {len(results)}/{len(to_tag)} tags to {conf_path}")
    if progress["fail"]:
        print(f"  WARNING: {progress['fail']} papers failed and were left unchanged")

    counts = Counter()
    for p in data["papers"]:
        for t in p.get("g") or []:
            counts[t] += 1
    print("top tags across the whole conference:")
    for name, c in counts.most_common(15):
        print(f"  {name:<30} {c:>5}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--conf", required=True, help="Conference id (e.g. kdd2026)")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model id (default {DEFAULT_MODEL})")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    p.add_argument("--max", type=int, help="Tag only the first N papers (test runs)")
    p.add_argument("--overwrite", action="store_true",
                   help="Re-tag papers even if g_source is already llm/openreview")
    p.add_argument("--dry-run", action="store_true",
                   help="Tag 3 papers and print results — does not save")
    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
