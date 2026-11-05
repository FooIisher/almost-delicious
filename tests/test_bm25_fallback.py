"""Compatibility tests for retired branch-only fallback."""
import unittest
from unittest.mock import patch
import recipe_search_api as api
from test_rrf import hit
from test_search import candidates
class FallbackTests(unittest.TestCase):
 def test_threshold_alias_and_failed_stats_preserve_single_required(self):
  with patch.object(api,'retrieve_candidates',return_value=candidates([hit('1')])) as retrieve:
   d=api.search(api.SearchRequest(query='soup',mode='bm25',include_ingredients=['durian'],bm25_fallback_threshold=5))
  self.assertEqual(retrieve.call_count,1);self.assertEqual(d['relaxation']['status'],'statistics_failed');self.assertEqual(d['relaxation']['threshold'],5)
  self.assertEqual(d['branch_filters']['bm25']['include_ingredients'],['durian'])
 def test_threshold_disabled_no_retry(self):
  with patch.object(api,'retrieve_candidates',return_value=candidates([hit('1')])) as retrieve:
   d=api.search(api.SearchRequest(query='soup',mode='hybrid',max_calories=100,bm25_fallback_threshold=0))
  self.assertEqual(retrieve.call_count,2);self.assertEqual(d['relaxation']['status'],'strict_sufficient')
 def test_no_relaxable_conditions_vector_runs_once(self):
  with patch.object(api,'retrieve_candidates',return_value=candidates([hit('1')])) as retrieve:
   d=api.search(api.SearchRequest(query='soup',mode='vector',exclude_ingredients=['onion']))
  self.assertEqual(retrieve.call_count,1);self.assertEqual(d['relaxation']['status'],'no_plan')
