"""Provider-reported intent usage and versioned USD estimates (not invoices)."""
import re

PRICING_VERSION = '2026-10-18'
# USD per million text tokens: uncached input, cached input, output.
RATES = {
    'gpt-4.1-mini': (.4, .1, 1.6),
    'gpt-4.1-nano': (.1, .025, .4),
    'gpt-6-astra': (10., 1., 50.),
}
SOURCES = {name:'https://developers.openai.com/api/docs/models/'+name for name in RATES}
SOURCES['deepseek-flash']='https://api-docs.deepseek.com/quick_start/pricing/'


def count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def usage_metrics(usage, model, service_tier=None):
    raw = usage if isinstance(usage, dict) else {}
    incoming = count(raw.get('input_tokens',raw.get('prompt_tokens')))
    outgoing = count(raw.get('output_tokens',raw.get('completion_tokens')))
    total = count(raw.get('total_tokens'))
    if total is None and incoming is not None and outgoing is not None:
        total = incoming + outgoing
    details = raw.get('input_tokens_details') or raw.get('prompt_tokens_details') or {}
    details = details if isinstance(details, dict) else {}
    cached = count(details.get('cached_tokens',raw.get('prompt_cache_hit_tokens')))
    missed = count(raw.get('prompt_cache_miss_tokens'))
    if cached is None and incoming is not None and missed is not None and missed <= incoming:
        cached = incoming-missed
    invalid_cache = incoming is not None and cached is not None and (cached > incoming or (missed is not None and cached+missed != incoming))
    tokens = dict(input_tokens=incoming,output_tokens=outgoing,total_tokens=total,
                  cached_input_tokens=None if invalid_cache else cached,source='provider' if raw else 'unavailable')
    cost = dict(currency='USD',status='unavailable',estimated_usd=None,min_usd=None,max_usd=None,
                pricing_version=PRICING_VERSION,pricing_model=None,source_url=None)
    if incoming is None or outgoing is None or invalid_cache:
        cost['note']='Provider usage is missing or invalid; no cost was inferred from text length.'
        return dict(token_usage=tokens,cost_estimate=cost)
    model = model if isinstance(model,str) else ''
    canonical = next((name for name in RATES if re.fullmatch(re.escape(name)+r'(?:-\d{4}-\d{2}-\d{2})?',model)),None)
    if model in ('deepseek-flash','deepseek-v4-flash','deepseek-v4.1-flash','deepseek-v4.1-flash-1017'):
        canonical='deepseek-flash'
    if not canonical:
        cost['note']='No verified price for the returned model; usage remains available.'
        return dict(token_usage=tokens,cost_estimate=cost)
    if service_tier not in (None,'default','standard','auto'):
        cost['note']='Non-standard service tier; its price is not configured.'
        return dict(token_usage=tokens,cost_estimate=cost)
    cost.update(pricing_model=canonical,source_url=SOURCES[canonical])
    rates = RATES.get(canonical)
    if canonical=='gpt-6-astra' and incoming>272000:
        rates=(20.,2.,75.)
    # DeepSeek time bands/public holidays are not reliably exposed by the API.
    # Report both official off-peak and peak rates rather than guess the invoice tier.
    low_rates,high_rates = ((.15,.003,.6),(.3,.006,1.2)) if canonical=='deepseek-flash' else (rates,rates)
    low_cached = incoming if cached is None else cached
    high_cached = 0 if cached is None else cached
    def expense(rates, cached_tokens):
        return ((incoming-cached_tokens)*rates[0]+cached_tokens*rates[1]+outgoing*rates[2])/1_000_000
    lower,upper=expense(low_rates,low_cached),expense(high_rates,high_cached)
    cost.update(status='estimated',estimated_usd=upper,min_usd=lower,max_usd=upper,
                rates_per_million=dict(input=high_rates[0],cached_input=high_rates[1],output=high_rates[2]))
    notes=['Approximate text-token cost, not an invoice; taxes, credits and account discounts excluded.']
    if canonical=='deepseek-flash':notes.append('Range spans official off-peak/peak rates; upper bound is shown as the estimate.')
    if cached is None:notes.append('Cache usage not reported; range includes cached/uncached input possibilities.')
    notes.append('Standard API pricing; separate cache-write or other unreported charges are excluded.')
    cost['note']=' '.join(notes)
    return dict(token_usage=tokens,cost_estimate=cost)


def aggregate_usage(calls):
    """Sum per-call estimates; unknown calls never silently contribute zero."""
    fields=('input_tokens','output_tokens','total_tokens','cached_input_tokens')
    tokens={}
    for field in fields:
        values=[call.get('token_usage',{}).get(field) for call in calls]
        tokens[field]=sum(values) if values and all(value is not None for value in values) else None
    tokens['reported_calls']=sum(call.get('token_usage',{}).get('total_tokens') is not None for call in calls)
    tokens['call_count']=len(calls)
    priced=[call['cost_estimate'] for call in calls if call.get('cost_estimate',{}).get('status')=='estimated']
    complete=bool(calls) and len(priced)==len(calls)
    low=sum(cost['min_usd'] for cost in priced)
    high=sum(cost['max_usd'] for cost in priced)
    cost=dict(currency='USD',status='estimated' if complete else 'partial' if priced else 'unavailable',
        estimated_usd=high if complete else None,min_usd=low if complete else None,max_usd=high if complete else None,
        known_min_usd=low if priced else None,known_max_usd=high if priced else None,
        priced_calls=len(priced),call_count=len(calls),pricing_version=PRICING_VERSION,
        note='Sum of per-call USD estimates, not an invoice. Unknown usage/prices are not treated as zero.' if calls else 'No model calls were made; no API cost incurred by this generation.')
    return dict(token_usage=tokens,cost_estimate=cost)
