# RQS-07 Real Chain Acceptance Report

- Created at: `2026-06-28T15:44:47.689554+00:00`
- Artifact set: `v36_rqs05_06_regression`
- Artifact dir: `quality/generated_variants/v36_rqs05_06_regression`
- Gate: `PASS`

## Gate Checks

- run_reports_have_no_failures: `pass`
- run_reports_have_no_blocked_outputs: `pass`
- artifacts_have_no_blocking: `pass`
- artifacts_have_no_failures: `pass`
- all_artifacts_score_ge_60: `pass`
- titles_readable_after_delivery_sanitize: `pass`
- all_required_domains_present: `pass`
- diagnosis_bodies_are_distinct: `pass`
- shadow_set_ready_rate_is_1: `pass`
- shadow_set_hard_block_is_0: `pass`

## Artifact Summary

- Artifacts: `48`
- Status counts: `{"ready": 48}`
- Route counts: `{"chat": 6, "offline_candidate": 6, "second_pass": 6, "analyze": 18, "generate": 12}`
- Blocking: `0`
- Failures: `0`
- Scores: count `48`, min `67.276`, mean `74.284`, median `74.068`, max `79.523`
- Score >= 60: `48/48`
- Score >= 72: `44/48`
- Title issues after delivery sanitize: `0`
- Titles changed by sanitize: `16`
- Chat regression fallback count: `2`

## Run Reports

- Run reports: `2`
- Ready outputs: `48`
- Failures: `0`
- Blocked outputs: `0`
- `quality/generated_variants/v36_rqs05_06_regression/run_report_20260628T151411Z.json` ready `36`, failures `0`, blocked `0`, mean `73.642`, min `67.276`
- `quality/generated_variants/v36_rqs05_06_regression/run_report_20260628T152141Z.json` ready `12`, failures `0`, blocked `0`, mean `76.211`, min `73.357`

## By Domain

| Domain | Count | Mean | Median | Min | >=72 | Blocking | Title Issues | Routes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 健身 | 8 | 75.497 | 75.341 | 73.43 | 8 | 0 | 0 | chat:1, offline_candidate:1, second_pass:1, analyze:3, generate:2 |
| 家居 | 8 | 74.528 | 74.285 | 72.936 | 8 | 0 | 0 | chat:1, offline_candidate:1, second_pass:1, analyze:3, generate:2 |
| 旅行 | 8 | 74.569 | 74.534 | 73.113 | 8 | 0 | 0 | chat:1, offline_candidate:1, second_pass:1, analyze:3, generate:2 |
| 穿搭 | 8 | 73.245 | 73.042 | 71.648 | 7 | 0 | 0 | chat:1, offline_candidate:1, second_pass:1, analyze:3, generate:2 |
| 美妆 | 8 | 73.031 | 73.002 | 70.017 | 7 | 0 | 0 | chat:1, offline_candidate:1, second_pass:1, analyze:3, generate:2 |
| 美食 | 8 | 74.834 | 74.385 | 67.276 | 6 | 0 | 0 | chat:1, offline_candidate:1, second_pass:1, analyze:3, generate:2 |

## Diagnosis Integrity

| Task | Plans | Unique Bodies | Unique Titles | Body Distinct |
|---|---:|---:|---:|---|
| beauty_yellow_skin_blush_001 | 3 | 3 | 3 | `True` |
| fashion_petite_commute_001 | 3 | 3 | 2 | `True` |
| fitness_home_fatloss_001 | 3 | 3 | 3 | `True` |
| food_shanghai_crab_noodle_001 | 3 | 3 | 3 | `True` |
| home_rental_38sqm_001 | 3 | 3 | 1 | `True` |
| travel_chengdu_3day_001 | 3 | 3 | 3 | `True` |

## Shadow QA

- Shadow report: `/tmp/rqs07_shadow_qa_generated_variants.v04.json`
- Shadow report created at: `2026-06-28T15:42:40.467462+00:00`
- Artifact set ready rate: `1.0`
- Artifact set hard block count: `0`
- Artifact set avg V0.4 score: `73.804`
- Artifact set >=72: `39/48`

### Historical Generated Variants Context

- This section is audit context only. The RQS-07 gate above is scoped to the current artifact set.
- Overall historical count: `810`
- Overall shadow ready rate: `0.9815`
- Overall hard block count: `15`
- Overall avg V0.4 score: `72.889`
- Overall >=72: `522/810`
- Historical top risks: `{"structured_fact_boundary": 15, "body_below_target_floor": 7, "body_length": 7, "food_missing_hours_signal": 6, "title_readability": 3, "travel_missing_transport_signal": 1}`

## Residual Risks

- Non-blocking <72 samples remain. They are above the 60 hard gate and should be handled by selector/chat in production:
  - `quality/generated_variants/v36_rqs05_06_regression/food_shanghai_crab_noodle_001/generate_initial.json` 美食 generate_initial score `67.276` title `南京西路蟹黄拌面58元，周末必点`
  - `quality/generated_variants/v36_rqs05_06_regression/beauty_yellow_skin_blush_001/generate_refined.json` 美妆 generate_refined score `70.017` title `黄皮混干皮腮红，奶杏玫瑰色显白`
  - `quality/generated_variants/v36_rqs05_06_regression/food_shanghai_crab_noodle_001/diagnosis_plan_a.json` 美食 diagnosis_plan_a score `70.631` title `南京西路蟹黄拌面58元，周末排队必点`
  - `quality/generated_variants/v36_rqs05_06_regression/fashion_petite_commute_001/generate_refined.json` 穿搭 generate_refined score `71.648` title `小个子通勤显高3套公式，89元起`
