# V0.4 Generated Variant Shadow QA

- Created at: `2026-06-28T02:34:38.864946+00:00`
- Train run: `20260628T013926Z`
- Classifier target: `publishable_or_repairable`

## Summary

- count: `358`
- shadow_ready_count: `358`
- shadow_ready_rate: `1.0`
- hard_block_count: `0`
- delivery_shape_applied_count: `195`
- delivery_shape_applied_rate: `0.5447`
- v04_score_ge_72_count: `154`
- v04_score_ge_72_rate: `0.4302`
- avg_v04_score: `71.415`
- avg_publishable_prob: `0.92`
- avg_naturalness: `13.81`

## By Domain

| Domain | Count | Ready Rate | Avg V0.4 | Avg Gate Prob | >=72 | Top Risks |
|---|---:|---:|---:|---:|---:|---|
| 健身 | 26 | 1.0 | 70.333 | 0.929 | 4 |  |
| 家居 | 26 | 1.0 | 72.225 | 0.758 | 12 |  |
| 旅行 | 108 | 1.0 | 72.021 | 0.928 | 55 | title_readability:1, travel_missing_transport_signal:1 |
| 母婴 | 26 | 1.0 | 68.995 | 0.928 | 3 |  |
| 穿搭 | 26 | 1.0 | 69.892 | 0.91 | 10 |  |
| 美妆 | 26 | 1.0 | 70.654 | 0.943 | 10 |  |
| 美食 | 120 | 1.0 | 71.946 | 0.941 | 60 | title_readability:3, food_missing_hours_signal:3 |

## Worst Cases

- `quality/generated_variants/v03_focus/fashion_wide_shoulder_soft_style_001/generate_initial.json` 穿搭 generate_initial score=`61.331` prob=`0.6903` ready=`True` risks=`` title=宽肩穿温柔感，先选领口再看肩线
- `quality/generated_variants/v07_food_travel_fact_sources/food_guangzhou_longxi_amap_002/claude_natural_candidate.json` 美食 claude_natural_candidate score=`61.954` prob=`0.8383` ready=`True` risks=`` title=番禺万博粤菜聚餐，人均98元这家很稳
- `quality/generated_variants/v08_food_expression_probe/food_guangzhou_taotaoju_amap_001/generate_refined.json` 美食 generate_refined score=`62.526` prob=`0.8412` ready=`True` risks=`` title=广州陶陶居早茶｜百年老字号人均110
- `quality/generated_variants/v08b_food_expression_probe/food_guangzhou_longxi_amap_002/claude_natural_candidate.json` 美食 claude_natural_candidate score=`62.802` prob=`0.8449` ready=`True` risks=`historical_artifact_blocking` title=番禺万博长禧家珑厨很稳
- `quality/generated_variants/v03_focus/fashion_wide_shoulder_soft_style_001/diagnosis_plan_a.json` 穿搭 diagnosis_plan_a score=`62.85` prob=`0.7139` ready=`True` risks=`` title=宽肩穿温柔感，领口和肩线决定成败
- `quality/generated_variants/v03_focus/travel_dali_slow_4day_001/claude_natural_candidate.json` 旅行 claude_natural_candidate score=`63.012` prob=`0.9347` ready=`True` risks=`` title=大理4天这样玩，不用每天赶景点
- `quality/generated_variants/v02_focus/beauty_sensitive_skin_sunscreen_001/claude_natural_candidate.json` 美妆 claude_natural_candidate score=`63.419` prob=`0.945` ready=`True` risks=`` title=敏感混干皮通勤防晒，早上两指量就够
- `quality/generated_variants/v02_focus/baby_teething_care_001/claude_natural_candidate.json` 母婴 claude_natural_candidate score=`63.514` prob=`0.9283` ready=`True` risks=`historical_artifact_blocking` title=宝宝出牙期这样护理，避免误区少走弯路
- `quality/generated_variants/v03_focus/fashion_wide_shoulder_soft_style_001/claude_natural_candidate.json` 穿搭 claude_natural_candidate score=`63.624` prob=`0.885` ready=`True` risks=`` title=宽肩穿温柔感，先看领口和肩线
- `quality/generated_variants/v07_food_travel_fact_sources/food_guangzhou_diandoude_amap_001/generate_initial.json` 美食 generate_initial score=`64.268` prob=`0.9566` ready=`True` risks=`` title=北京路逛街必吃｜点都德早茶人均86元
- `quality/generated_variants/v08_food_expression_probe/food_guangzhou_diandoude_amap_001/diagnosis_plan_a.json` 美食 diagnosis_plan_a score=`64.309` prob=`0.907` ready=`True` risks=`historical_artifact_blocking` title=广州北京路点都德早茶，人均86元很稳
- `quality/generated_variants/v03_focus/fashion_mens_clean_commute_001/diagnosis_plan_a.json` 穿搭 diagnosis_plan_a score=`64.424` prob=`0.9046` ready=`True` risks=`` title=175cm男生通勤穿搭：黑白灰蓝四色
- `quality/generated_variants/v03_focus/travel_guangzhou_hotel_family_001/generate_initial.json` 旅行 generate_initial score=`64.563` prob=`0.9081` ready=`True` risks=`` title=广州亲子酒店，地铁8分钟更省心
- `quality/generated_variants/v06_food_travel/food_shanghai_crab_noodle_hours_001/generate_refined.json` 美食 generate_refined score=`64.585` prob=`0.9032` ready=`True` risks=`` title=南京西路蟹黄面，11点半前排队
- `quality/generated_variants/v03_focus/fashion_mens_clean_commute_001/claude_natural_candidate.json` 穿搭 claude_natural_candidate score=`64.751` prob=`0.8031` ready=`True` risks=`` title=175身材男生通勤穿搭，干净利落不油
