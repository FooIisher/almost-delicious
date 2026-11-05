import unittest
from intent_usage import usage_metrics

class UsageTests(unittest.TestCase):
    def test_openai_cache_not_double_counted(self):
        d=usage_metrics({'input_tokens':1000,'output_tokens':100,'input_tokens_details':{'cached_tokens':800}},'gpt-4.1-mini')
        self.assertEqual(d['token_usage']['total_tokens'],1100)
        self.assertAlmostEqual(d['cost_estimate']['estimated_usd'],.00032)
    def test_deepseek_fields_and_blended_price(self):
        d=usage_metrics({'prompt_tokens':1000,'completion_tokens':100,'prompt_cache_hit_tokens':800},'deepseek-flash')
        self.assertEqual(d['token_usage']['cached_input_tokens'],800)
        # Mean of the official off-peak (.0000924) and peak (.0001848) estimates: one value for comparison.
        self.assertAlmostEqual(d['cost_estimate']['estimated_usd'],.0001386)
        self.assertEqual(d['cost_estimate']['min_usd'],d['cost_estimate']['max_usd'])
    def test_missing_unknown_zero(self):
        self.assertIsNone(usage_metrics(None,'gpt-4.1-mini')['cost_estimate']['estimated_usd'])
        self.assertIsNone(usage_metrics({'input_tokens':1,'output_tokens':2},'jev')['cost_estimate']['estimated_usd'])
        self.assertEqual(usage_metrics({'input_tokens':0,'output_tokens':0},'gpt-4.1-mini')['cost_estimate']['estimated_usd'],0)
    def test_invalid_or_partial(self):
        for usage in ({'input_tokens':True,'output_tokens':2},{'input_tokens':10},{'input_tokens':10,'output_tokens':2,'input_tokens_details':{'cached_tokens':11}}):
            self.assertEqual(usage_metrics(usage,'gpt-4.1-mini')['cost_estimate']['status'],'unavailable')
    def test_model_snapshot_and_cache_unknown(self):
        d=usage_metrics({'input_tokens':1000,'output_tokens':100},'gpt-4.1-nano-2025-04-14')
        self.assertEqual(d['cost_estimate']['pricing_model'],'gpt-4.1-nano')
        # Unreported cache usage is priced as uncached input: one value, no range.
        self.assertAlmostEqual(d['cost_estimate']['estimated_usd'],.00014)
        self.assertEqual(d['cost_estimate']['min_usd'],d['cost_estimate']['max_usd'])
    def test_astra_long_context_and_nonstandard_tier(self):
        d=usage_metrics({'input_tokens':300000,'output_tokens':1},'gpt-6-astra')
        self.assertEqual(d['cost_estimate']['rates_per_million']['input'],20)
        self.assertEqual(usage_metrics({'input_tokens':1,'output_tokens':2},'gpt-4.1-mini','priority')['cost_estimate']['status'],'unavailable')

class AggregateTests(unittest.TestCase):
    def test_sum_calls_and_cache(self):
        from intent_usage import aggregate_usage
        call=usage_metrics({'input_tokens':1000,'output_tokens':100,'input_tokens_details':{'cached_tokens':800}},'gpt-4.1-mini')
        data=aggregate_usage([call,call])
        self.assertEqual(data['token_usage']['total_tokens'],2200)
        self.assertEqual(data['token_usage']['cached_input_tokens'],1600)
        self.assertAlmostEqual(data['cost_estimate']['estimated_usd'],.00064)
    def test_unknown_not_free_or_complete(self):
        from intent_usage import aggregate_usage
        known=usage_metrics({'input_tokens':1000,'output_tokens':100},'gpt-4.1-mini')
        data=aggregate_usage([known,usage_metrics(None,'gpt-4.1-mini')])
        self.assertIsNone(data['token_usage']['total_tokens'])
        self.assertEqual(data['cost_estimate']['status'],'partial')
        self.assertIsNone(data['cost_estimate']['estimated_usd'])
        self.assertEqual(data['cost_estimate']['priced_calls'],1)
        self.assertEqual(aggregate_usage([])['cost_estimate']['status'],'unavailable')
