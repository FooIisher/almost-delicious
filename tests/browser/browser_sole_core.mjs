import {verifyVerticalFlow} from './vertical_flow_helpers.mjs';
import {mockEligibility,checkThenGenerate,finishCheck} from './split_browser_helpers.mjs';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../../src/recipe_search/web',import.meta.url));
const browser=await chromium.launch({...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{}),headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[],generations=[];
page.on('pageerror',error=>errors.push(error.message));
const query='fruit Salad with durian';
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


extraction.ingredients=[{name:'durian',entity_type:'specific',role:'required',evidence:'durian',core:true}];
extraction.required_expression={op:'ingredient',ingredient:'durian',children:[]};
extraction.dish_name='fruit salad';extraction.dish_type='salad';extraction.meal_type=null;
Object.assign(intent.parsed,extraction,{extraction,retrieval_queries:{bm25_query:'fruit salad',vector_query:'fruit salad',vector_scope_query:'fruit salad with durian',source:'Dish name'}});
intent.constraint_rows=[{field:'ingredient_required',label:'Required ingredient',value:['durian'],entity_type:'specific',role:'required',core:true,evidence:'durian',support:'supported'}];
recipes.forEach((r,i)=>Object.assign(r,{name:i===0?'Durian Ice Cream':i===1?'Banana Split Dessert or Salad':'Tropical Fruit Salad',ingredients:i===0?['durian']:['apple','banana'],keywords:i===0?['dessert']:['salad'],recipecategory:i===0?['ice cream']:['fruit salad'],description:'Recorded source recipe.',instructions:['Combine the recorded ingredients.']}));
const action={type:'drop_ingredient',value:'durian',level:2,ratio:1,sole_required_exception:true};
const plan={plan_id:'plan-1',actions:[action],cost:2,ratio:1,filter_match_count:200,additional_filter_matches:194,selected:true,reason:'Lowest-cost eligible plan'};
const relaxation={status:'complete',threshold:10,relaxed_candidates:10,strict_candidate_count:6,protected_conditions:[{name:'durian',protected:true,sole_core_exception:true}],plans:[plan],selected_plan:plan,statistics:{status:'complete',elapsed_ms:200,counts:{strict:6,'plan-1':200}},strict_branches:{bm25:{returned:0,elapsed_ms:592.54,status:'complete'},vector:{returned:6,elapsed_ms:10730,status:'complete'}},executions:{bm25:{returned:10,added:10,elapsed_ms:421,status:'complete'},vector:{returned:10,added:8,elapsed_ms:789,status:'complete'}}};
await page.route('**/api/search/stream',async route=>{
 const body=route.request().postDataJSON();assert.deepEqual(body.include_ingredients,['durian']);assert.deepEqual(body.core_ingredients,['durian']);
 const data=result(body);data.original_conditions=body;data.relaxation=relaxation;data.generation_candidate_levels={'1':{source_level:'strict'},'2':{source_level:'relaxed',relaxation:[action]},'3':{source_level:'relaxed',relaxation:[action]}};
 await route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify(data)+'\n\n'});
});
const deviation={name:'durian',reason:'Durian is not listed in the recorded preparation ingredients.'};
const missing={constraint_id:'hard-1',kind:'ingredient',name:'durian',category:'durian',role:'required',core:true,semantic_required:false,decision:'fail',status:'not_matched',source:'local',reason:deviation.reason,evidence:[]};
const assess=recipes.map((r,i)=>({recipe_id:r.recipe_id,source_level:i===0?'strict':'relaxed',status:i===0?'fail':'near_miss',checks:i===0?[{...missing,decision:'pass',status:'matched',evidence:['durian']},{constraint_id:'hard-2',kind:'dish_name',name:'fruit salad',role:'required',decision:'fail',source:'model',reason:'Ice cream is not fruit salad.',evidence:[],status:'not_matched'}]:[{...missing}],deviations:i===0?[]:[deviation],unresolved:[]}));
assess[1].deviations.push({kind:'dish_name',name:'fruit salad',reason:'Dish type may not fully match the requested fruit salad; dish identity remains unconfirmed.',uncertain:true});
assess[1].checks.push({constraint_id:'hard-2',kind:'dish_name',name:'fruit salad',role:'required',source:'model',status:'unknown',decision:'unknown',semantic_required:false,reason:'Borderline dessert-style salad.',evidence:['Banana Split Dessert or Salad']});
await page.route('**/content/eligibility/**',async route=>{const body=route.request().postDataJSON();await route.fulfill({json:{eligibility_id:body.local_only?null:'f'.repeat(64),generation_context:{query:body.query,recipe_ids:body.recipe_ids},qualified_recipe_ids:[],near_miss_recipe_ids:['2','3'],recipes,assessments:assess,constraint_counts:{pass:0,fail:1,unknown:0,not_checked:0,near_miss:2},eligibility_stats:{target:20,stop_reason:'candidate_pool_exhausted'},model_calls:[],warnings:[],check_ms:7}});});
await page.route('**/content/generate/**',async route=>{const context=route.request().postDataJSON().context;await route.fulfill({json:{schema_version:'recipe-generation-v13',generation_context:{query:context.query,recipe_ids:context.recipe_ids},summary:'I could not confirm a recipe that fully meets your requirements from these candidates. If you are open to options that do not list durian in their recorded ingredients, you could consider the recipes below.',recommendations:[],close_alternatives:recipes.slice(1).reverse().map(r=>({recipe_id:r.recipe_id,reason:deviation.reason,deviations:assess.find(a=>a.recipe_id===r.recipe_id).deviations,flavor:'Fruit',best_for:'Salad'})),recipes,assessments:assess,constraint_counts:{pass:0,fail:1,unknown:0,not_checked:0,near_miss:2},eligibility_stats:{target:20,stop_reason:'candidate_pool_exhausted'},model:'mock',input_recipe_count:2,generation_ms:9,warnings:[],model_calls:[]}});});
await page.goto('http://127.0.0.1:8003');await page.locator('#user-query').fill(query);await page.locator('#submit-request').click();
await page.locator('#intent-overview').waitFor();
assert.match(await page.locator('#intent-overview').innerText(),/durian · Core: yes/);
assert.match(await page.locator('#intent-content').innerHTML(),/Core: yes/);
await page.locator('#stage-intent > .stage-handoff button').click();await page.locator('#submit-button').click();await page.locator('#retrieval-research-details').evaluate(el=>el.open=true);await page.locator('#branch-flow-details').evaluate(el=>el.open=true);await page.locator('.unified-relaxed-bm25-output').waitFor();
assert.match(await page.locator('.branch-bm25 .flow-constraints').innerText(),/durian/);
assert.match(await page.locator('.unified-relaxed-bm25').innerText(),/421.00 ms/);assert.match(await page.locator('.unified-relaxed-vector').innerText(),/789.00 ms/);
assert.match(await page.locator('.unified-relaxed-bm25-output').innerText(),/10 returned · 10 new/);assert.match(await page.locator('.unified-relaxed-vector-output').innerText(),/10 returned · 8 new/);
assert.equal(await page.locator('.decision-inspect-icon').innerText(),'');assert.equal(await page.locator('.decision-inspect-icon').getAttribute('aria-label'),'Inspect relaxation decision');await page.locator('.unified-decision button').click();assert.match(await page.locator('.relaxation-inspector').innerText(),/sole required filter may relax for recall/);assert.doesNotMatch(await page.locator('tr[data-selected=true]').innerText(),/waived/);
await page.locator('.unified-decision button').click();await verifyVerticalFlow(page);await page.locator('#retrieval-flow').screenshot({path:'var/screenshots/sole-core-flow-desktop.png'});
await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await verifyVerticalFlow(page);await page.locator('#retrieval-flow').screenshot({path:'var/screenshots/sole-core-flow-mobile.png'});
await page.setViewportSize({width:1440,height:1000});await page.locator('[data-stage=check]').click();await page.locator('#check-candidates').click();await page.locator('[data-outcome=near_miss] > summary').click();for(const summary of await page.locator('[data-outcome=near_miss] .check-alternative-direction > summary').all())await summary.click();await page.locator('[data-outcome=near_miss] .check-recipe-evidence > summary').first().click();assert.match(await page.locator('[data-outcome=near_miss]').innerText(),/Durian is not listed/);
assert.equal(await page.locator('#stage-check > .stage-heading + .stage-handoff').count(),1);
await page.locator('#stage-check').screenshot({path:'var/screenshots/check-handoff-top.png'});
assert.equal(await page.locator('.related-ingredient-recipes').count(),0);
assert.deepEqual(await page.locator('[data-outcome=near_miss] .check-recipe').evaluateAll(nodes=>nodes.map(n=>n.dataset.recipeId)),['3','2']);
await page.locator('#check-output').screenshot({path:'var/screenshots/sole-core-check-desktop.png'});
await page.locator('#stage-check > .stage-handoff button').click();await page.locator('#generate-content').click();await page.locator('.generated-recipe').first().waitFor();assert.equal(await page.locator('.generated-recipe').count(),2);assert.equal(await page.locator('.close-alternative').count(),2);assert.equal(await page.locator('.close-alternatives-heading').count(),0);assert.equal(await page.locator('.recipe-comparison tbody tr').count(),2);assert.match(await page.locator('.recipe-comparison').innerText(),/Dish type may not fully match/);assert.match(await page.locator('.recipe-comparison').innerText(),/Durian is not listed/);assert.equal(await page.locator('.ingredient-waiver').count(),0);
assert.equal(await page.locator('.related-ingredient-recipes').count(),0);
await page.locator('#generation-output').screenshot({path:'var/screenshots/sole-core-generation-desktop.png'});
await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.locator('#generation-output').screenshot({path:'var/screenshots/sole-core-generation-mobile.png'});

