import {mockEligibility,checkThenGenerate,finishCheck} from './split_browser_helpers.mjs';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../../src/recipe_search/web',import.meta.url));
const browser=await chromium.launch({...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{}),headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[],generations=[];
page.on('pageerror',error=>errors.push(error.message));
const query='Find beef soup with broccoli, no onion.';
const extraction={intent:'recipe_search',search_text:'beef soup',dish_name:null,dish_type:'soup',meal_type:'dinner',meal_type_role:'required',cuisine:null,cuisine_role:null,target_evidence:{dish_name:null,dish_type:'soup',meal_type:'dinner',cuisine:null},ingredients:[{name:'beef',role:'required',entity_type:'specific',evidence:'beef'}],required_expression:null,bounds:[],soft_preferences:[],dietary_restrictions:[],generation_notes:[],corrections:[],clarification_questions:[]};
const intent={request_id:'mock',raw_query:query,model:'mock-flash',schema_version:'recipe-extraction-v7',provider:'deepseek_direct',intent_parse_ms:4,parsed:{...extraction,extraction,status:'ready',recipe_names:[],recipe_references:[],comparison_dimensions:[],missing_fields:[],uncertain_questions:[],retrieval_queries:{bm25_query:'beef soup',vector_query:'Hearty beef soup',vector_scope_query:'Beef soup for dinner',source:'Required ingredients + Dish type'}},constraint_rows:[],intent_scores:{},execution_support:'supported',context:{recipes:[]}};
const recipes=[1,2,3].map((id,i)=>({recipe_id:String(id),document_id:String(id),name:['Beef Soup One','Beef Soup Two','Beef Soup Three'][i],ingredients:['beef'],instructions:['Simmer source ingredients.'],description:'Recorded recipe.',keywords:['soup','dinner'],recipecategory:['soup'],total_time_minutes:25,aggregatedrating:4,score:.9-i*.1,rank:i+1,match_highlights:{}}));
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
  const body=route.request().postDataJSON().context;generations.push(body);const generatedRecipes=recipes.filter(r=>body.recipe_ids.includes(r.recipe_id));return route.fulfill({json:{schema_version:'recipe-generation-v13',generation_context:{query:body.query,recipe_ids:body.recipe_ids},summary:'Here are beef soups for your request.',recommendations:[{recipe_id:'1',reason:'Recorded beef and soup match your request.',flavor:'Beef',best_for:'Dinner'}],recipes:generatedRecipes,assessments:generatedRecipes.map(r=>({recipe_id:r.recipe_id,status:'pass',checks:[],unresolved:[]})),constraint_counts:{pass:2,fail:1,unknown:0,not_checked:0},model:'mock-flash',generation_ms:9,usage:{},warnings:[],model_calls:[]}});
 }
 if(path.startsWith('/recipes/'))return route.fulfill({json:recipes[0]});
 const file=path==='/'?'index.html':path.replace('/assets/','');try{return route.fulfill({body:await fs.readFile(root+'/'+file),contentType:file.endsWith('.html')?'text/html':file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'image/svg+xml'});}catch{return route.fulfill({status:404,body:''});}
});
const proof=[{field:'extract_ingredients',value:'broccoli',usage:'preparation'}];
recipes[0].extract_ingredients=['broccoli','Beef',' BROCCOLI '];recipes[0].extracted_usage=[{ingredient:'broccoli',usage:'preparation'}];recipes[0].ingredients=['beef'];recipes[0].ingredient_preference_matches=[{role:'prefer',target:'broccoli',evidence_sources:proof}];
let checkRequests=0,summaryRequest;
recipes[1].extract_ingredients=['onion'];
const excludedChecks=[{constraint_id:'hard-3',kind:'ingredient',category:'onion',name:'onion',role:'excluded',decision:'fail',status:'matched',reason:'Onion is mentioned in instructions.',evidence:['onion'],evidence_sources:[{field:'extract_ingredients',value:'onion',usage:'preparation'}],source:'local'}];
const checks=[{constraint_id:'hard-2',kind:'ingredient',category:'broccoli',name:'broccoli',role:'required',decision:'pass',status:'matched',reason:'Broccoli is mentioned in instructions.',evidence:['broccoli'],evidence_sources:proof,source:'local'}];
await page.route('**/api/search/stream',async route=>{
 const body=route.request().postDataJSON(),data=result(body);data.results[0].preference_evidence=[{group:'prefer',matched:['broccoli'],requested:['broccoli'],match_score:1,weight:1,contribution:1,final_contribution:.3,checks:[{target:'broccoli',evidence:['broccoli'],evidence_sources:proof}]}];
 return route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify(data)+'\n\n'});
});
await page.route('**/content/eligibility/**',async route=>{
 const b=route.request().postDataJSON();if(!b.local_only)checkRequests++;
 return route.fulfill({json:{schema_version:'recipe-generation-v13',eligibility_id:b.local_only?null:'d'.repeat(64),local_only:b.local_only,check_ms:3,generation_context:{query:b.query,recipe_ids:b.recipe_ids},qualified_recipe_ids:['1'],assessments:recipes.map(r=>({recipe_id:r.recipe_id,status:r.recipe_id==='2'?'fail':'pass',checks:r.recipe_id==='1'?checks:r.recipe_id==='2'?excludedChecks:[],unresolved:[]})),recipes,constraint_counts:{pass:2,fail:1,unknown:0,not_checked:0},eligibility_stats:{target:20,stop_reason:'candidate_pool_exhausted'},model_calls:[],warnings:[],usage:{}}});
});
await page.route('**/content/generate/**',async route=>{
 summaryRequest=route.request().postDataJSON();const b=summaryRequest.context;
 return route.fulfill({json:{schema_version:'recipe-generation-v13',generation_context:{query:b.query,recipe_ids:b.recipe_ids},summary:'Beef soup with broccoli mentioned in its instructions.',recommendations:[{recipe_id:'1',reason:'Broccoli is mentioned in the instructions and beef is listed.',flavor:'Not specified',best_for:'Soup'}],recipes,assessments:recipes.map(r=>({recipe_id:r.recipe_id,status:r.recipe_id==='2'?'fail':'pass',checks:r.recipe_id==='1'?checks:r.recipe_id==='2'?excludedChecks:[],unresolved:[]})),constraint_counts:{pass:2,fail:1,unknown:0,not_checked:0},generation_ms:5,model:'mock',model_calls:[],warnings:[],usage:{}}});
});
await page.goto('http://127.0.0.1:8003');await page.locator('#user-query').fill(query);await page.locator('#submit-request').click();await page.locator('#stage-intent > .stage-handoff button').click();await page.locator('#submit-button').click();await page.locator('#results .recipe-card').first().waitFor();
await page.locator('#stage-retrieval .stage-handoff button').click();await page.locator('#check-candidates').click();await page.locator('#stage-check > .stage-handoff button').waitFor();await page.locator('[data-outcome=pass] > summary').click();await page.locator('[data-outcome=pass] .check-recipe-evidence > summary').first().click();
assert.match(await page.locator('[data-outcome=pass]').innerText(),/broccoli \(mentioned in instructions · Used in preparation\)/);assert.equal(checkRequests,1);
await page.screenshot({path:'/tmp/extracted-check-desktop.png',fullPage:true});
await page.locator('#stage-check > .stage-handoff button').click();await page.locator('#generate-content').click();await page.locator('.generated-recipe').waitFor();
assert.equal(await page.locator('.generated-recipe .generated-instruction-matches').count(),0);
assert.equal(await page.locator('.recipe-essentials .instruction-ingredients').count(),0);
await page.locator('.matching-bubble').click();assert.match(await page.locator('.ingredient-source-signal').innerText(),/mentioned in instructions/);
assert.match(await page.locator('.ranking-explanation .generated-instruction-matches').innerText(),/instructions: broccoli/);
assert.equal(await page.locator('.generated-ingredients li').allTextContents().then(a=>a.join(',')),'beef');
await page.locator('.generated-checks > summary').click();assert.match(await page.locator('.generated-checks').innerText(),/mentioned in instructions · Used in preparation/);
await page.locator('.generation-research > summary').click();await page.locator('.generation-excluded > summary').click();assert.match(await page.locator('.generation-excluded').innerText(),/onion \(mentioned in instructions · Used in preparation\)/);
await page.screenshot({path:'/tmp/extracted-generation-desktop.png',fullPage:true});
await page.locator('.generated-visual').click();await page.locator('#detail-panel').filter({hasText:'From instructions'}).waitFor();assert.match(await page.locator('.detail-extracted-ingredients').innerText(),/broccoli/i);assert.equal(await page.locator('.detail-extracted-ingredients li').count(),1);await page.locator('#detail-panel .detail-card').screenshot({path:'/tmp/detail-instruction-ingredients.png'});await page.locator('.detail-close').click();
await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:'/tmp/extracted-generation-mobile.png',fullPage:true});assert.deepEqual(errors,[]);
await browser.close();console.log('Extracted ingredient browser passed: check evidence provenance, generation match note, preference evidence, separate original/extracted lists, recipe details, safe rendering and mobile.');
