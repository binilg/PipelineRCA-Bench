# PipelineRCA-Bench

**Can AI agents diagnose a broken data pipeline the way an experienced engineer would?**

PipelineRCA-Bench is a benchmark of 21 realistic data/ML pipeline failures. Each
scenario hands an agent the symptom an on-call engineer would actually see, plus a
folder of evidence — logs, DAG code, config, git history — with the real cause buried
somewhere inside and 2–4 plausible-but-wrong leads mixed in. The agent must name the
root cause, reconstruct the causal chain, and propose a fix that addresses the cause
rather than the symptom.

Unlike service-health benchmarks, these are **data-correctness** failures. In most of
them the pipeline reports **success**. There is no stack trace. The numbers are just
quietly wrong.

---

## Leaderboard

| Agent | Mean score | Causal-chain coverage | Required-elements coverage | Perfect scores |
|---|---|---|---|---|
| **Gemini** `gemini-3.6-flash` — closed-book | **0.978** | 0.974 | 0.984 | 18/21 |
| **Claude** `claude-sonnet-4-5` — closed-book | **0.952** | 0.952 | 0.952 | 16/21 |
| **Naive** — symptom echo, no tools | **0.075** | 0.00 | 0.19 | 0/21 |

Both frontier arms were collected via direct API calls with an identical closed-book
prompt (symptom + verbatim context files, `ground_truth` never included), and graded
by **cross-model automated judging**: Gemini grades Claude's diagnoses, Claude grades
Gemini's. Neither model ever grades its own answers.

Frontier models score roughly **13× the naive floor**. The two are close, and the
0.026 gap between them is within the range these judges disagree on — treat them as
comparable rather than ranked.

**Judge agreement.** On 18 of 21 scenarios (86%) the two independently-produced
diagnoses received *identical* scores from *different* judges. Disagreement is
confined to three scenarios — s007, s015, s018 — where scores differ by 0.13–0.23.
Two different model families, grading two different sets of answers against the same
published rubric, converging this closely is evidence the rubric is doing the work
rather than the grader's preferences.

Full methodology, per-scenario scores, and limitations:
[`harness/out/phase3_report.md`](harness/out/phase3_report.md).

