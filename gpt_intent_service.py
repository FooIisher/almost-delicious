"""Direct OpenAI and DeepSeek adapters for the intent preview UI."""
import hashlib
import json
import logging
import os
import socket
import time
import traceback
import urllib.error
import urllib.request
from uuid import uuid4
from typing import Literal
from pathlib import Path
from datetime import datetime, timezone
from pydantic import ValidationError
from fastapi import HTTPException
from intent_service import IntentRequest, PARSE_SLOTS, router
from experiments.validate_gpt6 import ENDPOINT, MODEL, PROMPT, Extraction, parse_response, TARGET_FIELDS, SCHEMA_VERSION

DIAGNOSTICS_DIR = Path(__file__).parent / 'verification' / 'intent-failures'
logger = logging.getLogger('uvicorn.error')


def save_failure(record, key):
    """Never persist request headers or credentials, even if echoed in model text."""
    payload = json.dumps(record, ensure_ascii=False, indent=2, default=str)
    if key:
        payload = payload.replace(key, '[REDACTED]')
    try:
        DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
        path = DIAGNOSTICS_DIR / (record['diagnostic_id'] + '.json')
        with path.open('x', encoding='utf-8') as output:
            os.chmod(path, 0o600)
            output.write(payload + '\n')
        return True
    except OSError:
        return False


def present(p, query, context, elapsed, raw):
    rows=[]
    def row(field,label,value,support='unsupported',unit='',operator='',evidence=None):
        rows.append(dict(field=field,label=label,value=value,support=support,unit=unit,
                         operator=operator,evidence=evidence,source='recognized',applied=False,
                         needs_confirmation=False,target_filter=None))
    for x in p.ingredients:
        row('ingredient_'+x.role, {'available':'Available ingredient','required':'Required ingredient',
            'excluded':'Excluded ingredient','prefer':'Preferred ingredient','avoid':'Ingredient to avoid'}[x.role],
            [x.name], {'available':'context','required':'supported','excluded':'supported',
                       'prefer':'preference','avoid':'preference'}[x.role],evidence=x.evidence)
    for x in p.bounds:
        row(x.field,{'total_time':'Total time','calories':'Calories','protein':'Protein'}[x.field],x.value,
            # Nutrition basis is not yet represented structurally; do not imply filter compatibility.
            'supported' if x.field=='total_time' and x.operator=='lte' else 'unsupported',
            x.unit,{'lt':'<','lte':'≤','gt':'>','gte':'≥','eq':'='}[x.operator],x.evidence)
    if p.dietary_restrictions: row('diet','Dietary requirements',p.dietary_restrictions)
    if p.soft_preferences: row('preferences','Soft preferences',p.soft_preferences,'preference')
    questions=p.clarification_questions
    supported=p.intent=='recipe_search'
    parsed=dict(intent=p.intent,status='needs_clarification' if questions else 'ready' if supported else 'unsupported',
                **{field: getattr(p, field) for field in TARGET_FIELDS},
                target_evidence=p.target_evidence.model_dump(),
                confidence=None,search_type=None,search_text=p.search_text,
                clarification_question=' '.join(questions) or None,clarification_reasons=[],unsupported_reason=None,
                recipe_names=[],recipe_references=[],comparison_dimensions=[],question_type=None,
                missing_fields=[],uncertain_questions=[],extraction=p.model_dump())
    return dict(request_id=str(uuid4()),raw_query=query,model=raw.get('model',MODEL),
                provider='openai_direct',prompt_version=hashlib.sha256(PROMPT.encode()).hexdigest()[:12],
                schema_version=SCHEMA_VERSION,intent_parse_ms=elapsed,parsed=parsed,
                constraint_rows=rows,intent_scores={},threshold=None,filters_applied=False,
                execution_support='supported' if supported else 'unsupported',context=context,
                corrections=[x.model_dump() for x in p.corrections],usage=raw.get('usage'))


OPENAI_MODELS = {'gpt6': MODEL, 'gpt41-nano': 'gpt-4.1-nano', 'gpt41-mini': 'gpt-4.1-mini'}
DEEPSEEK_ENDPOINT = 'https://api.deepseek.com/chat/completions'
DEEPSEEK_FORMAT_INSTRUCTION = 'Return a JSON object conforming to this JSON Schema: '


