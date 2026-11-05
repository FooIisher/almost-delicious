"""Bounded multi-plan recall. No embedding, source mutation or qualification here."""
import copy
import time
from concurrent.futures import ThreadPoolExecutor, wait
from rrf import recipe_id
from relaxation_planner import apply_actions


def filter_matches(query, source):
    """Evaluate the exact keyword/range-only DSL emitted by build_filters.
    Unknown DSL fails closed; this is provenance attribution, never eligibility.
    """
    if not query or 'match_all' in query:return True
    if 'match_none' in query:return False
    if 'bool' in query:
        b=query['bool'];many=lambda k: b.get(k,[]) if isinstance(b.get(k,[]),list) else [b[k]]
        return (all(filter_matches(c,source) for c in many('filter')+many('must')) and
                not any(filter_matches(c,source) for c in many('must_not')) and
                sum(filter_matches(c,source) for c in many('should'))>=int(b.get('minimum_should_match',1 if b.get('should') and not(b.get('filter') or b.get('must')) else 0)))
    if 'exists' in query:return source.get(query['exists']['field']) not in (None,[])
    for operator in ('term','terms'):
        if operator in query:
            field,expected=next(iter(query[operator].items()));values=source.get(field,[]);values=values if isinstance(values,list) else [values]
            if operator=='terms':return any(v in expected for v in values)
            insensitive=isinstance(expected,dict) and expected.get('case_insensitive');value=expected.get('value') if isinstance(expected,dict) else expected
            return any(str(v).casefold()==str(value).casefold() if insensitive else v==value for v in values)
    if 'range' in query:
        field,bounds=next(iter(query['range'].items()));value=source.get(field)
        if not isinstance(value,(int,float)):return False
        return all({'gt':value>n,'gte':value>=n,'lt':value<n,'lte':value<=n}.get(op,False) for op,n in bounds.items())
    return False


