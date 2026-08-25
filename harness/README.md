# PipelineRCA-Bench harness

Phase 2 of `notes.txt`. Turns the scenarios in `scenarios/` (21 as of
the round-2 taxonomy expansion, see `TAXONOMY.md`) into an
actual, runnable benchmark: discover scenarios, run an agent against
each (symptom + evidence only, never the answer), grade the diagnosis,
verify the proposed fix, and produce a report.

## Install

```
pip install -r harness/requirements.txt
```

## Run

From the project root:

```
python -m harness.run --scenarios-dir scenarios --agent keyword --out-dir out/
python -m harness.run --scenarios-dir scenarios --agent naive   --out-dir out/
```

Writes `out/results_<agent>.json` and `out/report_<agent>.md`, and prints
a markdown table to stdout.

## How it fits together

```
loader.discover_scenarios(scenarios_dir)
    -> [Scenario, ...]              # full record, INCLUDES ground_truth

for each Scenario:
    loader.validate_scenario(scenario)   # structural check, see below
    loader.build_agent_task(scenario)
        -> AgentTask                # symptom + context files ONLY

    ToolBelt(task.context)          # read_file / search_logs / profile_data / list_files
    agent.diagnose(task, tools)
        -> Diagnosis                # root_cause, causal_chain, proposed_fix

    scoring.rca_judge.score(scenario, diagnosis)
        -> JudgeScore                # graded against the hidden ground_truth

    scoring.fix_executor.run_verification(scenario, diagnosis)
        -> FixResult                 # runs verify/test_fix.py sandboxed

report.ScenarioResult(...) for each  -> report.write_json / write_markdown_report
```

## Ground truth isolation

`loader.py` is the only module allowed to read `manifest.yaml` off disk.
Everything downstream of `build_agent_task()` only ever touches an
`AgentTask`, whose dataclass fields are exactly `scenario_id`, `symptom`,
`context` -- there is no `ground_truth` field to accidentally pass
through. `loader_test.py` (used during development, not shipped) asserted
this directly: `task.__dataclass_fields__ == {"scenario_id", "symptom",
"context"}`.

`Scenario` (which does carry `ground_truth`) is only ever handed to
`scoring.rca_judge` and `scoring.fix_executor` -- never to an `Agent`.

## The judge: stub today, real later

`scoring/rca_judge.py` has two implementations of `DiagnosisJudge`:

- **`StubHeuristicJudge`** (default, what `make_default_judge()` returns
  with no arguments) -- deterministic lexical-overlap scoring, zero cost,
  zero API dependency. It exists to validate the harness plumbing, not to
  produce meaningful scores. It prints a warning on first use for exactly
  this reason, and it *will* mis-grade real diagnoses -- see "Known
  limitation" below.
- **`LLMDiagnosisJudge`** -- the real judge. Takes any `call_model(prompt:
  str) -> str` callable, so it's not tied to a specific SDK. The prompt
  it sends (`JUDGE_PROMPT_TEMPLATE`) is the "published prompt" from
  `notes.txt` phase 2 item 10 -- it asks the model to return per-item
  TRUE/FALSE hits against the ground truth's `causal_chain`,
  `required_answer_elements`, and `distractors`, as JSON.

To switch to real grading:

```python
from anthropic import Anthropic
from harness.scoring.rca_judge import LLMDiagnosisJudge

client = Anthropic()
def call_claude(prompt: str) -> str:
    resp = client.messages.create(
        model="claude-sonnet-5", max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text

judge = LLMDiagnosisJudge(call_claude)
```

then pass `judge` into `run()` instead of calling `make_default_judge()`
with no arguments (wire this into `run.py` when you're ready -- currently
`run.py` always calls the zero-arg default).

### Known limitation of the stub judge (found during integration testing)

Running both baseline agents against s001 under the stub judge, the
naive agent (which just echoes the symptom text verbatim) scored *higher*
than the keyword agent (which actually cites a specific evidence line).
That's backwards from what a human grader would conclude, and it's
expected: the symptom text happens to share vocabulary with the ground
truth causal chain, so verbatim-echoing gets "free" lexical credit, while
the keyword agent's more grounded but differently-worded answer doesn't
match as literally. This is exactly the failure mode the module docstring
warns about, and it's the concrete reason a real LLM judge (which grades
meaning, not word overlap) matters before running this on anything you
intend to draw conclusions from.

## The fix executor: what it verifies today vs. later

Every scenario's `verify/test_fix.py` is currently a **self-contained**
stub: it embeds both a "broken" and a "fixed" reference implementation
inline and asserts the fixed one behaves correctly. None of them yet take
an agent's actual `Diagnosis.fix_code` as input.

So today, `FixExecutor.run_verification()` runs each scenario's verify
file as-is, sandboxed (separate subprocess, wall-clock timeout, throwaway
cwd) and reports pass/fail. That's a real, useful regression test on its
own -- it's exactly what caught the s008 bug (an overly loose scaler
`std` that let a broken value slip past the "fixed" threshold check)
during this project's original scenario-authoring pass. When scenario
verify files are updated to accept externally-supplied fix code, the
integration point is `run_verification()` -- sandboxing is already there,
only the "inject the agent's fix" step needs adding.

**Sandboxing caveat**: process-level isolation (subprocess + timeout +
throwaway cwd), not container-level. No seccomp/gVisor/network denial.
Fine for scenario regression-testing; not yet safe for running arbitrary
untrusted agent-submitted code -- tighten this before pointing it at
externally submitted fixes.

## Adding a new agent

Implement the one-method contract in `agent.py`:

```python
from harness.agent import Agent, Diagnosis
from harness.loader import AgentTask
from harness.tools import ToolBelt

class MyAgent(Agent):
    def diagnose(self, task: AgentTask, tools: ToolBelt) -> Diagnosis:
        ...
        return Diagnosis(root_cause=..., causal_chain=[...], proposed_fix=...)
```

Register it in `agents/__init__.py`'s `AGENTS` dict and it's available via
`--agent your_name`.

Two agents ship today, both fully deterministic (no API calls, so the
harness runs end-to-end with nothing configured):

- `naive` (`NaiveEchoAgent`) -- the phase 3 floor baseline. Never opens a
  context file, just restates the symptom.
- `keyword` (`KeywordHeuristicAgent`) -- a toy tool-user. Searches every
  context file for a fixed list of "smoking gun" words and quotes
  whichever file has the most hits. Not a real solver -- it exists to
  exercise every `ToolBelt` method and give the discrimination check
  something to compare against `naive`.

Swap either out for a real model-backed agent (e.g. one that hands `task`
and tool descriptions to Claude in a small agent loop) when you're ready
for Phase 3.

## Testing this harness itself

`scoring/fix_executor.py`'s sandboxing means the harness needs no special
permissions to run scenario verify files. During development this was
validated with two standalone scripts (not part of the shipped package):
one built `Scenario`/`GroundTruth` objects in-memory and ran both
baseline agents through the full loader -> agent -> judge -> fix_executor
-> report pipeline; the other exercised `loader.discover_scenarios` /
`load_scenario` / `validate_scenario` / `build_agent_task` against a real
on-disk `manifest.yaml`, including asserting `validate_scenario` catches
a deliberately-removed context file. Recommended before trusting any
future change to `loader.py` in particular, since it's the ground-truth
isolation boundary.
