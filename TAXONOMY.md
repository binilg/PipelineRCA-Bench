# PipelineRCA-Bench scenario taxonomy

21 scenarios across 8 failure categories. Every scenario shares the same
fictional company's `daily_forecast_scoring` pipeline (Airflow + Python
+ pandas, retail demand forecasting) but is fully synthetic and
self-contained per `HOW_TO_WRITE_A_SCENARIO.md`.

Difficulty mix across all 21: 7 easy, 9 medium, 5 hard.

Categories 1-5 (15 scenarios) were the original set. Categories 6-8 (6
scenarios, s016-s021) were added after reviewing a real production
incident log across an org's forecasting pipelines -- see "Scenario
review, round 2" at the bottom of this file for that process and what
it changed.

## 1. recovery_temporal_state

A failure or gap on one day gets silently papered over -- by a fallback,
a zero-fill, or an unbackfilled gap -- so a later run looks clean while
quietly depending on bad or missing state from an earlier point in time.

- **s001** (hard) -- new zone's models have no trained artifact; scoring silently falls back to yesterday's forecast, under the alert threshold.
- **s004** (medium) -- an unbackfilled failed run leaves a hole in a 3-day rolling-average feature, which gets zero-filled instead of excluded.
- **s005** (easy) -- one zone's vendor actuals feed doesn't land for a day; missing data is treated as zero sales rather than "no data."

*Occurs in the wild as*: silent fallback / stale-cache-on-error patterns are a well-documented class of production ML incident (see e.g. Google's "Hidden Technical Debt in Machine Learning Systems," and common MLOps postmortems around "fail open" error handling).

## 2. rerun_idempotency_failure

A retry or backfill -- individually reasonable -- interacts badly with a
pipeline step that isn't safe to run twice, producing duplicate data or
duplicate side effects without any task ever reporting failure.

- **s002** (medium) -- clearing a failed downstream task with `--upstream` re-triggers an already-succeeded append-only write, doubling the partition.
- **s006** (medium) -- a retried upload re-fires a partner notification webhook that isn't gated on final success, causing the partner to double-ingest.
- **s007** (medium) -- a backfill CLI's `--days` flag is misunderstood, silently reprocessing 3 extra already-finalized days and staling a downstream rollup.

*Occurs in the wild as*: this is the classic "at-least-once execution without idempotent writes" problem discussed extensively in distributed-systems and workflow-orchestration literature (e.g. Airflow's own documentation on task idempotency, Google Cloud's Dataflow exactly-once processing guidance).

## 3. train_serving_skew

Training and serving quietly disagree about what a feature means or
contains. Nothing crashes -- the mismatch produces confidently wrong
predictions instead of an error.

- **s003** (medium) -- a categorical encoder trained before a new SKU group existed silently aliases it to an unrelated bucket instead of raising.
- **s008** (hard) -- an upstream currency-unit change (cents to dollars) desyncs a numeric feature from the scaler fit at training time.
- **s009** (medium) -- promoting a challenger model updates the training feature manifest but not the separate serving manifest, so a new feature is never computed and gets zero-filled.

*Occurs in the wild as*: training/serving skew is one of Google's canonical "ML Test Score" anti-patterns and a widely cited root cause of production model degradation.

## 4. data_quality_gate_failure

A validation or stability gate exists specifically to catch this class
of problem -- and doesn't, because of a bug or a blind spot in the gate
itself, not the data pipeline it's guarding.

- **s010** (easy) -- a refactor bug makes the stability check compare each day's partition to itself, so it always reports Green.
- **s011** (easy) -- a coverage threshold set for an old, smaller model count never gets raised, so it no longer catches a real partial-write shortfall.
- **s012** (hard) -- a forecast-cap validation rule was tested only against dev data containing exclusively each-unit SKUs, so it silently clips legitimate high-volume case-unit forecasts in production.

*Occurs in the wild as*: "tested the check, not the check's assumptions" is a recurring theme in data-quality engineering postmortems (e.g. Great Expectations' and Monte Carlo's public writeups on data quality incidents that validation suites missed).

## 5. resource_capacity_lifecycle_failure

Infrastructure-layer decisions -- storage lifecycle policies, memory
limits, cloud capacity -- interact with the pipeline in ways nobody
who owns the pipeline logic anticipated.

- **s013** (easy) -- a generic storage lifecycle policy archives a reference file the pipeline reads daily but never writes to, since "unmodified" isn't the same as "unused."
- **s014** (easy) -- a memory spike from a SKU-onboarding event gets a zone's scoring pod OOM-killed, and a best-effort skip-and-continue policy quietly drops it instead of retrying or alerting.
- **s015** (medium) -- a regional cloud capacity shortfall means the autoscaler can't provision enough workers, and the scheduler's "deferred, not failed" design silently and permanently drops whichever zones missed the cutoff.

*Occurs in the wild as*: cloud capacity shortfalls, OOM-kills under Kubernetes, and storage lifecycle/archival policies are all documented, provider-acknowledged categories of operational incident (e.g. cloud providers' own status-page histories of regional capacity constraints, Kubernetes' documented OOMKilled/exit-137 behavior).

## 6. change_management_failure

A code release, a config rename, or a schema migration is individually
reasonable and passes its own tests -- but breaks something the change
didn't (and structurally couldn't) exercise: an untested input
population, an environment the change was never validated against, or
a downstream consumer whose access wasn't part of the change at all.

