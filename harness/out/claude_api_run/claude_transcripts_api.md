# Claude Closed-Book Diagnoses -- Raw Transcripts (API-collected)

Each scenario was submitted to the Anthropic Messages API (`claude-sonnet-4-5`) using the exact same closed-book prompt (symptom + verbatim context files, no ground truth) as run_gemini_diagnoses.py uses for the Gemini arm, and the same prompt harness/loader.py's `build_agent_task()` would hand a real agent. This supersedes the earlier subagent-collected transcripts (harness/out/phase3_transcripts.md), which were used only because no API key was available at the time. Responses are pasted verbatim below.

Ground truth (`manifest.yaml`) was never included in any prompt.

---

## s001 — resource_capacity_lifecycle_failure (hard)

*Collected 2026-09-14, against the rewritten ground truth (see
`harness/out/phase3_report.md`'s 2026-09-14 update note). The original
s001 transcript, against the missing-training-config root cause, is no
longer part of this file; the scenario it describes no longer exists.*

ROOT CAUSE:
On 2026-07-14, zone Z_NW experienced a data volume spike from 6.1GB to 24.8GB due to a partner EDI feed backfill. The VM sizing system allocates resources based on a rolling 7-day average computed the night before each scoring run, meaning it cannot react to same-day volume spikes. Models M_0147, M_0148, and M_0149 (all in zone Z_NW) were allocated medium VMs with 8GB memory budgets based on the prior 7-day average of 6.0GB, but the actual feature-building workload on 2026-07-14 required 8.1-9.9GB due to the spike, causing MemoryErrors that triggered fallback to prior-day forecasts.

CAUSAL CHAIN:
1. On 2026-07-13, the VM sizing job computed zone Z_NW's rolling 7-day average as 6.0GB, assigning tier "medium" (8GB) for the 2026-07-14 scoring run
2. On 2026-07-14, the partner EDI feed backfill caused Z_NW's actual data volume to spike to 24.8GB
3. Models M_0147, M_0148, and M_0149 started scoring on medium VMs with 8GB memory budgets
4. Feature building for these models attempted to load and join the inflated 24.8GB dataset, requiring 8.1-9.9GB of memory
5. MemoryErrors were raised during feature building, caught by the exception handler in score_one()
6. The fallback handler sourced forecasts from 2026-07-13's partition and stamped them as 2026-07-14 forecasts
7. The DAG completed successfully (3 fallbacks < 5 tolerance threshold), but downstream systems detected stale forecasts and fired the fallback alert

PROPOSED FIX:
Implement a pre-flight memory check or dynamic VM sizing that can detect same-day volume spikes before scoring begins. Options include: (1) add a pre-scoring step that samples the current day's data volume and upgrades VM tier if it exceeds the allocated budget by a threshold margin, or (2) implement automatic VM tier escalation and retry logic when MemoryError is caught, rather than immediately falling back to stale data. Additionally, consider alerting or failing the DAG when fallbacks occur due to MemoryError specifically (vs. other transient errors), since these represent capacity planning failures rather than acceptable degradation scenarios.

---

## s002 — rerun_idempotency_failure (medium)

ROOT CAUSE:
The write_forecast_partition function uses `df.to_parquet(path, mode="append")` without deleting existing data before writing. When the on-call engineer cleared the DAG with `--upstream` flag on 2026-07-16 at 03:22, it re-ran both score_all_models and write_forecast_partition. The write task appended a second copy of the same 1,294,075 rows to the partition that had already been written during the first attempt at 03:07:40, resulting in 2,588,150 total rows (exactly double) for run_date 2026-07-16. The publish_to_warehouse task had failed due to a network timeout, but the upstream write had already succeeded and persisted data to disk. The retry logic did not account for the fact that the write operation is not idempotent.

CAUSAL CHAIN:
1. First DAG run on 2026-07-16 successfully scored 258 models and wrote 1,294,075 rows to `/warehouse/forecasts/run_date=2026-07-16` at 03:07:40
2. The publish_to_warehouse task failed at 03:14:33 due to network timeout to warehouse-api
3. On-call engineer cleared the DAG with `--upstream` flag at 03:22, which re-ran score_all_models and write_forecast_partition in addition to publish_to_warehouse
4. The second write_forecast_partition execution appended another 1,294,075 rows to the same partition at 03:49:02 (mode="append" with no pre-delete)
5. The partition now contained 2,588,150 rows (double the expected amount), confirmed in row_counts.csv
6. The uplift health check summed forecast_qty across all rows in the partition, counting each forecast twice, resulting in +97.8% uplift

PROPOSED FIX:
Change the write_forecast_partition function to delete the partition directory before writing, or use mode="overwrite" instead of mode="append". The write operation must be idempotent to support safe retries. Add: `shutil.rmtree(path, ignore_errors=True)` before the `to_parquet()` call, or change the mode parameter to `"overwrite"`. Additionally, consider changing the retry strategy to only clear the failed publish_to_warehouse task rather than using `--upstream`, since scoring and writing are expensive operations that should not be re-run unnecessarily when they've already succeeded.

---

## s003 — train_serving_skew (medium)

ROOT CAUSE:
The SEASONAL_PROMO sku_group was added to the catalog on 2026-07-18, but the model was trained on 2026-06-01 using a training_config.yaml that only includes six known sku_group values (GROCERY, CHILLED, FROZEN, BAKERY, PRODUCE, HOUSEHOLD). When the scoring pipeline encounters the unseen "SEASONAL_PROMO" category, the encode_sku_group function in feature_pipeline.py silently falls back to index 0 (GROCERY) instead of raising an error. This causes all 40 SEASONAL_PROMO SKUs to be scored as if they were GROCERY items, producing wildly inaccurate forecasts (187.4% MAPE) while the pipeline reports success.

CAUSAL CHAIN:
1. On 2026-06-01, the model was trained and training_config.yaml was generated with known_values for sku_group containing only [GROCERY, CHILLED, FROZEN, BAKERY, PRODUCE, HOUSEHOLD]
2. On 2026-07-18, merchandising added 40 new SKUs with sku_group=SEASONAL_PROMO to the catalog (commit c92a41f)
3. On 2026-07-20, the daily_forecast_scoring DAG loaded the updated catalog containing SEASONAL_PROMO SKUs
4. For each SEASONAL_PROMO SKU, build_features called encode_sku_group("SEASONAL_PROMO")
5. Since "SEASONAL_PROMO" is not in _SKU_GROUP_INDEX, encode_sku_group returned 0 (the GROCERY index) as a silent fallback
6. The model scored all SEASONAL_PROMO SKUs using GROCERY demand patterns instead of their actual category
7. The pipeline completed successfully with 1,842 rows (correct count) but incorrect feature values for 40 SKUs
8. Three days later, when actuals arrived, the forecasts for SEASONAL_PROMO showed 187.4% MAPE due to the category mismatch

PROPOSED FIX:
Modify encode_sku_group in feature_pipeline.py to raise an exception when encountering an unknown category instead of silently falling back to index 0. This will cause the pipeline to fail fast when new categories are added, alerting engineers that a model retrain is needed. The fix should be: `return _SKU_GROUP_INDEX[sku_group]` (removing the `.get(sku_group, 0)` fallback). Additionally, implement a pre-scoring validation step that checks whether all catalog sku_group values exist in the training_config known_values, and fails the DAG early if mismatches are detected. For immediate remediation, either retrain the model to include SEASONAL_PROMO or temporarily exclude those SKUs from scoring until the scheduled October retrain.

---

## s004 — recovery_temporal_state (medium)

ROOT CAUSE:
The forecast collapse on 2026-08-04 was caused by the trailing_avg feature calculation silently treating missing actuals data as zero demand. On 2026-08-02, the daily_forecast_scoring DAG failed due to a transient database connection issue, and no actuals partition was written for that date. When the 2026-08-04 run executed, it calculated a 3-day trailing average using data from 2026-08-03, 2026-08-02, and 2026-08-01. Because the 2026-08-02 partition was missing, the feature_loader.py code caught the FileNotFoundError and substituted 0.0 for that day's actuals, artificially deflating the trailing average by approximately one-third. This deflated feature value propagated through all 260 active models during scoring, producing systematically lower forecasts across the board.

CAUSAL CHAIN:
1. On 2026-08-02, the daily_forecast_scoring DAG failed due to a transient database connection issue, and no actuals partition was written for run_date 2026-08-02
2. The on-call engineer decided not to backfill immediately, deferring to the weekly backfill sweep on Friday
3. On 2026-08-04, the scoring pipeline ran successfully and calculated trailing_avg features for each model using a 3-day window (2026-08-03, 2026-08-02, 2026-08-01)
4. When trailing_avg attempted to load the 2026-08-02 partition, it caught FileNotFoundError and substituted 0.0 instead of failing or raising an alert
5. The 3-day average was computed as (actuals_08-03 + 0.0 + actuals_08-01) / 3, reducing the feature value by roughly 33%
6. All 260 models were scored with this artificially low trailing_avg feature, producing systematically depressed forecasts
7. The total forecast_qty dropped 42% compared to the prior day, triggering the uplift health check alert

PROPOSED FIX:
Change the trailing_avg function in feature_loader.py to raise an exception instead of silently substituting 0.0 when actuals partitions are missing. The current behavior masks data quality issues and creates incorrect features. The function should fail loudly when required input data is unavailable, forcing either immediate backfill or explicit handling of missing data scenarios. Additionally, implement an immediate backfill policy for failed scoring runs rather than deferring to weekly sweeps, since the 3-day trailing window creates a dependency on recent partitions. For the immediate incident, backfill 2026-08-02 actuals and re-run scoring for 2026-08-04.

---

## s005 — recovery_temporal_state (easy)

ROOT CAUSE:
The Z_SW zone did not receive vendor feed data on 2026-08-05 due to a public holiday (vendor site closed), yet the pipeline treated this missing data as zero sales for all SKUs in that zone. The `build_features` function performs a LEFT JOIN between the catalog and actuals, then fills missing `actual_qty` values with 0.0. This design cannot distinguish between "no sales occurred" and "no data was received." When Z_SW's entire feed was absent, all Z_SW SKUs received actual_qty=0.0 as features, causing the scoring models to produce artificially low forecasts for that zone. The pipeline completed successfully because missing vendor feeds are not configured as a hard block, and the code has no logic to detect or handle zone-level feed absence.

CAUSAL CHAIN:
1. Vendor feed for Z_SW did not land on 2026-08-05 due to public holiday (vendor site closed)
2. Ingestion bot proceeded with 5/6 zones since no hard block is configured for partial vendor landing
3. `load_actuals(run_date="2026-08-05")` returned a DataFrame with no rows for zone Z_SW
4. `catalog.merge(actuals, on=["sku_id", "zone"], how="left")` left all Z_SW SKU rows with NaN in the `actual_qty` column
5. `merged["actual_qty"].fillna(0.0)` replaced those NaNs with 0.0, treating missing feed data as zero sales
6. Scoring models received features indicating zero recent sales activity for all Z_SW SKUs
7. Models produced unusually low forecasts for Z_SW, causing the -18% total forecast volume drop
8. DAG completed successfully with no exceptions because the code executed as designed

PROPOSED FIX:
Add zone-level feed validation before feature building. After loading actuals, check that all expected zones are present in the data (compare against a configured list or prior-day zones). If any zone is completely missing, either (1) fail the DAG with a clear error message requiring manual review, or (2) use a fallback strategy such as carrying forward the prior day's actuals for the missing zone, with explicit logging. The fillna(0.0) logic should only apply to individual missing SKU-zone combinations within a zone that has data, not to entire missing zones. Example: `expected_zones = {"Z_N", "Z_NE", "Z_S", "Z_SE", "Z_SW", "Z_NW"}; received_zones = set(actuals["zone"].unique()); missing = expected_zones - received_zones; if missing: raise ValueError(f"Missing zone feeds: {missing}")`.

---

## s006 — rerun_idempotency_failure (medium)

ROOT CAUSE:
The `notify_partner_webhook` function is called unconditionally at the start of every task attempt, before the file upload occurs. When the first upload attempt failed due to a network timeout, the webhook had already been sent. On the retry, the webhook was sent again before the successful upload. Because the webhook has no idempotency key (as confirmed in the config: `idempotency_key: null`), the partner system treated both webhook calls as distinct events and ingested the file twice, even though only one successful upload occurred.

CAUSAL CHAIN:
1. At 05:10:02 on 2026-07-25, the first task attempt begins and immediately calls `notify_partner_webhook`, sending the first webhook notification to the partner
2. At 05:10:03, the task proceeds to `_transfer_file` which attempts the SFTP upload
3. At 05:11:03, the SFTP connection times out after 60 seconds, causing the task to fail
4. At 05:15, the task is requeued for retry (attempt 2)
5. At 05:16:10, the retry attempt begins and again immediately calls `notify_partner_webhook`, sending a second webhook notification for the same run_date
6. At 05:16:11, the file upload begins and completes successfully at 05:16:52
7. The partner's ingestion system receives two webhook notifications (6 minutes apart) for run_date 2026-07-25 and, lacking deduplication logic, processes the file twice

PROPOSED FIX:
Move the `notify_partner_webhook` call to execute only after `_transfer_file` completes successfully, not before. Additionally, implement an idempotency key in the webhook payload (e.g., based on run_date and feed name) so that even if duplicate notifications are sent due to retries or other failures, the partner system can deduplicate them. The git log shows this pattern was already implemented for `retailer_beta` integration in commit c1a90f3, so apply the same pattern to the `acme_retail_partner` integration.

---

## s007 — rerun_idempotency_failure (medium)

ROOT CAUSE:
The weekly rollup report for the week of 2026-07-28 was computed on 2026-08-01 (a Monday) by reading the forecast partitions as they existed at that time. On 2026-07-29, a backfill was executed that overwrote four of those partitions (2026-07-28 through 2026-07-31) with updated data containing different row counts and forecast values. The weekly_rollup_job.py explicitly does not track which partition versions it consumed and is never re-triggered when source partitions change after the fact. Therefore, the rollup report still reflects the old partition data from before the backfill, while the current partitions contain the newer backfilled data, causing the mismatch for exactly the four days that were backfilled.

CAUSAL CHAIN:
1. On 2026-08-01 (Monday), the weekly_rollup_job ran and read forecast partitions for 2026-07-28 through 2026-08-03, capturing the values that existed at that moment (e.g., 1284900 for 2026-07-28).
2. On 2026-07-29 (which is actually before 2026-08-01 chronologically, but the backfill_run_log shows timestamps of "2026-07-29 10:02:11" suggesting this happened on July 29th), a backfill was executed with `--start-date 2026-07-28 --days 4`, reprocessing and overwriting partitions for 2026-07-28, 2026-07-29, 2026-07-30, and 2026-07-31.
3. The backfill wrote new data to these four partitions with different row counts (e.g., 1296410 rows for 2026-07-28 instead of the previous 1284730), changing the forecast values.
4. The weekly rollup report was never automatically refreshed after the backfill because weekly_rollup_job.py has no mechanism to detect or respond to upstream partition changes.
5. When Finance compared the rollup report values to current partition values, the four backfilled days (2026-07-28 through 2026-07-31) showed mismatches, while the three non-backfilled days (2026-08-01 through 2026-08-03) matched perfectly.

PROPOSED FIX:
Implement partition lineage tracking in the weekly rollup job to record which partition versions were consumed, and add a mechanism to either (1) automatically re-trigger the rollup when any consumed partition is overwritten, or (2) add monitoring that alerts when source partitions change after a rollup has been computed. For immediate remediation, manually re-run the weekly_rollup_job for the week of 2026-07-28 to regenerate the report using the current backfilled partition data. Additionally, document the backfill process to include a step that identifies and re-triggers any downstream rollup reports that consumed the backfilled partitions.

---

## s008 — train_serving_skew (hard)

ROOT CAUSE:
The Z_SE zone's forecast model is receiving severely mis-scaled feature inputs due to a unit mismatch introduced on 2026-08-04. The feature pipeline's `scale_avg_unit_price` function was trained on data where prices were in cents (mean=1500, std=150), but Z_SE's pricing system migration changed its `avg_unit_price` export from cents to dollars on 2026-08-04. When a price that is now ~15 dollars (previously 1500 cents) is fed into the scaler expecting cents, it produces ((15 - 1500) / 150) = -9.9 instead of the expected ((1500 - 1500) / 150) = 0.0, causing the model to receive drastically out-of-distribution feature values and produce unreliable forecasts.

CAUSAL CHAIN:
1. On 2026-08-04, Z_SE's pricing system migration changed `avg_unit_price` from cents to dollars (e.g., 1500 cents became 15.0 dollars) while all other zones continued reporting in cents
2. The feature pipeline's `_PRICE_SCALER` was fit on training data in cents (mean=1500.0, std=150.0) and has no unit validation or conversion logic
3. Z_SE's dollar-denominated prices (≈15.0) are passed to `scale_avg_unit_price`, which applies (value - 1500) / 150, producing highly negative z-scores around -9.9 instead of near-zero values
4. The demand forecast model for Z_SE receives feature values far outside its training distribution, causing it to extrapolate poorly
5. Z_SE forecasts drop 58-63% below normal starting exactly on 2026-08-04, while other zones (still reporting in cents) remain healthy
6. The DAG runs green because the schema validation only checks that `avg_unit_price` is a float, not its unit or magnitude

PROPOSED FIX:
Add unit normalization in the feature pipeline to convert all prices to cents before scaling. Insert a conversion step in `scale_avg_unit_price` or in the data ingestion layer that detects or explicitly handles per-zone unit conventions. Immediate mitigation: multiply Z_SE's `avg_unit_price` by 100 before passing to the scaler. Long-term: add schema validation that checks price magnitudes are within expected ranges (e.g., 500-3000 for cents) to catch unit mismatches, and document the expected unit (cents) explicitly in the feature pipeline code and data contracts.

---

## s009 — train_serving_skew (medium)

ROOT CAUSE:
The demand_forecast_v5 model was trained with `promo_flag` as a feature and learned to use it to predict higher demand for SKUs on promotion. However, when v5 was promoted to production on 2026-08-06, the `serving_feature_manifest.yaml` was not updated to include `promo_flag` in the `active_model_features` list. As a result, the scoring pipeline does not include `promo_flag` in the feature vectors it builds. The `score_sku` function fills missing features with 0, so all SKUs are being scored with `promo_flag=0` (not on promotion) even when they actually are on promotion. This causes the model to systematically underforecast demand for promoted SKUs since it believes they are not on promotion.

CAUSAL CHAIN:
1. On 2026-08-06, demand_forecast_v5 is promoted to production; this model was trained with five features including `promo_flag`
2. The `serving_feature_manifest.yaml` file was last updated 2026-07-30 (one week before promotion) and still lists only the four features used by v4, without `promo_flag`
3. The scoring pipeline calls `load_serving_features()` which reads the manifest and returns only the four legacy features
4. `build_feature_vector()` constructs feature vectors containing only those four features; `promo_flag` is never included
5. `score_sku()` receives vectors missing `promo_flag` and fills it with 0 (the default for missing features)
6. The v5 model receives `promo_flag=0` for all SKUs, interpreting them as not being on promotion
7. For SKUs that are actually on promotion (per `promo_calendar.csv`), the model predicts lower demand than reality, causing systematic underforecasting
8. Non-promo SKUs are forecast correctly because `promo_flag=0` is the correct value for them

PROPOSED FIX:
Update `/config/serving_feature_manifest.yaml` to add `promo_flag` to the `active_model_features` list. The corrected manifest should read:
```yaml
active_model: demand_forecast_v5
active_model_features:
  - sku_group_idx
  - zone_idx
  - avg_unit_price_z
  - trailing_3d_avg
  - promo_flag
```
Additionally, implement a deployment checklist or automated validation that ensures the serving feature manifest matches the features expected by the model being promoted, to prevent this class of error in future promotions.

---

## s010 — data_quality_gate_failure (easy)

ROOT CAUSE:
The stability check compared the 2026-08-10 data against itself rather than against the previous day's data due to a bug introduced in commit d82f4a1 on 2026-07-20. The `_reference_date()` function incorrectly uses `timedelta(days=0)` instead of `timedelta(days=-1)`, causing it to return the same date as the run_date. When comparing a dataset's distribution against itself, the PSI calculation always yields 0.00 (perfect match), which explains why the check reported "Green (PSI=0.00)" despite the significant data corruption on 2026-08-10.

CAUSAL CHAIN:
1. On 2026-07-20, commit d82f4a1 "refactored" the date handling in `_reference_date()` but introduced a bug: changed the timedelta offset from -1 to 0
2. Starting 2026-07-21, all stability checks began comparing each day's data against itself instead of against the previous day
3. The logs show PSI=0.00 for every single run from 2026-07-21 onward, which is statistically impossible for real-world data distributions unless comparing identical datasets
4. On 2026-08-10, the upstream ETL bug corrupted ~40% of avg_unit_price values by roughly 3x
5. The stability check loaded the 2026-08-10 partition as both "today" and "reference" data
6. Computing PSI between identical distributions (same partition loaded twice) yielded PSI=0.00
7. PSI=0.00 < threshold of 0.2, so the check passed as "Green" and did not block the pipeline
8. The corrupted data proceeded through the scoring pipeline undetected

PROPOSED FIX:
Change line 11 in `stability_check.py` from `dt.timedelta(days=0)` to `dt.timedelta(days=-1)` to correctly compute yesterday's date as the reference. Additionally, add an integration test that exercises the full `run_stability_check()` function with actual date arithmetic and file loading to ensure the reference date is correctly resolved to the previous day's partition, preventing this class of bug from being reintroduced.

---

## s011 — data_quality_gate_failure (easy)

ROOT CAUSE:
The coverage check uses a static threshold (MIN_EXPECTED_ROWS = 1_000_000) that was set on 2026-02-14 when the pipeline had 255 active models producing ~1.28M rows/day. On 2026-08-12, a worker crash caused only 80 of 260 models to complete, producing 1,050,220 rows. This incomplete partition still passed the coverage check because 1,050,220 exceeds the outdated 1M threshold, even though it represents only 31% of the expected output. The threshold was never updated as the model count grew from 255 to 260, and more critically, it was set too low to detect partial failures—it would have failed to catch incomplete runs even at the original 255-model scale.

CAUSAL CHAIN:
1. On 2026-08-12 at 02:58:11, scoring_worker_07 crashed due to a segfault in the native BLAS library after completing only 80 of 260 models
2. The scoring_orchestrator had no auto-restart configured for this worker type, so the remaining 180 models were never processed
3. After 15 minutes of no progress, the finalize-on-timeout mechanism triggered and wrote a partition containing only the 80 completed models (1,050,220 rows)
4. The coverage check compared 1,050,220 rows against the static MIN_EXPECTED_ROWS threshold of 1,000,000
5. Since 1,050,220 >= 1,000,000, the check returned PASS and the DAG completed successfully
6. The inventory allocation team later discovered that 180 models' worth of SKUs were missing from the 2026-08-12 forecast

PROPOSED FIX:
Replace the static MIN_EXPECTED_ROWS threshold with a dynamic check that validates against the actual number of active models in the registry. The coverage check should verify that all 260 active models produced output, or at minimum set the threshold to a percentage of expected rows based on current model count (e.g., 95% of models_count * avg_rows_per_model). Additionally, add monitoring for worker crashes and enable auto-restart for scoring workers to prevent partial runs from being written in the first place. The finalize-on-timeout behavior should also be reconsidered—it may be better to fail the run explicitly rather than silently write incomplete data.

---

## s012 — data_quality_gate_failure (hard)

ROOT CAUSE:
The validation rule was developed and tuned against a dev dataset containing only EACH-unit SKUs (max observed forecast 3,180), leading to a hardcoded cap of 5,000 units. This cap is appropriate for EACH-unit SKUs but is inappropriately low for CASE-unit SKUs, which legitimately require forecasts in the 7,000-10,000 range. When case-unit SKUs were introduced to production in zone Z_SW (starting March 2025), the validation rule began silently clipping their legitimate model outputs to 5,000, causing persistent under-forecasting and stockouts for SKU_30011, SKU_30012, and SKU_30014.

CAUSAL CHAIN:
1. Dev dataset was seeded from zone Z_N only, which historically contained no case-unit SKUs (100% EACH-unit, max forecast 3,180)
2. Validation rule MAX_FORECAST_QTY_PER_SKU was set to 5,000 based on dev dataset characteristics, with no unit_type awareness built into the logic
3. Case-unit SKUs were introduced to production in Z_SW (commit c40e771, 2025-03-02) for bulk beverage/pantry lines, but dev dataset was never updated
4. Model correctly generates forecasts of 7,220-9,850 units for case-unit SKUs (SKU_30011, SKU_30012, SKU_30014) based on actual demand patterns
5. Validation rule clips these legitimate forecasts to 5,000, logging them identically to actual scoring bugs
6. Clipped forecasts (5,000) are consistently 30-50% below actual demand (7,180-9,910), causing recurring stockouts
7. Pipeline reports SUCCESS with no errors because clipping is working as designed; only business impact (stockouts) surfaces the problem

PROPOSED FIX:
Modify `validation_rule.py` to make the cap unit_type-aware. Add a parameter to `validate_and_clip()` to accept `unit_type`, and apply different thresholds: keep `MAX_FORECAST_QTY_PER_SKU = 5000` for EACH-unit SKUs, but set `MAX_FORECAST_QTY_PER_SKU_CASE = 15000` (or appropriate value based on production case-unit data analysis) for CASE-unit SKUs. Additionally, update the dev dataset to include representative case-unit SKUs from Z_SW so future validation rules are tuned against realistic production data for all unit types.

---

## s013 — resource_capacity_lifecycle_failure (easy)

ROOT CAUSE:
The holiday_calendar_reference.csv file was automatically moved to cold storage by a platform-wide lifecycle policy that archives any object in the reference-data bucket unmodified for 90 days or more. The file was created on 2026-04-20 and never modified thereafter; by 2026-08-14 (116 days later) it exceeded the 90-day threshold and was archived to cold storage. The storage SDK's standard read method cannot access cold-tier objects, causing the FileNotFoundError. This is a policy misconfiguration issue: static reference files that are intentionally read-only should be excluded from automatic archival, but no such exclusion was configured and the forecasting team was not on the notification list to be alerted when their files were archived.

CAUSAL CHAIN:
1. holiday_calendar_reference.csv was committed to the reference-data bucket on 2026-04-20 as a static, read-only reference file
2. The file was never modified after creation, as intended for a stable holiday calendar
3. The platform storage team's generic-cold-archive-90d policy continuously monitored all objects in the reference-data bucket for modification age
4. On approximately 2026-07-19 (90 days after 2026-04-20), the file met the condition object_unmodified_for_days >= 90
5. The lifecycle policy moved the file from standard tier to cold storage
6. The forecasting team was not notified because they were not subscribed to platform-storage-alerts@retailco.example.com
7. On 2026-08-14, the daily_forecast_scoring DAG attempted to read the file using pd.read_csv, which calls the storage SDK's standard-tier open method
8. The storage SDK raised FileNotFoundError because the object exists only in cold storage, not in the standard tier accessible to normal read operations

PROPOSED FIX:
1. Immediate remediation: Restore holiday_calendar_reference.csv from cold storage to standard tier so the pipeline can run
2. Prevent recurrence by adding an exclusion tag or metadata attribute to holiday_calendar_reference.csv (and similar static reference files) that exempts them from the 90-day archival policy
3. Update storage_lifecycle_policy.yaml to explicitly exclude objects tagged as "permanent-reference" or similar from automatic cold-storage archival
4. Subscribe the forecasting team (or a shared data-engineering distribution list) to platform-storage-alerts@retailco.example.com so they receive notifications when their files are archived in the future
5. Document in the reference-data bucket README that static files intended for indefinite active use must be tagged appropriately to avoid archival

---

## s014 — resource_capacity_lifecycle_failure (easy)

ROOT CAUSE:
Zone Z_S had no forecast rows for 2026-08-16 because its scoring task was OOM-killed twice due to insufficient memory allocation (4Gi limit vs 4.3Gi peak usage), triggered by a merchandising change that doubled the SKU count for Z_S on 2026-08-16. The DAG's "best-effort" design intentionally catches all exceptions including orchestrator-level pod terminations, logs them as warnings, and reports overall SUCCESS as long as any zones complete. This prevented the failure from surfacing in DAG status monitoring, while the infrastructure pod-events log that recorded the OOM kills exists in a separate system not routinely checked by the forecasting team.

CAUSAL CHAIN:
1. On 2026-08-15, merchandising onboarded 340 new pantry SKUs to zone Z_S's catalog (MERCH-4471), roughly doubling the SKU count effective 2026-08-16
2. On 2026-08-16 at 02:47:12, the scoring task for Z_S attempted to build a feature matrix with full price/promo history for all SKUs, causing memory usage to spike to 4.3Gi, exceeding the 4Gi pod limit set in commit b13d7f0
3. The orchestrator OOM-killed the pod (exit code 137) and retried once with the same 4Gi limit and same input data, resulting in a second OOM kill at 02:47:45
4. The exception from pod termination was caught by the `score_zone_best_effort` wrapper, logged as a warning "zone=Z_S skipped due to task failure: pod terminated (exit 137)", and returned False
5. The `score_all_models` function completed with 259/260 zones successful and logged "status=SUCCESS" because the best-effort design treats individual zone failures as acceptable
6. The DAG marked all tasks green since no Python exceptions propagated and the overall status was SUCCESS
7. No forecast rows were written for Z_S on 2026-08-16, but this was only discovered days later when inventory allocation queried for that zone/date

PROPOSED FIX:
Implement a multi-layered fix: (1) Add OOM-specific detection in `score_zone_best_effort` by checking for exit code 137 and automatically retry with increased memory (e.g., 8Gi or 12Gi); (2) Establish a data quality check that validates all active zones from the model registry have forecast output before marking the DAG as SUCCESS; (3) Create alerting when any zone is skipped, especially for OOM conditions, to surface infrastructure sizing issues immediately rather than relying on downstream consumers to discover missing data; (4) Require infrastructure sizing review as part of the merchandising onboarding process when SKU counts change significantly.

---

## s015 — resource_capacity_lifecycle_failure (medium)

ROOT CAUSE:
The scheduler is designed to defer zones when insufficient workers are available, logging a warning but not raising a failure. During the cloud provider capacity constraints for c6i.2xlarge instances (2026-08-11 through 2026-08-18), the autoscaler intermittently failed to provision the full worker pool, causing 1-3 zones per day to be deferred. The deferred zones are never retried or rescheduled—they are simply dropped from that day's run. The pipeline reports SUCCESS because the deferral policy explicitly treats insufficient capacity as a non-failure condition. The coverage check doesn't catch this because losing 1-3 zones out of 260 (~1% of data) doesn't breach the aggregate row-count threshold of 1,250,000 rows.

CAUSAL CHAIN:
1. Cloud provider experiences capacity constraints for c6i.2xlarge instances in ap-southeast-2 (2026-08-11 to 2026-08-18)
2. Autoscaler requests workers but receives fewer than the 260 needed to cover all zones
3. Scheduler's `assign_workers` function assigns only the first N zones (up to available_workers) and defers the remainder
4. Deferred zones are logged as a warning but never re-queued or retried within that day's run
5. The pipeline completes successfully with only the assigned zones processed
6. Coverage check passes because ~99% of expected rows are still present (well above the 1,250,000 threshold)
7. DAG reports SUCCESS with no failed tasks, masking the fact that some zones have no forecasts for that day

PROPOSED FIX:
Modify the scheduler to either (1) fail the DAG run when zones are deferred, forcing visibility and manual intervention, or (2) implement a retry mechanism that re-attempts deferred zones after the initial scheduling window, potentially with a longer timeout or by waiting for additional worker capacity. Additionally, consider implementing a per-zone coverage check rather than an aggregate row-count threshold, so that missing even a single zone triggers a failure. The current "deferred-not-failed" policy silently drops data, which violates the expectation that all zones receive daily forecasts.

---

## s016 — change_management_failure (medium)

ROOT CAUSE:
The vectorized refactor of `days_since_last_sale()` introduced a silent semantic change for SKUs with no sales history. The original loop-based implementation (commit 51c7a88) used a sentinel value of 999 for SKUs that had never recorded a sale, correctly signaling "no history" to the forecasting model. The new vectorized implementation fills NaN values (which result from NaT - Timestamp arithmetic for never-sold SKUs) with 0, which the model interprets as "sold today" — the strongest possible recency signal. This causes the model to massively over-forecast demand for newly launched SKUs that haven't yet recorded their first sale.

CAUSAL CHAIN:
1. On 2026-08-10, the vectorized `days_since_last_sale()` was deployed, replacing the loop-based implementation that returned sentinel value 999 for SKUs with no sales history (NaT `last_sale_date`)
2. For newly launched SKUs with zero sales, `(run - catalog["last_sale_date"])` produces NaN because `last_sale_date` is NaT
3. The `.fillna(0)` call converts these NaN values to 0, making the feature indistinguishable from SKUs that sold on the run date itself
4. The forecasting model interprets `days_since_last_sale=0` as maximum recency/momentum and generates extremely high demand forecasts
5. Newly launched SKUs (within 30 days) with zero sales history receive forecasts 240%+ above actual demand
6. The bug was not caught in testing because the QA sample explicitly filtered to `sales_history_days >= 180`, excluding all zero-history SKUs from the side-by-side comparison

PROPOSED FIX:
Replace `return diff.fillna(0)` with `return diff.fillna(999)` to restore the original sentinel value semantics for SKUs with no sales history. This ensures that never-sold SKUs are treated as having very stale (or no) recency signal rather than maximum recency. Additionally, expand the test suite to include SKUs with `last_sale_date=NaT` to prevent regression of this edge case.

---

## s017 — change_management_failure (easy)

ROOT CAUSE:
The engineer developed and tested the code change to use `fastparquet_writer` in their local development environment, where the library happened to be installed from a previous prototype experiment in April 2026. However, `fastparquet_writer` was never added to `requirements_prod.txt`, so when the code was deployed to production, the production environment did not have this dependency installed. The code worked locally (masking the missing dependency declaration) but failed immediately upon deployment to production where the library was absent.

CAUSAL CHAIN:
1. On 2026-04-02, the engineer installed `fastparquet_writer==0.3.1` locally for a prototype that never shipped to production
2. The library remained in the local development environment but was never added to `requirements_prod.txt`
3. On 2026-08-12, the engineer modified `upload_task.py` to import and use `fastparquet_writer`
4. The code change was tested locally and passed because `fastparquet_writer` was already installed in the local environment
5. The code was committed and deployed to production without the dependency being declared
6. On 2026-08-13 at 03:12:01, the production pipeline attempted to run the task
7. The production environment tried to import `fastparquet_writer` but the module was not installed
8. Python raised `ModuleNotFoundError: No module named 'fastparquet_writer'` causing immediate task failure

PROPOSED FIX:
Add `fastparquet_writer==0.3.1` to `requirements_prod.txt` and redeploy the production environment to install the missing dependency. Additionally, implement a process improvement: add a CI/CD check that compares all imports in the codebase against declared dependencies in `requirements_prod.txt` to catch undeclared dependencies before deployment.

---

## s018 — change_management_failure (easy)

ROOT CAUSE:
The forecast data for 2026-08-13 was successfully written to the new table `forecast_output_v2`, but downstream consumers cannot read it because the access provisioning system still references only the old table name `forecast_output`. When the schema migration renamed the output table from `forecast_output` to `forecast_output_v2` on 2026-08-12, the static configuration file `access_provisioning_config.yaml` (last updated 2026-05-02) was not updated to include the new table name. The access provisioning job grants read permissions only to tables listed in its configuration, and silently ignores any tables not present in the allowlist, so `forecast_output_v2` never receives the necessary read grants for `inventory_planning_svc` and other downstream consumers.

CAUSAL CHAIN:
1. On 2026-08-12, commit d0a7c21 migrated the output table from `forecast_output` to `forecast_output_v2` to add confidence_interval columns
2. The `access_provisioning_config.yaml` file was not updated as part of this migration (last update was 2026-05-02, before the migration)
3. On 2026-08-13, the daily_forecast_scoring DAG ran successfully and wrote 1,861,220 rows to `forecast_output_v2`
4. The write succeeded because the writing service account has implicit write access to tables it creates in its own project
5. The nightly access provisioning job ran and granted read permissions only to tables in its static allowlist: `forecast_output` and `model_registry`
6. The new table `forecast_output_v2` was silently skipped (no warning or error) because it's not in the `managed_tables` configuration
7. When `inventory_planning_svc` attempted to read from `forecast_output_v2`, it received a PermissionDeniedError because it never received the SELECT privilege grant

PROPOSED FIX:
Update `access_provisioning_config.yaml` to replace `forecast_output` with `forecast_output_v2` in the managed_tables section, preserving all existing read_grants (inventory_planning_svc, replenishment_svc, bi_reporting_svc). Additionally, consider adding validation to the access provisioning job to detect when pipeline output tables exist but are not present in the configuration, emitting warnings or errors to prevent silent permission gaps in future migrations. As an immediate remediation step, manually grant read access on `forecast_output_v2` to all affected downstream service accounts.

---

## s019 — secondary_model_layer_failure (medium)

ROOT CAUSE:
On 2026-07-24, the config file was updated to rename `enabled_zones` to `zones_enabled` under the `weather_adjustment` section. However, the code in `adjustment_pipeline.py` was not updated in the same commit. The `_load_enabled_zones()` function still attempts to read `config["weather_adjustment"]["enabled_zones"]` (the old key name), which no longer exists in the YAML file. When this KeyError occurs, it is caught by the try/except block and the function returns an empty list with only a DEBUG-level log message. Since the log level is INFO, this fallback message is never captured. With an empty enabled zones list, every zone fails the `if sku_row["zone"] not in enabled_zones` check in `apply_weather_adjustment()`, causing the function to return 0.0 for all zones.

CAUSAL CHAIN:
1. On 2026-07-24, commit 3a7c1f0 renamed the config key from `weather_adjustment.enabled_zones` to `weather_adjustment.zones_enabled` but did not update the code that reads this config
2. When `_load_enabled_zones()` executes, it attempts to access `config["weather_adjustment"]["enabled_zones"]` which no longer exists in the YAML
3. The KeyError is caught by the try/except block added in commit c5b0a44, designed to make adjustment failures non-blocking
4. The function logs a DEBUG message ("weather_adjustment.enabled_zones not found in config, disabling adjustment") and returns an empty list `[]`
5. The DEBUG message is not visible in scoring_summary.log because the log level is set to INFO
6. With `enabled_zones = []`, every call to `apply_weather_adjustment()` finds that `sku_row["zone"] not in enabled_zones` evaluates to True (since no zone is in an empty list)
7. The function returns 0.0 for every zone without ever calling `_compute_adjustment_delta()`
8. All adjustment_applied values are logged as 0.0, and the pipeline completes "successfully" with no errors

PROPOSED FIX:
Update `adjustment_pipeline.py` line 13 to read the correct config key name: change `return config["weather_adjustment"]["enabled_zones"]` to `return config["weather_adjustment"]["zones_enabled"]`. Additionally, consider changing the fallback log message from DEBUG to WARNING level so that config mismatches are visible in production logs and can alert operators to silent degradation.

---

## s020 — secondary_model_layer_failure (hard)

ROOT CAUSE:
The adjustment model retrains weekly on a trailing 6-week window of residuals without any mechanism to exclude anomalous events. The severe storm in week 2026-07-06 created a legitimate -14% residual for that week, but this single anomalous week is being averaged into every subsequent retrain. As of 2026-08-10, the storm week is still within the 6-week trailing window (spanning 2026-06-29 to 2026-08-10), causing the model to persistently learn a negative correction of -11% to -13% even though the underlying weather has been normal for five weeks. The model treats the one-off storm event as if it represents a systematic forecasting bias rather than a transient anomaly.

CAUSAL CHAIN:
1. Severe storm hits zone Z_SE during week of 2026-07-06, causing genuinely suppressed sales and a -14% residual (core_forecast minus actual).
2. Weekly retrain on 2026-07-20 includes the storm week in its 6-week trailing window (2026-06-08 to 2026-07-20), learning a -14.0% correction by averaging the storm week with five normal weeks.
3. Subsequent weeks (2026-07-27, 2026-08-03, 2026-08-10) have normal weather and sales, but each retrain still includes the storm week in the trailing 6-week window.
4. The -14% storm residual continues to drag down the average correction, yielding -13.1%, -12.4%, and -11.8% respectively, even as more normal weeks enter the window.
5. The adjustment layer applies these negative corrections to current forecasts, systematically under-forecasting demand in Z_SE.
6. Replenishment receives artificially low forecasts and orders insufficient inventory, leading to recurring stockouts.
7. The storm week will remain in the trailing window until 2026-08-17 (when the window starts at 2026-07-06, the storm week itself), and fully exit only on 2026-08-24 (when the window starts at 2026-07-13).

PROPOSED FIX:
Implement anomaly exclusion logic in the adjustment model. Add a mechanism to flag and exclude known one-off events (severe weather, holidays, store closures, etc.) from the trailing residual window used for retraining. This can be achieved by: (1) creating an event registry that marks specific weeks as anomalous with a reason code, (2) modifying `load_trailing_residuals()` to filter out weeks flagged in the registry, and (3) setting `anomaly_exclusion: true` in the config. Additionally, consider adding a magnitude cap (e.g., `max_negative_adjustment_pct: -0.05`) to prevent any single extreme week from dominating the learned correction, and implement event-tied decay logic so adjustments automatically expire when the causal event window ends.

---

## s021 — false_positive_correct_behavior (hard)

ROOT CAUSE:
The 47 missing sku-store combinations are intentionally excluded from scoring by the pipeline's eligibility filters, not due to a bug. Each combination fails at least one of four documented business rules: SKU_40011 through SKU_40014 have insufficient sales history (3 and 2 days vs. the required 14-day minimum), SKU_50201 through SKU_50203 have effective dates in the future relative to the run_date (September 2026 vs. August 13, 2026), SKU_10233 and SKU_10388 are not ranged at the specific stores listed in the missing combinations report (though they are active SKUs carried at other stores), and SKU_20601 and SKU_20602 are marked as discontinued in the catalog. The pipeline correctly filtered all 47 combinations before scoring began, which is why the DAG ran green with nominal row counts and no exceptions.

CAUSAL CHAIN:
1. On run_date=2026-08-13, the scoring pipeline loads the SKU catalog and applies four eligibility filters before attempting to score any sku-store combinations
2. SKU_40011, SKU_40012 (3 days history), SKU_40013, SKU_40014 (2 days history) fail the MIN_SALES_HISTORY_DAYS >= 14 filter
3. SKU_50201, SKU_50202 (effective_date=2026-09-01), SKU_50203 (effective_date=2026-09-15) fail the is_active() filter because their effective dates are after the run_date
4. SKU_10233 at stores ST_0300, ST_0301, ST_0302 and SKU_10388 at stores ST_0155, ST_0156, ST_0157, ST_0158 fail the is_ranged_at_store() filter because these sku-store pairs are not in the assortment table
5. SKU_20601 and SKU_20602 fail the is_not_discontinued() filter due to status="discontinued"
6. All 47 combinations are excluded before scoring, so no forecast rows are written for them
7. The downstream inventory-planning team queries for these combinations and finds them missing, interpreting this as a potential scoring bug rather than intentional exclusion

PROPOSED FIX:
No code fix needed. The pipeline is working as designed—all 47 missing combinations correctly fail documented eligibility rules and should not receive forecasts. However, to prevent future false-alarm tickets, consider adding an eligibility exclusion report as a DAG output that logs the count and reason code (insufficient_history, not_yet_active, not_ranged, discontinued) for each excluded sku-store combination. This would allow downstream teams to self-diagnose by checking the exclusion report before filing tickets, and would provide an audit trail showing that exclusions are intentional business logic rather than data quality issues.

---
