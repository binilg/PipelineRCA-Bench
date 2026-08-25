#!/usr/bin/env python3
"""Automated, cross-model grading for PipelineRCA-Bench -- a standalone
port of harness/scoring/rca_judge.py's LLMDiagnosisJudge, wired to a real
model via API instead of being hand-applied.

WHY THIS EXISTS
    Every scenario's headline score to date was produced by hand-applying
    JUDGE_PROMPT_TEMPLATE -- reading the diagnosis and the ground truth
    and deciding each hit/miss manually. That's honest about what it is
    (documented in every report's "Known limitations" section) but it has
    two real problems: it isn't automated/reproducible, and -- the more
    serious issue -- the same party who authored the ground truth also
    applied the rubric to every diagnosis. An LLM judge doesn't fix that
    by itself if it's the SAME model grading its own diagnoses (that's
    self-grading, not independent grading).

    This script exists to let you run genuinely cross-model grading:
    have Gemini grade Claude's diagnoses, and Claude grade Gemini's.
    Neither model ever grades its own answers. That's the actual fix for
    grader independence, not just automation for its own sake.

WHAT THIS DOES
    Loads ground truth from <scenarios-dir>/sNNN_*/manifest.yaml (root_cause,
    causal_chain, distractors, required_answer_elements). Loads diagnoses
    from <diagnoses-dir>/sNNN.txt (the exact output format both
    run_claude_diagnoses.py and run_gemini_diagnoses.py produce -- ROOT
    CAUSE / CAUSAL CHAIN / PROPOSED FIX sections). Builds the identical
    JUDGE_PROMPT_TEMPLATE from harness/scoring/rca_judge.py, sends it to
    the judge model you choose, parses the returned JSON hit arrays, and
    scores with the identical formula from that module's
    _score_from_hits() (kept byte-for-byte in sync by hand -- there's no
    shared import since this script is meant to be standalone):

        overall = (0.6*causal_chain_coverage + 0.4*required_elements_coverage)
                  * distractor_penalty

USAGE
    # 1. Set the judge model's API key as an environment variable.
    #      Windows (PowerShell):  $env:ANTHROPIC_API_KEY = "..."
    #                             $env:GEMINI_API_KEY = "..."
    #      macOS/Linux (bash):    export ANTHROPIC_API_KEY="..."
    #                             export GEMINI_API_KEY="..."
    #
    # 2. Grade Claude's diagnoses using Gemini as an independent judge:
    #      python run_llm_judge.py --judge gemini \
    #          --scenarios-dir "path/to/scenarios" \
    #          --diagnoses-dir "path/to/harness/out/claude_api_run" \
    #          --out "path/to/harness/out/claude_graded_by_gemini.json"
    #
    #    Grade Gemini's diagnoses using Claude as an independent judge:
    #      python run_llm_judge.py --judge claude \
    #          --scenarios-dir "path/to/scenarios" \
    #          --diagnoses-dir "path/to/harness/out/gemini_api_run" \
    #          --out "path/to/harness/out/gemini_graded_by_claude.json"
    #
    # Optional flags:
    #   --claude-model claude-sonnet-4-5   (default)
    #   --gemini-model gemini-3.6-flash    (default; 3.7-flash returned 503s in testing)
    #   --dry-run                          (print the first judge prompt and exit)
    #   --only s001,s005                   (grade a subset)
    #   --sleep 1.0                        (seconds between calls)

REQUIREMENTS
    Python 3.9+, PyYAML. Everything else is stdlib (urllib) -- no
    anthropic / google-generativeai SDKs required.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Missing dependency: PyYAML. Install with:  pip install pyyaml", file=sys.stderr)
    sys.exit(1)


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# ---------------------------------------------------------------------------
# Kept byte-for-byte identical to harness/scoring/rca_judge.py on purpose --
# this IS that module's judging logic, just wired to a real API call instead
# of being hand-applied. If you change the rubric, change it in both places.
# ---------------------------------------------------------------------------
JUDGE_PROMPT_TEMPLATE = """You are grading a root-cause-analysis (RCA) diagnosis against a hidden ground truth for a broken-pipeline benchmark scenario.

## Symptom given to the diagnosing agent
{symptom}

## Ground truth (hidden from the agent; use ONLY to grade)
Root cause:
{root_cause}

Causal chain (ordered steps from trigger to symptom):
{causal_chain_numbered}

