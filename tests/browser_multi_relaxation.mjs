import {verifyVerticalFlow} from './vertical_flow_helpers.mjs';
import {mockEligibility,checkThenGenerate,finishCheck} from './split_browser_helpers.mjs';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../web',import.meta.url));
const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[],generations=[];
page.on('pageerror',error=>errors.push(error.message));
const query='Find beef soup for dinner.';
const extraction={intent:'recipe_search',search_text:'beef soup',dish_name:null,dish_type:'soup',meal_type:'dinner',meal_type_role:'required',cuisine:null,cuisine_role:null,target_evidence:{dish_name:null,dish_type:'soup',meal_type:'dinner',cuisine:null},ingredients:[{name:'beef',role:'required',entity_type:'specific',evidence:'beef'}],required_expression:null,bounds:[],soft_preferences:[],dietary_restrictions:[],generation_notes:[],corrections:[],clarification_questions:[]};
const intent={request_id:'mock',raw_query:query,model:'mock-flash',schema_version:'recipe-extraction-v7',provider:'deepseek_direct',intent_parse_ms:4,parsed:{...extraction,extraction,status:'ready',recipe_names:[],recipe_references:[],comparison_dimensions:[],missing_fields:[],uncertain_questions:[],retrieval_queries:{bm25_query:'beef soup',vector_query:'Hearty beef soup',vector_scope_query:'Beef soup for dinner',source:'Required ingredients + Dish type'}},constraint_rows:[],intent_scores:{},execution_support:'supported',context:{recipes:[]}};
const recipes=[1,2,3].map((id,i)=>({recipe_id:String(id),document_id:String(id),name:['Beef Soup One','Beef Soup Two','Beef Soup Three'][i],ingredients:['beef'],instructions:['Simmer source ingredients.'],description:'Recorded recipe.',keywords:['soup','dinner'],recipecategory:['soup'],total_time_minutes:25,aggregatedrating:4,score:.9-i*.1,rank:i+1,match_highlights:{}}));
recipes[0].ingredients=['beef','tomatoes','green onions','ground chicken','plain fat-free yogurt','fresh coriander','fresh ginger','curry','dried coriander','cumin','cayenne','salt'];
let delay=0;
const ids=list=>list.map(r=>r.recipe_id);
function result(body){
 const bm=[recipes[1],recipes[0]].map((r,i)=>({...r,rank:i+1,score:10-i}));
 const vec=[recipes[0],recipes[2]].map((r,i)=>({...r,rank:i+1,score:.9-i*.1,semantic_similarity:.8-i*.2}));
 const hybrid=recipes.map((r,i)=>({...r,rank:i+1,rrf_rank:i+1,bm25_rank:i===2?null:i+1,vector_rank:i===1?null:i+1,bm25_contribution:.05,vector_contribution:.1,rrf_score:.15,normalized_rrf:.9-i*.1,final_score:1-i*.1,preference_score:.2,preference_evidence:[]}));
 const rows=body.mode==='hybrid'?hybrid:body.mode==='bm25'?bm:vec;
 return {type:'result',mode:body.mode,effective_mode:body.mode,execution:body.execution||'parallel',results:rows,result_count:rows.length,original_conditions:body,effective_filters:body,
   branch_results:{...(body.mode!=='vector'?{bm25:{status:'complete',candidate_count:2,results:bm,generation_candidate_ids:ids(bm)}}:{}),...(body.mode!=='bm25'?{vector:{status:'complete',candidate_count:2,results:vec,generation_candidate_ids:ids(vec)}}:{})},
   generation_candidate_ids:ids(rows),candidate_counts:{bm25:body.mode==='vector'?0:2,vector:body.mode==='bm25'?0:2,union:3,rrf:body.mode==='hybrid'?3:null},
   rrf:body.mode==='hybrid'?{k:10,bm25_boost:1,vector_boost:2}:null,preferences:body.mode==='hybrid'?{preference_lambda:.3,rating_boost:.1}:null,
   branches:{...(body.mode!=='vector'?{bm25:{status:'complete',elapsed_ms:12,candidate_count:2}}:{}),...(body.mode!=='bm25'?{vector:{status:'complete',elapsed_ms:20,candidate_count:2}}:{})},
   timings:{search_total_ms:24,bm25_recall_ms:12,vector_recall_ms:20,rrf_ms:1},match_result_size:{value:3,relation:'eq'},bm25_fallback:{triggered:false,used:false,initial_count:2,initial_ms:12},warnings:[],executed_queries:{}};
}
await page.route('**/*',async route=>{
 const path=new URL(route.request().url()).pathname;
 if(path==='/health')return route.fulfill({json:{status:'ok'}});
 if(path.startsWith('/intent/parse/'))return route.fulfill({json:intent});
 if(path==='/api/search/stream'){
  const body=route.request().postDataJSON();requests.push(body);const wait=delay;delay=0;
  if(wait)await new Promise(r=>setTimeout(r,wait));
  try{return await route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify(result(body))+'\n\n'});}catch{return;}
 }
 if(path.startsWith('/content/eligibility/'))return mockEligibility(route,recipes);
 if(path.startsWith('/content/generate/')){
  const body=route.request().postDataJSON().context;generations.push(body);const generatedRecipes=recipes.filter(r=>body.recipe_ids.includes(r.recipe_id));return route.fulfill({json:{schema_version:'recipe-generation-v13',generation_context:{query:body.query,recipe_ids:body.recipe_ids},summary:'Here are beef soups for your request.',recommendations:[{recipe_id:'1',reason:'Recorded beef and soup match your request.',flavor:'Beef',best_for:'Dinner'}],recipes:generatedRecipes,assessments:generatedRecipes.map(r=>({recipe_id:r.recipe_id,status:'pass',checks:[],unresolved:[]})),constraint_counts:{pass:3,fail:0,unknown:0,not_checked:0},model:'mock-flash',generation_ms:9,usage:{},warnings:[],model_calls:[]}});
 }
 if(path.startsWith('/recipes/'))return route.fulfill({json:recipes[0]});
 const file=path==='/'?'index.html':path.replace('/assets/','');try{return route.fulfill({body:await fs.readFile(root+'/'+file),contentType:file.endsWith('.html')?'text/html':file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'image/svg+xml'});}catch{return route.fulfill({status:404,body:''});}
});

