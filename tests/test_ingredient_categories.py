import os
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import gpt_intent_service as service
from recipe_search_api import app


class IngredientCategoryTests(unittest.TestCase):
    def output(self, ingredients):
        return dict(intent='recipe_search', search_text='beef soup', dish_name=None,
                    dish_type='soup', meal_type=None, cuisine=None,
                    target_evidence=dict(dish_name=None, dish_type='soup', meal_type=None, cuisine=None),
                    ingredients=ingredients, bounds=[], dietary_restrictions=[],
                    soft_preferences=[], corrections=[], clarification_questions=[])

    def test_categories_preserve_roles_but_have_no_execution_target_all_models(self):
        ingredients = [dict(name='beef', entity_type='specific', role='required', evidence='beef'),
                       dict(name='vegetable', entity_type='category', role='excluded', evidence='vegetables')]
        parsed = self.output(ingredients)
        models = {**service.OPENAI_MODELS, 'deepseek-flash': 'deepseek-flash'}
        for slug, model in models.items():
            raw = (dict(model=model, choices=[dict(finish_reason='stop', message=dict(content=json.dumps(parsed)))])
                   if slug == 'deepseek-flash' else
                   dict(model=model, status='completed', output=[dict(type='message', content=[dict(type='output_text', text=json.dumps(parsed))])]))
            with self.subTest(model=slug), patch.dict('os.environ', OPENAI_API_KEY='test', DEEPSEEK_API_KEY='test'), patch.object(service.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(raw).encode())):
                response = TestClient(app).post('/intent/parse/'+slug, json={'query': 'Find soup, must have beef, no vegetables'})
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result['parsed']['status'], 'ready')
            self.assertEqual(result['parsed']['extraction']['ingredients'],[{**i,'core':i['role']=='required' and i['entity_type']=='specific'} for i in ingredients])
            category = result['constraint_rows'][1]
            self.assertEqual(category['entity_type'], 'category')
            self.assertEqual(category['role'], 'excluded')
            self.assertEqual(category['support'], 'unsupported')
            self.assertFalse(category['applied'])
            self.assertIsNone(category['target_filter'])
            self.assertEqual(result['constraint_rows'][0]['support'], 'supported')
            self.assertTrue(result['constraint_rows'][0]['core'])
            self.assertFalse(result['constraint_rows'][1]['core'])

    def test_entity_type_required_and_invalid_values_rejected(self):
        for entity in (None, 'unknown', 'vegetable'):
            ingredient = dict(name='beef', evidence='beef', role='required')
            if entity is not None:
                ingredient['entity_type'] = entity
            with self.subTest(entity=entity), self.assertRaises(ValueError):
                service.Extraction.model_validate(self.output([ingredient]))
        schema = service.Extraction.model_json_schema()['$defs']['Ingredient']
        self.assertIn('entity_type', schema['required'])

    def test_category_still_requires_original_evidence(self):
        parsed = self.output([dict(name='vegetable', entity_type='category', role='excluded', evidence='not in query')])
        raw = dict(status='completed', output=[dict(type='message', content=[dict(type='output_text', text=json.dumps(parsed))])])
        with tempfile.TemporaryDirectory() as directory, patch.object(service, 'DIAGNOSTICS_DIR', Path(directory)), patch.dict('os.environ', OPENAI_API_KEY='test'), patch.object(service.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(raw).encode())):
            response = TestClient(app).post('/intent/parse/gpt41-mini', json={'query':'beef soup without vegetables'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['detail']['validation_stage'], 'ingredients.0.evidence')