Known distractors (plausible-but-wrong causes present in the evidence):
{distractors_numbered}

Required answer elements (the answer must address each of these to be considered complete):
{required_elements_numbered}

## The agent's diagnosis to grade
Root cause claim:
{diagnosis_root_cause}

Causal chain claim (if given):
{diagnosis_causal_chain}

Proposed fix:
{diagnosis_proposed_fix}

## Your task
For each numbered causal_chain step, decide TRUE if the diagnosis correctly
identifies that step (even if worded differently), FALSE otherwise.
For each numbered required_answer_element, decide TRUE if the diagnosis
satisfies it, FALSE otherwise.
For each numbered distractor, decide TRUE if the diagnosis incorrectly
asserts that distractor as (part of) the root cause, FALSE otherwise.

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{
  "causal_chain_hits": [true, false, ...],
  "required_element_hits": [true, false, ...],
  "distractor_hits": [true, false, ...],
  "rationale": "one or two sentences explaining the grading"
}}
"""


@dataclass
class GroundTruthLite:
    root_cause: str
    causal_chain: list[str]
    distractors: list[str]
    required_answer_elements: list[str]


@dataclass
class ScenarioLite:
    scenario_id: str
    category: str
    difficulty: str
    symptom: str
    ground_truth: GroundTruthLite


@dataclass
class Diagnosis:
    root_cause: str = ""
    causal_chain: list[str] = field(default_factory=list)
    proposed_fix: str = ""


def discover_scenarios(scenarios_root: Path) -> dict[str, ScenarioLite]:
    """Loads exactly the fields the judge prompt needs. Deliberately does
    NOT reuse harness/loader.py's Scenario dataclass -- this script is
    meant to run standalone, without the harness package on the path."""
    out: dict[str, ScenarioLite] = {}
    for manifest_path in sorted(scenarios_root.glob("*/manifest.yaml")):
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        gt = data["ground_truth"]
        out[data["id"]] = ScenarioLite(
            scenario_id=data["id"],
            category=data["category"],
            difficulty=data["difficulty"],
            symptom=data["symptom"].strip(),
            ground_truth=GroundTruthLite(
                root_cause=gt["root_cause"].strip(),
                causal_chain=list(gt["causal_chain"]),
                distractors=list(gt["distractors"]),
                required_answer_elements=list(data["required_answer_elements"]),
            ),
        )
    return out


_SECTION_RE = re.compile(
    r"ROOT CAUSE:\s*(?P<root_cause>.*?)\s*"
    r"CAUSAL CHAIN:\s*(?P<causal_chain>.*?)\s*"
    r"PROPOSED FIX:\s*(?P<proposed_fix>.*)\Z",
    re.DOTALL,
)
_NUMBERED_LINE_RE = re.compile(r"^\s*\d+[.)]\s*(.+)$")


def parse_diagnosis(text: str) -> Diagnosis:
    """Parses the ROOT CAUSE / CAUSAL CHAIN / PROPOSED FIX format both
    run_claude_diagnoses.py and run_gemini_diagnoses.py produce. Falls
    back to treating the whole response as root_cause if the expected
    section headers aren't found (e.g. a malformed/errored response),
    rather than crashing the whole grading run over one bad scenario."""
    match = _SECTION_RE.search(text)
    if not match:
        return Diagnosis(root_cause=text.strip())
    causal_chain = [
        m.group(1).strip()
        for line in match.group("causal_chain").splitlines()
        if (m := _NUMBERED_LINE_RE.match(line))
    ]
    return Diagnosis(
        root_cause=match.group("root_cause").strip(),
        causal_chain=causal_chain,
        proposed_fix=match.group("proposed_fix").strip(),
    )


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{i+1}. {item}" for i, item in enumerate(items))


def build_judge_prompt(scenario: ScenarioLite, diagnosis: Diagnosis) -> str:
    gt = scenario.ground_truth
    return JUDGE_PROMPT_TEMPLATE.format(
        symptom=scenario.symptom,
        root_cause=gt.root_cause,
        causal_chain_numbered=_numbered(gt.causal_chain),
        distractors_numbered=_numbered(gt.distractors),
        required_elements_numbered=_numbered(gt.required_answer_elements),
        diagnosis_root_cause=diagnosis.root_cause or "(none given)",
        diagnosis_causal_chain=_numbered(diagnosis.causal_chain) or "(none given)",
        diagnosis_proposed_fix=diagnosis.proposed_fix or "(none given)",
    )


def _score_from_hits(causal_chain_hits, required_element_hits, distractor_hits, rationale) -> dict:
    """Identical formula to harness/scoring/rca_judge.py's _score_from_hits."""
    cc = sum(causal_chain_hits) / len(causal_chain_hits) if causal_chain_hits else 0.0
    re_ = sum(required_element_hits) / len(required_element_hits) if required_element_hits else 0.0
    dp = 1.0 - (sum(distractor_hits) / len(distractor_hits) if distractor_hits else 0.0) * 0.5
    overall = (0.6 * cc + 0.4 * re_) * dp
    return {
        "causal_chain_hits": [bool(x) for x in causal_chain_hits],
        "required_element_hits": [bool(x) for x in required_element_hits],
        "distractor_hits": [bool(x) for x in distractor_hits],
        "causal_chain_coverage": round(cc, 4),
        "required_elements_coverage": round(re_, 4),
        "distractor_penalty": round(dp, 4),
        "overall": round(overall, 4),
        "rationale": rationale,
    }


