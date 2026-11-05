import copy, socket, unittest
from unittest.mock import patch
import content_generation as service
import test_content_generation as legacy
from eligibility import apply_semantic,local_checks
from content_generation import Assessment,CategoryCheck

class BatchRecoveryTests(unittest.TestCase):
    setUp=legacy.ContentGenerationTests.setUp
    provider=legacy.ContentGenerationTests.provider
    def check(self,**extra):
        return self.client.post('/content/eligibility/gpt41-mini',json={**self.request,**extra})
    def retry(self,data,**extra):
        return self.check(retry_run_id=data['check_run_id'],retry_batch_ids=[data['failed_batches'][0]['batch_id']],**extra)
    def test_extra_local_checks_ignored_and_batch_input_is_pending_only(self):
        self.request['retrieval_snapshot'].update(dish_name_target='soup',dish_type_target='soup')
        def extra(out,p,checking):
            if checking:
                for a in out['assessments']:
                    a['checks']=[dict(constraint_id='hard-3',status='fail',evidence=['invented local evidence'],reason='Must not overwrite local.')]+a['checks']+[dict(constraint_id='hard-2',status='not_matched',evidence=[],reason='Must not overwrite local.')]
        self.change=extra
        with patch.object(service.urllib.request,'urlopen',side_effect=self.provider) as calls:r=self.check()
        self.assertEqual(r.status_code,200,r.text);d=r.json();self.assertFalse(d['partial']);self.assertEqual(d['constraint_counts']['pass'],23)
        self.assertEqual(calls.call_count,2);self.assertTrue(any('Ignored already-decided' in w for w in d['warnings']))
        for payload in self.inputs:
            self.assertEqual([c['constraint_id'] for c in payload['category_constraints']],['hard-1'])
            self.assertNotIn('required_expression',payload)
        self.assertTrue(all(c['source']=='local' and c['decision']=='pass' for a in d['assessments'] for c in a['checks'] if c['kind'] in ('dish_name','dish_type')))
    def test_one_bad_recipe_preserves_others_and_retry_only_failed_recipe(self):
        self.change=lambda out,p,c: next((a for a in out['assessments'] if a['recipe_id']=='1'),{'checks':[]}).update(checks=[]) if c else None
        with patch.object(service.urllib.request,'urlopen',side_effect=self.provider) as calls:r=self.check()
        self.assertEqual(r.status_code,200,r.text);d=r.json();self.assertTrue(d['partial']);self.assertIsInstance(d['eligibility_id'],str);self.assertNotEqual(d['eligibility_id'],d['check_run_id']);self.assertEqual(d['constraint_counts']['pass'],22);self.assertEqual(d['constraint_counts']['not_checked'],1)
        self.assertEqual(d['failed_batches'][0]['recipe_ids'],['1']);self.assertEqual(calls.call_count,2)
        with patch.object(service.urllib.request,'urlopen') as calls:
            cached=self.check();self.assertTrue(cached.json()['cache_hit']);calls.assert_not_called()
            forged=self.client.post('/content/generate/gpt41-mini',json={'eligibility_id':d['check_run_id']});self.assertEqual(forged.status_code,409)
        self.change=None;self.inputs=[]
        with patch.object(service.urllib.request,'urlopen',side_effect=self.provider) as calls:r=self.retry(d)
        self.assertEqual(r.status_code,200,r.text);done=r.json();self.assertFalse(done['partial']);self.assertEqual(done['constraint_counts']['pass'],23)
        self.assertEqual(calls.call_count,1);self.assertEqual(self.inputs[0]['expected_recipe_ids'],['1'])
        self.assertEqual(done['new_model_call_count'],1);self.assertEqual(done['token_usage']['call_count'],3);self.assertEqual(done['current_attempt_usage']['token_usage']['call_count'],1)
        self.assertEqual(done['usage']['total_tokens'],30)
    def test_retry_preserves_provider_model_name(self):
        import json
        for model_key in ('gpt41-mini','deepseek-flash'):
            with self.subTest(model=model_key):
                self.change=lambda out,p,c: next((a for a in out['assessments'] if a['recipe_id']=='1'),{'checks':[]}).update(checks=[]) if c else None
                with patch.object(service.urllib.request,'urlopen',side_effect=self.provider):
                    d=self.client.post('/content/eligibility/'+model_key,json=self.request).json()
                self.assertTrue(d['partial'])
                self.change=None
                def provider(call,**kwargs):
                    body=json.loads(call.data)
                    self.assertEqual(body['model'],model_key if model_key=='deepseek-flash' else service.OPENAI_MODELS[model_key])
                    return self.provider(call,**kwargs)
                with patch.object(service.urllib.request,'urlopen',side_effect=provider):
                    result=self.client.post('/content/eligibility/'+model_key,json={**self.request,'retry_run_id':d['check_run_id'],'retry_batch_ids':[d['failed_batches'][0]['batch_id']]})
                self.assertEqual(result.status_code,200,result.text)
                self.assertFalse(result.json()['partial'])
                self.assertIsInstance(result.json()['model'],str)

    def test_invalid_first_batch_keeps_second_batch_and_its_usage(self):
        def change(out,p,c):
            if c and p['expected_recipe_ids'][0]=='1':out['assessments']={}
        self.change=change
        with patch.object(service.urllib.request,'urlopen',side_effect=self.provider) as calls:r=self.check()
        self.assertEqual(r.status_code,200,r.text);d=r.json();self.assertEqual(d['constraint_counts'],{'pass':3,'fail':0,'unknown':0,'not_checked':20,'near_miss':0})
        self.assertEqual(d['failed_batches'][0]['recipe_ids'],[str(i) for i in range(1,21)]);self.assertEqual(len(d['model_calls']),2)
        self.change=None;self.inputs=[]
        with patch.object(service.urllib.request,'urlopen',side_effect=self.provider) as calls:r=self.retry(d)
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(calls.call_count,1);self.assertEqual(self.inputs[0]['expected_recipe_ids'],[str(i) for i in range(1,21)])
        self.assertEqual(r.json()['constraint_counts']['pass'],23)
    def test_one_malformed_assessment_does_not_discard_valid_rows(self):
        def change(out,p,c):
            if c and p['expected_recipe_ids'][0]=='1':out['assessments'][0].pop('checks')
        self.change=change
        with patch.object(service.urllib.request,'urlopen',side_effect=self.provider):r=self.check()
        self.assertEqual(r.status_code,200,r.text);d=r.json()
        self.assertEqual(d['constraint_counts']['pass'],22);self.assertEqual(d['failed_batches'][0]['recipe_ids'],['1'])
    def test_partial_retry_context_data_model_and_expiry_guards(self):
        self.change=lambda out,p,c:out.update(assessments=[]) if c else None
        with patch.object(service.urllib.request,'urlopen',side_effect=self.provider):d=self.check().json()
        with patch.object(service.urllib.request,'urlopen') as calls:
            r=self.check(retry_run_id=d['check_run_id'],retry_batch_ids=['unknown']);self.assertEqual(r.status_code,409)
            r=self.retry(d,local_only=True);self.assertEqual(r.status_code,422)
            changed=copy.deepcopy(self.request);changed['retrieval_snapshot']['exclude_ingredients']=['onion']
            r=self.client.post('/content/eligibility/gpt41-mini',json={**changed,'retry_run_id':d['check_run_id'],'retry_batch_ids':[d['failed_batches'][0]['batch_id']]});self.assertEqual(r.status_code,409)
            self.es.mget.return_value['docs'][0]['_source']['ingredients'].append('carrot')
            self.assertEqual(self.retry(d).status_code,409)
            calls.assert_not_called()
    def test_order_is_not_a_failure_and_unknown_or_duplicate_ids_still_rejected(self):
        recipe=dict(name='Soup',ingredients=['broccoli'],extract_ingredients=[],keywords=[],recipecategory=[])
        constraints=[dict(constraint_id='a',kind='category',name='vegetable',role='required'),dict(constraint_id='b',kind='category',name='meat',role='excluded')]
        checks=local_checks(recipe,constraints)
        a=Assessment(recipe_id='1',checks=[CategoryCheck(constraint_id='b',status='not_matched',evidence=[],reason='No recorded meat.'),CategoryCheck(constraint_id='a',status='matched',evidence=['broccoli'],reason='Broccoli is a vegetable.')])
        self.assertEqual(apply_semantic(a,recipe,checks,checks[:]),[]);self.assertTrue(all(c['decision']=='pass' for c in checks))
        for ids in [['a','a'],['a','unknown']]:
            checks=local_checks(recipe,constraints)
            a=Assessment(recipe_id='1',checks=[CategoryCheck(constraint_id=i,status='matched',evidence=['broccoli'],reason='Recorded.') for i in ids])
            with self.assertRaises(ValueError):apply_semantic(a,recipe,checks,checks[:])
