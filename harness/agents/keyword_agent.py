"""A toy tool-using agent, deterministic (no LLM). It exists to exercise
every ToolBelt method end-to-end and to give the harness's discrimination
check something to differentiate from NaiveEchoAgent without needing API
access. It is NOT a real RCA solver -- it just surfaces the file with the
densest concentration of generic operational-anomaly vocabulary and quotes
it. Replace with a real model-backed agent for anything resembling real
evaluation.

On the choice of SIGNAL_WORDS
-----------------------------
An earlier revision used words drawn from this benchmark's own root causes
(silent, fallback, duplicate, append, idempotent, stale, scaler, ...).
That made the baseline an oracle rather than a floor: those terms are the
answers, so any score it earned measured leakage from the scenario set
into the baseline, not lexical matching as a strategy. Published next to
real agents, a reviewer would rightly discount every number in the table.

The list below is deliberately generic -- the vocabulary any ops-log
grep would use without knowing what these scenarios are about. It must
stay that way. When adding a scenario, do NOT add its distinguishing
vocabulary here. The test is simple: if a word would only occur to someone
who already knows a scenario's answer, it does not belong in this list.
"""
from __future__ import annotations

from ..agent import Agent, Diagnosis
from ..loader import AgentTask
from ..tools import ToolBelt

# Generic operational-anomaly vocabulary. Scenario-agnostic by construction:
# every term here would appear in a grep of any production pipeline's logs.
SIGNAL_WORDS = [
    "error", "exception", "failed", "failure", "warn", "warning",
    "timeout", "timed out", "retry", "retried", "abort", "aborted",
    "skip", "skipped", "null", "none", "empty", "invalid", "mismatch",
    "unexpected", "exceeded", "rejected",
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

        if best_file is None or best_score == 0:
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
