# V0.4 Generated Variant Shadow QA

- Created at: `2026-06-28T07:04:55.845019+00:00`
- Train run: `20260628T013926Z`
- Classifier target: `publishable_or_repairable`

## Summary

- count: `386`
- shadow_ready_count: `386`
- shadow_ready_rate: `1.0`
- hard_block_count: `0`
- delivery_shape_applied_count: `187`
- delivery_shape_applied_rate: `0.4845`
- v04_score_ge_72_count: `179`
- v04_score_ge_72_rate: `0.4637`
- avg_v04_score: `71.619`
- avg_publishable_prob: `0.918`
- avg_naturalness: `12.812`

## By Domain

| Domain | Count | Ready Rate | Avg V0.4 | Avg Gate Prob | >=72 | Top Risks |
|---|---:|---:|---:|---:|---:|---|
| 健身 | 32 | 1.0 | 72.32 | 0.916 | 19 |  |
| 家居 | 30 | 1.0 | 72.24 | 0.755 | 15 |  |
| 旅行 | 112 | 1.0 | 71.978 | 0.929 | 56 | title_readability:1, travel_missing_transport_signal:1 |
| 母婴 | 28 | 1.0 | 69.889 | 0.934 | 4 |  |
| 穿搭 | 30 | 1.0 | 70.345 | 0.912 | 13 |  |
| 美妆 | 30 | 1.0 | 70.723 | 0.944 | 11 |  |
| 美食 | 124 | 1.0 | 71.879 | 0.941 | 61 | title_readability:3, food_missing_hours_signal:3, body_below_target_floor:1, body_length:1 |

## Worst Cases

- `quality/generated_variants/v03_focus/fashion_wide_shoulder_soft_style_001/generate_initial.json` 穿搭 generate_initial score=`61.331` prob=`0.6903` ready=`True` risks=`` title=宽肩穿温柔感，先选领口再看肩线
- `quality/generated_variants/v07_food_travel_fact_sources/food_guangzhou_longxi_amap_002/claude_natural_candidate.json` 美食 claude_natural_candidate score=`61.954` prob=`0.8383` ready=`True` risks=`` title=番禺万博粤菜聚餐，人均98元这家很稳
- `quality/generated_variants/v08_food_expression_probe/food_guangzhou_taotaoju_amap_001/generate_refined.json` 美食 generate_refined score=`62.526` prob=`0.8412` ready=`True` risks=`` title=广州陶陶居早茶｜百年老字号人均110
- `quality/generated_variants/v08b_food_expression_probe/food_guangzhou_longxi_amap_002/claude_natural_candidate.json` 美食 claude_natural_candidate score=`62.802` prob=`0.8449` ready=`True` risks=`historical_artifact_blocking` title=番禺万博长禧家珑厨很稳
- `quality/generated_variants/v03_focus/fashion_wide_shoulder_soft_style_001/diagnosis_plan_a.json` 穿搭 diagnosis_plan_a score=`62.85` prob=`0.7139` ready=`True` risks=`` title=宽肩穿温柔感，领口和肩线决定成败
- `quality/generated_variants/v03_focus/travel_dali_slow_4day_001/claude_natural_candidate.json` 旅行 claude_natural_candidate score=`63.012` prob=`0.9347` ready=`True` risks=`` title=大理4天这样玩，不用每天赶景点
- `quality/generated_variants/v02_focus/beauty_sensitive_skin_sunscreen_001/claude_natural_candidate.json` 美妆 claude_natural_candidate score=`63.419` prob=`0.945` ready=`True` risks=`` title=敏感混干皮通勤防晒，早上两指量就够
- `quality/generated_variants/v03_focus/fashion_wide_shoulder_soft_style_001/claude_natural_candidate.json` 穿搭 claude_natural_candidate score=`63.624` prob=`0.885` ready=`True` risks=`` title=宽肩穿温柔感，先看领口和肩线
- `quality/generated_variants/v01/fitness_home_fatloss_001/diagnosis_plan_b.json` 健身 diagnosis_plan_b score=`64.045` prob=`0.9456` ready=`True` risks=`` title=新手7天居家减脂，每晚20分钟
- `quality/generated_variants/v07_food_travel_fact_sources/food_guangzhou_diandoude_amap_001/generate_initial.json` 美食 generate_initial score=`64.268` prob=`0.9566` ready=`True` risks=`` title=北京路逛街必吃｜点都德早茶人均86元
- `quality/generated_variants/v08_food_expression_probe/food_guangzhou_diandoude_amap_001/diagnosis_plan_a.json` 美食 diagnosis_plan_a score=`64.309` prob=`0.907` ready=`True` risks=`historical_artifact_blocking` title=广州北京路点都德早茶，人均86元很稳
- `quality/generated_variants/v03_focus/fashion_mens_clean_commute_001/diagnosis_plan_a.json` 穿搭 diagnosis_plan_a score=`64.424` prob=`0.9046` ready=`True` risks=`` title=175cm男生通勤穿搭：黑白灰蓝四色
- `quality/generated_variants/v03_focus/travel_guangzhou_hotel_family_001/generate_initial.json` 旅行 generate_initial score=`64.563` prob=`0.9081` ready=`True` risks=`` title=广州亲子酒店，地铁8分钟更省心
- `quality/generated_variants/v06_food_travel/food_shanghai_crab_noodle_hours_001/generate_refined.json` 美食 generate_refined score=`64.585` prob=`0.9032` ready=`True` risks=`` title=南京西路蟹黄面，11点半前排队
- `quality/generated_variants/v03_focus/fashion_mens_clean_commute_001/claude_natural_candidate.json` 穿搭 claude_natural_candidate score=`64.751` prob=`0.8031` ready=`True` risks=`` title=175身材男生通勤穿搭，干净利落不油
