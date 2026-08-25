"""Aggregates per-scenario results into JSON + a markdown table, plus a
summary by category/difficulty -- report.py from phase 2 item 12.

Scenarios excluded by structural validation are carried through as
SkippedScenario records and reported alongside the scores. A benchmark
whose subject is silent failure must not silently shrink its own
denominator: every report states how many scenarios were attempted and
how many produced a score.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean

from .scoring.rca_judge import JudgeScore
from .scoring.fix_executor import FixResult


@dataclass
class ScenarioResult:
    scenario_id: str
    title: str
    category: str
    difficulty: str
    judge_score: JudgeScore
    fix_result: FixResult
    agent_name: str


@dataclass
class SkippedScenario:
    """A scenario excluded from the run because validate_scenario() rejected
    it. Recorded so the reported denominator is always auditable."""
    scenario_id: str
    errors: list[str] = field(default_factory=list)


def to_dict(results: list[ScenarioResult]) -> list[dict]:
    return [
        {
            "scenario_id": r.scenario_id,
            "title": r.title,
            "category": r.category,
            "difficulty": r.difficulty,
            "agent_name": r.agent_name,
            "judge_score": asdict(r.judge_score),
            "fix_result": asdict(r.fix_result),
        }
        for r in results
    ]


def write_json(
    results: list[ScenarioResult],
    path: Path,
    skipped: list[SkippedScenario] | None = None,
) -> None:
    skipped = skipped or []
    payload = {
        "summary": summarize(results, skipped),
        "results": to_dict(results),
        "skipped": [asdict(s) for s in skipped],
    }
    Path(path).write_text(json.dumps(payload, indent=2))


def to_markdown_table(results: list[ScenarioResult]) -> str:
    header = "| scenario | category | difficulty | causal_chain | required_elements | distractor_penalty | overall | fix_passed |"
    sep = "|---|---|---|---|---|---|---|---|"
    rows = [header, sep]
    for r in sorted(results, key=lambda r: r.scenario_id):
        js = r.judge_score
        rows.append(
            f"| {r.scenario_id} | {r.category} | {r.difficulty} "
            f"| {js.causal_chain_coverage:.0%} | {js.required_elements_coverage:.0%} "
            f"| {js.distractor_penalty:.0%} | {js.overall:.0%} "
            f"| {'yes' if r.fix_result.passed else 'no'} |"
        )
    return "\n".join(rows)


def summarize(
    results: list[ScenarioResult],
    skipped: list[SkippedScenario] | None = None,
) -> dict:
    skipped = skipped or []
    n_attempted = len(results) + len(skipped)
    if not results:
        return {
            "n_attempted": n_attempted,
            "n_scored": 0,
            "n_skipped": len(skipped),
        }

    by_category: dict[str, list[float]] = {}
    by_difficulty: dict[str, list[float]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r.judge_score.overall)
        by_difficulty.setdefault(r.difficulty, []).append(r.judge_score.overall)

    return {
        "n_attempted": n_attempted,
        "n_scored": len(results),
        "n_skipped": len(skipped),
        "overall_mean_score": round(mean(r.judge_score.overall for r in results), 4),
        "fix_pass_rate": round(mean(1.0 if r.fix_result.passed else 0.0 for r in results), 4),
        "mean_score_by_category": {k: round(mean(v), 4) for k, v in sorted(by_category.items())},
        "mean_score_by_difficulty": {k: round(mean(v), 4) for k, v in sorted(by_difficulty.items())},
    }


def write_markdown_report(
    results: list[ScenarioResult],
    path: Path,
    skipped: list[SkippedScenario] | None = None,
) -> None:
    skipped = skipped or []
    summary = summarize(results, skipped)
    n_scored = summary.get("n_scored", 0)
    n_attempted = summary.get("n_attempted", 0)

    lines = [
        f"# PipelineRCA-Bench report ({results[0].agent_name if results else 'n/a'})",
        "",
        f"Scenarios scored: {n_scored} of {n_attempted} attempted",
    ]
    if skipped:
        lines.append("")
        lines.append(
            f"**WARNING: {len(skipped)} scenario(s) were excluded by structural "
            "validation and are NOT reflected in any score below.**"
        )
    lines += [
        "",
        f"Overall mean diagnosis score: {summary.get('overall_mean_score', 0):.0%}",
        f"Fix verification pass rate: {summary.get('fix_pass_rate', 0):.0%}",
        "",
        "## By category",
        "",
    ]
    for cat, score in summary.get("mean_score_by_category", {}).items():
        lines.append(f"- {cat}: {score:.0%}")
    lines += ["", "## By difficulty", ""]
    for diff, score in summary.get("mean_score_by_difficulty", {}).items():
        lines.append(f"- {diff}: {score:.0%}")
    lines += ["", "## Per-scenario", "", to_markdown_table(results), ""]

    if skipped:
        lines += ["## Excluded scenarios", ""]
        for s in skipped:
            lines.append(f"- **{s.scenario_id}**: {'; '.join(s.errors)}")
        lines.append("")

    Path(path).write_text("\n".join(lines))