recipes[0].name='Slow-simmered Beef Soup with Broccoli and Aromatic Herbs';
recipes[0].description='A comforting beef soup with recorded vegetables and a clear broth. This is the source introduction, preserved without rewriting.';
recipes[0].instructions=['Brown the beef in a large pan, then add the recorded broth and bring it to a gentle simmer.','Stir in the remaining recorded ingredients and cook until tender. Serve according to the original recipe.'];
recipes[0].extract_ingredients=['broccoli','garlic'];recipes[0].ingredient_preference_matches=[{role:'prefer',target:'broccoli',evidence_sources:[{field:'extract_ingredients',value:'broccoli',usage:'preparation'}]}];
recipes[1].description='A second recorded soup, presented as another option with its original cooking instructions.';
recipes[1].instructions=['Combine the recorded ingredients in a saucepan.','Simmer until cooked and serve.'];
let responses=0;
await page.route('**/content/generate/**',async route=>{
 const context=route.request().postDataJSON().context;responses++;
 return route.fulfill({json:{schema_version:'recipe-generation-v13',generation_context:{query:context.query,recipe_ids:context.recipe_ids},summary:'Here are two beef soups for your request, with their recorded introductions and cooking instructions. Each option below includes a short explanation of its supported matches.',
 recommendations:recipes.slice(0,2).map((r,i)=>({recipe_id:r.recipe_id,reason:i===0?'The recorded beef makes this a relevant option, and broccoli is also mentioned in its preparation.':'This recorded beef soup offers another option for dinner.',flavor:i===0?'Beef and herbs':'Beef',best_for:i===0?'A comforting soup':'A simple dinner option'})),recipes,
 assessments:recipes.map(r=>({recipe_id:r.recipe_id,status:'pass',checks:[{kind:'ingredient',category:'beef',name:'beef',role:'required',decision:'pass',status:'matched',reason:'Beef is recorded in the ingredient list.',evidence:['beef'],evidence_sources:[{field:'ingredients',value:'beef'}],source:'local'},...(r.recipe_id==='1'?[{kind:'ingredient',category:'garlic',name:'garlic',role:'required',decision:'unknown',status:'unknown',alternative_not_needed:true,reason:'Preparation use is not confirmed; the other OR alternative passed.',evidence:['garlic'],evidence_sources:[{field:'extract_ingredients',value:'garlic',usage:'unknown'}],source:'local'}]:[])],unresolved:[]})),
 constraint_counts:{pass:3,fail:0,unknown:0,not_checked:0},eligibility_stats:{target:20,total:3,processed:3,batches:0,stop_reason:'candidate_pool_exhausted'},requested_recipe_count:5,recommendation_limit:2,model:'mock-layout-fixture',input_recipe_count:3,generation_ms:8,prompt_version:'fixture',warnings:[],usage:{},
 token_usage:{input_tokens:8290,output_tokens:746,total_tokens:9036,cached_input_tokens:0,call_count:1},cost_estimate:{status:'unavailable',note:'Simulated UI fixture; no paid model call.'},
 model_calls:[{phase:'summary',recipe_ids:['1','2','3'],elapsed_ms:8,model_input:{model:'mock-layout-fixture',input:'Synthetic layout fixture'},model_output:{summary:'Synthetic fixture'},usage:{total_tokens:9036},prompt_version:'fixture'}],}});
});

