# Gemini Closed-Book Diagnoses -- Raw Transcripts

Each scenario was submitted to the Gemini API (`gemini-3.6-flash`) using the exact same closed-book prompt (symptom + verbatim context files, no ground truth) as the harness's `AgentTask` would provide. This supersedes the earlier manual browser-run transcripts. Responses are pasted verbatim below.

Ground truth (`manifest.yaml`) was never included in any prompt.

---

## s001 — resource_capacity_lifecycle_failure (hard)

*Collected 2026-09-14, against the rewritten ground truth (see
`harness/out/phase3_report.md`'s 2026-09-14 update note). The original
s001 transcript, against the missing-training-config root cause, is no
longer part of this file; the scenario it describes no longer exists.*

ROOT CAUSE:
Models **M_0147**, **M_0148**, and **M_0149** (all in zone `Z_NW`) fell back to prior-day forecasts because feature generation exceeded the 8 GB memory limit of the assigned `medium` VM tier. This occurred because a partner EDI feed with a multi-week backfill was enabled on 2026-07-14, causing `Z_NW` daily data volume to spike from ~6.0 GB to 24.8 GB. Because VM sizing is computed nightly from a trailing 7-day rolling average prior to the run, worker sizing could not anticipate the same-day volume spike, resulting in a `MemoryError` during feature joins that safely triggered the built-in fallback handler as designed.

CAUSAL CHAIN:
1. Commit `8a4c1f0` enabled the partner EDI feed for zone `Z_NW`, introducing a multi-week backfill on 2026-07-14.
2. Incoming data volume for `Z_NW` spiked to 24.8 GB (nominal volume is ~6.0 GB).
3. The nightly VM sizing job sized `Z_NW` worker nodes based on the trailing 7-day average (6.0 GB), provisioning a `medium` VM tier with an 8 GB memory budget.
4. During feature generation, input frames after joins required 9.9 GB (M_0147), 8.6 GB (M_0148), and 8.1 GB (M_0149), exceeding the 8 GB budget and raising `MemoryError`.
5. The `score_one` exception handler caught the errors and invoked `_fallback_to_prior_day`, stamping 2026-07-13 forecasts for 2026-07-14.
6. The DAG completed successfully because 3 fallback substitutions remained within `FALLBACK_TOLERANCE` (5), but the downstream fallback monitor alerted on the substituted models.

PROPOSED FIX:
No code fix needed. The pipeline functioned as designed: the one-time data spike safely triggered fallback predictions without crashing the pipeline, remaining well within the configured tolerance threshold (3 out of 5). Furthermore, subsequent runs automatically self-healed as the 7-day rolling average incorporated the spike and upgraded `Z_NW` to tier `large` (24 GB) starting 2026-07-15. If fresh (non-fallback) forecasts are strictly required for `M_0147`, `M_0148`, and `M_0149` for the 2026-07-14 partition, an operator can manually re-trigger scoring for those three models on a `large` VM.

---

## s002 — rerun_idempotency_failure (medium)

ROOT CAUSE:
When the `publish_to_warehouse` task failed due to a network timeout, the operator cleared the task with the `--upstream` flag, causing the upstream `score_all_models` and `write_forecast_partition` tasks to re-execute for `run_date=2026-07-16`. Because `write_forecast_partition` uses `df.to_parquet(path, mode="append")` without deleting prior output or overwriting existing files, the second run appended duplicate Parquet files into `/warehouse/forecasts/run_date=2026-07-16`. This doubled the row count from 1,294,075 to 2,588,150 for that partition and caused `forecast_qty` to nearly double (+97.8% uplift) when published to the analytics warehouse.

CAUSAL CHAIN:
1. `publish_to_warehouse` timed out on its initial run for `run_date=2026-07-16` after `score_all_models` and `write_forecast_partition` had already succeeded and written 1,294,075 rows to `/warehouse/forecasts/run_date=2026-07-16`.
2. On-call ops cleared `publish_to_warehouse` using `--upstream`, which reset and re-ran `score_all_models` and `write_forecast_partition`.
3. `write_forecast_partition` ran a second time and called `df.to_parquet(path, mode="append")`, appending a duplicate set of 1,294,075 rows into the existing partition directory.
4. `publish_to_warehouse` succeeded on the second attempt and published the duplicated dataset (2,588,150 total rows) to the warehouse.
5. The nightly uplift health check summed `forecast_qty` over the duplicated partition data, recording 31,822,410 total forecast quantity (+97.8% over the prior day's 16,088,505) and triggering an alert.

PROPOSED FIX:
1. Update `write_forecast_partition` in `context/dag.py` to write partitions idempotently by passing `mode="overwrite"` to `to_parquet` (or deleting/clearing the target directory `/warehouse/forecasts/run_date={run_date}` before writing).
2. Remediate the corrupted partition for `2026-07-16` by removing duplicate Parquet files or re-running the scoring and overwrite process for that `run_date`, then re-publishing the corrected dataset to the analytics warehouse.

---

## s003 — train_serving_skew (medium)

ROOT CAUSE:
On 2026-07-18, Merchandising added 40 new SKUs under a new `sku_group` (`SEASONAL_PROMO`) to `sku_catalog.csv`, but the active scoring models and `training_config.yaml` were last updated on 2026-06-01 and only recognize six categorical values. When `feature_pipeline.py` encoded `SEASONAL_PROMO`, `_SKU_GROUP_INDEX.get(sku_group, 0)` failed to find the key in `known_values` and silently defaulted to index `0` (`GROCERY`). Consequently, all `SEASONAL_PROMO` SKUs were scored using `GROCERY` feature representations, causing the models to produce severely inaccurate forecasts (187.4% MAPE) without throwing any pipeline errors.

CAUSAL CHAIN:
1. Merchandising committed catalog changes adding 40 SKUs with `sku_group="SEASONAL_PROMO"` on 2026-07-18 (commit `c92a41f`).
2. `training_config.yaml` (last updated on 2026-06-01) did not contain `SEASONAL_PROMO` in `feature_encoders.sku_group.known_values`.
3. During the 2026-07-20 forecast run, `score_zone` invoked `build_features` for the new `SEASONAL_PROMO` SKUs.
4. `encode_sku_group` attempted to look up `SEASONAL_PROMO` in `_SKU_GROUP_INDEX` and defaulted to index `0` (`GROCERY`).
5. The model scored all 40 `SEASONAL_PROMO` SKUs across all six zones as regular `GROCERY` items, completing without runtime errors.
6. Once actual demand data arrived 3 days later, the accuracy monitor detected a 187.4% MAPE anomaly for `sku_group=SEASONAL_PROMO`.

PROPOSED FIX:
1. Retrain the model family and regenerate `training_config.yaml` so that `known_values` includes `SEASONAL_PROMO` and the model learns appropriate weights for the new category.
2. Modify `encode_sku_group` in `feature_pipeline.py` to raise an explicit exception or emit a high-severity warning when an unknown category is encountered during inference rather than silently mapping unrecognized categories to index `0`.

---

## s004 — recovery_temporal_state (medium)

ROOT CAUSE:
In `feature_loader.py`, the `trailing_avg` function catches `FileNotFoundError` when an actuals parquet partition is missing and silently imputes `0.0` for that day's demand. On 2026-08-02, a transient database connection pool exhaustion prevented the actuals partition for 2026-08-02 from being written, and on-call operations deferred the backfill to a weekly sweep. When `daily_forecast_scoring` ran for 2026-08-04, its 3-day trailing window included 2026-08-02; treating this missing partition as zero demand severely depressed the input feature `trailing_3d_avg`, leading the scoring models to output a collapsed forecast total (-42%).

CAUSAL CHAIN:
1. On 2026-08-02, a database connection pool exhaustion interrupted actuals processing, resulting in no partition being written to `/warehouse/actuals/zone={zone}/run_date=2026-08-02/total.parquet`.
2. On-call operations deferred backfilling the missing 2026-08-02 actuals partition until the weekly Friday sweep.
3. On 2026-08-04, `daily_forecast_scoring` executed `build_features`, invoking `trailing_avg` with a 3-day lookback window covering 2026-08-03, 2026-08-02, and 2026-08-01.
4. `trailing_avg` encountered a `FileNotFoundError` when attempting to load the 2026-08-02 partition and silently assigned a demand value of `0.0`.
5. The zero-imputation artificially lowered `trailing_3d_avg` across active models, causing the generated forecasts for 2026-08-04 to drop by 42% and trigger the health check alert.

PROPOSED FIX:
1. Backfill the missing actuals partition for `2026-08-02` in `/warehouse/actuals/` immediately so that current scoring runs receive accurate historical actuals.
2. Update `trailing_avg` in `context/feature_loader.py` to stop treating missing partitions as `0.0` demand. Instead, either average only over available partitions within the trailing window (e.g., divide by non-missing count) or raise an exception to fail the DAG task explicitly when required upstream actuals partitions are absent.

---

## s005 — recovery_temporal_state (easy)

ROOT CAUSE:
The data ingestion pipeline allowed feature building to proceed with an incomplete vendor POS dataset when zone Z_SW failed to upload actuals due to a public holiday. In `build_features()`, a left join with actuals leaves missing zone data as null, which is then explicitly filled with `0.0` (`merged["actual_qty"].fillna(0.0)`). This improperly treated the unreceived vendor feed as zero historical sales rather than missing data, leading the scoring models to output severely depressed forecast volumes for zone Z_SW.

CAUSAL CHAIN:
1. Zone Z_SW vendor site was closed for a public holiday on 2026-08-05, resulting in no vendor POS feed being uploaded.
2. The ingestion process proceeded without blocking on partial landing (5 of 6 feeds landed), leaving Z_SW actuals out of `/warehouse/actuals/run_date=2026-08-05`.
3. `build_features()` left-joined the SKU catalog with the incomplete actuals table, resulting in null `actual_qty` values for all Z_SW SKUs.
4. `merged["actual_qty"].fillna(0.0)` converted all null Z_SW actuals to zero sales.
5. Forecast models scored Z_SW using 0.0 actuals as input features, causing Z_SW forecasts to artificially collapse.
6. Total forecast volume dropped by 18% overall, triggering the `uplift_health_check` alert and regional ops investigation.

PROPOSED FIX:
1. Add an ingestion gate in the DAG or ingestion pipeline that validates all expected zone feeds have landed for the `run_date` before proceeding with feature engineering, raising a blocking dependency error if feeds are missing.
2. Modify `build_features()` in `context/dag.py` so missing vendor feeds are not blindly converted to zero sales (`fillna(0.0)`). Instead, handle unlanded feeds by failing the job or using an appropriate fallback strategy (such as forward-filling prior day actuals or explicit null/imputation handling) to distinguish missing feed data from actual zero sales.

---

## s006 — rerun_idempotency_failure (medium)

ROOT CAUSE:
The `upload_to_partner_feed` task calls `notify_partner_webhook` unconditionally before executing `_transfer_file` on every task execution attempt, without gating on upload success or including an idempotency key. On the first attempt for run_date 2026-07-25, `notify_partner_webhook` successfully sent a notification at 05:10 UTC prior to `_transfer_file` timing out and failing the task. When the task was retried on attempt 2 at 05:16 UTC, `notify_partner_webhook` ran again and dispatched a second notification before completing the upload, leading the partner system to trigger ingestion twice for the same run date.

CAUSAL CHAIN:
1. `upload_to_partner_feed` begins attempt 1 and calls `notify_partner_webhook` before initiating the file transfer.
2. The partner receives the first "forecast-ready" webhook at 05:10 UTC and triggers downstream ingestion.
3. `_transfer_file` times out after 60 seconds on attempt 1, causing the task to fail and requeue.
4. The task retries at 05:16 UTC for attempt 2 and executes `notify_partner_webhook` a second time before `_transfer_file`.
5. The partner receives the second "forecast-ready" webhook at 05:16 UTC and ingests the forecast file a second time due to lack of idempotency/deduplication.
6. `_transfer_file` succeeds on attempt 2, marking the task complete internally while leaving duplicate ingestions on the partner side.

PROPOSED FIX:
Move the `notify_partner_webhook(run_date)` call in `dag.py` so it executes after `_transfer_file(run_date, timeout_s=60)` succeeds rather than before. In addition, configure an `idempotency_key` (such as `f"daily_forecast-{run_date}"`) in `partner_feed_config.yaml` and include it in the webhook payload so partner endpoints can deduplicate requests across retries.

---

## s007 — rerun_idempotency_failure (medium)

ROOT CAUSE:
A manual backfill (`backfill_cli.py`) reprocessed and overwrote the daily forecast partitions for run dates 2026-07-28 through 2026-07-31 with updated data. Because `weekly_rollup_job.py` generates a static CSV report (`/reports/weekly_rollup_2026-07-28.csv`) on Mondays and lacks an automated trigger or partition-versioning mechanism to refresh reports when underlying daily partitions are modified after generation, the stored rollup report retained the pre-backfill values and drifted out of sync with the updated warehouse partitions.

CAUSAL CHAIN:
1. `backfill_cli.py` was executed with `--start-date 2026-07-28 --days 4`, reprocessing daily scoring for dates 2026-07-28 through 2026-07-31.
2. The backfill overwrote the parquet partitions in `/warehouse/forecasts/run_date=...` for those four dates, updating their row counts and forecast values.
3. The weekly rollup report generated on 2026-08-01 was computed using the original pre-backfill partition values (or before the backfill overwrote the data).
4. `weekly_rollup_job.py` did not detect or listen for updates to historical forecast partitions, leaving `/reports/weekly_rollup_2026-07-28.csv` unchanged.
5. Finance compared the static rollup report CSV against current partition values, discovering mismatches across the four backfilled dates (2026-07-28 to 2026-07-31).

PROPOSED FIX:
1. Immediately re-run `run_weekly_rollup("2026-07-28", "2026-08-03")` to regenerate `/reports/weekly_rollup_2026-07-28.csv` with the backfilled forecast partition data.
2. Update the pipeline DAG or `backfill_cli.py` to automatically identify and re-trigger affected `weekly_rollup_job` runs whenever historical forecast partitions are reprocessed.

---

## s008 — train_serving_skew (hard)

ROOT CAUSE:
On August 4, 2026, zone Z_SE migrated its point-of-sale reporting system, changing `avg_unit_price` in its daily pricing export from cents to dollars (e.g., reporting 15.0 instead of 1500.0). However, `context/feature_pipeline.py` passes raw `avg_unit_price` directly into `_PRICE_SCALER`, which was fit on cents-denominated data (`mean=1500.0`, `std=150.0`). Because there is no unit normalization in the feature pipeline, dollar values (~15.0) generate extreme negative z-scores (~ -9.9), causing the demand forecasting model to produce severely depressed forecast outputs for zone Z_SE.

CAUSAL CHAIN:
1. On 2026-08-04, Z_SE migrated its pricing export system to report `avg_unit_price` in dollars instead of cents.
2. `daily_forecast_scoring` ingests the new dollar-based `avg_unit_price` values (e.g., 15.0) for Z_SE and passes them to `scale_avg_unit_price()`.
3. `scale_avg_unit_price()` evaluates raw dollar inputs against `_PRICE_SCALER` expecting cents, calculating `(15.0 - 1500.0) / 150.0 = -9.9`.
4. The demand forecasting model receives these severe negative z-scores during scoring and produces forecasts ~60% below baseline for Z_SE.
5. `uplift_health_check` detects the forecast drop starting 2026-08-04 and triggers consecutive ALERT warnings for Z_SE.

PROPOSED FIX:
Update `scale_avg_unit_price()` in `context/feature_pipeline.py` to convert raw `avg_unit_price` values to cents (multiplying by 100.0) before applying `_PRICE_SCALER`, or re-fit `_PRICE_SCALER` on dollar units and retrain the model to expect dollars.

---

## s009 — train_serving_skew (medium)

ROOT CAUSE:
When `demand_forecast_v5` was promoted to production on 2026-08-06, `serving_feature_manifest.yaml` was not updated to include `promo_flag` in `active_model_features`. As a result, the scoring pipeline loaded feature vectors omitting `promo_flag`. The inference wrapper filled missing feature values with 0, causing all SKUs on active promotions to be evaluated with `promo_flag = 0` and producing systematically underforecasted demand estimates for promoted SKUs.

CAUSAL CHAIN:
1. Model `demand_forecast_v5` was promoted to production on 2026-08-06, introducing `promo_flag` as a required feature.
2. `serving_feature_manifest.yaml` was not updated during promotion, leaving `promo_flag` missing from `active_model_features`.
3. `score_all_models` executed `load_serving_features()`, fetching expected features that excluded `promo_flag`.
4. `build_feature_vector()` generated dictionaries containing only `sku_group_idx`, `zone_idx`, `avg_unit_price_z`, and `trailing_3d_avg`.
5. `score_sku()` received vectors missing `promo_flag` and defaulted unsupplied feature values to 0 before scoring.
6. `model.predict()` evaluated active promo SKUs as if `promo_flag == 0`, ignoring promotional demand spikes and causing systematic underforecasting.

PROPOSED FIX:
Update `/config/serving_feature_manifest.yaml` to include `promo_flag` in `active_model_features`:

```yaml
active_model: demand_forecast_v5
active_model_features:
  - sku_group_idx
  - zone_idx
  - avg_unit_price_z
  - trailing_3d_avg
  - promo_flag
```

Additionally, update the model promotion process or deployment checks to automatically validate that `serving_feature_manifest.yaml` matches the required feature schema defined in `training_feature_manifest.yaml` for the active model.

---

## s010 — data_quality_gate_failure (easy)

ROOT CAUSE:
In `context/stability_check.py`, the `_reference_date` helper function subtracts `dt.timedelta(days=0)` from `run_date` instead of `dt.timedelta(days=1)` due to a bug introduced during refactoring on 2026-07-20. As a result, `run_stability_check` loads today's input partition for both `today_df` and `ref_df`, comparing the daily partition against itself. This produces a Population Stability Index (PSI) of 0.00 every day regardless of distribution changes, allowing the upstream data corruption on 2026-08-10 to pass the stability gate undetected.

CAUSAL CHAIN:
1. On 2026-07-20, commit `d82f4a1` refactored `_reference_date` in `stability_check.py` and erroneously set `dt.timedelta(days=0)` instead of `dt.timedelta(days=1)`.
2. Unit tests in `test_stability_check.py` only invoked `compute_psi` directly on synthetic DataFrames, leaving `_reference_date` and `run_stability_check` unexercised.
3. On 2026-08-10, an upstream ETL job used a stale exchange rate table, corrupting `avg_unit_price` by ~3x across ~40% of SKUs.
4. The `daily_forecast_scoring` DAG ran `run_stability_check` with `run_date="2026-08-10"`.
5. `_reference_date("2026-08-10")` returned `"2026-08-10"`, causing `run_stability_check` to load `/warehouse/inputs/run_date=2026-08-10` for both `today_df` and `ref_df`.
6. `compute_psi` evaluated identical datasets, yielding `PSI=0.00` (below `PSI_THRESHOLD = 0.2`), logging a "Green" status and allowing the pipeline run to proceed with corrupted data.

PROPOSED FIX:
Update `_reference_date` in `context/stability_check.py` to subtract `dt.timedelta(days=1)`:

```python
def _reference_date(run_date: str) -> str:
    return (dt.date.fromisoformat(run_date) - dt.timedelta(days=1)).isoformat()
```

Additionally, update `test_stability_check.py` to add tests for `_reference_date` and `run_stability_check` to prevent regression.

---

## s011 — data_quality_gate_failure (easy)

ROOT CAUSE:
The coverage gate relies on a hardcoded, static threshold (`MIN_EXPECTED_ROWS = 1_000_000`) rather than validating model completion counts or dynamic baseline row counts. On 2026-08-12, a worker crashed due to a native BLAS segfault after processing only 80 of 260 models. The orchestrator timed out after 15 minutes of inactivity and finalized the forecast partition using only the 80 completed models. Because those 80 models produced 1,050,220 rows, the output exceeded the outdated 1,000,000 row threshold, causing the coverage check to pass and mask an incomplete partition missing 180 models.

CAUSAL CHAIN:
1. `scoring_worker_07` crashed due to a native BLAS segfault after completing 80 out of 260 active models.
2. With no worker auto-restart configured, scoring stalled, triggering the orchestrator's 15-minute finalize-on-timeout mechanism.
3. The orchestrator wrote a partial output partition containing predictions for only the 80 completed models (1,050,220 rows).
4. `run_coverage_check` evaluated the partition against `MIN_EXPECTED_ROWS = 1_000_000` (a static value set in February 2026 when expected full output was ~1.28M rows).
5. Because 1,050,220 rows exceeded 1,000,000 rows, `run_coverage_check` logged `PASS` and allowed the job to complete green, hiding the fact that 180 models were missing.

PROPOSED FIX:
Update the validation and orchestration logic to enforce model-level completeness:
1. Modify the coverage gate to check that all active registered models (e.g. 260/260 models, or 100% model completion) are present in the partition, rather than relying solely on a static total row count threshold.
2. Change the orchestrator timeout handling so that finalizing on timeout raises an error or marks the run as failed if model completion is under 100%.

---

## s012 — data_quality_gate_failure (hard)

ROOT CAUSE:
The post-scoring validation rule (`validation_rule.py`) applies a hardcoded cap of 5,000 (`MAX_FORECAST_QTY_PER_SKU`) to all forecast quantities regardless of SKU `unit_type`. This cap was calibrated against a dev dataset consisting strictly of single-unit (`EACH`) SKUs from zone Z_N. When high-volume case-unit (`CASE`) SKUs were introduced in zone Z_SW, their legitimate forecast outputs exceeding 5,000 were misinterpreted as model scoring bugs and clipped down to 5,000, causing inventory planning to persistently under-provision stock.

CAUSAL CHAIN:
1. High-volume `CASE` unit SKUs (e.g., SKU_30011, SKU_30012, SKU_30014) were onboarded in zone Z_SW with legitimate daily forecast demands ranging from ~7,000 to ~9,800 units.
2. The post-scoring validation rule was configured with a hardcoded cap of 5,000 based on a dev dataset that only contained `EACH` SKUs from zone Z_N (where maximum observed forecast was 3,180).
3. During scoring runs, `validate_and_clip` processes valid model output forecasts exceeding 5,000 for these Z_SW `CASE` SKUs and clips them down to exactly 5,000, logging a mild INFO message without raising pipeline errors.
4. Downstream inventory planning receives the truncated 5,000-unit daily forecast instead of actual higher predictions, leading to recurring stockouts in zone Z_SW.

PROPOSED FIX:
Update `validate_and_clip` in `validation_rule.py` to incorporate SKU metadata (specifically `unit_type` from `sku_catalog.csv`). Either remove the cap for `CASE` SKUs, establish separate, higher validation thresholds based on `unit_type` (or zone), or calculate unit-aware dynamically scaled bounds. Additionally, backfill `CASE` SKUs into the dev dataset to ensure future validation testing covers all production packaging types.

---

## s013 — resource_capacity_lifecycle_failure (easy)

ROOT CAUSE:
`holiday_calendar_reference.csv` was created on 2026-04-20 as a static reference file and was never modified after creation. Because the platform storage lifecycle policy (`generic-cold-archive-90d`) automatically transitions any object in the `reference-data` bucket that has been unmodified for 90 days into cold storage, and no exclusion tags were configured on the object, the storage system moved the file out of standard storage. When the `daily_forecast_scoring` DAG ran on 2026-08-14 and attempted to read the file, the storage SDK could not locate it in standard storage and raised a `FileNotFoundError`.

CAUSAL CHAIN:
1. On 2026-04-20, `holiday_calendar_reference.csv` was created in the `reference-data` bucket without lifecycle exclusion tags.
2. The file was regularly read but never modified, leaving its modification timestamp unchanged for over 90 days.
3. The platform team's `generic-cold-archive-90d` lifecycle policy evaluated the object, satisfied the `object_unmodified_for_days >= 90` condition, and transitioned `holiday_calendar_reference.csv` to cold storage.
4. On 2026-08-14, `daily_forecast_scoring` executed `load_holiday_calendar()` to read `/reference-data/holiday_calendar_reference.csv`.
5. `storage_sdk/client.py` attempted standard tier access, failed to find the archived file in standard tier, and raised `FileNotFoundError`, causing the DAG task to fail.

PROPOSED FIX:
1. Restore `holiday_calendar_reference.csv` from cold storage back to standard tier storage.
2. Coordinate with the platform storage team to tag `holiday_calendar_reference.csv` (and any other static reference datasets) with an exclusion tag, and update `storage_lifecycle_policy.yaml` to exclude tagged reference objects from automated cold archiving.

---

## s014 — resource_capacity_lifecycle_failure (easy)

ROOT CAUSE:
On 2026-08-15, 340 new pantry SKUs were onboarded to the Z_S catalog (ticket MERCH-4471) without an infrastructure sizing review, doubling the SKU count scored for Z_S on 2026-08-16. Generating feature matrices for the enlarged catalog drove peak memory usage to 4.3Gi, exceeding the pod's default 4Gi memory limit and causing Kubernetes to OOM-kill (exit code 137) the Z_S scoring pod twice. Because the `score_zone_best_effort` wrapper catches task failures and logs them as skips rather than throwing errors, the overall DAG run succeeded with 259/260 zones, masking the failure and leaving zero forecast rows for zone Z_S.

CAUSAL CHAIN:
1. Merchandising onboarded 340 new pantry SKUs to zone Z_S effective 2026-08-16 without reviewing memory limits.
2. During the 2026-08-16 forecast run, memory usage for zone Z_S reached 4.3Gi while generating feature matrices and scoring the expanded SKU set.
3. The Z_S scoring pod exceeded its configured 4Gi memory limit and was terminated by Kubernetes with exit code 137 (OOMKilled).
4. A retry attempt for zone Z_S ran under the same memory constraint and was also OOMKilled.
5. The `score_zone_best_effort` function caught the pod termination exception, logged a warning that zone Z_S was skipped, and allowed execution to continue.
6. The `score_all_models` function aggregated the results, reported 259/260 zones OK with status SUCCESS, and marked the DAG run green without emitting alerts for the omitted Z_S forecasts.

PROPOSED FIX:
1. Increase the memory resource request and limit for `scoring-zone-*` pods (or specifically for zone Z_S) from 4Gi to a higher threshold (e.g., 8Gi) to support the increased SKU volume.
2. Update `dag.py` to differentiate fatal process terminations (like exit code 137 / OOMKilled) from standard recoverable model failures, emitting explicit alerts or failing the DAG run when a zone task is skipped due to infrastructure resource limits.

---

## s015 — resource_capacity_lifecycle_failure (medium)

ROOT CAUSE:
Intermittent cloud provider capacity constraints for `c6i.2xlarge` instances prevented the worker pool from scaling up to full capacity during daily forecast runs. When available worker count was lower than the total zone count, `scheduler.py` deferred unassigned zones without re-queuing them or raising a task failure. Downstream, `coverage_check.py` validated output using an aggregate row threshold (`1,250,000` rows) that was too low to detect a ~1% row deficit from 1–3 missing zones, allowing incomplete runs to finish with a `SUCCESS` status and leaving deferred zones missing from daily forecasts.

CAUSAL CHAIN:
1. Regional cloud provider capacity constraints on `c6i.2xlarge` instances prevented autoscaling from provisioning enough workers before the scheduling deadline.
2. `scheduler.py` assigned available workers to the first batch of zones and put remaining zones into a `deferred` list.
3. `scheduler.py` logged deferred zones as warnings but deliberately returned only assigned zones without raising an error or re-queuing deferred zones for subsequent execution.
4. Unassigned zones were silently excluded from the scoring step for that run date.
5. `coverage_check.py` checked total row count against `MIN_EXPECTED_ROWS = 1_250_000`, which passed despite missing 1–3 zones (~1% lower row count).
6. The DAG orchestrator reported overall `SUCCESS`, hiding the fact that specific zones lacked forecasts.

PROPOSED FIX:
1. Modify `scheduler.py` to re-queue deferred zones or raise a retryable error if any zones remain unscheduled by the deadline, ensuring missing zones are processed before pipeline completion.
2. Update `coverage_check.py` to validate complete zone coverage explicitly (e.g., verifying all 260 required zone IDs exist in the generated dataset) rather than relying solely on a loose aggregate row threshold.
3. Update the worker pool configuration to specify fallback instance types (e.g., `c6a.2xlarge` or `c5.2xlarge`) so worker capacity can scale even during single-instance-type provider shortages.

---

## s016 — change_management_failure (medium)

ROOT CAUSE:
In the vectorized refactor of `days_since_last_sale()` (commit `e4a1c90`), missing `last_sale_date` values (`NaT`) for SKUs with no sales history were handled using `diff.fillna(0)` instead of preserving the original implementation's explicit no-history sentinel value of `999` (commit `51c7a88`). Setting `days_since_last_sale` to `0` causes the forecast model to treat newly launched SKUs with zero sales history as having sold earlier today—the strongest recency signal—leading to extreme over-forecasting.

CAUSAL CHAIN:
1. Commit `e4a1c90` replaced the loop-based `days_since_last_sale()` with a vectorized implementation that used `diff.fillna(0)` to fill `NaN` values resulting from `NaT` `last_sale_date` entries.
2. The QA side-by-side comparison filtered the test sample to `sales_history_days >= 180`, omitting zero-history SKUs and allowing the improper default value to pass testing unnoticed.
3. When daily scoring ran on production data, newly launched SKUs with zero sales history were assigned `days_since_last_sale = 0` instead of the sentinel value `999`.
4. The scoring model interpreted `0` as maximum sales recency, heavily boosting demand predictions and generating severe over-forecasting (MAPE > 240%) specifically for SKUs launched within the last 30 days.

PROPOSED FIX:
Update `days_since_last_sale()` in `context/recency_feature.py` to fill `NaN` values with `999` instead of `0`:
```python
return diff.fillna(999)
```
Additionally, update `test_recency_feature.py` to include test cases with `NaT` in `last_sale_date` to verify that zero-history SKUs evaluate to `999`.

---

## s017 — change_management_failure (easy)

ROOT CAUSE:
Commit 6f1a9d3 updated `upload_task.py` to use `fastparquet_writer`, but `fastparquet_writer` was never added to `requirements_prod.txt`. The developer had previously installed `fastparquet_writer` on their local machine during a prototype in April 2026, so local testing succeeded despite the missing production dependency. When the change was deployed, the production Python environment lacked the `fastparquet_writer` package, causing `upload_to_warehouse` to fail on import with `ModuleNotFoundError`.

CAUSAL CHAIN:
1. On 2026-08-12, commit 6f1a9d3 changed `upload_task.py` to import and use `fastparquet_writer` instead of the original pyarrow-based implementation.
2. The author's workstation environment already had `fastparquet_writer==0.3.1` installed from a prior prototype, allowing local execution to pass.
3. The author did not add `fastparquet_writer` to `requirements_prod.txt` when committing the code changes.
4. The commit was deployed to production, where `fastparquet_writer` was not installed in the Python environment.
5. On the next scheduled run (2026-08-13 03:12:01), `upload_task.py` attempted to `import fastparquet_writer` and failed immediately with `ModuleNotFoundError: No module named 'fastparquet_writer'`.

PROPOSED FIX:
Add `fastparquet_writer` (e.g., `fastparquet_writer==0.3.1`) to `requirements_prod.txt` and redeploy the production environment so the package is installed. Alternatively, if `fastparquet_writer` is not approved for production use, revert commit 6f1a9d3 to restore the previous pyarrow-based implementation.

---

## s018 — change_management_failure (easy)

ROOT CAUSE:
During the schema migration on 2026-08-12, the pipeline output table was updated from `forecast_output` to `forecast_output_v2` in `write_task.py`, but the static permission file `access_provisioning_config.yaml` was not updated with the new table entry. Because `access_provisioning.py` relies solely on `access_provisioning_config.yaml` to assign read grants and silently skips unlisted tables, downstream read permissions for `forecast_output_v2` were never granted to consumer service accounts (including `inventory_planning_svc`), causing downstream reads to fail with a permission-denied error despite the forecast pipeline successfully generating and writing the data.

CAUSAL CHAIN:
1. On 2026-08-12, commit `d0a7c21` changed the forecast output table from `forecast_output` to `forecast_output_v2` in `write_task.py` without updating `access_provisioning_config.yaml`.
2. On 2026-08-13, `write_forecast_partition` successfully wrote 1,861,220 rows to `forecast_output_v2` because the writing service account has implicit write privileges on its own created tables.
3. The nightly `run_access_provisioning()` job executed and checked `access_provisioning_config.yaml`, which only contained read grant definitions for `forecast_output` and `model_registry`.
4. Because `forecast_output_v2` was absent from `access_provisioning_config.yaml`, `access_provisioning.py` silently skipped granting permissions on `forecast_output_v2`.
5. The downstream inventory-planning nightly job attempted to query `forecast_output_v2` using `inventory_planning_svc` and failed with `PermissionDeniedError`.

PROPOSED FIX:
1. Update `access_provisioning_config.yaml` to include `forecast_output_v2` under `managed_tables` with read grants for `inventory_planning_svc`, `replenishment_svc`, and `bi_reporting_svc` (and remove or deprecate the legacy `forecast_output` entry).
2. Manually execute `run_access_provisioning()` or grant SELECT privileges on `forecast_output_v2` to `inventory_planning_svc` immediately so downstream jobs can read the 2026-08-13 forecast output.
3. Optionally update `access_provisioning.py` to log warnings or throw errors when active output tables in the pipeline registry are missing from `access_provisioning_config.yaml`.

---

## s019 — secondary_model_layer_failure (medium)

ROOT CAUSE:
On 2026-07-24, commit 3a7c1f0 renamed the YAML configuration key `weather_adjustment.enabled_zones` to `weather_adjustment.zones_enabled`, but `adjustment_pipeline.py` was not updated to read the new key name. When `_load_enabled_zones()` attempts to read `config["weather_adjustment"]["enabled_zones"]`, a `KeyError` is raised and caught by a non-blocking `try...except` block. The exception handler logs a debug message (which is filtered out at the production log level of `INFO`) and defaults to returning an empty list `[]`. Because `enabled_zones` is empty, `apply_weather_adjustment()` treats all zones as disabled and returns `0.0` for every row, allowing the pipeline to complete successfully with zero weather adjustments.

CAUSAL CHAIN:
1. Commit 3a7c1f0 renamed `enabled_zones` to `zones_enabled` in `weather_adjustment_config.yaml` without updating `adjustment_pipeline.py`.
2. When scoring runs, `_load_enabled_zones()` attempts to access `config["weather_adjustment"]["enabled_zones"]`.
3. The missing dictionary key raises a `KeyError`.
4. The `except KeyError` block catches the exception, emits a `log.debug` log message (suppressed by the logger's `INFO` threshold), and returns an empty list `[]`.
5. `apply_weather_adjustment()` evaluates `sku_row["zone"] not in enabled_zones` as `True` for every zone and immediately returns `0.0`.
6. `score_with_adjustment()` logs `adjustment_applied=0.0` and completes successfully, producing zero adjustments across all runs for three weeks.

PROPOSED FIX:
Update `_load_enabled_zones()` in `adjustment_pipeline.py` to reference `zones_enabled` instead of `enabled_zones`:

```python
def _load_enabled_zones() -> list:
    config = yaml.safe_load(open("/config/weather_adjustment_config.yaml"))
    try:
        return config["weather_adjustment"]["zones_enabled"]
    except KeyError:
        log.warning("weather_adjustment.zones_enabled not found in config, disabling adjustment")
        return []
```

Additionally, change the log level inside the `except KeyError` block from `log.debug` to `log.warning` so future configuration mismatches are visible in standard log output.

---

## s020 — secondary_model_layer_failure (hard)

ROOT CAUSE:
The persistent negative forecast correction in zone Z_SE is caused by the weather-adjustment model (`adjustment_model.py`) calculating corrections as an unweighted mean of historical residuals over a trailing 6-week window (`TRAILING_WINDOW_WEEKS = 6`), without anomaly exclusion, magnitude capping, or event-end decay logic (`retrain_config.yaml`). Because external weather logs (`weather_event_log.txt`) are not consumed by the model and `anomaly_exclusion` is set to false, the severe, temporary sales drop from the storm week of 2026-07-06 remains inside the 6-week calculation window through 2026-08-17. Consequently, the single historic storm week continuously skews the rolling average negative, depressing daily core forecasts during weeks of normal weather.

CAUSAL CHAIN:
1. A severe storm hit zone Z_SE during the week of 2026-07-06, creating a large temporary negative sales residual for that week.
2. `adjustment_model.py` retrains weekly by calculating `residuals["pct_residual"].mean()` over a strict 6-week trailing window, weighting all weeks equally regardless of external weather events.
3. On retrain runs from 2026-07-13 through 2026-08-10, the trailing 6-week window continues to include the 2026-07-06 storm week residual (and will continue to do so until the 2026-08-24 retrain).
4. The large negative residual from the storm week heavily drags down the 6-week average, forcing `retrain_zone_correction()` to apply an ongoing -11.8% to -14.0% daily correction to core forecasts in Z_SE despite normal weather since 2026-07-10.
5. The artificially depressed core forecasts cause replenishment services to under-predict demand, resulting in recurring inventory stockouts across Z_SE.

PROPOSED FIX:
1. Integrate the external weather event log (`weather_event_log.txt`) into `adjustment_model.py` and set `anomaly_exclusion: true` in `retrain_config.yaml` to exclude known severe event weeks from the trailing residual calculation once the event ends.
2. Update `retrain_config.yaml` and `retrain_zone_correction()` to support event-end decay (`decay_on_event_end: true`) and impose maximum bounds on negative adjustments (`max_negative_adjustment_pct`).
3. Alternatively, modify `load_trailing_residuals()` / `retrain_zone_correction()` to use a weighted moving average or robust statistic (e.g., median or trimmed mean) rather than an unweighted mean to prevent single-week anomalies from dominating the multi-week forecast correction.

---

## s021 — false_positive_correct_behavior (hard)

ROOT CAUSE:
There is no bug in the scoring pipeline; the absence of forecasts for these 47 SKU-store combinations is expected behavior enforced by `scoring_eligibility_rules.py`. During catalog pre-filtering, every missing combination failed at least one business eligibility rule: SKUs with insufficient sales history (`sales_history_days` < 14, such as SKU_40011-40014), SKUs with future catalog effective dates after 2026-08-13 (such as SKU_50201-50203), store-SKU pairs that are not carried/ranged in the store assortment catalog (such as SKU_10233 and SKU_10388 at the reported stores), or SKUs with a `discontinued` status (such as SKU_20601-20602). Because ineligible combinations are intentionally excluded prior to scoring, no forecast rows were generated for them.

CAUSAL CHAIN:
1. Downstream inventory planning noticed 47 missing SKU-store entries in the forecast tables for `run_date=2026-08-13` and reported potential scoring failure.
2. The `daily_forecast_scoring` pipeline evaluated all SKU-store combinations against eligibility criteria in `scoring_eligibility_rules.py` prior to running scoring models.
3. The reported combinations failed specific eligibility criteria:
   - **Insufficient Sales History (< 14 days):** SKU_40011, SKU_40012, SKU_40013, SKU_40014 have only 2–3 days of history (`is_forecastable` failed).
   - **Future Effective Date:** SKU_50201, SKU_50202, SKU_50203 have effective dates in September 2026 (`is_active` failed).
   - **Not Ranged at Store:** SKU_10233 (at ST_0300–ST_0302) and SKU_10388 (at ST_0155–ST_0158) are not carried in `store_assortment.csv` (`is_ranged_at_store` failed).
   - **Discontinued Status:** SKU_20601 and SKU_20602 are marked as discontinued (`is_not_discontinued` failed).
4. `eligible_for_scoring()` filtered out all 47 ineligible combinations before model scoring, and the DAG completed successfully (`status=SUCCESS`).

PROPOSED FIX:
No code fix needed. The scoring pipeline is functioning as designed. Downstream planning teams can self-diagnose future missing combinations by checking the catalog and assortment inputs against the four criteria in `scoring_eligibility_rules.py`: minimum 14 days of sales history, effective date on or before run date, active store ranging, and non-discontinued status. If desired in a future sprint, an optional audit logging/reporting dataset could be added to publish per-combination exclusion reasons for downstream visibility.

---
