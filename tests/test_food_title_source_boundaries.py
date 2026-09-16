"""Legacy prompt-copy regression; pure definitions, no API/DB/model/HTTP import."""
import ast
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def definitions(path, names, namespace):
    nodes = []
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            nodes.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id in names for target in targets):
                nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)


ns = {'re': re}
definitions(ROOT / 'model/prompt_composer.py', {
    '_TRAVEL_DOMAIN_ALIASES', '_DOMAIN_ALIASES', '_GEN_CHECKLIST_ALIASES', '_GEN_CHECKLISTS',
}, ns)
definitions(ROOT / 'model/api.py', {
    '_FOOD_LEGACY_PROMPT_TITLE_EXAMPLES', '_food_prompt_example_reuse_issues',
    '_delivery_integrity_issues', '_has_blocking_quality_issues',
}, ns)
# Unrelated fact/density families are covered by their existing regressions.
for name in ('_structured_fact_boundary_issues', '_user_constraint_delivery_issues',
             '_fitness_source_action_coverage_issues', '_fitness_unverified_result_issues',
             '_travel_hotel_fact_density_issues', '_home_replicability_density_issues'):
    ns[name] = lambda *args, **kwargs: []
ns['_quality_min_acceptable_percentile'] = lambda domain: 0
api = SimpleNamespace(**ns)
ORIGINAL_BAD = '成都本地人才知道的排队王，一周去了三次'
DECHU = '用户补充名称：广州德厨云宴\n\n商家原始素材：广州德厨云宴，上传了菜品和店内照片。'


class FoodPromptExampleBoundaryTests(unittest.TestCase):
    def issues(self, title, source=DECHU):
        return api._food_prompt_example_reuse_issues(title, source, '美食')

    def test_persisted_example_is_blocking_in_main_and_alternative(self):
        for text, variants in ((ORIGINAL_BAD + '\n真实正文', []),
                               ('广州德厨云宴聚餐\n真实正文', [ORIGINAL_BAD])):
            with self.subTest(variants=variants):
                issues = api._delivery_integrity_issues(text, DECHU, '美食', title_variants=variants)
                self.assertTrue(any('旧Prompt完整示例' in issue for issue in issues))
                self.assertTrue(api._has_blocking_quality_issues(99, issues, '美食'))
                if variants:
                    self.assertTrue(all(issue.startswith('备选标题1：') for issue in issues))

    def test_all_five_original_examples_are_checked(self):
        self.assertEqual(len(api._FOOD_LEGACY_PROMPT_TITLE_EXAMPLES), 5)
        for example in api._FOOD_LEGACY_PROMPT_TITLE_EXAMPLES:
            with self.subTest(example=example):
                self.assertTrue(self.issues(example))

    def test_copy_with_whitespace_and_punctuation_is_still_a_copy(self):
        self.assertTrue(self.issues('“成都本地人才知道的排队王, 一周去了三次!”'))
        self.assertTrue(self.issues('方案A：' + ORIGINAL_BAD + '。'))

    def test_original_user_text_match_is_not_mislabelled_prompt_only(self):
        for example in api._FOOD_LEGACY_PROMPT_TITLE_EXAMPLES:
            self.assertEqual(self.issues(example, '原素材：' + example), [])
        self.assertEqual(self.issues(ORIGINAL_BAD, '原素材：成都本地人才知道的排队王, 一周去了三次!'), [])

    def test_provider_or_expert_appendix_does_not_make_copy_user_material(self):
        for heading in ('【联网事实补全】', '【内容专家草稿】', '【候选】'):
            self.assertTrue(self.issues(ORIGINAL_BAD, DECHU + '\n' + heading + '\n' + ORIGINAL_BAD))

    def test_normal_titles_and_partial_overlap_are_not_a_general_city_guard(self):
        for title in ('广州德厨云宴，这桌菜值得记录', '成都小吃在广州', '万博这家餐厅',
                      '成都本地人才知道的小店', '广州德厨云宴，一周去了三次'):
            with self.subTest(title=title):
                self.assertEqual(self.issues(title), [])

    def test_other_domain_unchanged(self):
        self.assertEqual(api._food_prompt_example_reuse_issues(ORIGINAL_BAD, DECHU, '旅行'), [])

    def test_food_prompt_uses_structures_without_the_factual_examples(self):
        prompt = ns['_GEN_CHECKLISTS']['美食']
        for example in api._FOOD_LEGACY_PROMPT_TITLE_EXAMPLES:
            self.assertNotIn(example, prompt)
        self.assertIn('主标题和每个备选标题', prompt)
        self.assertIn('到店次数必须有本人素材依据', prompt)

    def test_both_generation_final_paths_call_existing_variant_guard(self):
        tree = ast.parse((ROOT / 'model/api.py').read_text())
        guarded = []
        for function in tree.body:
            if isinstance(function, ast.AsyncFunctionDef) and function.name in ('_run_generation_agents', '_generate_pipeline_stream'):
                guarded.append(function.name)
                calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Name) and node.func.id == '_delivery_integrity_issues']
                self.assertTrue(any(any(kw.arg == 'title_variants' for kw in call.keywords) for call in calls))
        self.assertEqual(len(guarded), 2)


if __name__ == '__main__':
    unittest.main()