recipes[0].total_time_minutes=14;recipes[1].total_time_minutes=17;
const action={type:'numeric',field:'total_time',level:1,ratio:.2,from:[{field:'total_time',operator:'lte',value:15,basis:'not_applicable'}],to:[{field:'total_time',operator:'lte',value:18,basis:'not_applicable'}]};
const plan={plan_id:'plan-1',actions:[action],cost:1,ratio:.2,filter_match_count:30,additional_filter_matches:28,selected:true,reason:'Lowest-cost eligible plan'};
const relaxation={status:'complete',threshold:10,relaxed_candidates:10,strict_candidate_count:2,protected_conditions:[{name:'beef',protected:true}],plans:[plan],selected_plan:plan,statistics:{status:'complete',elapsed_ms:200,counts:{strict:2,'plan-1':30}},strict_branches:{bm25:{returned:1,elapsed_ms:12,status:'complete'},vector:{returned:1,elapsed_ms:20,status:'complete'}},executions:{bm25:{returned:2,added:1,elapsed_ms:15,status:'complete'},vector:{returned:2,added:1,elapsed_ms:18,status:'complete'}}};
await page.route('**/api/search/stream',async route=>{const body=route.request().postDataJSON();const data=result(body);data.relaxation=relaxation;data.generation_candidate_levels={'1':{source_level:'strict'},'2':{source_level:'relaxed',relaxation:[action]},'3':{source_level:'strict'}};await route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify(data)+'\n\n'});});
const deviation={name:'total_time',kind:'numeric',actual_value:17,required_value:15,difference:2,reason:'17 minutes total; exceeds the 15-minute limit by 2 minutes.'};
const assess=recipes.map((r,i)=>({recipe_id:r.recipe_id,status:i===1?'near_miss':'pass',checks:[],unresolved:[],deviations:i===1?[deviation]:[]}));
await page.route('**/content/eligibility/**',async route=>{const body=route.request().postDataJSON();await route.fulfill({json:{eligibility_id:body.local_only?null:'f'.repeat(64),generation_context:{query:body.query,recipe_ids:body.recipe_ids},qualified_recipe_ids:['1'],near_miss_recipe_ids:['2'],recipes,assessments:assess,constraint_counts:{pass:2,near_miss:1,fail:0,unknown:0,not_checked:0},eligibility_stats:{target:20,stop_reason:'candidate_pool_exhausted'},model_calls:[],warnings:[],check_ms:7}});});
await page.route('**/content/generate/**',async route=>{const c=route.request().postDataJSON().context;responses++;await route.fulfill({json:{schema_version:'recipe-generation-v13',generation_context:{query:c.query,recipe_ids:c.recipe_ids},summary:'I found one confirmed recipe, plus a close alternative with a longer cooking time.',recommendations:[{recipe_id:'1',reason:'Matches your recorded requirements.',flavor:'Beef',best_for:'Soup'}],close_alternatives:[{recipe_id:'2',reason:'An alternative if a two-minute longer cooking time works for you.',flavor:'Beef',best_for:'More time',deviations:[deviation]}],recipes,assessments:assess,constraint_counts:{pass:2,near_miss:1,fail:0,unknown:0,not_checked:0},eligibility_stats:{target:20,stop_reason:'candidate_pool_exhausted'},requested_recipe_count:5,model:'mock',input_recipe_count:2,generation_ms:8,prompt_version:'fixture',warnings:[],model_calls:[]}});});

