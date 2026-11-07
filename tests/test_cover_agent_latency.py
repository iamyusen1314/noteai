"""Actual SDK convergence/image receipts; all provider responses are synthetic."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest import mock

from tests import test_cover_agent_runtime as fixture

runtime, provider = fixture.runtime, fixture.provider


class ProgressTimingBoundaryTests(unittest.TestCase):
    def test_optional_progress_is_exact_content_free_and_qc_never_goes_backward(self):
        events = []
        bridge = runtime.Bridge(job_id=str(uuid.uuid4()), directory=Path('/unused'), sources=[],
            hooks=SimpleNamespace(on_progress=events.append))
        self.assertFalse(bridge.progress({'phase': 'layout', 'detail_code': 'rendering', 'revision': 0,
            'prompt': 'PRIVATE_MUST_NOT_CROSS'}))
        self.assertFalse(bridge.progress({'phase': 'layout', 'detail_code': 'rendering', 'revision': True}))
        self.assertEqual(events, [])
        self.assertTrue(bridge.progress({'phase': 'qc', 'detail_code': 'checking_quality', 'revision': 0}))
        bridge.progress_revision = 1
        self.assertTrue(bridge.progress({'phase': 'layout', 'detail_code': 'rendering', 'revision': 1}))
        self.assertEqual(events[-1], {'phase': 'qc', 'detail_code': 'rendering', 'revision': 1})
        bridge.hooks = SimpleNamespace()
        self.assertFalse(bridge.progress({'phase': 'saving', 'detail_code': 'storing', 'revision': 1}))
        bridge.hooks = SimpleNamespace(on_progress=mock.Mock(side_effect=RuntimeError('private failure')))
        with self.assertLogs(level='WARNING') as logged:
            self.assertFalse(bridge.progress({'phase': 'saving', 'detail_code': 'storing', 'revision': 1}))
        self.assertNotIn('private failure', '\n'.join(logged.output))

    def test_bounded_timing_is_observation_and_unknown_is_never_repeated(self):
        bridge = runtime.Bridge(job_id=str(uuid.uuid4()), directory=Path('/unused'), sources=[], hooks=SimpleNamespace())
        call = mock.Mock(side_effect=provider.CoverAgentProviderError('fixture_unknown', outcome_unknown=True))
        with mock.patch.object(runtime.time, 'monotonic', side_effect=[1.0, 2.25]):
            with self.assertRaises(provider.CoverAgentProviderError):
                bridge._timed_call('primary', call)
        call.assert_called_once()
        self.assertEqual(bridge.model_timings[0], {'ordinal': 1, 'kind': 'primary', 'phase': 'design',
            'elapsed_ms': 1250, 'state': 'unconfirmed'})
        for _ in range(129):
            bridge._timed_call('qc', lambda: None)
        result = bridge.execution_summary()
        self.assertEqual((result['adapter_attempts'], result['dropped_attempts'], len(result['calls'])), (130, 2, 128))
        self.assertEqual(set(result['calls'][0]), {'ordinal', 'kind', 'phase', 'elapsed_ms', 'state'})
        result['calls'][0]['phase'] = 'mutated-copy'
        self.assertNotEqual(bridge.model_timings[0]['phase'], 'mutated-copy')


class HostInlinePixelBoundaryTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required for actual host helper')
    def test_actual_helpers_bind_images_and_only_guide_a_first_draft_with_current_pixels(self):
        script = r'''
import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';
import {createHash}from'node:crypto';
const s=fs.readFileSync(process.argv[1],'utf8');
const helpers=s.slice(s.indexOf('function toolResultText('),s.indexOf('function recoverableOriginalViewRejection('));
const sha=x=>createHash('sha256').update(x).digest('hex');
const ctx=vm.createContext({Buffer,MAX_FILE:10485760,sha,error:c=>Object.assign(new Error(c),{code:c}),imageFile:()=>{throw Error('unexpected actual file read')}});
vm.runInContext(helpers+'\nglobalThis.api={resultWithPixels,firstDraftRequest,toolResultText};',ctx);
const image=Buffer.from('synthetic identity bytes'),digest=sha(image),file={uri:'data:image/png;base64,'+image.toString('base64'),mime:'image/png',name:'fixed.png'};
const result={content:'{"ok":true}'};
const out=await ctx.api.resultWithPixels(result,'/job',[{path:'fixed.png',sha256:digest}],async()=>file);
assert.equal(out.content[0].text,result.content);assert.equal(out.content[1].uri,file.uri);assert.equal(typeof result.content,'string');
await assert.rejects(ctx.api.resultWithPixels(result,'/job',[{path:'fixed.png',sha256:'a'.repeat(64)}],async()=>file),/INLINE_IMAGE_CHANGED/);
assert.equal(ctx.api.toolResultText({type:'content',value:out.content}),result.content);
const render={type:'function',function:{name:'cover_render',parameters:{properties:{prepare:{properties:{files:{minItems:1,maxItems:6}}}},required:['request']}}};
const body={model:'fixed-pro',messages:[{role:'user',content:[{type:'image_url',image_url:{url:file.uri}}]}],
 tools:[render,{type:'function',function:{name:'cover_view'}},{type:'function',function:{name:'cover_write'}}]};
const before=JSON.stringify(body),guided=ctx.api.firstDraftRequest(body,{concept_sha256:digest});
assert.equal(JSON.stringify(body),before);
assert.deepEqual(Array.from(guided.tools,x=>x.function.name),['cover_view','cover_render']);
assert.equal(guided.tools[1].function.parameters.properties.prepare.properties.files.minItems,6);
assert.ok(guided.tools[1].function.parameters.required.includes('prepare'));
assert.equal(ctx.api.firstDraftRequest(body,{concept_sha256:digest,first_draft_attempted:true}),body);
assert.equal(ctx.api.firstDraftRequest(body,{concept_sha256:digest,first_draft_fallback:true}),body);
assert.equal(ctx.api.firstDraftRequest({...body,messages:[]},{concept_sha256:digest}).tools,body.tools);
assert.equal(ctx.api.firstDraftRequest({...body,tool_choice:'none'},{concept_sha256:digest}).tools,body.tools);
console.log(JSON.stringify({actual_host_helpers:true,current_pixels_required:true,changed_image_rejected:true,
 source_detail_view_retained:true,legacy_repair_menu_preserved:true,original_request_unchanged:true}));
'''
        result = subprocess.run([os.environ.get('NOTEAI_COVER_NODE', 'node'), '--input-type=module', '-e', script,
            str(runtime.ROOT / 'cover_agent_host/host.mjs')], text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


class BatchedScriptedBridge(fixture.ScriptedBridge):
    fail_first_prepare = False
    reject_first_qc = False

    def response(self, text, calls=None):
        if getattr(self, '_rejecting_qc', False):
            qc = json.loads(text)
            qc.update(approved=False, issues=['Improve title contrast'], local_adjustment={'contrast': 'stronger'})
            text = json.dumps(qc)
        return super().response(text, calls)

    def model(self, payload, stage='design'):
        if stage == 'qc':
            self._rejecting_qc = self.reject_first_qc and not any(item['stage'] == 'qc' for item in self.requests)
            try:
                return super().model(payload, stage)
            finally:
                self._rejecting_qc = False
        prepared, bound = provider.prepare_payload(self._restore_thinking(payload))
        self.ordinal += 1
        call_id = str(uuid.uuid5(uuid.UUID(self.job_id), 'offline:' + str(self.ordinal)))
        hashes = runtime._images_in(prepared)
        self.seen_images.update(hashes)
        self._record_source_inspections(hashes, call_id)
        self.requests.append({'stage': stage, 'input_bound': bound, 'body': prepared,
            'image_sha256': sorted(hashes), 'call_id': call_id})
        self.design_turn += 1
        turn = self.design_turn
        names = {item['function']['name'] for item in prepared.get('tools', [])}
        if self.progress_revision == 1:
            revision_turn = turn - (5 if self.fail_first_prepare else 4)
            if revision_turn == 1:
                if not {'cover_write', 'cover_render', 'cover_view'}.issubset(names):
                    raise AssertionError('QC revision lost the original local repair tools')
                html = self.html(self.sources[0]['path']).replace('--ink:#203a34', '--ink:#152720')
                calls = [('cover_write', {'path': 'index.html', 'text': html}),
                    ('cover_render', {'request': self.render_request})]
            elif revision_turn == 2:
                rendered = fixture.returned_value(prepared, 'png_sha256')
                if rendered['png_sha256'] not in hashes or rendered['thumbnail_sha256'] not in hashes:
                    raise AssertionError('QC repair final and thumbnail pixels not actually inspected')
                calls = [('cover_write', {'path': 'render-review.md', 'text': 'Inspected actual contrast repair pixels.'})]
            elif revision_turn == 3:
                return self.response('Local contrast repair inspected; ready for independent recheck.'), call_id
            else:
                raise AssertionError('Unexpected extra QC repair continuation')
        elif turn == 1:
            calls = [('cover_seedream', {'prompt': 'Offline exact-source synthetic composition concept.'})]
        elif turn == 2 or (self.fail_first_prepare and turn == 3):
            self.assert_concept = self.concept_hash in hashes
            if not self.assert_concept:
                raise AssertionError('Concept actual pixels did not accompany its tool receipt')
            if turn == 2:
                if names != {'cover_view', 'cover_render'}:
                    raise AssertionError('Actual SDK first-draft menu is not focused: ' + str(sorted(names)))
                schema = next(item['function']['parameters'] for item in prepared['tools']
                    if item['function']['name'] == 'cover_render')
                if 'prepare' not in schema['required'] or schema['properties']['prepare']['properties']['files']['minItems'] != 6:
                    raise AssertionError('Actual first-draft request lacks whole-packet contract')
            else:
                if not {'cover_read', 'cover_write', 'cover_check'}.issubset(names):
                    raise AssertionError('Real first-draft rejection did not restore repair tools')
                if fixture.returned_value(prepared, 'ok')['ok'] is not False:
                    raise AssertionError('Expected actual first-draft rejection')
            source = self.sources[0]
            html = self.html(source['path']).replace('--font-title:"Noto Sans SC Variable",sans-serif}',
                '--font-title:"Noto Sans SC Variable",sans-serif;}')
            files = [{'path': 'index.html', 'text': html},
                {'path': 'poster.json', 'text': json.dumps({'canvas': {'width': 1776, 'height': 2368}, 'scale': 1, 'dpi': None})},
                {'path': 'brief.md', 'text': 'Synthetic exact source and title.'},
                {'path': 'design-plan.md', 'text': 'Written only after actual inline concept pixels.'},
                {'path': 'asset-plan.json', 'text': json.dumps({'source': source['path']})},
                {'path': 'prompts.md', 'text': 'Synthetic concept and truthful original-photo shipping.'}]
            request = {'project_dir': '.', 'sources': [{'path': source['path']}],
                'text_layers': [{'id': 'title', 'allowed_rect': {'x': 90, 'y': 100, 'width': 1600, 'height': 350}}],
                'protected_regions': [{'x': 500, 'y': 800, 'width': 700, 'height': 800}]}
            self.render_request = request
            if self.fail_first_prepare and turn == 2:
                files[1]['path'] = 'not-an-approved-file.json'
            calls = [('cover_render', {'request': request,
                'prepare': {'files': files, 'fonts': [{'font_id': 'cjk-sans', 'css_var': '--font-title'}]}})]
        elif turn == (4 if self.fail_first_prepare else 3):
            try:
                rendered = fixture.returned_value(prepared, 'png_sha256')
            except AssertionError as error:
                returned = fixture.returned_value(prepared, 'prepare')
                raise AssertionError('Actual compound result: ' + json.dumps(returned)) from error
            if rendered['png_sha256'] not in hashes or rendered['thumbnail_sha256'] not in hashes:
                raise AssertionError('Actual final and thumbnail pixels were not included in next request')
            self.inline_render = rendered
            calls = [('cover_write', {'path': 'render-review.md',
                'text': 'Reviewed actual synthetic final and thumbnail; preserved source and readable title.'})]
        elif turn == (5 if self.fail_first_prepare else 4):
            return self.response('Synthetic final and thumbnail inspected; ready for independent QC.'), call_id
        else:
            raise AssertionError('Unexpected extra synthetic model continuation: ' + str(turn))
        return self.response(None, calls), call_id


class InlineConvergenceSDKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get('NOTEAI_COVER_HOST_NODE_MODULES') or not shutil.which('node'):
            raise unittest.SkipTest('Explicit approved existing SDK and Node required')

    def run_flow(self, fail_first_prepare, reject_first_qc=False):
        original = fixture.synthetic_png((2400, 1800), '#5A7F75')
        concept = fixture.synthetic_png((1776, 2368), '#A1A8B1')
        source = {'media_ref': str(uuid.uuid4()), 'payload': original, 'sha256': hashlib.sha256(original).hexdigest()}
        events = []
        hooks = fixture.cover_runtime.RuntimeHooks(lambda *_: None, lambda _: None,
            on_progress=events.append)
        def fake_image(**kwargs):
            record = {'stage': 'image', 'status': 'responded', 'provider': 'synthetic-fixture', 'call_id': kwargs['call_id']}
            kwargs['before_call']('image', kwargs['call_id'], {})
            kwargs['on_call'](record)
            return concept, record
        with tempfile.TemporaryDirectory(prefix='cover-inline-sdk-') as root:
            BatchedScriptedBridge.instances = []
            with mock.patch.dict(os.environ, {'NOTEAI_COVER_AGENT_STATE_ROOT': root}), \
                    mock.patch.object(BatchedScriptedBridge, 'fail_first_prepare', fail_first_prepare), \
                    mock.patch.object(BatchedScriptedBridge, 'reject_first_qc', reject_first_qc), \
                    mock.patch.object(runtime.cover_seedream, 'generate_background', side_effect=fake_image) as image:
                result = runtime.run_cover(job_id=str(uuid.uuid4()), user_id='offline-owner',
                    report={'title': '原照独立图层中文排字测试', 'body': 'Synthetic fixture, no merchant.', 'title_variants': []},
                    sources=[source], hooks=hooks, bridge_class=BatchedScriptedBridge)
            bridge = BatchedScriptedBridge.instances[-1]
            design_calls = (5 if fail_first_prepare else 4) + (3 if reject_first_qc else 0)
            self.assertEqual(bridge.design_turn, design_calls)
            self.assertEqual(len(bridge.requests), design_calls + (2 if reject_first_qc else 1))
            self.assertEqual(sum(item['stage'] == 'qc' for item in bridge.requests), 2 if reject_first_qc else 1)
            self.assertEqual(image.call_count, 1)
            self.assertTrue(bridge.assert_concept)
            self.assertEqual(result.layout['source_hashes'], {source['media_ref']: source['sha256']})
            self.assertEqual(result.layout['qc_status'], 'INITIAL_VISUAL_QC_PASSED')
            checkpoint = json.loads((bridge.directory / 'host-state/host-checkpoint.json').read_text())
            self.assertEqual(len(checkpoint['model_timings']), bridge.design_turn)
            self.assertTrue(all(set(item) == {'ordinal', 'kind', 'phase', 'elapsed_ms', 'state', 'http_status'}
                for item in checkpoint['model_timings']))
            self.assertTrue(all(set(item) == {'phase', 'detail_code', 'revision'} for item in events))
            self.assertIn({'phase': 'saving', 'detail_code': 'storing', 'revision': int(reject_first_qc)}, events)
            if reject_first_qc:
                revised = [event for event in events if event['revision'] == 1]
                self.assertIn({'phase': 'qc', 'detail_code': 'adjusting', 'revision': 1}, revised)
                self.assertIn({'phase': 'qc', 'detail_code': 'rechecking', 'revision': 1}, revised)
                self.assertTrue(all(event['phase'] in {'qc', 'saving'} for event in revised))
                self.assertEqual((result.design['local_revisions'], checkpoint['revision_count']), (1, 1))
            print('COVER_INLINE_CONVERGENCE_PROOF=' + json.dumps({'synthetic_design_calls': bridge.design_turn,
                'synthetic_total_Pro_calls': len(bridge.requests), 'original_legacy_design_calls': 7,
                'real_model_calls': 0, 'image_calls': 1, 'image_calls_are_synthetic': True,
                'actual_pixels_received_without_cover_view': True, 'real_renderer_and_independent_QC': True,
                'rejected_prepare_recovered': fail_first_prepare,
                'independent_QC_local_repair_preserved': reject_first_qc}, sort_keys=True))

    def test_actual_sdk_inline_pixels_and_complete_first_draft_reduce_decision_rounds(self):
        self.run_flow(False)

    def test_actual_prepare_rejection_restores_tools_and_still_reaches_real_qc(self):
        self.run_flow(True)

    def test_independent_qc_rejection_retains_one_actual_local_render_and_recheck(self):
        self.run_flow(False, reject_first_qc=True)