@router.post('/intent/parse/{model_key}')
def parse_gpt6(request: IntentRequest, model_key: Literal['gpt6', 'gpt41-nano', 'gpt41-mini', 'deepseek-flash'] = 'gpt6'):
    deepseek = model_key == 'deepseek-flash'
    selected_model = model_key if deepseek else OPENAI_MODELS[model_key]
    provider_name = 'DeepSeek' if deepseek else 'OpenAI'
    provider = 'deepseek_direct' if deepseek else 'openai_direct'
    key_name = 'DEEPSEEK_API_KEY' if deepseek else 'OPENAI_API_KEY'
    key=os.environ.get(key_name,'').strip()
    if not key:
        raise HTTPException(503,detail={'code':'missing_api_key','message':f'Set {key_name} in the server terminal and restart the server.'})
    if not PARSE_SLOTS.acquire(blocking=False):
        raise HTTPException(503,detail={'code':'intent_busy','message':'Intent parsing is busy. Please retry.'})
    started=time.perf_counter()
    raw = None
    response_text = None
    stage = 'response_json'
    issues = []
    try:
        body=dict(model=selected_model,store=False,max_output_tokens=3500,
                  instructions=PROMPT,input=request.query,
                  text={'format':{'type':'json_schema','name':'recipe_intent','strict':True,'schema':Extraction.model_json_schema()}})
        if model_key == 'gpt6':
            body['reasoning'] = {'effort': 'low'}
        if deepseek:
            body = dict(model=selected_model, max_tokens=3500, stream=False,
                        thinking={'type': 'disabled'}, response_format={'type': 'json_object'},
                        messages=[{'role': 'system', 'content': PROMPT},
                                  {'role': 'system', 'content': DEEPSEEK_FORMAT_INSTRUCTION + json.dumps(Extraction.model_json_schema())},
                                  {'role': 'user', 'content': request.query}])
        req=urllib.request.Request(DEEPSEEK_ENDPOINT if deepseek else ENDPOINT,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=30) as response:
            response_text = response.read().decode('utf-8')
        raw = json.loads(response_text)
        stage = 'structured_output'
        if not isinstance(raw, dict):
            raise ValueError('Expected a response object')
        if deepseek:
            choices = raw.get('choices')
            if not isinstance(choices, list) or not choices:
                raise ValueError('DeepSeek returned no choices')
            choice = choices[0]
            if choice.get('finish_reason') != 'stop':
                raise ValueError('DeepSeek output did not finish normally: ' + str(choice.get('finish_reason')))
            p = Extraction.model_validate_json(choice['message']['content'])
        else:
            p=parse_response(raw)
        issues = []
        def evidence_issue(field, value, message):
            if value is not None and (not value or value.casefold() not in request.query.casefold()):
                issues.append(dict(field=field, value=value, reason=message + ': evidence must be a continuous substring of the original query (case-insensitive).'))
        for field, evidence in p.target_evidence.model_dump().items():
            evidence_issue(f'target_evidence.{field}', evidence, 'Invalid target evidence')
        for group in ('ingredients', 'bounds'):
            for index, x in enumerate(getattr(p, group)):
                evidence_issue(f'{group}.{index}.evidence', x.evidence, 'Invalid evidence')
        for index, x in enumerate(p.corrections):
            evidence_issue(f'corrections.{index}.original', x.original, 'Invalid correction evidence')
        for index, x in enumerate(p.bounds):
            expected = {'total_time':'minutes','calories':'kcal','protein':'g'}[x.field]
            if x.unit != expected:
                issues.append(dict(field=f'bounds.{index}.unit', value=x.unit, reason=f'Expected unit: {expected}'))
        if issues:
            stage = issues[0]['field']
            raise ValueError('; '.join(x['field'] + ': ' + x['reason'] for x in issues))
        stage = 'presentation'
        result = present(p,request.query,{'recipes':[],'selected_recipe_id':None},round((time.perf_counter()-started)*1000,2),raw)
        result['requested_model'] = selected_model
        result['model'] = raw.get('model') or selected_model
        result['provider'] = provider
        result['output_mode'] = 'json_object' if deepseek else 'json_schema'
        if deepseek:
            result['thinking_mode'] = 'disabled'
            result['format_instruction_version'] = hashlib.sha256(body['messages'][1]['content'].encode()).hexdigest()[:12]
        return result
    except urllib.error.HTTPError as e:
        try: code=json.loads(e.read()).get('error',{}).get('code')
        except (ValueError,AttributeError): code=None
        message=(f'{provider_name} API credits are exhausted. Check API billing.' if e.code==402 or code in ('credit_balance_exhausted','insufficient_quota')
                 else f'{provider_name} rejected the API key.' if e.code==401
                 else f'{provider_name} rate limit reached. Please retry later.' if e.code==429
                 else f'{provider_name} request failed. Check model access and server configuration.')
        raise HTTPException(502,detail={'code':'deepseek_request_failed' if deepseek else 'openai_request_failed','message':message}) from None
    except (TimeoutError,socket.timeout):
        raise HTTPException(504,detail={'code':'intent_timeout','message':f'{provider_name} intent parsing timed out.'}) from None
    except urllib.error.URLError:
        raise HTTPException(502,detail={'code':'connection_failed','message':f'Cannot connect to {provider_name}.'}) from None
    except (ValueError,KeyError,TypeError,AttributeError) as exc:
        if isinstance(exc, ValidationError):
            issues = [dict(field='.'.join(map(str, e['loc'])) or 'structured_output',
                           reason=e['msg'], value=e.get('input'))
                      for e in exc.errors(include_url=False, include_context=False)]
        if not issues:
            issues = [dict(field=stage, reason=str(exc), value=None)]
        model_text = ''
        if deepseek and isinstance(raw, dict):
            choices = raw.get('choices')
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get('message')
                if isinstance(message, dict) and isinstance(message.get('content'), str):
                    model_text = message['content']
        if isinstance(raw, dict) and isinstance(raw.get('output'), list):
            for item in raw['output']:
                if not isinstance(item, dict) or not isinstance(item.get('content'), list):
                    continue
                for part in item['content']:
                    if isinstance(part, dict):
                        value = part.get('text') or part.get('refusal')
                        if isinstance(value, str):
                            model_text += value
        try:
            model_output = json.loads(model_text)
        except ValueError:
            model_output = model_text or response_text
        diagnostic_id = str(uuid4())
        elapsed = round((time.perf_counter()-started)*1000, 2)
        # Format before logging so credentials echoed inside invalid model data
        # cannot leak through an unsanitized exception message.
        error_trace = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        if key:
            error_trace = error_trace.replace(key, '[REDACTED]')
        logger.error('Intent validation failed: model=%s stage=%s diagnostic_id=%s\n%s',
                     selected_model, stage, diagnostic_id, error_trace)
        saved = save_failure({
            'diagnostic_id': diagnostic_id, 'created_at': datetime.now(timezone.utc).isoformat(),
            'query': request.query, 'requested_model': selected_model,
            'provider': provider,
            'schema_version': SCHEMA_VERSION,
            'prompt_version': hashlib.sha256(PROMPT.encode()).hexdigest()[:12],
            'intent_parse_ms': elapsed, 'validation_stage': stage,
            'exception_type': type(exc).__name__, 'validation_error': str(exc),
            'validation_errors': issues,
            'raw_response': raw, 'raw_response_text': response_text if raw is None else None,
        }, key)
        if not saved:
            logger.warning('Could not save intent diagnostic: diagnostic_id=%s', diagnostic_id)
        detail = dict(code='invalid_model_output', status='validation_failed',
            message='Model output failed validation. It is shown for review only; no conditions were applied.',
            diagnostic_id=diagnostic_id, request_id=diagnostic_id, diagnostic_saved=saved,
            raw_query=request.query, requested_model=selected_model,
            model=raw.get('model', selected_model) if isinstance(raw, dict) else selected_model,
            validation_stage=stage, intent_parse_ms=elapsed,
            validation_errors=issues, model_output=model_output,
            filters_applied=False, execution_support='blocked')
        # Apply the same credential redaction to the browser response as to disk/logs.
        detail = json.loads(json.dumps(detail, default=str).replace(key, '[REDACTED]'))
        raise HTTPException(502, detail=detail) from None
    finally:
        PARSE_SLOTS.release()
