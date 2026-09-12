# PipelineRCA-Bench — Phase 3 Results

*Current as of 2026-08-23. This supersedes all earlier passes; superseded
scores are retained in `phase3_results.json` under `*_deprecated` keys for
audit trail.*

Baseline runs against all 21 scenarios: a naive floor baseline, a blind
Claude (Sonnet) diagnosis, and a blind Gemini diagnosis. Both frontier arms
are collected via **direct API calls** using an identical closed-book prompt
(symptom plus verbatim context files; `ground_truth` is never included), and
graded by **cross-model automated judging** — Gemini grades Claude's
diagnoses, Claude grades Gemini's, so no model ever grades its own answers.
Grading applies the harness's published rubric (`JUDGE_PROMPT_TEMPLATE` in
`harness/scoring/rca_judge.py`) against each scenario's hidden ground truth.

This design resolves the two methodological gaps present in every earlier
pass: collection was previously subagent-simulated or browser-collected
rather than API-driven, and grading was hand-applied by a party who had also
authored ground truth. Both are now automated and independent.

The first 15 scenarios were run before the round-2 taxonomy expansion
(see `TAXONOMY.md`); s016-s021 (3 new categories, added after reviewing
a real production incident log) were run afterward using the identical
methodology for all three agents and merged in below.

## Headline result

| Agent | Mean score | Causal-chain coverage | Required-elements coverage |
|---|---|---|---|
| **Naive** (symptom echo, no tools) | **0.075** | 0.00 | 0.19 |
| **Claude** (closed-book, full evidence, API) — judged by Gemini | **0.952** | 0.95 | 0.95 |
| **Gemini** (closed-book, full evidence, API) — judged by Claude | **0.978** | 0.97 | 0.98 |

Both frontier models score roughly **13x** the naive floor — the
benchmark's core discrimination signal: diagnosing these incidents
requires actually reading and connecting the evidence, not just
restating the symptom. Under this pass's independent, cross-model
judging, Gemini edges out Claude (0.978 vs. 0.952, a ~2.6-point gap) —
a reversal from every earlier pass, where Claude led. See "Known
limitations" for why this reversal happened and why it should be read
cautiously rather than as "Gemini is now the stronger model."

## Methodology

**Naive baseline** (`harness/agents/naive_agent.py`, `NaiveEchoAgent`) is
fully deterministic and was scored by hand-applying its exact,
documented logic: it returns `root_cause = "The pipeline behaved
unexpectedly: " + symptom.strip()[:200]`, an empty causal chain, and the
fixed proposed fix "Retry the run and monitor; escalate if it recurs."
No tools, no context files. This is pure code — there is no ambiguity in
what it outputs for a given scenario.

**Claude arm (current, API-based)**: collected via
`harness/run_claude_diagnoses.py`, a standalone script that calls
`https://api.anthropic.com/v1/messages` directly (model
`claude-sonnet-4-5`) for each scenario's `symptom` + verbatim
`context_files` — the same `AgentTask` payload the harness would hand a
real agent, with no access to `ground_truth`. This sandbox's outbound
network blocks `api.anthropic.com`, so the script was run by the user
in their own environment with their own API key; all 21 scenarios
completed with no failures or retries. This replaces the previous pass's
subagent-simulated Claude arm (preserved as
`claude_handgraded_deprecated`), which was never a real API call.

**Gemini arm (current, API-based)**: collected via
`harness/run_gemini_diagnoses.py` against
`https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
(model `gemini-3.6-flash`, `temperature=0`), run by the user for the
same network-access reason. Both arms use the identical closed-book
prompt (no tools, no filesystem access, no scenario ID, explicit
`ROOT CAUSE` / `CAUSAL CHAIN` / `PROPOSED FIX` output format), so the
only difference between the two diagnosis sets is the model itself.

**Grading (current, automated, cross-model)**: `harness/run_llm_judge.py`
is a standalone port of `JUDGE_PROMPT_TEMPLATE` and `_score_from_hits()`
from `harness/scoring/rca_judge.py`, run twice: once with
`--judge gemini` (`gemini-3.5-flash`) against the Claude diagnoses, and
once with `--judge claude` (`claude-sonnet-4-5`) against the Gemini
diagnoses. Each judge call submits the ground truth's `causal_chain`,
`required_answer_elements`, and `distractors` alongside the diagnosis
text and asks for a JSON object of per-item hit booleans, which is then
run through the harness's unmodified scoring formula:

```
overall = (0.6 * causal_chain_coverage + 0.4 * required_elements_coverage)
          * distractor_penalty
