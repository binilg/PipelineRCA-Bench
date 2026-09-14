"""Discovers and validates PipelineRCA-Bench scenarios.

This is the only module in the harness that is allowed to read
manifest.yaml (and therefore ground_truth) off disk. Every other
component -- agents, tools, the judge's *input* to an agent -- only ever
sees objects built here that structurally cannot carry ground_truth:
AgentTask has no ground_truth field at all, so there is no attribute to
accidentally leak.
"""
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path


REQUIRED_TOP_LEVEL = [
    "id", "title", "category", "difficulty", "stack", "symptom",
    "context_files", "ground_truth", "required_answer_elements",
]
REQUIRED_GROUND_TRUTH = [
    "root_cause", "causal_chain", "distractors", "verification",
    # "acceptable_fixes"/"partial_credit_fixes" are required UNLESS
    # is_false_positive is true, in which case "acceptable_conclusion"
    # is required instead -- see validate_scenario().
]


@dataclass(frozen=True)
class GroundTruth:
    """Hidden from agents. Read only by loader and scoring.rca_judge.

    is_false_positive / acceptable_conclusion support category 8
    (false_positive_correct_behavior) scenarios, where the correct
    answer is "nothing is broken, no fix needed" -- see s021 and
    HOW_TO_WRITE_A_SCENARIO.md's "False-positive scenarios" section.
    For these, acceptable_fixes/partial_credit_fixes are typically
    empty and acceptable_conclusion carries the correct diagnosis
    instead. rca_judge.py needs no special-casing for this: it already
    grades purely against causal_chain / required_answer_elements /
    distractors, never against acceptable_fixes, so a
    required_answer_elements entry like "does not propose an
    unnecessary code fix" (see s021) is sufficient to penalize a
    fabricated fix under the existing scoring formula.
    """
    root_cause: str
    causal_chain: list[str]
    distractors: list[str]
    acceptable_fixes: list[dict]
    partial_credit_fixes: list[dict]
    verification: str  # path relative to scenario dir, e.g. "verify/test_fix.py"
    is_false_positive: bool = False
    acceptable_conclusion: str = ""


@dataclass(frozen=True)
class Scenario:
    """Full internal representation, including ground truth. Never pass
    this object to an Agent -- pass the result of loader.build_agent_task()
    instead."""
    id: str
    title: str
    category: str
    difficulty: str
    stack: list[str]
    symptom: str
    context_files: list[str]        # paths relative to scenario_dir, e.g. "context/dag.py"
    required_answer_elements: list[str]
    scenario_dir: Path
    ground_truth: GroundTruth

    def verify_path(self) -> Path:
        return self.scenario_dir / self.ground_truth.verification


@dataclass(frozen=True)
class AgentTask:
    """Agent-safe view of a scenario. Structurally cannot carry ground
    truth -- there is no field for it."""
    scenario_id: str
    symptom: str
    context: dict[str, str] = field(default_factory=dict)  # relative path -> file content


def load_scenario(manifest_path: Path) -> Scenario:
    manifest_path = Path(manifest_path)
    data = yaml.safe_load(manifest_path.read_text())
    scenario_dir = manifest_path.parent
    gt = data["ground_truth"]
    ground_truth = GroundTruth(
        root_cause=gt["root_cause"],
        causal_chain=list(gt["causal_chain"]),
        distractors=list(gt["distractors"]),
        acceptable_fixes=list(gt.get("acceptable_fixes", [])),
        partial_credit_fixes=list(gt.get("partial_credit_fixes", [])),
        verification=gt["verification"],
        is_false_positive=bool(gt.get("is_false_positive", False)),
        acceptable_conclusion=gt.get("acceptable_conclusion", ""),
    )
    return Scenario(
        id=data["id"],
        title=data["title"],
        category=data["category"],
        difficulty=data["difficulty"],
        stack=list(data.get("stack", [])),
        symptom=data["symptom"],
        context_files=list(data["context_files"]),
        required_answer_elements=list(data["required_answer_elements"]),
        scenario_dir=scenario_dir,
        ground_truth=ground_truth,
    )


def discover_scenarios(scenarios_root: Path) -> list[Scenario]:
    """Finds every sNNN_*/manifest.yaml under scenarios_root and loads it.
    Returns scenarios sorted by id."""
    scenarios_root = Path(scenarios_root)
    manifests = sorted(scenarios_root.glob("*/manifest.yaml"))
    return [load_scenario(m) for m in manifests]


def validate_scenario(scenario: Scenario) -> list[str]:
    """Structural validation. Returns a list of problems; empty = valid.
    Does not re-parse YAML (that already succeeded by construction) --
    checks the things a scenario author can still get wrong: missing
    files, too-thin distractors/fixes, contradicting the how-to guide."""
    errors: list[str] = []

    for rel_path in scenario.context_files:
        full = scenario.scenario_dir / rel_path
        if not full.exists():
            errors.append(f"context_files entry not found on disk: {rel_path}")

    if not scenario.verify_path().exists():
        errors.append(f"verification file not found: {scenario.ground_truth.verification}")

    if len(scenario.ground_truth.distractors) < 2:
        errors.append("fewer than 2 distractors (how-to guide recommends 2-4)")

    if scenario.ground_truth.is_false_positive:
        if not scenario.ground_truth.acceptable_conclusion.strip():
            errors.append("is_false_positive scenario has no acceptable_conclusion")
        if scenario.ground_truth.acceptable_fixes:
            errors.append("is_false_positive scenario should not have acceptable_fixes (nothing to fix)")
    elif len(scenario.ground_truth.acceptable_fixes) < 1:
        errors.append("no acceptable_fixes")

    if len(scenario.ground_truth.causal_chain) < 3:
        errors.append("causal_chain has fewer than 3 steps")

    if len(scenario.required_answer_elements) < 2:
        errors.append("fewer than 2 required_answer_elements")

    if scenario.difficulty not in ("easy", "medium", "hard"):
        errors.append(f"difficulty must be easy/medium/hard, got {scenario.difficulty!r}")

    return errors


def build_agent_task(scenario: Scenario) -> AgentTask:
    """The sanctioned way to turn a Scenario into something an Agent may
    see. Reads every file in context_files; ground_truth never enters
    the returned object."""
    context: dict[str, str] = {}
    for rel_path in scenario.context_files:
        full = scenario.scenario_dir / rel_path
        # e.g. s001's context/model_logs/ entry -- expand directories to every
        # file inside. Checked with is_dir() rather than a bare read_text()
        # try/except IsADirectoryError: POSIX raises IsADirectoryError for
        # open() on a directory, but Windows raises PermissionError instead,
        # which silently swallowed every such scenario's directory context
        # until this was caught running the harness on Windows.
        if full.is_dir():
            for sub in sorted(full.rglob("*")):
                if sub.is_file():
                    rel_sub = str(sub.relative_to(scenario.scenario_dir))
                    context[rel_sub] = sub.read_text(errors="replace")
        else:
            context[rel_path] = full.read_text(errors="replace")
    return AgentTask(scenario_id=scenario.id, symptom=scenario.symptom, context=context)
