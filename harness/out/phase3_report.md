# PipelineRCA-Bench — Phase 3 Results

*Current as of 2026-08-23, with s001 rewritten and re-collected/re-graded
on 2026-09-14 and s007 rewritten and re-collected/re-graded on
2026-11-15 (see the update notes directly below). Supersedes all
earlier passes; superseded scores are retained in `phase3_results.json`
under `*_deprecated` keys for audit trail.*

**Update (2026-09-14): s001's ground truth was rewritten.** The original
s001 ("new zone's training config never updated, so its models were
never trained") had an unresolved internal inconsistency: the fallback
path it relied on needs a legitimate prior-day forecast to fall back
to, but the affected models were only 3 days old at the incident date,
with no evidence of how a valid prior-day forecast could have existed
for them. Rather than leave that gap, s001 was rewritten around a
different mechanism — an undersized worker VM, sized off a lagging
rolling average, that couldn't handle a same-day data-volume spike —
which does not have that gap (these are long-running models with a
real prior day to fall back to). Every number below reflects the new
s001; see `scenarios/s001_undersized_vm_silent_fallback/manifest.yaml`
and its `context/` for the current version. Its folder was renamed to
match (from `s001_silent_fallback_missing_model`) so the directory
name doesn't lie about what's inside. s001 also moved category, from
`recovery_temporal_state` to `resource_capacity_lifecycle_failure`.

**Update (2026-11-15): s007's context and ground truth were rewritten.**
The original s007's evidence contradicted itself: the backfill log ran
the backfill on 2026-07-29 (before the 2026-08-01 rollup it supposedly
made stale, and while "reprocessing" dates that hadn't happened yet);
`rollup_report_comparison.csv` showed 4 mismatched days against a
ground truth and symptom of 3; a distractor claimed row counts were
unchanged when `row_counts.csv` showed every count changing; and the
engineer's mistaken belief about `--days` (causal steps 1-2) was not
evidenced anywhere in the context. The rewrite keeps the same mechanism
but fixes the timeline (backfill on 2026-08-04 of 2026-07-26, after the
week-of-07-27 rollup ran on 2026-08-03), adds `on_call_notes.txt` to
evidence the engineer's belief, and makes every file agree on exactly 3
stale days. Both arms were then re-collected for s007 only
(`run_claude_diagnoses.py --only s007` with `claude-sonnet-4-5`,
`run_gemini_diagnoses.py --only s007` with `gemini-3.6-flash`) and
cross-graded with `run_llm_judge.py --only s007`. Both now score 1.000
(previously Claude 0.700, Gemini 0.880); the old values are kept under
`*_pre_rewrite_deprecated` keys in `phase3_results.json`. Every number
below reflects the new s007. Two caveats specific to this re-run:

- **Claude's 1.000 on s007 is a lenient grade.** Claude's diagnosis
  treats reprocessing 4 days as intentional ("due to the 4-day rolling
  window") and never identifies the engineer's misreading of `--days`,
  yet the Gemini judge marked causal step 2 and required element 1 as
  hits. A strict grade would be roughly 0.80-0.87. It is published as
  the judge returned it, consistent with how every other score here is
  handled, and noted in `claude_graded_by_gemini.json`.
- **Judge model version.** The Gemini judge for this one re-grade was
  `gemini-3.6-flash` (the script's current default); the other 20
  Claude scenarios were graded by `gemini-3.5-flash`.

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
| **Naive** (symptom echo, no tools) | **0.079** | 0.00 | 0.20 |
| **Claude** (closed-book, full evidence, API) — judged by Gemini | **0.974** | 0.98 | 0.97 |
| **Gemini** (closed-book, full evidence, API) — judged by Claude | **0.996** | 0.99 | 1.00 |

Both frontier models score roughly **12x** the naive floor — the
benchmark's core discrimination signal: diagnosing these incidents
requires actually reading and connecting the evidence, not just
restating the symptom. Under this pass's independent, cross-model
judging, Gemini edges out Claude (0.996 vs. 0.974, a ~2.2-point gap) —
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
diagnoses (except the 2026-11-15 s007 re-grade of Claude, judged by
`gemini-3.6-flash`; see the update note above). Each judge call submits the ground truth's `causal_chain`,
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
publishing a mismatched denominator.

**Update (2026-11-15): resolved.** The affected 0.880 is gone from the
current results: s007 was rewritten and re-graded with the length check
in place (see the s007 update note at the top). The 0.880 survives only
as `gemini_pre_rewrite_deprecated` in `phase3_results.json`.

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
| s001 | resource_capacity_lifecycle_failure | hard | 0.100 | 0.900 | 1.000 |
| s002 | rerun_idempotency_failure | medium | 0.100 | 1.000 | 1.000 |
| s003 | train_serving_skew | medium | 0.133 | 1.000 | 1.000 |
| s004 | recovery_temporal_state | medium | 0.133 | 0.914 | 0.914 |
| s005 | recovery_temporal_state | easy | 0.133 | 1.000 | 1.000 |
| s006 | rerun_idempotency_failure | medium | 0.133 | 1.000 | 1.000 |
| s007 | rerun_idempotency_failure | medium | 0.133 | 1.000* | 1.000 |
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

\* s007 was rewritten on 2026-11-15 and re-run; Claude's 1.000 there is
a lenient grade (strict estimate ~0.80-0.87) — see the update note at
the top.

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

Under this pass, Claude is the model with more non-perfect scores (4:
s001, s004, s015, s018) versus Gemini (1: s004) — the
reverse of every prior pass, where Gemini trailed Claude. See "Known
limitations" for why this flip is likely a grading-methodology effect
as much as (or more than) a capability difference.

## By category

| Category | Naive mean | Claude mean | Gemini mean |
|---|---|---|---|
| recovery_temporal_state | 0.133 | 0.957 | 0.957 |
| rerun_idempotency_failure | 0.122 | 1.000 | 1.000 |
| train_serving_skew | 0.133 | 1.000 | 1.000 |
| data_quality_gate_failure | 0.000 | 1.000 | 1.000 |
| resource_capacity_lifecycle_failure | 0.092 | 0.917 | 1.000 |
| change_management_failure | 0.000 | 0.956 | 1.000 |
| secondary_model_layer_failure | 0.067 | 1.000 | 1.000 |
| false_positive_correct_behavior | 0.133 | 1.000 | 1.000 |

Claude and Gemini now tie exactly in 6 of 8 categories
(`recovery_temporal_state`, `rerun_idempotency_failure`, `train_serving_skew`,
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
| medium (9 scenarios) | 0.085 | 0.965 | 0.990 |
| hard (5 scenarios) | 0.100 | 0.980 | 1.000 |

The two models are no longer near-identical on `hard` scenarios the
way they were in every prior pass (0.949 each) — Gemini now scores a
clean 1.000 on all five, while Claude's 0.980 reflects its one miss on
the rewritten s001 (see per-scenario table). Neither model's difficulty
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
  family both times). (The means in the rest of this bullet are as
  measured at the time, before the s001 and s007 rewrites.) That means
  Gemini's mean-score jump (0.943 → 0.978)
  isolates a grading-method effect fairly cleanly, while Claude's
  mean-score drop (0.978 → 0.952) cannot be cleanly attributed to either
  "real-API Claude reasons differently than the subagent-simulated
  version did" or "Gemini is a stricter judge than Claude's own
  hand-grading of itself" — both changed at once. Isolating these would
  require re-grading the old subagent-collected Claude transcripts with
  the new automated Gemini judge, which hasn't been done. Flagged as
  follow-up work before reading too much into the reversal itself.
- **Judges can be lenient.** Two concrete cases found on review: on
  s002, Claude-as-judge credited Gemini with a causal step whose second
  half ("nothing in the run history indicates a rerun happened") the
  diagnosis never states; on the rewritten s007, Gemini-as-judge gave
  Claude full marks despite Claude missing the `--days` misreading
  entirely (strict estimate ~0.80-0.87). Scores are published as the
  judges returned them; a stricter or third judge would likely pull
  both arms down slightly.
- The judge hit-array length anomaly disclosed in Methodology is fixed
  in code and no longer affects any current number (see the
  2026-11-15 update there).
- **The judge pool is still only two model families.** Cross-judging
  removes same-model self-grading, but a third, unrelated model (or
  human review) grading a sample would be a further check worth running
  before treating these numbers as fully settled.
- **s001's numbers are not comparable to any pre-2026-09-14 pass** —
  see the update note at the top of this report. Its ground truth was
  rewritten, not just re-collected or re-graded, so its old scores
  (0.747 for both models, in every prior pass including this one before
  the rewrite) describe a scenario that no longer exists. The
  `*_pre_rewrite_deprecated` keys in `phase3_results.json` preserve the
  old numbers for audit trail.
- **s007's numbers are not comparable to any pre-2026-11-15 pass.**
  It was previously the hardest scenario for both models (Claude 0.700,
  Gemini 0.880), but review showed that was largely caused by
  self-contradicting evidence rather than diagnostic difficulty; after
  the rewrite both models score 1.000. The old values are preserved
  under `*_pre_rewrite_deprecated` keys in `phase3_results.json`.
- **Ceiling effect.** With s007 fixed, the two frontier arms are at
  0.974 and 0.996 with 17/21 and 20/21 perfect scores. In this
  closed-book setting (all evidence pasted into the prompt) the set no
  longer separates frontier models well; harder scenarios, larger and
  noisier context, or a tool-using protocol where the agent must find
  the evidence are the natural next steps.
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