**[→ Submit your agent's results](#submitting-results)**

---

## Why this benchmark

Data and ML pipelines fail in ways that don't look like failures. A job silently falls
back to yesterday's numbers. A well-meaning rerun duplicates a partition. A model
confidently mis-scores a category it has never seen. A validation gate that exists to
catch exactly this problem compares a partition to itself and reports Green.

Existing agentic-ops benchmarks (AIOpsLab, MicroRemed and others) focus on
**microservice and infrastructure health** — availability, traces, topology, alerts.
That work is valuable and adjacent, but a service-health framing has no natural place
for an incident where every task is green and the output is wrong. PipelineRCA-Bench
targets that gap.

The scenarios are authored from patterns seen in production forecasting and ML
operations. Every artifact — logs, code, data, config — is **entirely synthetic**;
what is drawn from experience is the *shape* of each failure and, critically, which
wrong answers look convincing.

---

## The scenarios

21 scenarios across 8 categories, 7 easy / 9 medium / 5 hard. Full detail with
public-source grounding for each category is in [`TAXONOMY.md`](TAXONOMY.md).

| Category | n | What it covers |
|---|---|---|
| `recovery_temporal_state` | 3 | A gap on one day is silently papered over; a later run depends on bad state |
| `rerun_idempotency_failure` | 3 | A reasonable retry interacts badly with a step that isn't safe to run twice |
| `train_serving_skew` | 3 | Training and serving quietly disagree; no crash, just confident wrong answers |
| `data_quality_gate_failure` | 3 | The gate built to catch this class of bug has a blind spot of its own |
| `resource_capacity_lifecycle_failure` | 3 | Infra decisions interact with pipeline logic in unanticipated ways |
| `change_management_failure` | 3 | A change ships correctly in one place and not in another |
| `secondary_model_layer_failure` | 2 | An adjustment/ensemble layer degrades silently while the core model is fine |
| `false_positive_correct_behavior` | 1 | Nothing is broken — the correct diagnosis is "no bug exists" |

That last category is deliberate. An agent that always finds a bug is not diagnosing;
it is pattern-matching. `s021` penalises inventing a fix for correct behaviour.

### Anatomy of a scenario

```
scenarios/s019_adjustment_config_key_rename_silent_noop/
├── manifest.yaml          # symptom, context list, hidden ground truth, distractors
├── context/               # everything the agent may see
│   ├── adjustment_pipeline.py
│   ├── weather_adjustment_config.yaml
│   ├── scoring_summary.log
│   └── git_log.txt
└── verify/test_fix.py     # executable check on the proposed fix
```

The agent receives the `symptom` and `context/` only. `ground_truth` is withheld by
the loader and used solely for grading.

---

## Quickstart

```bash
git clone https://github.com/binilg/pipelinerca-bench.git
cd pipelinerca-bench
pip install -r harness/requirements.txt

# run the bundled baselines
python -m harness.run --scenarios-dir scenarios --agent naive   --out-dir out/
python -m harness.run --scenarios-dir scenarios --agent keyword --out-dir out/
```

Writes `out/results_<agent>.json` and `out/report_<agent>.md`.

### Reproducing the leaderboard

Both frontier arms call live APIs, so you need keys. Set them as environment
variables — never in a file inside the repo.

```bash
export ANTHROPIC_API_KEY="..."     # console.anthropic.com
export GEMINI_API_KEY="..."        # aistudio.google.com/apikey

# collect diagnoses (closed-book, temperature 0)
python harness/run_claude_diagnoses.py --scenarios-dir scenarios \
       --out-dir harness/out/claude_api_run
python harness/run_gemini_diagnoses.py --scenarios-dir scenarios \
       --out-dir harness/out/gemini_api_run

# grade cross-family: each model's answers judged by the other
python harness/run_llm_judge.py --judge gemini --diagnoses-dir harness/out/claude_api_run
python harness/run_llm_judge.py --judge claude --diagnoses-dir harness/out/gemini_api_run
```

Total API cost for a full pass is a few dollars.

### Evaluating your own agent

Implement one method:

```python
from harness.agent import Agent, Diagnosis

class MyAgent(Agent):
    def diagnose(self, task, tools) -> Diagnosis:
        # task.symptom          -> what the on-call engineer sees
        # task.context          -> file list; read via tools
        # tools.read_file(path), tools.search_logs(pattern),
        # tools.profile_data(path), tools.list_files()
        return Diagnosis(
            root_cause="...",
            causal_chain=["...", "..."],
            proposed_fix="...",
        )
```

Register it in `harness/agents/__init__.py` and pass `--agent myagent`.

---

## How scoring works

Three components, reported separately rather than collapsed into one number:

**Causal-chain coverage (60%)** — how many of the ground-truth causal steps the
diagnosis explicitly asserts. Partial credit is the point: an agent that gets 4 of 6
links has done more than one that guesses the headline.

**Required-elements coverage (40%)** — anti-gaming checks. Each scenario specifies
claims the answer *must* contain (and sometimes must *not* contain), so a vague or
hedged diagnosis cannot score well by vocabulary overlap alone.

**Distractor penalty** — asserting a planted wrong cause reduces the score.

```
overall = (0.6 * causal_chain_coverage + 0.4 * required_elements_coverage)
          * distractor_penalty
```

The judging rubric is published in full as `JUDGE_PROMPT_TEMPLATE` in
[`harness/scoring/rca_judge.py`](harness/scoring/rca_judge.py), and is applied by
[`harness/run_llm_judge.py`](harness/run_llm_judge.py). Grading a benchmark with an
LLM judge is a contested practice; two mitigations are used here. First, **cross-family
grading** — no model grades its own answers. Second, the prompt is published verbatim,
so any score can be audited or disputed.

---

## Known limitations

Stated plainly, because a benchmark whose weaknesses are hidden is not a useful
measuring instrument.

- **Fix verification does not yet differentiate agents.** `verify/test_fix.py` files
  are self-contained regression tests; they do not currently consume the agent's
  actual `proposed_fix`. The fix dimension is therefore not yet scored.
- **No external validation yet.** No engineer outside the project has confirmed the
  scenarios are realistic and solvable. This is the highest-priority next step, and
  contributions in that direction are especially welcome.
- **Single-pass, temperature 0.** Each arm is one run per scenario. No variance
  estimate across repeated runs.
- **n=21.** Small enough that a few scenario-level misses move the aggregate
  noticeably, and small enough that difficulty labels don't cleanly predict error
  rates (medium scored below hard for the Claude arm). Construct validity of the
  difficulty labels is an open question as the set grows.
- **Judges are LLMs.** Cross-family grading removes the worst conflict of interest,
  but both judges are still language models applying a rubric. The rubric is published
  in full so any score can be audited or disputed.
- **Scenario authorship is single-source.** All 21 scenarios were authored by one
  practitioner. Broader authorship would reduce the risk of a systematic blind spot.

Superseded passes (hand-graded, and browser-collected for Gemini) are retained under
`*_deprecated` keys in `phase3_results.json` for audit trail.

## Submitting results

1. Run the harness against all 21 scenarios with your agent.
2. Open a PR adding `results/<date>-<agent-name>.json` (the harness output).
3. Include: model/version, whether tools were used, and any deviation from the
   standard protocol.

Results with a clear methodology statement will be added to the leaderboard.

## Contributing scenarios

New scenarios are welcome, especially in under-represented categories.
[`HOW_TO_WRITE_A_SCENARIO.md`](HOW_TO_WRITE_A_SCENARIO.md) covers the format and —
more importantly — what makes a scenario *good*: a symptom that doesn't reveal the
cause, an answer that is genuinely derivable from the evidence, and distractors that
a competent engineer would actually fall for.

Scenarios must be fully synthetic. Do not contribute real logs, schemas, or data from
any employer or client.

## Citing

```bibtex
@misc{george2026pipelinercabench,
  author = {George, Binil Kavinal},
  title  = {PipelineRCA-Bench: A Benchmark for Agentic Root-Cause Analysis
            of Data and ML Pipeline Failures},
  year   = {2026},
  url    = {https://github.com/binilg/pipelinerca-bench}
}
```

## License

MIT — see [LICENSE](LICENSE).