def _extract_json(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Judge response did not contain a JSON object: {raw!r}")
    return json.loads(match.group(0))


# ---------------------------------------------------------------------------
# Judge model backends
# ---------------------------------------------------------------------------

def call_claude(model: str, api_key: str, prompt: str, max_retries: int = 5) -> str:
    body = json.dumps({
        "model": model, "max_tokens": 1024, "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            ANTHROPIC_API_URL, data=body, method="POST",
            headers={"content-type": "application/json", "x-api-key": api_key,
                     "anthropic-version": ANTHROPIC_VERSION},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                return "\n".join(b["text"] for b in payload.get("content", []) if b.get("type") == "text")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                wait = min(2 ** attempt, 60)
                print(f"    HTTP {e.code}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise RuntimeError(f"Anthropic API error {e.code}: {err_body}") from e
        except urllib.error.URLError as e:
            if attempt < max_retries:
                time.sleep(min(2 ** attempt, 60))
                continue
            raise
    raise RuntimeError("exhausted retries")


def call_gemini(model: str, api_key: str, prompt: str, max_retries: int = 6) -> str:
    url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        # 8192, not 1024: gemini-3.6-flash is a thinking model, and
        # maxOutputTokens caps thinking + final text combined. At 1024 the
        # model can burn the whole budget reasoning about the prompt and
        # get cut off before ever emitting the JSON object, which then
        # fails _extract_json with "did not contain a JSON object" even
        # though the model wasn't actually wrong -- it just never finished.
        "generationConfig": {"temperature": 0, "maxOutputTokens": 8192},
    }).encode("utf-8")
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(url, data=body, method="POST",
                                      headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                candidates = payload.get("candidates") or []
                if not candidates:
                    raise RuntimeError(f"No candidates: {payload.get('promptFeedback')}")
                parts = candidates[0].get("content", {}).get("parts", [])
                return "\n".join(p["text"] for p in parts if "text" in p and not p.get("thought"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                # 429s on this key needed more than 30s of cumulative backoff
                # to clear in testing, so this caps higher (90s) than the
                # diagnosis-collection script's 60s and allows one more
                # attempt (max_retries=6) before giving up.
                wait = min(3 ** attempt, 90)
                print(f"    HTTP {e.code}, retrying in {wait}s (attempt {attempt}/{max_retries})...")
                time.sleep(wait)
                continue
            raise RuntimeError(f"Gemini API error {e.code}: {err_body}") from e
        except urllib.error.URLError as e:
            if attempt < max_retries:
                time.sleep(min(3 ** attempt, 90))
                continue
            raise
    raise RuntimeError("exhausted retries")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--judge", required=True, choices=["claude", "gemini"],
                     help="Which model grades. Use the model you are NOT evaluating.")
    ap.add_argument("--scenarios-dir", required=True, type=Path)
    ap.add_argument("--diagnoses-dir", required=True, type=Path,
                     help="Folder of sNNN.txt diagnosis transcripts to grade")
    ap.add_argument("--out", required=True, type=Path, help="Path to write the results .json")
    ap.add_argument("--claude-model", default="claude-sonnet-4-5")
    ap.add_argument("--gemini-model", default="gemini-3.6-flash")
    ap.add_argument("--only", default=None, help="Comma-separated scenario ids, e.g. s001,s005")
    ap.add_argument("--sleep", type=float, default=4.0,
                     help="Seconds between scenario calls (default: 4.0 -- higher than the "
                          "diagnosis-collection scripts' default, since judge calls hit rate "
                          "limits faster back-to-back in testing)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    scenarios = discover_scenarios(args.scenarios_dir)
    if not scenarios:
        print(f"No scenarios found under {args.scenarios_dir}", file=sys.stderr)
        sys.exit(1)

    diagnosis_files = sorted(args.diagnoses_dir.glob("s*.txt"))
    if not diagnosis_files:
        print(f"No sNNN.txt diagnosis files found under {args.diagnoses_dir}", file=sys.stderr)
        sys.exit(1)

    ids = [f.stem for f in diagnosis_files]
    if args.only:
        wanted = set(args.only.split(","))
        ids = [i for i in ids if i in wanted]

    missing = [i for i in ids if i not in scenarios]
    if missing:
        print(f"Diagnoses found with no matching scenario manifest: {missing}", file=sys.stderr)
        sys.exit(1)

    if args.judge == "claude":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        key_name = "ANTHROPIC_API_KEY"
        call = lambda p: call_claude(args.claude_model, api_key, p)  # noqa: E731
        model_id = args.claude_model
    else:
        api_key = os.environ.get("GEMINI_API_KEY")
        key_name = "GEMINI_API_KEY"
        call = lambda p: call_gemini(args.gemini_model, api_key, p)  # noqa: E731
        model_id = args.gemini_model

    if not api_key and not args.dry_run:
        print(f"Set your judge model's API key first: {key_name} is not set.", file=sys.stderr)
        sys.exit(1)

    print(f"Grading {len(ids)} scenario(s) from {args.diagnoses_dir} using {args.judge} ({model_id}) as judge.")

    if args.dry_run:
        first = ids[0]
        diag = parse_diagnosis((args.diagnoses_dir / f"{first}.txt").read_text(encoding="utf-8"))
        print(f"\n--- DRY RUN: judge prompt for {first} ---\n")
        print(build_judge_prompt(scenarios[first], diag))
        return

    results: dict[str, dict] = {}
    errors: list[str] = []
    for i, sid in enumerate(ids, 1):
        scenario = scenarios[sid]
        print(f"[{i}/{len(ids)}] {sid} ({scenario.category}, {scenario.difficulty})")
        raw_diag = (args.diagnoses_dir / f"{sid}.txt").read_text(encoding="utf-8")
        diagnosis = parse_diagnosis(raw_diag)
        prompt = build_judge_prompt(scenario, diagnosis)
        try:
            raw_response = call(prompt)
            payload = _extract_json(raw_response)
            score = _score_from_hits(
                payload["causal_chain_hits"], payload["required_element_hits"],
                payload["distractor_hits"], payload.get("rationale", ""),
            )
        except Exception as e:
            print(f"    FAILED: {e}")
            errors.append(f"{sid}: {e}")
            score = {"error": str(e)}

        results[sid] = {
            "category": scenario.category,
            "difficulty": scenario.difficulty,
            **score,
        }

        if i < len(ids):
            time.sleep(args.sleep)

    scored = [r for r in results.values() if "overall" in r]
    mean = round(sum(r["overall"] for r in scored) / len(scored), 4) if scored else None

    out_payload = {
        "judge": args.judge,
        "judge_model": model_id,
        "diagnoses_dir": str(args.diagnoses_dir),
        "scenarios_dir": str(args.scenarios_dir),
        "methodology": (
            f"Diagnoses in {args.diagnoses_dir} graded via {args.judge} ({model_id}) "
            "using JUDGE_PROMPT_TEMPLATE from harness/scoring/rca_judge.py, ported "
            "byte-for-byte into this standalone script, and scored with the identical "
            "_score_from_hits formula: overall = (0.6*causal_chain_coverage + "
            "0.4*required_elements_coverage) * distractor_penalty. This is a "
            "cross-model grading pass -- the judge model is deliberately different "
            "from the model whose diagnoses are being graded, so no model grades "
            "its own answers."
        ),
        "mean": mean,
        "scenarios": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")

    print(f"\nDone. Mean score: {mean}")
    print(f"Results written to: {args.out}")
    if errors:
        print(f"\n{len(errors)} scenario(s) FAILED to grade:")
        for e in errors:
            print(f"  - {e}")


if __name__ == "__main__":
    main()