def execute_relaxed(request,plans,names,strict_ids,emit):
    import recipe_search_api as api
    deadline=time.perf_counter()+request.relaxation_timeout_seconds
    filters={p['plan_id']:api.build_filters(apply_actions(request,p['actions'])) for p in plans}
    result={name:dict(hits=[],query_trace=[],plans=[],status='running',elapsed_ms=0,returned=0,added=0,error_type=None) for name in names}
    # Main threads read only after workers finish or deadline expires. A late
    # HTTP response cannot mutate the published snapshot.
    import threading
    lock=threading.Lock()
    def remaining():
        seconds=deadline-time.perf_counter()
        if seconds<=0:raise TimeoutError('Relaxation stage deadline')
        return seconds
    def publish(name,entry):
        with lock:
            if time.perf_counter()>deadline:return
            result[name]['plans'].append(entry)
    def request_many(name,bodies,entries):
        remaining_seconds=remaining()
        searches=[]
        for body in bodies:searches.extend([{'index':api.DEFAULT_INDEX},body])
        started=time.perf_counter()
        client=api.get_client().options(request_timeout=remaining_seconds,max_retries=0)
        response=client.msearch(searches=searches,max_concurrent_searches=1)
        responses=response.get('responses',[])
        for index,(body,entry) in enumerate(zip(bodies,entries)):
            r=responses[index] if index<len(responses) else {'error':'Missing msearch response'}
            okay=not r.get('error') and not r.get('timed_out') and not r.get('_shards',{}).get('failed',0)
            hits=r.get('hits',{}).get('hits',[]) if okay else []
            record=dict(**entry,status='complete' if okay else 'failed',returned=len(hits),elapsed_ms=r.get('took'),error_type=None if okay else str(r.get('error','Incomplete ES response')))
            trace=dict(branch=name,attempt='relaxed',plan_id=entry['plan_id'],body={'index':api.DEFAULT_INDEX,**body},settings=request.model_dump(),semantic_query=request.vector_query if name=='vector' else None,semantic_scope_query=request.vector_scope_query,vector_scope_weight=request.vector_scope_weight)
            with lock:
                if time.perf_counter()>deadline:return []
                result[name]['query_trace'].append(trace)
            publish(name,record)
            for hit in hits:
                hit=copy.deepcopy(hit)
                applicable=[p for p in plans if (p['plan_id']==entry['plan_id'] or entry['plan_id']=='combined') and filter_matches(filters[p['plan_id']],hit.get('_source',{}))]
                if not applicable:continue
                if entry['method']=='small_plan_direct':hit['_score']=None
                hit.update(source_level='relaxed',bm25_source_level='relaxed' if name=='bm25' else None,relaxation_plans=applicable,source_plans=[p['plan_id'] for p in applicable])
                with lock:
                    if time.perf_counter()<=deadline:result[name]['hits'].append(hit)
        return responses
    source={'excludes':api.SOURCE_EXCLUDES+['instructions','extract_ingredient_evidence','extract_ingredients_evidence']}
    def worker(name):
        if time.perf_counter()>=deadline:return
        started=time.perf_counter();emit('relaxed_'+name,'running',plans=[p['plan_id'] for p in plans])
        try:
            if name=='bm25':
                bodies=[dict(size=request.relaxed_bm25_per_plan,track_total_hits=False,_source=source,query=api.bm25_query(request.bm25_query,filters[p['plan_id']],request)) for p in plans]
                request_many(name,bodies,[dict(plan_id=p['plan_id'],method='bm25',requested=request.relaxed_bm25_per_plan) for p in plans])
            else:
                small=[p for p in plans if p['filter_match_count']<=request.relaxation_small_plan_threshold]
                large=[p for p in plans if p not in small]
                bodies=[dict(size=p['filter_match_count'],track_total_hits=False,_source=source,query=filters[p['plan_id']] or {'match_all':{}},sort=['_doc']) for p in small]
                entries=[dict(plan_id=p['plan_id'],method='small_plan_direct',requested=p['filter_match_count']) for p in small]
                state=getattr(request,'_relax_embedding_state',{})
                vector=state.get('vector')
                if large and vector is None:
                    publish(name,dict(plan_id='combined',method='combined_knn',requested=request.relaxed_vector_k,returned=0,status='failed',error_type='Strict embedding unavailable; not encoded again'))
                    large=[]
                if large:
                    k=request.relaxed_vector_k
                    if request.relaxation_vector_strategy=='separate':
                        for p in large:
                            count=request.relaxed_bm25_per_plan
                            bodies.append(dict(size=count,track_total_hits=False,_source=source,knn=dict(field='content_vector',query_vector=vector,k=count,num_candidates=max(count,request.relaxed_vector_num_candidates),filter=filters[p['plan_id']])))
                            entries.append(dict(plan_id=p['plan_id'],method='separate_knn',requested=count))
                        large=[]
                if large:
                    bodies.append(dict(size=k,track_total_hits=False,_source=source,knn=dict(field='content_vector',query_vector=vector,k=k,num_candidates=max(k,request.relaxed_vector_num_candidates),filter={'bool':{'should':[filters[p['plan_id']] or {'match_all':{}} for p in large],'minimum_should_match':1}})))
                    entries.append(dict(plan_id='combined',method='combined_knn',requested=k))
                if bodies:request_many(name,bodies,entries)
                # At most two underrepresented directions get a bounded refill.
                for p in [p for p in large if sum(p['plan_id'] in h['source_plans'] and recipe_id(h) not in strict_ids for h in result[name]['hits'])<request.relaxed_bm25_per_plan][:2]:
                    if time.perf_counter()>=deadline:break
                    k=request.relaxed_bm25_per_plan
                    request_many(name,[dict(size=k,track_total_hits=False,_source=source,knn=dict(field='content_vector',query_vector=vector,k=k,num_candidates=max(k,request.relaxed_vector_num_candidates),filter=filters[p['plan_id']]))],[dict(plan_id=p['plan_id'],method='knn_refill',requested=k)])
            with lock:
                records=result[name]['plans'];result[name]['status']='complete' if records and all(p['status']=='complete' for p in records) else 'partial' if result[name]['hits'] else 'failed'
        except Exception as error:
            with lock:result[name].update(status='partial' if result[name]['hits'] else 'failed',error_type=type(error).__name__)
        finally:
            with lock:result[name]['elapsed_ms']=(time.perf_counter()-started)*1000
    # Reuse bounded process-wide admission; avoid unbounded timeout worker growth.
    from retrieval_execution import POOL,SLOTS
    futures=[]
    for name in names:
        if not SLOTS.acquire(blocking=False):result[name].update(status='failed',error_type='CapacityExceeded');continue
        future=POOL.submit(worker,name);future.add_done_callback(lambda _:SLOTS.release());futures.append(future)
    wait(futures,timeout=max(0,deadline-time.perf_counter()))
    for future in futures:
        if not future.done():future.cancel()
    with lock:
        snapshot=copy.deepcopy(result)
    for name,run in snapshot.items():
        if run['status']=='running':run.update(status='partial' if run['hits'] or any(p['status']=='complete' for p in run['plans']) else 'timeout',error_type='RelaxationDeadline',elapsed_ms=request.relaxation_timeout_seconds*1000)
        # Preserve plan quotas before combining branch rankings. Highest rank
        # within each source response wins; no cross-DSL score comparison.
        seen={};ordered=[]
        for p in plans:
            rows=[h for h in run['hits'] if p['plan_id'] in h['source_plans'] and recipe_id(h) not in strict_ids]
            for h in rows[:request.relaxed_bm25_per_plan]:
                identifier=recipe_id(h)
                if identifier not in seen:seen[identifier]=h;ordered.append(h)
                else:
                    old=seen[identifier];old['relaxation_plans']=list({a['plan_id']:a for a in old['relaxation_plans']+h['relaxation_plans']}.values());old['source_plans']=[a['plan_id'] for a in old['relaxation_plans']]
        run['fetched_count']=len({recipe_id(h) for h in run['hits']});run['retained_count']=len(ordered)
        run['hits']=ordered;run['returned']=len(ordered);run['added']=sum(recipe_id(h) not in strict_ids for h in ordered)
        run['plan_counts']={p['plan_id']:sum(p['plan_id'] in h['source_plans'] for h in ordered) for p in plans}
        emit('relaxed_'+name,run['status'],run['elapsed_ms'],candidate_count=run['returned'],added=run['added'],plan_counts=run['plan_counts'])
    return snapshot
