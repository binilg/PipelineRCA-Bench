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

For `--judge claude` you also need the Anthropic SDK and an API key:

```
pip install anthropic
export ANTHROPIC_API_KEY=...
```

## Run

From the project root:

```
python -m harness.run --scenarios-dir scenarios --agent keyword --out-dir out/
python -m harness.run --scenarios-dir scenarios --agent naive   --out-dir out/
python -m harness.run --scenarios-dir scenarios --agent keyword --judge claude
python -m harness.run --scenarios-dir scenarios --agent keyword --strict
```

Writes `out/results_<agent>.json` and `out/report_<agent>.md`, and prints
a markdown table to stdout.

| flag | default | meaning |
|---|---|---|
| `--scenarios-dir` | `scenarios` | root containing `sNNN_*/manifest.yaml` |
| `--agent` | `keyword` | which agent under test (see "Adding a new agent") |
| `--judge` | `stub` | `stub` = lexical placeholder, `claude` = real `LLMDiagnosisJudge` |
| `--out-dir` | `out` | where results JSON and markdown report are written |
| `--strict` | off | abort the run if any scenario fails structural validation |

The process exits non-zero if any scenario was excluded by validation,
so CI catches a malformed manifest without anyone reading the report.

## How it fits together

```
loader.discover_scenarios(scenarios_dir)
    -> [Scenario, ...]              # full record, INCLUDES ground_truth

# validation happens for ALL scenarios first, before any agent runs
for each Scenario:
    loader.validate_scenario(scenario)   # structural check, see below
        -> [] = runnable | [errors] = SkippedScenario, excluded and reported

for each runnable Scenario:
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
report.SkippedScenario(...) for each excluded scenario, carried into both outputs
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

A second, independent layer sits in `tools.py`: a `ToolBelt` is built from
an already-resolved `{path: content}` dict, never a filesystem handle into
the scenario directory. There is no method on the class that *could* read
`manifest.yaml`, because the object it wraps was never given a path to it.

## Validation and the reported denominator

`validate_scenario()` checks what a scenario author can still get wrong
after the YAML parses: every `context_files` entry exists on disk, the
verification file exists, at least 2 distractors, at least 3 causal-chain
steps, at least 2 required answer elements, a difficulty of
easy/medium/hard, and at least one acceptable fix -- unless
`is_false_positive` is set, in which case it requires
`acceptable_conclusion` and forbids `acceptable_fixes` instead.

Scenarios that fail validation are **excluded from the run but never
silently dropped**. They are collected as `report.SkippedScenario`
records and surfaced in three places: stderr at the start of the run, a
bolded warning plus an "Excluded scenarios" section in the markdown
report, and a `skipped` key in the results JSON. Every report states
`n_scored` of `n_attempted`.

This matters more here than in a typical harness. A benchmark whose
entire subject is pipelines that succeed while producing wrong output
cannot itself silently shrink its own denominator and report a clean
mean over whatever survived. Use `--strict` in CI to make it a hard
failure.

## The judge: stub by default, real via `--judge claude`

`scoring/rca_judge.py` has two implementations of `DiagnosisJudge`:

- **`StubHeuristicJudge`** (what `--judge stub`, the default, selects) --
  deterministic lexical-overlap scoring, zero cost, zero API dependency.
  It exists to validate the harness plumbing, not to produce meaningful
  scores. It prints a warning on first use for exactly this reason, and
  it *will* mis-grade real diagnoses -- see "Known limitation" below.
- **`LLMDiagnosisJudge`** (`--judge claude`) -- the real judge. Takes any
  `call_model(prompt: str) -> str` callable, so it's not tied to a
  specific SDK. The prompt it sends (`JUDGE_PROMPT_TEMPLATE`) is the
  "published prompt" from `notes.txt` phase 2 item 10 -- it asks the model
  to return per-item TRUE/FALSE hits against the ground truth's
  `causal_chain`, `required_answer_elements`, and `distractors`, as JSON.

`run.build_judge()` is the only place that knows about a specific SDK.
Wiring a different provider means editing that one function; the judge,
the scoring formula, and everything downstream stay unchanged.

Both judges funnel through the same `_score_from_hits()`, so their output
is structurally identical and the two are interchangeable at any point.

### The scoring formula

```
overall = (0.6 x causal_chain_coverage + 0.4 x required_elements_coverage)
          x distractor_penalty