const second={plan_id:'plan-2',selection_rank:2,actions:[{type:'drop_ingredient',value:'onion',level:2,ratio:1}],cost:2,ratio:1,filter_match_count:124,additional_filter_matches:122,selected:true,reason:'Distinct eligible relaxation direction'};
const third={plan_id:'plan-3',selection_rank:3,actions:[{type:'drop_ingredient',value:'pineapple',level:2,ratio:1}],cost:2,ratio:1,filter_match_count:244,additional_filter_matches:242,selected:true,reason:'Distinct eligible relaxation direction'};
plan.reason='Distinct eligible relaxation direction';plan.selection_rank=1;
relaxation.strategy='multi';relaxation.plan_min_matches=3;relaxation.selected_plans=[plan,second,third];relaxation.plans=relaxation.selected_plans;
relaxation.statistics.counts['plan-2']=124;relaxation.statistics.counts['plan-3']=244;
for(const branch of ['bm25','vector'])relaxation.executions[branch].plan_counts={'plan-1':1,'plan-2':1,'plan-3':1};
recipes[0].total_time_minutes=17;recipes[0].ingredients=['beef','onion','pineapple'];recipes[1].ingredients=['beef','pineapple'];recipes[2].ingredients=['beef','onion'];
const groups=[{group_key:'numeric:total_time',title:'Keeps beef and onion · more cooking time',summary:'Keeps your ingredients if a little more cooking time works for you.',recipe_ids:['1']},{group_key:'missing:onion',title:'Keeps beef and pineapple · without onion',summary:'Keeps beef and pineapple; onion is not recorded.',recipe_ids:['2']},{group_key:'missing:pineapple',title:'Keeps beef and onion · without pineapple',summary:'Keeps beef and onion; pineapple is not recorded.',recipe_ids:['3']}];
const checks=recipes.map((r,i)=>({recipe_id:r.recipe_id,status:'near_miss',group_key:groups[i].group_key,checks:[],unresolved:[],deviations:[i===0?deviation:{name:i===1?'onion':'pineapple',kind:'ingredient',reason:'No '+(i===1?'onion':'pineapple')+' in the recorded preparation ingredients.'}]}));
await page.route('**/content/eligibility/**',async route=>{const body=route.request().postDataJSON();await route.fulfill({json:{eligibility_id:body.local_only?null:'f'.repeat(64),generation_context:{query:body.query,recipe_ids:body.recipe_ids},qualified_recipe_ids:[],near_miss_recipe_ids:['1','2','3'],alternative_groups:groups,recipes,assessments:checks,constraint_counts:{pass:0,near_miss:3,fail:0,unknown:0,not_checked:0},eligibility_stats:{target:20,stop_reason:'candidate_pool_exhausted'},model_calls:[],warnings:[],check_ms:7}});});
await page.route('**/content/generate/**',async route=>{const c=route.request().postDataJSON().context;await route.fulfill({json:{schema_version:'recipe-generation-v13',generation_context:{query:c.query,recipe_ids:c.recipe_ids},summary:'We found three different tradeoffs among the checked recipes. Each group shows which requirements are retained and which are not met.',recommendations:[],close_alternatives:recipes.map((r,i)=>({recipe_id:r.recipe_id,reason:groups[i].summary,flavor:'Recorded style',best_for:'An alternative',deviations:checks[i].deviations})),alternative_groups:groups,recipes,assessments:checks,constraint_counts:{pass:0,near_miss:3,fail:0,unknown:0,not_checked:0},eligibility_stats:{target:20,stop_reason:'candidate_pool_exhausted'},requested_recipe_count:5,model:'mock',input_recipe_count:3,generation_ms:8,prompt_version:'fixture',warnings:[],model_calls:[]}});});
await page.goto('http://127.0.0.1:8003');await page.locator('#user-query').fill(query);await page.locator('#submit-request').click();await page.locator('#stage-intent > .stage-handoff button').click();await page.locator('#submit-button').click();await page.locator('#results .recipe-card').first().waitFor();
assert.equal(await page.locator('#branch-flow-details').isVisible(),true);
assert.equal(await page.locator('#retrieval-research-details').evaluate(el=>el.open),false);
assert.match(await page.locator('.unified-decision').innerText(),/3 relaxation directions/);
await page.locator('.unified-decision button').click();assert.equal(await page.locator('.relaxation-directions li').count(),3);
assert.match(await page.locator('.relaxation-inspector').innerText(),/Per-plan minimum 3/);
const decisionText=await page.locator('.unified-decision > strong').boundingBox();assert.ok(decisionText.width>65);assert.ok(decisionText.height<65);
await page.locator('#retrieval-flow').screenshot({path:'/tmp/multi-plan-flow-desktop.png'});
await page.locator('.unified-decision button').click();
await page.locator('[data-stage=check]').click();await page.locator('#check-candidates').click();await page.locator('#stage-check > .stage-handoff button').waitFor();await page.locator('#stage-check > .stage-handoff button').click();
assert.equal(await page.locator('#generate-content').isEnabled(),true);await page.locator('#generate-content').click();await page.locator('.alternative-direction').first().waitFor();
assert.equal(await page.locator('.alternative-direction').count(),3);assert.equal(await page.locator('.close-alternative').count(),3);
assert.match(await page.locator('.alternative-direction').nth(1).innerText(),/without onion/);
for(const width of [1440,768,390]){await page.setViewportSize({width,height:1000});await page.waitForTimeout(250);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.locator('#generation-output').screenshot({path:'/tmp/multi-plan-generation-'+width+'.png'});}
await page.locator('[data-stage=retrieval]').click();await page.locator('#retrieval-flow').screenshot({path:'/tmp/multi-plan-flow-mobile.png'});
assert.deepEqual(errors,[]);await browser.close();console.log('Multi-plan UI passed: above-list flow, 3 directions, counts/inspection, near-only generation, grouped tradeoffs, desktop/tablet/mobile.');
