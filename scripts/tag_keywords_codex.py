"""Tag conference papers in batches through the authenticated Codex CLI.

This is the no-API-key counterpart to ``tag_keywords_llm.py``.  Each Codex
process runs read-only in an empty temporary directory and returns validated
structured JSON. Results are checkpointed after every completed batch to both
the conference JSON and the re-applicable ``<conf>_tags.json`` sidecar.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from tag_keywords_llm import MAX_ABSTRACT_CHARS, build_system_prompt, load_tag_catalogue


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "gpt-5.4-mini"


def chunks(items: list[dict], size: int) -> list[list[dict]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def output_schema(tag_names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "papers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string", "enum": tag_names},
                            "minItems": 1,
                            "maxItems": 5,
                        },
                    },
                    "required": ["id", "tags"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["papers"],
        "additionalProperties": False,
    }


def build_prompt(system_prompt: str, batch: list[dict]) -> str:
    payload = []
    for paper in batch:
        abstract = paper.get("a") or ""
        if len(abstract) > MAX_ABSTRACT_CHARS:
            abstract = abstract[:MAX_ABSTRACT_CHARS] + " [...]"
        payload.append({
            "id": str(paper["i"]),
            "title": paper.get("t") or "",
            "abstract": abstract,
        })
    return (
        system_prompt
        + "\n\nClassify every paper in the JSON array below. Return exactly one result "
          "for every input id, preserve each id verbatim, and return only the "
          "structured response required by the output schema. Do not inspect "
          "files, run tools, or perform any other task.\n\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


def run_batch(
    codex_exe: str,
    model: str,
    schema_path: Path,
    work_dir: Path,
    system_prompt: str,
    batch_num: int,
    batch: list[dict],
) -> tuple[int, dict[str, list[str]], str | None]:
    out_path = work_dir / f"batch_{batch_num:04d}.json"
    prompt = build_prompt(system_prompt, batch)
    cmd = [
        codex_exe,
        "exec",
        "--ephemeral",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--color", "never",
        "--sandbox", "read-only",
        "--model", model,
        "-c", 'model_reasoning_effort="low"',
        "--cd", str(work_dir),
        "--output-schema", str(schema_path),
        "--output-last-message", str(out_path),
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=300,
        )
    except Exception as exc:
        return batch_num, {}, f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "unknown Codex error")[-1200:]
        return batch_num, {}, detail
    try:
        response = json.loads(out_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return batch_num, {}, f"invalid output: {type(exc).__name__}: {exc}"

    expected = {str(p["i"]) for p in batch}
    results: dict[str, list[str]] = {}
    for row in response.get("papers") or []:
        paper_id = str(row.get("id") or "")
        tags = list(dict.fromkeys(row.get("tags") or []))
        if paper_id in expected and tags:
            results[paper_id] = tags
    missing = expected - set(results)
    if missing:
        return batch_num, {}, f"response omitted {len(missing)} paper ids"
    return batch_num, results, None


def save(conf_path: Path, data: dict, tags_path: Path, saved_tags: dict) -> None:
    with conf_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    with tags_path.open("w", encoding="utf-8") as f:
        json.dump(saved_tags, f, ensure_ascii=False, separators=(",", ":"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conf", required=True)
    parser.add_argument("--cycle")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    codex_exe = shutil.which("codex.exe") or shutil.which("codex")
    if not codex_exe:
        raise SystemExit("Codex CLI not found")

    tag_names, catalogue_text, _fallback = load_tag_catalogue()
    system_prompt = build_system_prompt(catalogue_text)
    conf_path = ROOT / "conferences" / f"{args.conf}.json"
    tags_path = ROOT / "conferences" / f"{args.conf}_tags.json"
    with conf_path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    saved_tags = {}
    if tags_path.exists():
        with tags_path.open("r", encoding="utf-8-sig") as f:
            saved_tags = json.load(f)

    pool = [p for p in data["papers"] if not args.cycle or p.get("c") == args.cycle]
    if not args.overwrite:
        pool = [p for p in pool if not p.get("g")]
    if args.max:
        pool = pool[:args.max]
    if args.dry_run:
        pool = pool[:3]
    batches = chunks(pool, max(1, args.batch_size))
    print(f"{args.conf}: cycle={args.cycle or 'all'}, model={args.model}")
    print(f"  papers={len(pool)}, batches={len(batches)}, concurrency={args.concurrency}")
    if not batches:
        return

    pid_to_paper = {str(p["i"]): p for p in data["papers"]}
    completed = 0
    failures = 0
    collected: dict[str, list[str]] = {}

    with tempfile.TemporaryDirectory(prefix="codex-paper-tags-") as temp_name:
        work_dir = Path(temp_name)
        schema_path = work_dir / "schema.json"
        schema_path.write_text(
            json.dumps(output_schema(tag_names), ensure_ascii=False),
            encoding="utf-8",
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = [
                executor.submit(
                    run_batch,
                    codex_exe,
                    args.model,
                    schema_path,
                    work_dir,
                    system_prompt,
                    i + 1,
                    batch,
                )
                for i, batch in enumerate(batches)
            ]
            for future in concurrent.futures.as_completed(futures):
                batch_num, results, error = future.result()
                if error:
                    failures += 1
                    print(f"  batch {batch_num}/{len(batches)} FAILED: {error}", flush=True)
                    continue
                collected.update(results)
                completed += len(results)
                print(f"  batch {batch_num}/{len(batches)}: +{len(results)} "
                      f"({completed}/{len(pool)})", flush=True)
                if not args.dry_run:
                    for paper_id, tags in results.items():
                        paper = pid_to_paper[paper_id]
                        paper["g"] = tags
                        paper["g_source"] = "Codex-direct"
                    saved_tags.update(results)
                    data["fields_present"] = sorted(set(data.get("fields_present") or []) | {"g"})
                    data["keyword_field"] = "g"
                    save(conf_path, data, tags_path, saved_tags)

    if args.dry_run:
        for paper_id, tags in collected.items():
            print(f"  {pid_to_paper[paper_id]['t']}\n    -> {tags}")
        print("dry-run: no files changed")
        return

    counts = Counter(tag for tags in collected.values() for tag in tags)
    print(f"\nsaved {completed}/{len(pool)} papers; failed batches={failures}")
    for name, count in counts.most_common(15):
        print(f"  {name:<30} {count:>5}")


if __name__ == "__main__":
    main()
