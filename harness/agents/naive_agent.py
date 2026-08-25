"""The floor baseline (phase 3 item 13): looks only at the symptom, never
calls a tool, never reads a single context file. Establishes what "not
even trying" scores, so real baselines have something to beat. This is a
deterministic stand-in for a real naive LLM baseline -- swap in an actual
single-shot LLM call (symptom only, no tools) when Phase 3 starts."""
from __future__ import annotations

from ..agent import Agent, Diagnosis
from ..loader import AgentTask
from ..tools import ToolBelt


class NaiveEchoAgent(Agent):
    def diagnose(self, task: AgentTask, tools: ToolBelt) -> Diagnosis:
        return Diagnosis(
            root_cause=f"The pipeline behaved unexpectedly: {task.symptom.strip()[:200]}",
            causal_chain=[],
            proposed_fix="Retry the run and monitor; escalate if it recurs.",
            raw_transcript="[naive baseline: symptom only, no tool calls made]",
        )
