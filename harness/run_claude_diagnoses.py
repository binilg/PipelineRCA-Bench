#!/usr/bin/env python3
"""Collect closed-book Claude diagnoses for PipelineRCA-Bench via the
Anthropic Messages API, replacing the subagent-collected transcripts.

WHY THIS EXISTS
    The original Claude arm (phase3_transcripts.md) was collected by
    handing each scenario's evidence to an isolated subagent instance,
    because no Anthropic API key was available in that environment. That
    is not independently reproducible the way a documented API call is.
    This script closes that gap using the identical closed-book prompt
    and protocol already used for run_gemini_diagnoses.py, so the two
    arms are collected the same way and are directly comparable.

WHAT THIS DOES
    For each scenario under <scenarios-dir>/sNNN_*/manifest.yaml, this
    script reads ONLY the scenario's `symptom` and verbatim `context_files`
    (never `ground_truth` -- that key is never even accessed), builds a
    closed-book prompt, and sends it to the Anthropic Messages API.
    Responses are saved both as individual .txt files and as one combined
    markdown file, in the same format run_gemini_diagnoses.py uses, so
    the two are drop-in comparable and both work with run_llm_judge.py.

WHAT THIS DOES NOT DO
    It does not grade the responses. Use run_llm_judge.py for that --
    ideally with a DIFFERENT model as judge than the one being graded
    here, since a model grading its own diagnoses is not an independent
    grader (see the "Known limitations" note on grader independence).

USAGE
    # 1. Set your API key as an environment variable (don't pass it on the
    #    command line -- that leaks into shell history).
    #      Windows (PowerShell):  $env:ANTHROPIC_API_KEY = "your-key-here"
    #      macOS/Linux (bash):    export ANTHROPIC_API_KEY="your-key-here"
    #
    # 2. Run from anywhere, pointing at your local copy of the project:
    #      python run_claude_diagnoses.py \
    #          --scenarios-dir "path/to/PipelineRCA-Bench project/scenarios" \
    #          --out-dir "path/to/PipelineRCA-Bench project/harness/out/claude_api_run"
    #
    # Optional flags:
    #   --model claude-sonnet-4-5     (default; matches the model id used elsewhere in this project)
    #   --dry-run                     (print the first prompt and exit, no API calls, no cost)
    #   --only s001,s005              (run a subset, comma-separated scenario ids)
    #   --sleep 1.0                   (seconds between calls, default 1.0)

REQUIREMENTS
    Python 3.9+, and PyYAML (`pip install pyyaml`). Everything else is
    stdlib (urllib) -- no anthropic SDK required.
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


API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Identical wording to run_gemini_diagnoses.py's CLOSED_BOOK_INSTRUCTIONS,
# so the two arms are prompted the same way. Keep these in sync by hand if
# either changes -- there's deliberately no shared import, since each
# script is meant to be copy-pasteable and standalone.
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


def call_claude(model: str, api_key: str, prompt: str, max_retries: int = 5) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 4096,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            API_URL, data=body, method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
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
            raise RuntimeError(f"Anthropic API error {e.code}: {err_body}") from e
        except urllib.error.URLError as e:
            if attempt < max_retries:
                wait = min(2 ** attempt, 60)
                print(f"    Network error ({e.reason}), retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("exhausted retries")


def _extract_text(payload: dict) -> str:
    content = payload.get("content") or []
    texts = [block["text"] for block in content if block.get("type") == "text"]
    if not texts:
        raise RuntimeError(f"No text content in response: {json.dumps(payload)[:500]}")
    return "\n".join(texts).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios-dir", required=True, type=Path,
                     help="Path to the scenarios/ folder (contains sNNN_*/manifest.yaml)")
    ap.add_argument("--out-dir", required=True, type=Path,
                     help="Where to write per-scenario .txt files and the combined .md file")
    ap.add_argument("--model", default="claude-sonnet-4-5",
                     help="Anthropic model id (default: claude-sonnet-4-5)")
    ap.add_argument("--api-key-env", default="ANTHROPIC_API_KEY",
                     help="Name of the env var holding your API key (default: ANTHROPIC_API_KEY)")
    ap.add_argument("--only", default=None,
                     help="Comma-separated scenario ids to run, e.g. s001,s005 (default: all)")
    ap.add_argument("--sleep", type=float, default=1.0,
                     help="Seconds to sleep between API calls (default: 1.0)")
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
        "# Claude Closed-Book Diagnoses -- Raw Transcripts (API-collected)",
        "",
        f"Each scenario was submitted to the Anthropic Messages API (`{args.model}`) "
        "using the exact same closed-book prompt (symptom + verbatim context files, "
        "no ground truth) as run_gemini_diagnoses.py uses for the Gemini arm, and the "
        "same prompt harness/loader.py's `build_agent_task()` would hand a real agent. "
        "This supersedes the earlier subagent-collected transcripts "
        "(harness/out/phase3_transcripts.md), which were used only because no API key "
        "was available at the time. Responses are pasted verbatim below.",
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
            text = call_claude(args.model, api_key, prompt)
        except Exception as e:
            print(f"    FAILED: {e}")
            errors.append(f"{task.scenario_id}: {e}")
            text = f"[ERROR: generation failed -- {e}]"

        (args.out_dir / f"{task.scenario_id}.txt").write_text(text, encoding="utf-8")

        md_lines.append(f"## {task.scenario_id} — {task.category} ({task.difficulty})")
        md_lines.append("")
        md_lines.append(text)
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

        if i < len(scenarios):
            time.sleep(args.sleep)

    combined_path = args.out_dir / "claude_transcripts_api.md"
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
