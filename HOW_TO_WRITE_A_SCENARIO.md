# How to write a PipelineRCA-Bench scenario

A scenario is a self-contained folder that poses one broken-pipeline puzzle to an
AI agent. The agent sees the `context/` files and the `symptom`; it must output
(a) the root cause and (b) a valid fix. The `ground_truth` in `manifest.yaml` is
hidden from the agent and used only for scoring.

Use `s002_duplicate_rows_after_downstream_reclear/` as your template. Copy the
folder, rename it `sNNN_short_description`, and edit. (Not s001 — its ground
truth was rewritten 2026-09-14, so its folder name no longer matches its
current content; s002 hasn't changed and its folder name still does.)

## The folder

```
sNNN_short_description/
├── manifest.yaml          # metadata + hidden ground truth
├── context/               # everything the agent is allowed to see
│   ├── <logs, dag, configs, data samples, git history...>
└── verify/
    └── test_fix.py        # executable check that a proposed fix works
```

## The manifest — the important part

| Field | What it is | Why it matters |
|---|---|---|
| `symptom` | What the on-call engineer is told | The starting point. Keep it realistic — often deceptively clean. |
| `context_files` | List of files the agent sees | The evidence. Real diagnosis needs the answer to be *derivable* from these. |
| `ground_truth.root_cause` | The real answer | Hidden. What the LLM judge grades against. |
| `ground_truth.causal_chain` | Ordered steps from trigger to symptom | Enables partial credit — an agent that gets 3 of 5 links scores better than one that guesses. |
| `ground_truth.distractors` | Plausible-but-WRONG causes present in the context | **This is the craft.** Real logs are full of red herrings. Good distractors are what separate a real benchmark from a toy. |
| `acceptable_fixes` | Fixes that count as correct | Usually more than one valid fix. |
| `partial_credit_fixes` | Mitigations that treat the symptom but not the cause | E.g. "fail loudly" instead of "fix why it failed". |
| `required_answer_elements` | Things the answer MUST contain | Anti-gaming: stops a vague answer scoring full marks. |

## The five things that make a scenario GOOD

1. **The symptom shouldn't reveal the cause.** If the error message says exactly
   what's wrong, there's nothing to diagnose. The best scenarios have a symptom
   that points *away* from the real cause (or no error at all — see s001).

2. **The answer must be derivable.** A competent engineer, given only `context/`,
   should be able to reach the root cause. If they can't, evidence is missing.

3. **Plant real distractors.** For every scenario, add 2–4 plausible-but-wrong
   causes into the context — a benign warning, an unrelated recent commit, a
   scary-looking metric that's actually fine. This is where your production
   experience is irreplaceable: you know what *looks* like the cause but isn't.

4. **Reward depth over surface.** The obvious fix ("retry it", "make it fail
   loudly") should earn only partial credit. Full credit requires tracing to the
   real cause. Encode that in `acceptable_fixes` vs `partial_credit_fixes`.

5. **Keep it fully synthetic.** Invented zones, model IDs, log lines, data. No
   real employer schemas, numbers, or system names. The *pattern* is yours to
   contribute; the *artifacts* are fabricated.

## False-positive scenarios ("nothing is actually broken")

Most scenarios present a real bug the agent must find and fix. A small
number (category 8, `false_positive_correct_behavior`) present a
symptom that *looks* like a bug but isn't -- the pipeline is working as
designed, and the correct answer is "no fix needed." These test
precision: does the agent fabricate a plausible-sounding root cause
under pressure to find one, or correctly conclude there's nothing to
fix.

These scenarios use two schema differences from a normal scenario:

- `is_false_positive: true` at the top level of `ground_truth`, so the
  harness and judge know not to expect (or reward) a proposed code fix.
- `acceptable_conclusion` replaces `acceptable_fixes` / `partial_credit_fixes`.
  It describes the correct diagnosis -- typically "each of these
  sub-populations is legitimately excluded for reason X, Y, Z; no
  pipeline change needed" -- and may include a legitimate *process* fix
  (e.g. better downstream-facing documentation) that doesn't touch the
  pipeline itself.

`required_answer_elements` for these should include an explicit
anti-gaming check that the answer does *not* propose an unnecessary
code/pipeline change -- an agent that invents a fix for a non-bug should
score worse than one that correctly says "no action needed," not
better. See `s021` for a worked example.

## Difficulty guide

- **easy** — cause is in the logs if you read carefully; few distractors.
- **medium** — cause requires cross-referencing 2–3 files (logs + git + config).
- **hard** — cause isn't in the obvious place at all (another day's run, a config
  the failure doesn't mention, a silent success). s001 is hard.

Aim for a mix: ~5 easy, ~7 medium, ~3 hard across the first 15.
