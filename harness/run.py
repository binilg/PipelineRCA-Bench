"""CLI entry point tying loader -> agent -> judge -> fix_executor -> report
together.

Usage:
    python -m harness.run --scenarios-dir scenarios --agent keyword --out-dir out/

With no --agent flag, defaults to the keyword baseline. Use --agent naive
for the floor baseline. Both run with the stub judge unless you edit
make_default_judge() to pass a real call_model.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import loader
from .agents import AGENTS
from .scoring.rca_judge import make_default_judge
from .scoring.fix_executor import FixExecutor
from .report import ScenarioResult, write_json, write_markdown_report, to_markdown_table
from .tools import ToolBelt


def run(scenarios_dir: Path, agent_name: str, out_dir: Path) -> list[ScenarioResult]:
    scenarios = loader.discover_scenarios(scenarios_dir)
    if not scenarios:
        print(f"No scenarios found under {scenarios_dir}", file=sys.stderr)
        return []

    agent = AGENTS[agent_name]()
    judge = make_default_judge()
    executor = FixExecutor()

    results: list[ScenarioResult] = []
    for scenario in scenarios:
        errors = loader.validate_scenario(scenario)
        if errors:
            print(f"[SKIP] {scenario.id}: {'; '.join(errors)}", file=sys.stderr)
            continue

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
    write_json(results, out_dir / f"results_{agent_name}.json")
    write_markdown_report(results, out_dir / f"report_{agent_name}.md")
    return results


def main():
    parser = argparse.ArgumentParser(description="Run PipelineRCA-Bench scenarios against an agent.")
    parser.add_argument("--scenarios-dir", type=Path, default=Path("scenarios"))
    parser.add_argument("--agent", choices=sorted(AGENTS.keys()), default="keyword")
    parser.add_argument("--out-dir", type=Path, default=Path("out"))
    args = parser.parse_args()

    results = run(args.scenarios_dir, args.agent, args.out_dir)
    if results:
        print()
        print(to_markdown_table(results))


if __name__ == "__main__":
    main()
