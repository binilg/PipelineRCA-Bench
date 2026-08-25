#!/usr/bin/env python3
"""Redo the closed-book Gemini diagnoses for PipelineRCA-Bench via the
Gemini API, replacing the manual browser-run transcripts.

WHAT THIS DOES
    For each scenario under <scenarios-dir>/sNNN_*/manifest.yaml, this
    script reads ONLY the scenario's `symptom` and verbatim `context_files`
    (never `ground_truth` -- that key is never even accessed), builds the
    same closed-book prompt described in harness/out/phase3_transcripts.md's
    methodology note, and sends it to the Gemini API. Responses are saved
    both as individual .txt files and as one combined markdown file in the
    same style as harness/out/gemini_transcripts.md, so it can directly
    replace that file.

WHAT THIS DOES NOT DO
    It does not grade the responses or touch the leaderboard. Send the
    output folder back and that's a separate follow-up step.

USAGE
    # 1. Set your API key as an environment variable (don't pass it on the
    #    command line -- that leaks into shell history).
    #      Windows (PowerShell):  $env:GEMINI_API_KEY = "your-key-here"
    #      macOS/Linux (bash):    export GEMINI_API_KEY="your-key-here"
    #
    # 2. Run from anywhere, pointing at your local copy of the project:
    #      python run_gemini_diagnoses.py \
    #          --scenarios-dir "path/to/PipelineRCA-Bench project/scenarios" \
    #          --out-dir "path/to/PipelineRCA-Bench project/harness/out/gemini_api_run"
    #
    # Optional flags:
    #   --model gemini-3.7-flash      (default; try gemini-3.1-pro-preview for a comparison run)
    #   --dry-run                     (print the first prompt and exit, no API calls, no cost)
    #   --only s001,s005              (run a subset, comma-separated scenario ids)
    #   --sleep 2.0                   (seconds between calls, default 2.0)

REQUIREMENTS
    Python 3.9+, and PyYAML (`pip install pyyaml`). Everything else is
    stdlib (urllib) -- no google-generativeai SDK required.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Missing dependency: PyYAML. Install with:  pip install pyyaml", file=sys.stderr)
    sys.exit(1)


API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

CLOSED_BOOK_INSTRUCTIONS = """You are an on-call engineer investigating a production data-pipeline incident.

You have NO tools, NO filesystem access, and NO ability to run code. You must \
reason only from the evidence pasted below -- this is a closed-book diagnosis. \
You do not know the name of this project, the scenario id, or anything about \
it beyond what is pasted here; treat this as a fresh, isolated incident report.

## Symptom

{symptom}

## Context files (pasted verbatim)

{context_block}

## Your task

Based only on the evidence above, diagnose the root cause. Do not guess at \
information that isn't given. If, after reasoning through the evidence, you \
conclude the pipeline is actually behaving correctly and there is no bug to \
fix, say so plainly in ROOT CAUSE and leave PROPOSED FIX as "No code fix \
needed" with your reasoning why.

Respond in EXACTLY this format, with no preamble and no text outside these \
three sections:

ROOT CAUSE:
<one paragraph explaining the underlying cause>

CAUSAL CHAIN:
1. <first step, from trigger toward the observed symptom>
2. <next step>
...

PROPOSED FIX:
<your recommended fix, or "No code fix needed" with reasoning if this is a false alarm>
"""


@dataclass
class ScenarioTask:
    scenario_id: str
    title: str
    category: str
    difficulty: str
    symptom: str
    context: dict[str, str]  # relative path -> file content


def discover_scenarios(scenarios_root: Path) -> list[ScenarioTask]:
    """Mirrors harness/loader.py's build_agent_task(), but standalone.
    Reads id/title/category/difficulty/symptom/context_files. Never reads
    or references the manifest's ground_truth key."""
    tasks: list[ScenarioTask] = []
    for manifest_path in sorted(scenarios_root.glob("*/manifest.yaml")):
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        scenario_dir = manifest_path.parent

        context: dict[str, str] = {}
        for rel_path in data["context_files"]:
            full = scenario_dir / rel_path
            if full.is_dir():
                for sub in sorted(full.rglob("*")):
                    if sub.is_file():
                        rel_sub = str(sub.relative_to(scenario_dir))
                        context[rel_sub] = sub.read_text(encoding="utf-8", errors="replace")
            else:
                context[rel_path] = full.read_text(encoding="utf-8", errors="replace")

        tasks.append(ScenarioTask(
            scenario_id=data["id"],
            title=data["title"],
            category=data["category"],
            difficulty=data["difficulty"],
            symptom=data["symptom"].strip(),
            context=context,
        ))
    return tasks


def build_prompt(task: ScenarioTask) -> str:
    blocks = []
    for rel_path, content in task.context.items():
        blocks.append(f"### {rel_path}\n```\n{content}\n```")
    context_block = "\n\n".join(blocks)
    return CLOSED_BOOK_INSTRUCTIONS.format(symptom=task.symptom, context_block=context_block)


