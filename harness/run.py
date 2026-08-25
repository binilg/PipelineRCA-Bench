"""CLI entry point tying loader -> agent -> judge -> fix_executor -> report
together.

Usage:
    python -m harness.run --scenarios-dir scenarios --agent keyword --out-dir out/
    python -m harness.run --scenarios-dir scenarios --agent keyword --judge claude
    python -m harness.run --scenarios-dir scenarios --agent keyword --strict

With no --agent flag, defaults to the keyword baseline. Use --agent naive
for the floor baseline.

--judge selects the grader. `stub` (default) is the deterministic
lexical-overlap placeholder -- fine for testing the plumbing, meaningless
as a score. `claude` wires LLMDiagnosisJudge to the Anthropic SDK and
requires ANTHROPIC_API_KEY in the environment.

--strict aborts the run if any scenario fails structural validation.
Without it, invalid scenarios are excluded from the run but are recorded
and reported explicitly -- they are never silently dropped.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import loader
from .agents import AGENTS
from .scoring.rca_judge import DiagnosisJudge, LLMDiagnosisJudge, make_default_judge
from .scoring.fix_executor import FixExecutor
from .report import (
    ScenarioResult,
    SkippedScenario,
    write_json,
    write_markdown_report,
    to_markdown_table,
)
from .tools import ToolBelt

JUDGE_MODEL = "claude-sonnet-4-6"


def build_judge(judge_name: str) -> DiagnosisJudge:
    """Returns the grader named on the command line.

    `stub` needs nothing configured. `claude` constructs a call_model
    callable over the Anthropic SDK and hands it to LLMDiagnosisJudge --
    the judge itself stays SDK-agnostic, so swapping providers means
    replacing this function only.
    """
    if judge_name == "stub":
        return make_default_judge()

    if judge_name == "claude":
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise SystemExit(
                "--judge claude requires the anthropic package: pip install anthropic"
            ) from exc
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("--judge claude requires ANTHROPIC_API_KEY to be set")

        client = Anthropic()

        def call_claude(prompt: str) -> str:
            resp = client.messages.create(
                model=JUDGE_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text

        return LLMDiagnosisJudge(call_claude)

    raise SystemExit(f"unknown judge: {judge_name!r}")


def run(
    scenarios_dir: Path,
    agent_name: str,
    out_dir: Path,
    judge_name: str = "stub",
    strict: bool = False,
) -> tuple[list[ScenarioResult], list[SkippedScenario]]:
    scenarios = loader.discover_scenarios(scenarios_dir)
    if not scenarios:
        print(f"No scenarios found under {scenarios_dir}", file=sys.stderr)
        return [], []

    agent = AGENTS[agent_name]()
    judge = build_judge(judge_name)
    executor = FixExecutor()

    # Validate everything up front so a malformed manifest is a loud failure
    # at the start of the run, not a line of stderr buried mid-run.
    skipped: list[SkippedScenario] = []
    runnable = []
    for scenario in scenarios:
        errors = loader.validate_scenario(scenario)
        if errors:
            skipped.append(SkippedScenario(scenario_id=scenario.id, errors=errors))
        else:
            runnable.append(scenario)

    if skipped:
        print(
            f"\n{len(skipped)} of {len(scenarios)} scenarios failed validation:",
            file=sys.stderr,
        )
        for s in skipped:
            print(f"  [INVALID] {s.scenario_id}: {'; '.join(s.errors)}", file=sys.stderr)
        if strict:
            raise SystemExit(
                "aborting: --strict set and at least one scenario is invalid"
            )
        print(
            "Continuing without them. These scenarios are EXCLUDED from all "
            "scores below and are listed in the report.\n",
            file=sys.stderr,
        )

    results: list[ScenarioResult] = []
    for scenario in runnable:
        task = loader.build_agent_task(scenario)
        tools = ToolBelt(task.context)
        diagnosis = agent.diagnose(task, tools)

        judge_score = judge.score(scenario, diagnosis)
        fix_result = executor.run_verification(scenario, diagnosis)

        results.append(ScenarioResult(
            scenario_id=scenario.id,
            title=scenario.title,
            category=scenario.category,
            difficulty=scenario.difficulty,
            judge_score=judge_score,
            fix_result=fix_result,
            agent_name=agent_name,
        ))
        print(f"[{scenario.id}] overall={judge_score.overall:.0%} fix_passed={fix_result.passed}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(results, out_dir / f"results_{agent_name}.json", skipped=skipped)
    write_markdown_report(results, out_dir / f"report_{agent_name}.md", skipped=skipped)
    return results, skipped


def main():
    parser = argparse.ArgumentParser(description="Run PipelineRCA-Bench scenarios against an agent.")
    parser.add_argument("--scenarios-dir", type=Path, default=Path("scenarios"))
    parser.add_argument("--agent", choices=sorted(AGENTS.keys()), default="keyword")
    parser.add_argument("--judge", choices=["stub", "claude"], default="stub",
                        help="stub = lexical placeholder (not a real score); claude = LLMDiagnosisJudge")
    parser.add_argument("--out-dir", type=Path, default=Path("out"))
    parser.add_argument("--strict", action="store_true",
                        help="abort if any scenario fails structural validation")
    args = parser.parse_args()

    results, skipped = run(
        args.scenarios_dir, args.agent, args.out_dir,
        judge_name=args.judge, strict=args.strict,
    )
    if results:
        print()
        print(to_markdown_table(results))
    if skipped:
        print()
        print(f"NOTE: {len(skipped)} scenario(s) excluded from these numbers. See the report.")
        sys.exit(1)


if __name__ == "__main__":
    main()
