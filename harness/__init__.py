"""PipelineRCA-Bench harness.

A scenario poses a broken-pipeline puzzle: an agent sees a symptom and a
context/ directory of evidence, and must produce a root-cause diagnosis
and a proposed fix. Ground truth is hidden from the agent and used only
for scoring.

Modules:
  loader          -- discover/validate scenarios; the ONLY place ground
                      truth is read from disk. Builds agent-safe tasks.
  agent           -- the plug-in contract every agent under test implements.
  tools           -- the tool surface (read_file/search_logs/profile_data/
                      list_files) exposed to an agent during diagnosis.
  scoring.rca_judge      -- grades a diagnosis against hidden ground truth.
  scoring.fix_executor   -- sandboxed execution of a scenario's verify test.
  report          -- aggregates scenario results into JSON + markdown.
"""
from . import loader, agent, tools, report  # noqa: F401