distractor_penalty = 1.0 - (fraction_of_distractors_asserted x 0.5)
```

Causal-chain coverage is weighted above required-element coverage because
naming the mechanism is the harder and more diagnostic skill. The
distractor term is **multiplicative rather than additive**, so a correct
root cause wrapped around a confidently-asserted wrong distractor still
loses real credit rather than netting out against it. Falling for every
distractor halves the score rather than zeroing it, since a diagnosis can
be partially right while over-claiming.

`JudgeScore` retains the per-item boolean lists
(`per_causal_chain_step`, `per_required_element`, `fell_for_distractor`),
not just the aggregates, so per-step error analysis is possible after the
fact without re-running.

### Known limitation of the stub judge (found during integration testing)

Running both baseline agents against the original s001 under the stub
judge (before its 2026-09-14 ground-truth rewrite — see
`harness/out/phase3_report.md`), the naive agent (which just echoes the
symptom text verbatim) scored *higher* than the keyword agent (which
actually cites a specific evidence line). That's backwards from what a
human grader would conclude, and it happened because the symptom text
shared vocabulary with that version's ground truth causal chain, so
verbatim-echoing got "free" lexical credit while the keyword agent's
more grounded but differently-worded answer didn't match as literally.
This is exactly the failure mode the module docstring warns about, and
it's the concrete reason a real LLM judge (which grades meaning, not
word overlap) matters before running this on anything you intend to
draw conclusions from. (Against the current, rewritten s001, both
baselines tie at 0.1 under the stub judge — a less dramatic case of the
same underlying unreliability, not evidence the stub judge has gotten
more trustworthy.)

**Do not publish stub-judge numbers.** Use `--judge claude` for any run
whose output leaves this repository.

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

For `is_false_positive` scenarios (category 8, e.g. s021),
`verify/test_fix.py` is not a broken-vs-fixed check -- there is no fix,
since nothing is broken. It's a consistency check confirming the
scenario's own claimed ground truth is actually correct (s021 asserts
each of its four claimed exclusion reasons really does exclude the
combination it claims to). `run_verification()` runs it identically
either way; the distinction only matters when interpreting a pass.

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
  context file for a fixed list of generic operational-anomaly words and
  quotes whichever file has the most hits. Not a real solver -- it exists
  to exercise every `ToolBelt` method and give the discrimination check
  something to compare against `naive`.

Swap either out for a real model-backed agent (e.g. one that hands `task`
and tool descriptions to Claude in a small agent loop) when you're ready
for Phase 3.

### A note on `keyword`'s SIGNAL_WORDS list

An earlier revision of `keyword_agent.py` used signal words drawn from
this benchmark's own root causes (`silent`, `fallback`, `duplicate`,
`append`, `idempotent`, `stale`, `scaler`, ...). That made the baseline an
oracle rather than a floor: those terms *are* the answers, so any score it
earned measured leakage from the scenario set into the baseline, not
lexical matching as a strategy. Published next to real agents, a reviewer
would rightly discount every number in the table.

The current list is deliberately generic (`error`, `timeout`, `retry`,
`mismatch`, ...) -- vocabulary any ops-log grep would use without knowing
what these scenarios are about. **It must stay that way.** When adding a
scenario, do not add its distinguishing vocabulary here. The test: if a
word would only occur to someone who already knows a scenario's answer,
it does not belong in the list.

Because of this change, `keyword` scores are not comparable to any run
recorded before it. The older, higher numbers were inflated by leakage.

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

## Output format

`results_<agent>.json` is an object with three keys:

```json
{
  "summary": { "n_attempted": 21, "n_scored": 21, "n_skipped": 0, "...": "..." },
  "results": [ { "scenario_id": "s001", "...": "..." } ],
  "skipped": []
}
```

Note this replaced an earlier format in which the file was a bare list of
result objects. Anything downstream that parses `results_*.json` needs to
read `payload["results"]` rather than iterating the top level.
