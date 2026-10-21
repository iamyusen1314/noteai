"""Offline source-pixel, typography and persisted-geometry contracts for v2."""
import copy
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw
from model import cover_renderer as renderer

REF_A = '11111111-1111-4111-8111-111111111111'
REF_B = '22222222-2222-4222-8222-222222222222'
REF_C = '33333333-3333-4333-8333-333333333333'


def photo(color='green', size=(1200, 700)):
    image = Image.new('RGB', size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((500, 220, 900, 520), fill='#C93C36')
    stream = io.BytesIO()
    image.save(stream, 'PNG')
    return stream.getvalue()


def plan():
    return {'schema_version': 2, 'route': 'photo', 'text': '高楼里的\n日式庭院汤泉',
        'background_color': '#F6F1E8',
        'photos': [{'source_ref': REF_A, 'crop': [0, 0, 1, 1],
                    'subject_bbox': [.40, .25, .90, .80], 'bbox': [.02, .03, .98, .48]},
                   {'source_ref': REF_B, 'crop': [0, 0, 1, 1],
                    'subject_bbox': [.40, .25, .90, .80], 'bbox': [.02, .64, .98, .99]}],
        'text_layers': [
            {'text': '高楼里的', 'bbox': [.06, .48, .94, .53], 'font_id': 'SourceHanSerifSC-Regular',
             'font_size': 64, 'align': 'left', 'color': '#294A3D'},
            {'text': '日式庭院汤泉', 'bbox': [.06, .53, .94, .63], 'font_id': 'SourceHanSansSC-Bold',
             'font_size': 142, 'align': 'left', 'color': '#294A3D', 'stroke_width': 1}]}


def sources():
    return [{'media_ref': REF_A, 'payload': photo()}, {'media_ref': REF_B, 'payload': photo('blue')}]


class CoverRendererV2Tests(unittest.TestCase):
    def assert_code(self, code, fn, *args, **kwargs):
        with self.assertRaisesRegex(renderer.CoverRenderError, '^' + code + '$'):
            fn(*args, **kwargs)

    def test_multiphoto_exact_source_pixels_and_artifact(self):
        src, spec = sources(), plan()
        base, layout = renderer.compose_sources(src, spec)
        image = renderer.read_image(base)
        for item, source in zip(layout['photos'], src):
            bounds = item['photo_pixels']
            expected = renderer.read_image(source['payload']).crop(item['crop_pixels']).resize(
                (bounds[2] - bounds[0], bounds[3] - bounds[1]), Image.Resampling.LANCZOS)
            self.assertEqual(expected.tobytes(), image.crop(bounds).tobytes())
        result, final = renderer.render_text(base, layout)
        proof = renderer.validate_artifact(result, final)
        self.assertTrue(proof['valid'])
        self.assertEqual((1776, 2368), renderer.read_image(result).size)
        self.assertEqual(renderer.RENDERER_V2_VERSION, final['renderer_version'])
        self.assertEqual('高楼里的日式庭院汤泉', ''.join(final['rendered_lines']))
        self.assertEqual(set(final['source_hashes']), {REF_A, REF_B})

    def test_crop_and_projected_subject_protected(self):
        spec = plan()
        spec['photos'][0]['crop'] = [.6, 0, 1, 1]
        self.assert_code('COVER_SUBJECT_CROPPED', renderer.validate_plan, spec)
        spec = plan()
        spec['text_layers'][0]['bbox'] = [.45, .19, .9, .26]
        self.assert_code('COVER_TEXT_OVER_SUBJECT', renderer.compose_sources, sources(), spec)

    def test_invisible_type_is_corrected_against_actual_background_and_reopens(self):
        # A valid plan used to produce exactly the no-text base and still pass
        # artifact validation. Check pixels, not just metadata claiming text.
        for color, expected in [('#FFFFFF', '#111111'), ('#111111', '#FFFFFF')]:
            with self.subTest(background=color):
                spec = plan()
                spec['background_color'] = color
                for layer in spec['text_layers']:
                    layer.update(color=color, stroke_width=0)
                base, layout = renderer.compose_sources(sources(), spec)
                final, meta = renderer.render_text(base, layout)
                self.assertNotEqual(final, base)
                self.assertTrue(renderer.validate_artifact(final, meta)['valid'])
                self.assertTrue(all(layer['color'] == expected for layer in meta['text_layers']))
                before, after = renderer.read_image(base), renderer.read_image(final)
                for layer in meta['text_layers']:
                    box = renderer._pixels(layer['bbox'])
                    self.assertIsNotNone(ImageChops.difference(before.crop(box), after.crop(box)).getbbox())
                reopened = json.loads(json.dumps(meta))
                again, updated = renderer.render_text(base, reopened)
                self.assertEqual(again, final)
                self.assertEqual(updated['source_hashes'], layout['source_hashes'])
                self.assertEqual(updated['text'], layout['text'])

    def test_contrasting_outline_is_retained_on_actual_light_panel(self):
        spec = plan()
        spec['background_color'] = '#FFFFFF'
        for layer in spec['text_layers']:
            layer.update(color='#FFFFFF', stroke_width=2, stroke_color='#111111')
        base, layout = renderer.compose_sources(sources(), spec)
        final, meta = renderer.render_text(base, layout)
        self.assertNotEqual(final, base)
        self.assertTrue(all(layer['color'] == '#FFFFFF' for layer in meta['text_layers']))
        self.assertTrue(renderer.validate_artifact(final, meta)['valid'])

    def test_free_position_cannot_silently_change_saved_typography(self):
        image = Image.new('RGB', (1200, 1600), '#FFFFFF')
        ImageDraw.Draw(image).rectangle((0, 800, 1200, 1600), fill='#111111')
        stream = io.BytesIO()
        image.save(stream, 'PNG')
        spec = {'schema_version': 2, 'route': 'photo', 'text': '庭院汤泉',
            'background_color': '#FFFFFF',
            'photos': [{'source_ref': REF_A, 'crop': [0, 0, 1, 1],
                'subject_bbox': [.4, .4, .6, .6], 'bbox': [0, 0, 1, 1]}],
            'text_layers': [{'text': '庭院汤泉', 'bbox': [.1, .025, .9, .125],
                'font_id': 'SourceHanSansSC-Bold', 'font_size': 100,
                'align': 'left', 'color': '#111111'}]}
        base, layout = renderer.compose_sources([{'media_ref': REF_A, 'payload': stream.getvalue()}], spec)
        final, saved = renderer.render_text(base, layout)
        original = copy.deepcopy(saved)
        self.assertIn('bottom', renderer.position_options(saved))
        self.assert_code('COVER_TEXT_CONTRAST_INVALID', renderer.render_text,
                         base, saved, position=[.1, .875])
        self.assertEqual(original, saved)
        self.assertTrue(renderer.validate_artifact(final, saved)['valid'])
        # A move over the same light background keeps all immutable styles and
        # can pass the existing storage contract without a model call.
        adjusted, moved = renderer.render_text(base, saved, text='庭院', position=[.1, .15])
        mutable = {'text', 'bbox', 'rendered_lines', 'text_pixels', 'paint_pixels'}
        self.assertEqual({k: v for k, v in saved['text_layers'][0].items() if k not in mutable},
                         {k: v for k, v in moved['text_layers'][0].items() if k not in mutable})
        self.assertTrue(renderer.validate_artifact(adjusted, moved)['valid'])

    def test_valid_crop_projection_and_contain_preserve_original_pixels(self):
        src, spec = sources(), plan()
        spec['photos'][0]['crop'] = [.1, .1, .95, .9]
        base, layout = renderer.compose_sources(src, spec)
        item = layout['photos'][0]
        self.assertEqual([120, 70, 1140, 630], item['crop_pixels'])
        x, y, right, bottom = item['photo_pixels']
        expected = renderer.read_image(src[0]['payload']).crop(item['crop_pixels']).resize(
            (right-x, bottom-y), Image.Resampling.LANCZOS)
        self.assertEqual(expected.tobytes(), renderer.read_image(base).crop(item['photo_pixels']).tobytes())
        self.assertTrue(renderer._contains(item['photo_pixels'], item['subject_pixels']))
        self.assertGreater(item['subject_pixels'][0], x)
        final, meta = renderer.render_text(base, layout)
        self.assertTrue(renderer.validate_artifact(final, meta)['valid'])

    def test_text_in_photo_empty_region_is_allowed(self):
        spec = plan()
        spec['text_layers'][0]['bbox'] = [.04, .04, .37, .10]
        base, layout = renderer.compose_sources(sources(), spec)
        final, result = renderer.render_text(base, layout)
        self.assertTrue(renderer.validate_artifact(final, result)['valid'])
        self.assertLess(result['text_layers'][0]['paint_pixels'][0][2], layout['photos'][0]['subject_pixels'][0])

    def test_panel_is_also_paint_and_cannot_cover_subject(self):
        spec = plan()
        spec['text_layers'][0].update(bbox=[.04, .04, .8, .3], panel_opacity=.2)
        self.assert_code('COVER_TEXT_OVER_SUBJECT', renderer.compose_sources, sources(), spec)

    def test_text_layers_cannot_cover_each_other_and_styles_are_explicit(self):
        spec = plan()
        spec['text_layers'][1].update(bbox=[.06, .48, .94, .63], font_size=64)
        self.assert_code('COVER_TEXT_LAYERS_OVERLAP', renderer.compose_sources, sources(), spec)
        spec = plan()
        spec['text_layers'][0].update(align='right', stroke_width=2, stroke_color='#FFFFFF',
                                    panel_color='#FFFFFF', panel_opacity=.4)
        base, layout = renderer.compose_sources(sources(), spec)
        final, meta = renderer.render_text(base, layout)
        self.assertTrue(renderer.validate_artifact(final, meta)['valid'])
        self.assertEqual(.4, meta['text_layers'][0]['panel_opacity'])
        self.assertEqual('#294A3D', meta['text_layers'][0]['color'])

    def test_later_photo_cannot_hide_earlier_subject(self):
        spec = plan()
        spec['photos'][1]['bbox'] = [.3, .10, .98, .40]
        self.assert_code('COVER_PHOTO_OVER_SUBJECT', renderer.compose_sources, sources(), spec)

    def test_three_photos_and_no_duplicate_refs(self):
        spec = plan()
        spec['photos'][0]['bbox'] = [0, 0, .49, .4]
        spec['photos'][1]['bbox'] = [.51, 0, 1, .4]
        spec['photos'].append({'source_ref': REF_C, 'crop': [0, 0, 1, 1],
            'subject_bbox': [.4, .25, .9, .8], 'bbox': [0, .66, 1, 1]})
        base, layout = renderer.compose_sources(sources() + [{'media_ref': REF_C, 'payload': photo('yellow')}], spec)
        self.assertEqual(3, len(layout['photos']))
        spec['photos'][2]['source_ref'] = REF_A
        self.assert_code('COVER_SOURCE_DUPLICATED', renderer.validate_plan, spec)

    def test_overflow_does_not_shrink_font_or_truncate(self):
        spec = plan()
        spec['text_layers'][1]['bbox'] = [.05, .53, .15, .56]
        self.assert_code('COVER_TEXT_OVERFLOW', renderer.compose_sources, sources(), spec)

    def test_missing_glyph_no_fallback(self):
        spec = plan()
        spec['text_layers'][0]['text'] = chr(0x10FFFF)
        spec['text'] = chr(0x10FFFF) + '\n日式庭院汤泉'
        self.assert_code('COVER_TEXT_GLYPH_UNSUPPORTED', renderer.validate_plan, spec)

    def test_plan_finite_fields_and_exact_spaces(self):
        for value in [float('nan'), float('inf'), 10**1000, True]:
            spec = plan()
            spec['text_layers'][0]['line_height'] = value
            self.assert_code('COVER_LINE_HEIGHT_INVALID', renderer.validate_plan, spec)
        spec = plan()
        spec['text_layers'][0]['bbox'][0] = 10**1000
        self.assert_code('COVER_TEXT_INVALID', renderer.validate_plan, spec)
        spec = plan()
        spec['text'] = '高楼里的 日式庭院汤泉'
        self.assert_code('COVER_LAYER_TEXT_MISMATCH', renderer.validate_plan, spec)

    def test_persisted_metadata_recomputed(self):
        base, layout = renderer.compose_sources(sources(), plan())
        final, metadata = renderer.render_text(base, layout)
        for path in [('photos', 0, 'subject_pixels'), ('photos', 0, 'photo_pixels'),
                     ('text_layers', 0, 'paint_pixels'), ('text_layers', 0, 'font_sha256')]:
            changed = copy.deepcopy(metadata)
            changed[path[0]][path[1]][path[2]] = []
            self.assert_code('COVER_LAYOUT_METADATA_INVALID', renderer.validate_layout_metadata, changed)
        changed = copy.deepcopy(metadata)
        changed['source_hashes'][REF_A] = '0' * 64
        self.assert_code('COVER_LAYOUT_SOURCE_INVALID', renderer.validate_layout_metadata, changed)
        changed = copy.deepcopy(metadata)
        changed['final_sha256'] = '0' * 64
        self.assert_code('COVER_ARTIFACT_HASH_MISMATCH', renderer.validate_artifact, final, changed)
        changed['final_sha256'] = True
        self.assert_code('COVER_ARTIFACT_HASH_MISMATCH', renderer.validate_layout_metadata, changed)

    def test_free_rewrite_no_ghost_or_model_and_sources_unchanged(self):
        base, layout = renderer.compose_sources(sources(), plan())
        _, previous = renderer.render_text(base, layout)
        final, changed = renderer.render_text(base, previous, text='高楼里的日式庭院汤泉好松弛')
        fresh, same = renderer.render_text(base, layout, text='高楼里的日式庭院汤泉好松弛')
        self.assertEqual(final, fresh)
        self.assertEqual(changed['photos'], previous['photos'])
        self.assertEqual(changed['source_hashes'], previous['source_hashes'])
        self.assertEqual(changed['base_sha256'], previous['base_sha256'])
        self.assertEqual('高楼里的日式庭院汤泉好松弛', ''.join(changed['rendered_lines']))
        self.assertEqual([64, 142], [p['font_size'] for p in same['text_layers']])
        self.assert_code('COVER_BASE_HASH_MISMATCH', renderer.render_text, final, previous)

    def test_free_linebreak_content_and_shorter_title(self):
        spec = plan()
        spec['text_layers'][1]['font_size'] = 80
        base, layout = renderer.compose_sources(sources(), spec)
        final, changed = renderer.render_text(base, layout, lines=['高楼里的', '日式庭院', '汤泉'])
        self.assertEqual('高楼里的日式庭院汤泉', ''.join(changed['rendered_lines']))
        self.assert_code('COVER_LINEBREAK_CONTENT_MISMATCH', renderer.render_text, base, layout, lines=['高楼里的汤泉'])
        _, short = renderer.render_text(base, layout, text='汤泉')
        self.assertEqual('汤泉', short['text'])
        self.assertEqual(1, len(short['text_layers']))

    def test_free_position_moves_group_and_checks_actual_subject(self):
        base, layout = renderer.compose_sources(sources(), plan())
        # Safe small translation preserves the per-layer offset.
        final, moved = renderer.render_text(base, layout, position=[.07, .48])
        for before, after in zip(layout['text_layers'], moved['text_layers']):
            self.assertAlmostEqual(.01, after['bbox'][0] - before['bbox'][0])
            self.assertAlmostEqual(0, after['bbox'][1] - before['bbox'][1])
        self.assert_code('COVER_TEXT_OVER_SUBJECT', renderer.render_text, base, layout, position=[.06, .19])
        self.assertNotIn('bottom', renderer.position_options(layout))

    def test_source_hash_and_missing_reference_fail(self):
        src = sources()
        src[0]['sha256'] = '0' * 64
        self.assert_code('COVER_SOURCE_HASH_MISMATCH', renderer.compose_sources, src, plan())
        self.assert_code('COVER_SOURCE_MISSING', renderer.compose_sources, sources()[:1], plan())

    def test_free_edit_glyphs_overflow_and_runtime_metadata(self):
        base, layout = renderer.compose_sources(sources(), plan())
        layout.update(runtime_version='runtime-v2', design_model='lite', qc_model='lite',
                      input_source_hashes={'all-nine': 'immutable'}, selected_source_ref=REF_A)
        _, changed = renderer.render_text(base, layout, text='庭院')
        for key in ('runtime_version', 'design_model', 'qc_model', 'input_source_hashes', 'selected_source_ref'):
            self.assertEqual(layout[key], changed[key])
        self.assert_code('COVER_TEXT_GLYPH_UNSUPPORTED', renderer.render_text, base, layout, text=chr(0x10FFFF))
        self.assert_code('COVER_TEXT_OVERFLOW', renderer.render_text, base, layout, text='汤' * 64)

    def test_fonts_catalog_pins_license_and_bounded_cache(self):
        manifest = json.loads((renderer.FONT_PATH.parent / 'MANIFEST.json').read_text())
        files = {p['filename']: p for p in manifest['files']}
        for name, item in renderer.FONT_CATALOG.items():
            self.assertEqual(item['sha256'], hashlib.sha256(item['path'].read_bytes()).hexdigest())
            self.assertEqual(item['sha256'], files[item['path'].name]['sha256'])
        self.assertEqual(8, renderer._v2_face.cache_info().maxsize)
        self.assertEqual(list(renderer.FONT_CATALOG), renderer.design_capabilities()['font_ids'])
        with patch.dict(renderer.FONT_CATALOG, {'SourceHanSerifSC-Regular': {'path': renderer.FONT_PATH, 'sha256': '0'*64}}):
            self.assert_code('COVER_FONT_UNAVAILABLE', renderer.validate_plan, plan())


if __name__ == '__main__':
    unittest.main()