- **s016** (medium) -- a performance rewrite of a recency feature is tested only against SKUs with long sales history, silently mis-scoring every newly launched SKU.
- **s017** (easy) -- a new library import works in dev (installed there for an unrelated reason months earlier) but was never added to the prod build manifest.
- **s018** (easy) -- a table rename ships correctly on the write side, but the separate access-provisioning automation's static allowlist was never updated, so no downstream consumer can read the new table.

*Occurs in the wild as*: "tested the change, not the change's blast radius" is one of the most common root-cause patterns in real deployment postmortems -- unrepresentative test/QA sampling, environment drift between dev and prod, and access-provisioning gaps after a schema migration are all standard categories in SRE incident retrospectives (e.g. Google's SRE book chapters on postmortem culture and change management).

## 7. secondary_model_layer_failure

A correction or adjustment layer sits on top of a core model and is
designed to be safely ignorable when something goes wrong with it --
which is exactly what makes its own failures invisible. It fails
silently (no-ops instead of erroring) or fails to bound itself (an
adjustment that should be transient becomes structurally permanent).

- **s019** (medium) -- a config key rename desyncs the adjustment layer's loader from its config file; a broad try/except silently disables the adjustment for every zone, logged only at DEBUG.
- **s020** (hard) -- a one-off severe-weather week stays inside the adjustment model's trailing retrain window for six consecutive weekly retrains, and with no anomaly exclusion or magnitude cap, a transient event gets relearned as a persistent correction.

*Occurs in the wild as*: "fail open" layered/ensemble correction systems are a known blind spot in ML system design -- a component built to be non-blocking by design is, for the same reason, rarely monitored as carefully as the primary path (see Google's "Hidden Technical Debt in Machine Learning Systems" on correction cascades and pipeline jungles).

## 8. false_positive_correct_behavior

The pipeline is working exactly as designed. What looks like a bug from
the outside is legitimate, expected behavior, and the correct diagnosis
is "no fix needed." These scenarios test precision, not just recall --
whether an agent under pressure to find a root cause will fabricate one
rather than correctly conclude nothing is broken.

- **s021** (hard) -- downstream reports forecast "missing" for a batch of sku-store combinations; every one is legitimately excluded (non-forecastable, not yet active, not ranged at that store, or intentionally discontinued), and the correct answer is that no pipeline change is needed.

*Occurs in the wild as*: alert fatigue and false-positive escalations are a well-documented cost center in on-call/incident-response literature; testing whether a diagnostic system (human or AI) can correctly say "this isn't a bug" is as important as testing whether it can find real ones.

---

## Scenario review, round 2

The original 15 scenarios were fully synthetic, authored from general
domain knowledge of ML pipeline failure modes. After that set was
built, a real production incident log (24 actual incidents from a
retail demand-forecasting org, spanning roughly a year) was reviewed
against it as a validation and gap-finding exercise.

**What validated well**: several real incidents mapped almost exactly
onto scenarios already in the set -- a storage lifecycle policy
archiving a live dependency (s013), a missing model for a category
(s001), a VM capacity shortfall causing fallback (s015), and a code bug
causing a forecast file to publish twice (s006) all had close
real-world analogues already covered, which was a useful sanity check
that the original 15 weren't purely speculative.

**What was missing**: the real log surfaced five patterns the original
5-category taxonomy had no coverage for at all -- release/deployment
regressions, environment drift between dev and prod, access-provisioning
gaps, secondary/adjustment-model-layer failures (as distinct from
core-model train/serving skew), and false-positive "nothing is actually
broken" cases. Categories 6-8 above and scenarios s016-s021 were added
to close those gaps. A few real incidents were deliberately *not* turned
into new scenarios -- near-duplicates of patterns already covered (three
separate real incidents were all "cloud infra issue causes fallback,"
which s014/s015 already cover), or too operationally thin to support a
real diagnostic chain (e.g. "a config file was missing a copy job failed,
requeuing fixed it" is a one-line fix with no real RCA depth).
