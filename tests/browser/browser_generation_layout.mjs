import {mockEligibility,checkThenGenerate,finishCheck} from './split_browser_helpers.mjs';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../../src/recipe_search/web',import.meta.url));
const browser=await chromium.launch({...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{}),headless:true,args:['--no-sandbox']});
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

for(const recipe of recipes)Object.assign(recipe,{display_image_url:'/assets/recipe-icons/soup.svg',fallback_image_url:'/assets/recipe-icons/soup.svg',image_source:'fallback:soup:1',fallback_label:'Soup / stew'});
recipes[0].name='Slow-simmered Beef Soup with Broccoli and Aromatic Herbs';
recipes[0].description='A comforting beef soup with recorded vegetables and a clear broth. This is the source introduction, preserved without rewriting.';
recipes[0].instructions=['Brown the beef in a large pan, then add the recorded broth and bring it to a gentle simmer.','Stir in the remaining recorded ingredients and cook until tender. Serve according to the original recipe.'];
recipes[0].extract_ingredients=['broccoli','garlic'];recipes[0].ingredient_preference_matches=[{role:'prefer',target:'broccoli',evidence_sources:[{field:'extract_ingredients',value:'broccoli',usage:'preparation'}]}];
recipes[1].description='Make and share this Beef Soup Two recipe from Food.com.';
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
await page.goto('http://127.0.0.1:8003');await page.locator('#user-query').fill(query);await page.locator('#submit-request').click();await page.locator('#stage-intent > .stage-handoff button').click();await page.locator('#submit-button').click();await page.locator('#results .recipe-card').first().waitFor();await checkThenGenerate(page);await page.locator('.generated-recipe').first().waitFor();
assert.equal(await page.locator('.generated-description').filter({hasText:'Make and share'}).count(),0);assert.equal(await page.locator('.recipe-essentials[open]').count(),0);await page.locator('#generation-output').screenshot({path:'/tmp/generation-compact-default.png'});const caption=await page.locator('.generated-visual .recipe-category-label').first().boundingBox(),iconBox=await page.locator('.generated-visual').first().boundingBox();const imageBox=await page.locator('.generated-photo').first().boundingBox();assert.ok(caption.y>=iconBox.y);assert.ok(caption.y+caption.height<=iconBox.y+iconBox.height+1);assert.equal(await page.locator('.generated-visual .recipe-category-label').first().innerText(),'Soup / stew');await page.locator('.generated-visual').nth(1).evaluate(el=>el.classList.remove('category-icon'));assert.equal((await page.locator('.generated-visual').first().boundingBox()).width,(await page.locator('.generated-visual').nth(1).boundingBox()).width);assert.ok((await page.locator('.generated-visual').first().boundingBox()).height<(await page.locator('.generated-visual').nth(1).boundingBox()).height);await page.locator('.generated-visual').nth(1).evaluate(el=>el.classList.add('category-icon'));assert.equal(await page.locator('.matching-bubble span').first().innerText(),'Why this recipe');assert.equal(responses,1);assert.equal(await page.locator('.generation-status-note').isVisible(),true);assert.match(await page.locator('.generation-status-note').innerText(),/3 qualified/);assert.match(await page.locator('.generation-status-note').innerText(),/Qualification target 20/);
assert.equal(await page.locator('.generated-recipe .matching-bubble,.generated-recipe .generated-checks,.generated-recipe .generated-facts').count(),0);
assert.equal(await page.locator('.generation-recipe-notes .matching-bubble').count(),2);assert.equal(await page.locator('.generation-recipe-notes .generated-checks').count(),2);
const frame=page.locator('.generation-recipe-row').first(),reason=frame.locator('.generated-reason'),bubble=frame.locator('.matching-bubble');
let [mainBox,notesBox,reasonBox,bubbleBox]=await Promise.all([frame.locator('.generated-recipe').boundingBox(),frame.locator('.generation-recipe-notes').boundingBox(),reason.boundingBox(),bubble.boundingBox()]);
assert.ok(notesBox.x>=mainBox.x+mainBox.width+20);assert.ok(Math.abs(reasonBox.y-bubbleBox.y)<3);assert.ok(reasonBox.width>450);const overview=await page.locator('.generation-status-note').boundingBox();assert.ok(overview.y+overview.height<notesBox.y);const lead=await page.locator('.generation-lead').boundingBox(),firstTitle=await frame.locator('.answer-recipe-title').boundingBox();assert.ok(firstTitle.y-lead.y-lead.height<20);
assert.equal(await page.locator('.generation-footer > .generation-research').count(),1);assert.equal(await page.locator('.generation-footer > .generation-usage-disclosure').count(),1);assert.equal(await page.locator('.generation-footer > details').first().evaluate(el=>el.open),false);assert.equal(await page.locator('.generation-footer > details').last().evaluate(el=>el.open),false);
assert.equal(await page.locator('.generated-answer .generation-footer').count(),0);assert.equal(await page.locator('#generation-output > .generation-footer').count(),1);
const answerBox=await page.locator('.generated-answer').boundingBox(),footerBox=await page.locator('.generation-footer').boundingBox();assert.ok(footerBox.y>=answerBox.y+answerBox.height+20);
assert.equal(await page.locator('.recipe-comparison tbody tr').count(),2);assert.equal(await page.locator('.generated-list').getByText('Mentioned in instructions',{exact:true}).count(),0);
assert.equal(await frame.locator('.recipe-essentials').evaluate(el=>el.open),false);await frame.locator('.recipe-essentials > summary').click();
assert.deepEqual(await frame.locator('.recipe-essentials ol li').allTextContents(),recipes[0].instructions);
assert.deepEqual(await frame.locator('.generation-source-ingredients li').allTextContents(),recipes[0].ingredients);assert.equal(await frame.locator('.generation-source-ingredients .field-help').count(),0);assert.equal(await frame.locator('.ingredients-two-columns').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length),3);assert.equal(await frame.locator('.generation-source-ingredients').isVisible(),true);assert.equal(await frame.locator('.ranking-explanation .generated-ingredients').count(),0);
await page.screenshot({path:'/tmp/generation-evidence-rail-desktop.png',fullPage:true});await page.locator('#generation-output').screenshot({path:'/tmp/generation-evidence-panel-desktop.png'});
await bubble.focus();await page.keyboard.press('Enter');assert.equal(await bubble.getAttribute('aria-expanded'),'true');assert.match(await frame.locator('.ranking-explanation').innerText(),/instructions: broccoli/);assert.doesNotMatch(await frame.locator('.ranking-explanation .generated-instruction-matches').innerText(),/garlic/);
await frame.locator('.generated-checks > summary').click();assert.match(await frame.locator('.generated-checks').innerText(),/Beef is recorded/);
await page.screenshot({path:'/tmp/generation-evidence-rail-expanded.png',fullPage:true});
await bubble.click();await frame.locator('.generated-checks > summary').click();
for(const width of [1024,900,768,390,320]){
 await page.setViewportSize({width,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`overflow at ${width}`);
 if(width===390){
   const body=await frame.locator('.recipe-essentials').boundingBox(),note=await frame.locator('.generation-recipe-notes').boundingBox(),reason=await frame.locator('.generated-reason').boundingBox();assert.ok(note.y>=reason.y+reason.height);assert.ok(body.y>=note.y+note.height);
   await page.screenshot({path:'/tmp/generation-evidence-rail-mobile.png',fullPage:true});await page.locator('#generation-output').screenshot({path:'/tmp/generation-evidence-panel-mobile.png'});
 }
}
await page.locator('.generated-visual').first().click();await page.locator('#detail-panel').waitFor({state:'visible'});await page.locator('.detail-close').click();
const unsupportedQuery='Plan meals for three days';
await page.route('**/intent/parse/**',route=>route.fulfill({json:{...intent,raw_query:unsupportedQuery,parsed:{...intent.parsed,intent:'meal_planning',status:'unsupported'},execution_support:'unsupported'}}));
await page.locator('#user-query').fill(unsupportedQuery);await page.locator('#submit-request').click();await page.locator('#intent-state').filter({hasText:'Outside scope'}).waitFor();
assert.match(await page.locator('.intent-footer > span').innerText(),/cannot run/);assert.doesNotMatch(await page.locator('.intent-footer > span').innerText(),/fills|Click Retrieval/);
assert.deepEqual(errors,[]);await browser.close();console.log('Generation layout passed: narrative/evidence separation, aligned desktop rail, source instructions, matched-only extraction provenance, footer disclosures, keyboard, five widths and recipe detail.');