await page.locator('[data-stage=retrieval]').click();
for(const mode of ['bm25','vector']){
 const data=result({mode,include_ingredients:['durian']});data.relaxation=relaxation;
 await page.evaluate(({mode,data})=>{RecipeRetrievalFlow.start(mode,{include:['durian']});RecipeRetrievalFlow.complete(data);},{mode,data});
 await verifyVerticalFlow(page);
 const active=mode==='bm25'?'bm25':'vector',inactive=active==='bm25'?'vector':'bm25';
 assert.equal(await page.locator('.unified-relaxed-'+active+'-output').isVisible(),true);
 assert.equal(await page.locator('.unified-relaxed-'+inactive+'-output').isVisible(),false);
}
const sufficient=result({mode:'hybrid',include_ingredients:['durian']});sufficient.relaxation={...relaxation,status:'strict_sufficient',selected_plan:null,strict_candidate_count:20,executions:{}};
await page.evaluate(data=>{RecipeRetrievalFlow.start('hybrid',{include:['durian']});RecipeRetrievalFlow.complete(data);},sufficient);
await verifyVerticalFlow(page);
assert.equal(await page.locator('.unified-relaxed-bm25').isVisible(),false);assert.equal(await page.locator('.unified-relaxed-vector-output').isVisible(),false);assert.equal(await page.locator('.unified-decision').count(),0,'No relaxation card for sufficient strict recall');
assert.deepEqual(errors,[]);await browser.close();console.log('Sole-core UI passed: core markers, original filters, separate branch timings/counts, near-miss separation, Check → Generation and mobile.');