def call_gemini(model: str, api_key: str, prompt: str, max_retries: int = 5) -> str:
    url = f"{API_BASE}/{model}:generateContent?key={api_key}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 8192,
        },
    }).encode("utf-8")

    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                return _extract_text(payload)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                wait = min(2 ** attempt, 60)
                print(f"    HTTP {e.code}, retrying in {wait}s (attempt {attempt}/{max_retries})...")
                time.sleep(wait)
                continue
            raise RuntimeError(f"Gemini API error {e.code}: {err_body}") from e
        except urllib.error.URLError as e:
            if attempt < max_retries:
                wait = min(2 ** attempt, 60)
                print(f"    Network error ({e.reason}), retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("exhausted retries")


def _extract_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        block_reason = payload.get("promptFeedback", {}).get("blockReason")
        raise RuntimeError(f"No candidates returned. promptFeedback={payload.get('promptFeedback')}")
    parts = candidates[0].get("content", {}).get("parts", [])
    texts = [p["text"] for p in parts if "text" in p and not p.get("thought")]
    if not texts:
        raise RuntimeError(f"No text parts in response: {json.dumps(payload)[:500]}")
    return "\n".join(texts).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios-dir", required=True, type=Path,
                     help="Path to the scenarios/ folder (contains sNNN_*/manifest.yaml)")
    ap.add_argument("--out-dir", required=True, type=Path,
                     help="Where to write per-scenario .txt files and the combined .md file")
    ap.add_argument("--model", default="gemini-3.7-flash",
                     help="Gemini model id (default: gemini-3.7-flash)")
    ap.add_argument("--api-key-env", default="GEMINI_API_KEY",
                     help="Name of the env var holding your API key (default: GEMINI_API_KEY)")
    ap.add_argument("--only", default=None,
                     help="Comma-separated scenario ids to run, e.g. s001,s005 (default: all)")
    ap.add_argument("--sleep", type=float, default=2.0,
                     help="Seconds to sleep between API calls (default: 2.0)")
    ap.add_argument("--dry-run", action="store_true",
                     help="Print the first prompt and exit -- no API calls")
    args = ap.parse_args()

    api_key = os.environ.get(args.api_key_env)
    if not api_key and not args.dry_run:
        print(f"Set your API key first: environment variable {args.api_key_env} is not set.", file=sys.stderr)
        sys.exit(1)

    scenarios = discover_scenarios(args.scenarios_dir)
    if not scenarios:
        print(f"No scenarios found under {args.scenarios_dir} (expected sNNN_*/manifest.yaml)", file=sys.stderr)
        sys.exit(1)

    if args.only:
        wanted = set(args.only.split(","))
        scenarios = [t for t in scenarios if t.scenario_id in wanted]

    print(f"Found {len(scenarios)} scenario(s). Model: {args.model}")

    if args.dry_run:
        print("\n--- DRY RUN: first prompt only ---\n")
        print(build_prompt(scenarios[0]))
        return

    args.out_dir.mkdir(parents=True, exist_ok=True)
    md_lines = [
        "# Gemini Closed-Book Diagnoses -- Raw Transcripts",
        "",
        f"Each scenario was submitted to the Gemini API (`{args.model}`) using the exact "
        "same closed-book prompt (symptom + verbatim context files, no ground truth) as the "
        "harness's `AgentTask` would provide. This supersedes the earlier manual "
        "browser-run transcripts. Responses are pasted verbatim below.",
        "",
        "Ground truth (`manifest.yaml`) was never included in any prompt.",
        "",
        "---",
        "",
    ]

    errors: list[str] = []
    for i, task in enumerate(scenarios, 1):
        print(f"[{i}/{len(scenarios)}] {task.scenario_id} -- {task.title}")
        prompt = build_prompt(task)
        try:
            text = call_gemini(args.model, api_key, prompt)
        except Exception as e:
            print(f"    FAILED: {e}")
            errors.append(f"{task.scenario_id}: {e}")
            text = f"[ERROR: generation failed -- {e}]"

        (args.out_dir / f"{task.scenario_id}.txt").write_text(text, encoding="utf-8")

        md_lines.append(f"## {task.scenario_id} \u2014 {task.category} ({task.difficulty})")
        md_lines.append("")
        md_lines.append(text)
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

        if i < len(scenarios):
            time.sleep(args.sleep)

    combined_path = args.out_dir / "gemini_transcripts.md"
    combined_path.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"\nDone. Combined transcripts: {combined_path}")
    print(f"Per-scenario files: {args.out_dir}/sNNN.txt")
    if errors:
        print(f"\n{len(errors)} scenario(s) FAILED:")
        for e in errors:
            print(f"  - {e}")
        print("Re-run with --only <failed-ids> after checking the error above.")


if __name__ == "__main__":
    main()
