"""The agent plug-in contract: one ABC, one method.

Anyone adding a new agent under test (a baseline, Claude, GPT, a human
transcript replayed as an agent) implements Agent.diagnose(). Nothing in
this file, or in the object passed to diagnose(), carries ground truth.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .loader import AgentTask
from .tools import ToolBelt


@dataclass
class Diagnosis:
    """What an agent hands back for scoring."""
    root_cause: str
    causal_chain: list[str] = field(default_factory=list)
    proposed_fix: str = ""
    fix_code: str | None = None      # optional patch/snippet for scoring.fix_executor
    raw_transcript: str | None = None  # optional, for debugging/audit


class Agent(ABC):
    """Implement this to plug an agent into the harness."""

    @abstractmethod
    def diagnose(self, task: AgentTask, tools: ToolBelt) -> Diagnosis:
        """task carries only the symptom and context files -- no ground
        truth. tools is scoped to this scenario's context/ directory.
        Return a Diagnosis."""
        raise NotImplementedError
