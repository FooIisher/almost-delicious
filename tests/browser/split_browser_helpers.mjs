export async function mockEligibility(route,recipes){
 const body=route.request().postDataJSON(),rows=recipes.filter(r=>body.recipe_ids.includes(String(r.recipe_id)));
 return route.fulfill({json:{eligibility_id:body.local_only?null:'a'.repeat(64),local_only:body.local_only,cache_hit:false,check_ms:3,model:'mock-check',generation_context:{query:body.query,recipe_ids:body.recipe_ids},qualified_recipe_ids:rows.map(r=>String(r.recipe_id)),recipes:rows,assessments:rows.map(r=>({recipe_id:String(r.recipe_id),status:'pass',checks:[],unresolved:[]})),constraint_counts:{pass:rows.length,fail:0,unknown:0,not_checked:0},eligibility_stats:{target:20,processed:rows.length,total:rows.length,batches:0,stop_reason:'candidate_pool_exhausted'},model_calls:[],usage:{},warnings:[]}});
}
export async function finishCheck(page){
 await page.locator('[data-stage=check]').click();await page.locator('#check-candidates').click();await page.locator('#stage-check > .stage-handoff button').waitFor();await page.locator('#stage-check > .stage-handoff button').click();
}
export async function checkThenGenerate(page){await finishCheck(page);await page.locator('#generate-content').click();}