```

This closes both gaps flagged in the prior pass: the judge is now a
real model call rather than hand-applied by the project author, and the
judge model is always different from the model being graded, so no
model ever grades its own diagnoses.

**Grading anomaly found and disclosed**: while merging results, a
length mismatch was found in one judge response — for s007, Claude's
judge output for Gemini's diagnosis returned a 5-element
`causal_chain_hits` array against a 6-step ground-truth causal chain
(the accompanying rationale text explicitly references "causal step 6,"
so the judge evaluated all 6 steps but its JSON array dropped one
entry). `_score_from_hits()` computes coverage from
`len(causal_chain_hits)` as returned, so this silently used a
denominator of 5 instead of 6, inflating s007's Gemini causal-chain
coverage from an intended 4/6 (0.667) to the recorded 4/5 (0.8) — a
swing of roughly +0.08 on that one scenario's overall score (recorded
0.880 vs. an estimated "correct" 0.800). This is a real limitation of
`run_llm_judge.py`, not a scoring-formula bug: the script does not
currently validate that a judge's returned array length matches the
number of ground-truth items it was asked to grade. The recorded number
(0.880) is published as-is rather than silently corrected, and a
length-validation check (reject and retry the judge call if array
lengths don't match) is flagged as follow-up work.

**Update (2026-09-12): the length-validation fix has been implemented**
in both `run_llm_judge.py` and `harness/scoring/rca_judge.py`'s
`LLMDiagnosisJudge` — a judge response whose `causal_chain_hits` /
`required_element_hits` / `distractor_hits` length doesn't match the
scenario's ground-truth item count now raises instead of scoring, and
the caller retries the judge call (default 3 attempts) rather than
publishing a mismatched denominator. The s007 number in the table below
(0.880) has **not yet been regenerated** with the fix — that requires
re-running `--judge claude --diagnoses-dir harness/out/gemini_api_run
--only s007` with `ANTHROPIC_API_KEY` set, which wasn't available in
the environment this fix was written in. Until that re-run happens,
treat s007's Gemini-judged-by-Claude score as the old, disclosed-buggy
0.880 rather than the corrected ~0.800.

**Keyword agent** (`KeywordHeuristicAgent`) was intentionally excluded
from this comparison. Per its own docstring it's "a toy tool-user...
not a real solver," built to exercise `ToolBelt` during Phase 2
integration testing, not to represent a meaningful Phase 3 data point.

**Fix verification**: not re-run in this pass, for the same reason
documented in earlier passes — the shipped `verify/test_fix.py` files
are self-contained regression tests that don't yet accept an agent's
actual `Diagnosis.fix_code` as input, so re-running them would not
differentiate any of the three agents. Flagged as future work in
`harness/README.md`.

## Per-scenario scores

| ID | Category | Difficulty | Naive | Claude (judged by Gemini) | Gemini (judged by Claude) |
|---|---|---|---|---|---|
| s001 | recovery_temporal_state | hard | 0.000 | 0.747 | 0.747 |
| s002 | rerun_idempotency_failure | medium | 0.100 | 1.000 | 1.000 |
| s003 | train_serving_skew | medium | 0.133 | 1.000 | 1.000 |
| s004 | recovery_temporal_state | medium | 0.133 | 0.914 | 0.914 |
| s005 | recovery_temporal_state | easy | 0.133 | 1.000 | 1.000 |
| s006 | rerun_idempotency_failure | medium | 0.133 | 1.000 | 1.000 |
| s007 | rerun_idempotency_failure | medium | 0.133 | 0.700 | 0.880 |
| s008 | train_serving_skew | hard | 0.133 | 1.000 | 1.000 |
| s009 | train_serving_skew | medium | 0.133 | 1.000 | 1.000 |
| s010 | data_quality_gate_failure | easy | 0.000 | 1.000 | 1.000 |
| s011 | data_quality_gate_failure | easy | 0.000 | 1.000 | 1.000 |
| s012 | data_quality_gate_failure | hard | 0.000 | 1.000 | 1.000 |
| s013 | resource_capacity_lifecycle_failure | easy | 0.133 | 1.000 | 1.000 |
| s014 | resource_capacity_lifecycle_failure | easy | 0.133 | 1.000 | 1.000 |
| s015 | resource_capacity_lifecycle_failure | medium | 0.000 | 0.767 | 1.000 |
| s016 | change_management_failure | medium | 0.000 | 1.000 | 1.000 |
| s017 | change_management_failure | easy | 0.000 | 1.000 | 1.000 |
| s018 | change_management_failure | easy | 0.000 | 0.867 | 1.000 |
| s019 | secondary_model_layer_failure | medium | 0.000 | 1.000 | 1.000 |
| s020 | secondary_model_layer_failure | hard | 0.133 | 1.000 | 1.000 |
| s021 | false_positive_correct_behavior | hard | 0.133 | 1.000 | 1.000 |

s021 is the false-positive scenario (the correct diagnosis is "no bug
exists"). Both models score a perfect 1.000, correctly concluding no
fix is needed rather than inventing one — the judge grades this the
same way as every other scenario, since `required_answer_elements`
already encodes "does not propose an unnecessary code fix."

Naive's nonzero scores are not partial understanding — they come from
required-answer-elements phrased as negative claims (e.g. "does not
conclude X"), which a diagnosis that asserts nothing at all satisfies
vacuously. Its causal-chain coverage is 0.00 on every single scenario,
which is the more meaningful number: it never once correctly identifies
a mechanism.

Under this pass, Claude is the model with more non-perfect scores (5:
s001, s004, s007, s015, s018) versus Gemini (3: s001, s004, s007) — the
reverse of every prior pass, where Gemini trailed Claude. See "Known
limitations" for why this flip is likely a grading-methodology effect
as much as (or more than) a capability difference.

## By category

| Category | Naive mean | Claude mean | Gemini mean |
|---|---|---|---|
| recovery_temporal_state | 0.089 | 0.887 | 0.887 |
| rerun_idempotency_failure | 0.122 | 0.900 | 0.960 |
| train_serving_skew | 0.133 | 1.000 | 1.000 |
| data_quality_gate_failure | 0.000 | 1.000 | 1.000 |
| resource_capacity_lifecycle_failure | 0.089 | 0.922 | 1.000 |
| change_management_failure | 0.000 | 0.956 | 1.000 |
| secondary_model_layer_failure | 0.067 | 1.000 | 1.000 |
| false_positive_correct_behavior | 0.133 | 1.000 | 1.000 |

Claude and Gemini now tie exactly in 5 of 8 categories
(`recovery_temporal_state`, `train_serving_skew`,
`data_quality_gate_failure`, `secondary_model_layer_failure`,
`false_positive_correct_behavior`). Gemini's remaining edge comes
entirely from `resource_capacity_lifecycle_failure` and
`change_management_failure`, both driven by single-scenario misses for
Claude (s015 and s018 respectively) that were perfect scores in the
prior, differently-collected-and-graded pass.

## By difficulty

| Difficulty | Naive mean | Claude mean | Gemini mean |
|---|---|---|---|
| easy (7 scenarios) | 0.057 | 0.981 | 1.000 |
| medium (9 scenarios) | 0.085 | 0.931 | 0.977 |
| hard (5 scenarios) | 0.080 | 0.949 | 0.949 |

Both models are statistically indistinguishable on `hard` scenarios
(0.949 each, identical to two prior passes). Neither model's difficulty
means are monotonic — medium scores below hard for both — the same
non-monotonic pattern seen in every pass so far. At only 21 scenarios (9
medium, 5 hard) this is best read as "these difficulty labels don't
cleanly predict either model's error rate" rather than evidence the
medium tier is miscalibrated.

## Known limitations of this pass

- **The Claude-vs-Gemini score reversal conflates two changed
  variables.** Compared to the prior pass, Claude's diagnosis
  *collection* method changed (subagent-simulated → real API call) at
  the same time its *grader* changed (self-graded by hand → Gemini via
  automated API). Gemini's diagnosis text, by contrast, was already
  API-collected in the prior pass — only its grader changed (hand-applied
  by the project author → Claude via automated API, same judge model
  family both times). That means Gemini's mean-score jump (0.943 → 0.978)
  isolates a grading-method effect fairly cleanly, while Claude's
  mean-score drop (0.978 → 0.952) cannot be cleanly attributed to either
  "real-API Claude reasons differently than the subagent-simulated
  version did" or "Gemini is a stricter judge than Claude's own
  hand-grading of itself" — both changed at once. Isolating these would
  require re-grading the old subagent-collected Claude transcripts with
  the new automated Gemini judge, which hasn't been done. Flagged as
  follow-up work before reading too much into the reversal itself.
- **A judge response array-length mismatch was found and left
  uncorrected in the published number** — see "Grading anomaly found
  and disclosed" in Methodology. Affects s007's Gemini score (recorded
  0.880; likely 0.800 with a correctly-sized array). `run_llm_judge.py`
  should validate hit-array lengths against ground-truth item counts in
  a future revision.
- **The judge pool is still only two model families.** Cross-judging
  removes same-model self-grading, but a third, unrelated model (or
  human review) grading a sample would be a further check worth running
  before treating these numbers as fully settled.
- s001 and s007 remain the two hardest scenarios for both models, as in
  every prior pass, though the two models no longer miss identically:
  s001 is still an exact tie (0.747 each), but s007 now splits
  (Claude 0.700, Gemini 0.880, the latter subject to the array-length
  caveat above). Worth a scenario-authoring look in a future revision —
  e.g. making s007's "engineer's mistaken belief about the `--days`
  flag" more directly evidenced in the context files rather than
  requiring it to be inferred.
- Fix verification exists as a regression-test layer but doesn't yet
  differentiate agents (see Methodology above).
- s004's authored ground truth had a minor internal inconsistency,
  found and fixed in an earlier pass: `causal_chain` step 3 originally
  claimed 2026-08-03 "doesn't yet require" the missing 2026-08-02
  partition, when the code's trailing-window offset math and the
  scenario's own distractor both show 08-03's window *does* include
  08-02. Fixed in `s004/manifest.yaml` prior to the original pass. Both
  models still land at 0.914 on s004 in this pass (identical score,
  identical miss), one of the few scenarios where collection-method and
  grading-method changes happened to cancel out.
- No external validation yet: no engineer outside the project has
  confirmed the scenarios are realistic and solvable. This remains the
  highest-priority next step.
