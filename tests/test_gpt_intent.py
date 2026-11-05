import os
import io
import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch
from urllib.error import HTTPError
from fastapi.testclient import TestClient
from recipe_search_api import app
import gpt_intent_service as service

class GPTIntentTests(unittest.TestCase):
    def setUp(self):
        diagnostics = tempfile.TemporaryDirectory()
        self.addCleanup(diagnostics.cleanup)
        self.diagnostics = Path(diagnostics.name)
        directory_patch = patch.object(service, 'DIAGNOSTICS_DIR', self.diagnostics)
        directory_patch.start()
        self.addCleanup(directory_patch.stop)
        self.client=TestClient(app)
        self.cases=json.loads((Path(__file__).resolve().parents[1]/'verification/gpt6-direct-intent-validation.json').read_text())['cases']
        # Synthetic v2 fixtures for adapter tests; historical live files stay intact.
        for case in self.cases:
            case['parsed'].update({field: None for field in service.TARGET_FIELDS})
            case['parsed']['target_evidence'] = dict.fromkeys(service.TARGET_FIELDS)

    def response(self,parsed):
        return io.BytesIO(json.dumps({'model':'gpt-6-astra','status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(parsed)}]}]}).encode())

    def test_v2_fixtures_are_compatible(self):
        for case in self.cases:
            with self.subTest(case=case['case']), patch.dict('os.environ',{'OPENAI_API_KEY':'test-key'}), patch.object(service.urllib.request,'urlopen',return_value=self.response(case['parsed'])) as call:
                response=self.client.post('/intent/parse/gpt6',json={'query':case['query']})
                self.assertEqual(response.status_code,200,response.text)
                data=response.json()
                self.assertFalse(data['filters_applied'])
                self.assertIsNone(data['parsed']['confidence'])
                self.assertEqual(data['parsed']['extraction'],case['parsed'])
                req=call.call_args.args[0]
                self.assertEqual(req.full_url,'https://api.openai.com/v1/responses')
                self.assertEqual(json.loads(req.data)['model'],'gpt-6-astra')
                if case['case']=='typo_soft':
                    avoid = next(row for row in data['constraint_rows'] if row['field'] == 'ingredient_avoid')
                    self.assertEqual(avoid['support'],'preference')
                    self.assertEqual(data['corrections'][0]['normalized'],'broccoli')
                if case['case']=='conflict': self.assertEqual(data['parsed']['status'],'needs_clarification')

    def test_missing_key_does_not_call_gateway(self):
        with patch.dict('os.environ',{'OPENAI_API_KEY':''}),patch.object(service.urllib.request,'urlopen') as call:
            self.assertEqual(self.client.post('/intent/parse/gpt6',json={'query':'salad'}).status_code,503)
            call.assert_not_called()

    def test_deepseek_direct_request_and_shared_validation(self):
        case = self.cases[0]
        raw = {'model': 'deepseek-flash', 'choices': [{'finish_reason': 'stop',
               'message': {'content': json.dumps(case['parsed'])}}]}
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'deepseek-test'}), patch.object(service.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(raw).encode())) as call:
            response = self.client.post('/intent/parse/deepseek-flash', json={'query': case['query']})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['provider'], 'deepseek_direct')
        self.assertEqual(data['parsed']['extraction'], case['parsed'])
        req = call.call_args.args[0]
        self.assertEqual(req.full_url, service.DEEPSEEK_ENDPOINT)
        self.assertEqual(req.get_header('Authorization'), 'Bearer deepseek-test')
        body = json.loads(req.data)
        self.assertEqual(body['messages'][0]['content'], service.PROMPT)
        self.assertEqual(body['messages'][-1]['content'], case['query'])
        self.assertEqual(body['thinking'], {'type': 'disabled'})
        self.assertEqual(body['response_format'], {'type': 'json_object'})

    def test_deepseek_requires_own_key(self):
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': '', 'OPENAI_API_KEY': 'test-key'}), patch.object(service.urllib.request, 'urlopen') as call:
            response = self.client.post('/intent/parse/deepseek-flash', json={'query': 'soup'})
        self.assertEqual(response.status_code, 503)
        self.assertIn('DEEPSEEK_API_KEY', response.text)
        call.assert_not_called()

    def test_deepseek_bad_evidence_and_truncation_preserve_output(self):
        p = self.cases[0]['parsed']
        for finish in ('stop', 'length'):
            raw = {'model': 'deepseek-flash', 'choices': [{'finish_reason': finish,
                   'message': {'content': json.dumps(p)}}]}
            with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'deepseek-test'}), patch.object(service.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(raw).encode())):
                response = self.client.post('/intent/parse/deepseek-flash', json={'query': 'unrelated'})
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.json()['detail']['model_output'], p)
            self.assertFalse(response.json()['detail']['filters_applied'])

    def test_deepseek_balance_error(self):
        error = HTTPError(service.DEEPSEEK_ENDPOINT, 402, 'balance', {}, io.BytesIO(b'{}'))
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'deepseek-test'}), patch.object(service.urllib.request, 'urlopen', side_effect=error):
            response = self.client.post('/intent/parse/deepseek-flash', json={'query': 'soup'})
        self.assertEqual(response.status_code, 502)
        self.assertIn('DeepSeek API credits', response.text)

    def test_credit_error(self):
        error=HTTPError(service.ENDPOINT,429,'quota',{},io.BytesIO(b'{"error":{"code":"credit_balance_exhausted"}}'))
        with patch.dict('os.environ',{'OPENAI_API_KEY':'test-key'}),patch.object(service.urllib.request,'urlopen',side_effect=error):
            response=self.client.post('/intent/parse/gpt6',json={'query':'salad'})
            self.assertEqual(response.status_code,502)
            self.assertIn('credits are exhausted',response.json()['detail']['message'])

    def test_invalid_evidence(self):
        result=dict(self.cases[0]['parsed'])
        with patch.dict('os.environ',{'OPENAI_API_KEY':'test-key'}),patch.object(service.urllib.request,'urlopen',return_value=self.response(result)):
            self.assertEqual(self.client.post('/intent/parse/gpt6',json={'query':'pasta'}).status_code,502)

    def test_model_routing_and_parameters(self):
        case=self.cases[0]
        for slug,model in service.OPENAI_MODELS.items():
            with self.subTest(model=model),patch.dict('os.environ',{'OPENAI_API_KEY':'test-key'}),patch.object(service.urllib.request,'urlopen',return_value=self.response(case['parsed'])) as call:
                response=self.client.post('/intent/parse/'+slug,json={'query':case['query']})
                self.assertEqual(response.status_code,200,response.text)
                body=json.loads(call.call_args.args[0].data)
                self.assertEqual(body['model'],model)
                self.assertEqual('reasoning' in body,slug=='gpt6')
                self.assertTrue(body['text']['format']['strict'])
                self.assertEqual(response.json()['requested_model'],model)
                self.assertEqual(response.json()['parsed']['extraction'],case['parsed'])

    def test_unknown_model_rejected_without_network(self):
        with patch.object(service.urllib.request,'urlopen') as call:
            self.assertEqual(self.client.post('/intent/parse/arbitrary-model',json={'query':'salad'}).status_code,422)
            call.assert_not_called()

    def test_validation_failure_is_logged_with_stage_and_traceback(self):
        invalid = dict(self.cases[0]['parsed'])
        invalid['dish_name'] = {'invalid': 'test-key'}
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch.object(service.urllib.request, 'urlopen', return_value=self.response(invalid)), self.assertLogs('uvicorn.error', level='ERROR') as captured:
            response = self.client.post('/intent/parse/gpt41-nano', json={'query': self.cases[0]['query']})
        self.assertEqual(response.status_code, 502)
        log = '\n'.join(captured.output)
        self.assertIn('model=gpt-4.1-nano stage=structured_output', log)
        self.assertIn('Traceback', log)
        self.assertIn('dish_name', log)
        self.assertIn(response.json()['detail']['diagnostic_id'], log)
        self.assertNotIn('test-key', log)

    def test_failure_diagnostic_preserves_response_and_redacts_key(self):
        p = dict(self.cases[0]['parsed'])
        p['cuisine'] = 'test-key'
        p['target_evidence'] = {**dict.fromkeys(service.TARGET_FIELDS), 'cuisine': 'absent evidence'}
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch.object(service.urllib.request, 'urlopen', return_value=self.response(p)):
            r = self.client.post('/intent/parse/gpt41-nano', json={'query': self.cases[0]['query']})
        detail = r.json()['detail']
        self.assertEqual(r.status_code, 502)
        self.assertTrue(detail['diagnostic_saved'])
        self.assertEqual(detail['validation_stage'], 'target_evidence.cuisine')
        text = (self.diagnostics/(detail['diagnostic_id']+'.json')).read_text()
        self.assertNotIn('test-key', text)
        log = json.loads(text)
        self.assertEqual(log['requested_model'], 'gpt-4.1-nano')
        self.assertIn('raw_response', log)
        self.assertIn('Invalid target evidence', log['validation_error'])

    def test_unwritable_diagnostics_keep_original_failure(self):
        invalid = dict(self.cases[0]['parsed'])
        del invalid['dish_name']
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch.object(service.urllib.request, 'urlopen', return_value=self.response(invalid)), patch.object(service.Path, 'mkdir', side_effect=OSError('disk full')):
            r = self.client.post('/intent/parse/gpt41-mini', json={'query': self.cases[0]['query']})
        self.assertEqual(r.status_code, 502)
        self.assertFalse(r.json()['detail']['diagnostic_saved'])

    def test_target_fields_and_evidence_round_trip_all_models(self):
        p = dict(self.cases[0]['parsed'])
        p.update(intent='recipe_search', search_text='quick Chinese beef soup for dinner',
                 dish_name='beef soup', dish_type='soup', meal_type='dinner', cuisine='chinese',
                 target_evidence=dict(dish_name='beef soup', dish_type='soup', meal_type='dinner', cuisine='Chinese'),
                 ingredients=[], bounds=[], corrections=[], clarification_questions=[])
        for slug in service.OPENAI_MODELS:
            with self.subTest(slug=slug), patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch.object(service.urllib.request, 'urlopen', return_value=self.response(p)) as call:
                r = self.client.post('/intent/parse/'+slug, json={'query': 'Give me a quick Chinese beef soup for dinner'})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()['schema_version'], 'recipe-extraction-v2')
                for field in service.TARGET_FIELDS:
                    self.assertEqual(r.json()['parsed'][field], p[field])
                schema = json.loads(call.call_args.args[0].data)['text']['format']['schema']
                self.assertTrue(set(service.TARGET_FIELDS) <= set(schema['required']))

    def test_missing_new_field_and_fabricated_target_evidence_rejected(self):
        p = dict(self.cases[0]['parsed'])
        del p['dish_name']
        for invalid in [p, {**self.cases[0]['parsed'], 'cuisine': 'chinese',
                            'target_evidence': {**dict.fromkeys(service.TARGET_FIELDS), 'cuisine': 'Chinese'}}]:
            with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch.object(service.urllib.request, 'urlopen', return_value=self.response(invalid)):
                self.assertEqual(self.client.post('/intent/parse/gpt41-mini', json={'query': self.cases[0]['query']}).status_code, 502)

    def test_multiple_evidence_failures_are_visible_and_blocked(self):
        p = dict(self.cases[0]['parsed'])
        p.update(dish_name='beef soup', cuisine='mexican',
                 target_evidence={**dict.fromkeys(service.TARGET_FIELDS),
                                  'dish_name': 'beef soup', 'cuisine': 'mexican'},
                 ingredients=[dict(name='onion', evidence='allergic to onion', role='excluded')],
                 bounds=[], corrections=[])
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch.object(service.urllib.request, 'urlopen', return_value=self.response(p)):
            response = self.client.post('/intent/parse/gpt41-nano', json={'query': 'I am allergic to onino. Find soup with beef and Mexican flavor'})
        detail = response.json()['detail']
        self.assertEqual(response.status_code, 502)
        self.assertEqual(detail['model_output'], p)
        self.assertEqual([e['field'] for e in detail['validation_errors']],
                         ['target_evidence.dish_name', 'ingredients.0.evidence'])
        self.assertEqual(detail['status'], 'validation_failed')
        self.assertEqual(detail['execution_support'], 'blocked')
        self.assertFalse(detail['filters_applied'])
        self.assertNotIn('parsed', detail)

    def test_schema_errors_preserve_output_and_redact_browser_response(self):
        p = dict(self.cases[0]['parsed'])
        p.update(dish_name={'secret': 'test-key'}, cuisine=42)
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch.object(service.urllib.request, 'urlopen', return_value=self.response(p)):
            response = self.client.post('/intent/parse/gpt41-mini', json={'query': 'soup'})
        detail = response.json()['detail']
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('test-key', response.text)
        self.assertEqual(detail['model_output']['dish_name']['secret'], '[REDACTED]')
        self.assertEqual({e['field'] for e in detail['validation_errors']}, {'dish_name', 'cuisine'})

    def test_malformed_model_json_is_displayable(self):
        raw = {'status': 'completed', 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': '{"intent":'}]}]}
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch.object(service.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(raw).encode())):
            response = self.client.post('/intent/parse/gpt41-nano', json={'query': 'soup'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['detail']['model_output'], '{"intent":')
        self.assertTrue(response.json()['detail']['validation_errors'])

    def test_evidence_accepts_case_differences_and_preserves_model_values(self):
        p = dict(self.cases[0]['parsed'])
        p.update(dish_name=None, dish_type=None, meal_type=None, cuisine='chinese',
                 target_evidence={**dict.fromkeys(service.TARGET_FIELDS), 'cuisine': 'chinese'},
                 ingredients=[dict(name='pork', evidence='PORK', role='required')],
                 bounds=[dict(field='total_time', operator='lte', value=30, unit='minutes', evidence='30 MINUTES')],
                 corrections=[dict(original='FAVOR', normalized='flavor')])
        for slug in service.OPENAI_MODELS:
            with self.subTest(model=slug), patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch.object(service.urllib.request, 'urlopen', return_value=self.response(p)):
                response = self.client.post('/intent/parse/'+slug, json={'query': 'Chinese favor pork soup in 30 minutes'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['parsed']['extraction'], p)
