"""A toy tool-using agent, deterministic (no LLM). It exists to exercise
every ToolBelt method end-to-end and to give the harness's discrimination
check something to differentiate from NaiveEchoAgent without needing API
access. It is NOT a real RCA solver -- it just surfaces the file with the
densest concentration of a fixed list of "smoking gun" keywords that tend
to appear near real root causes across these scenarios (silent, fallback,
clip, archive, defer, OOM, stale, etc.) and quotes it. Replace with a real
model-backed agent for anything resembling real evaluation."""
from __future__ import annotations

import re

from ..agent import Agent, Diagnosis
from ..loader import AgentTask
from ..tools import ToolBelt

SIGNAL_WORDS = [
    "silent", "silently", "fallback", "clip", "clipped", "archive", "archived",
    "defer", "deferred", "oom", "stale", "unseen", "missing", "duplicate",
    "append", "idempotent", "threshold", "cap", "unit", "scaler", "manifest",
]


class KeywordHeuristicAgent(Agent):
    def diagnose(self, task: AgentTask, tools: ToolBelt) -> Diagnosis:
        files = tools.list_files()
        best_file, best_score, best_lines = None, -1, []
        for f in files:
            matches = []
            for word in SIGNAL_WORDS:
                matches.extend(m.line for m in tools.search_logs(word, relative_path=f))
            if len(matches) > best_score:
                best_file, best_score, best_lines = f, len(matches), matches[:5]

        if best_file is None:
            return Diagnosis(
                root_cause="No signal words found in any context file; unable to form a hypothesis.",
                proposed_fix="Manual investigation required.",
                raw_transcript="[keyword baseline: no matches]",
            )

        quoted = " | ".join(line.strip() for line in best_lines)
        root_cause = (
            f"The evidence in {best_file} appears most relevant "
            f"({best_score} signal-word matches). Representative lines: {quoted}"
        )
        return Diagnosis(
            root_cause=root_cause,
            causal_chain=[f"Signal concentrated in {best_file}"],
            proposed_fix="Investigate the flagged file further and address the underlying condition it describes.",
            raw_transcript=f"[keyword baseline] searched {len(files)} files, best={best_file} score={best_score}",
        )
