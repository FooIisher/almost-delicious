import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:1280,height:800}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/*',async route=>{const name=new URL(route.request().url()).pathname;if(name==='/real-photo.svg')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="500" height="300"><rect width="500" height="300" fill="#c4d8c9"/><text x="100" y="150">Original image fixture</text></svg>'});try{return route.fulfill({contentType:'image/svg+xml',body:await fs.readFile('web'+name.replace('/assets',''))});}catch{return route.fulfill({status:404,body:''});}});
await page.setContent('<base href="http://fixture.test/"><section id="results"></section>');
await page.addStyleTag({content:await fs.readFile('web/research.css','utf8')});
await page.addScriptTag({content:await fs.readFile('web/recipe-image-ui.js','utf8')});
await page.evaluate(()=>{
 const host=document.getElementById('results');
 for(const [id,recipe] of [['icon',{name:'Chicken stir fry',display_image_url:'/assets/recipe-icons/stirfry.svg',fallback_image_url:'/assets/recipe-icons/stirfry.svg',image_source:'fallback:stirfry:1',fallback_label:'Stir fry'}],['original',{name:'Original photo',display_image_url:'/real-photo.svg',fallback_image_url:'/assets/recipe-icons/salad.svg',image_source:'original',fallback_label:'Salad'}],['broken',{name:'Broken photo',display_image_url:'/missing.jpg',fallback_image_url:'/assets/recipe-icons/soup.svg',image_source:'original',fallback_label:'Soup / stew'}]]){
  const card=document.createElement('article');card.id=id;card.className='recipe-card';card.innerHTML='<div class="recipe-image"><img></div><div><h2>'+recipe.name+'</h2><p>Recorded recipe and recommendation.</p></div>';host.append(card);const img=card.querySelector('img');RecipeImage.bind(img,card,recipe);img.src=recipe.display_image_url;
 }
});
await page.waitForFunction(()=>document.querySelector('#broken').classList.contains('recipe-fallback')&&[...document.images].every(i=>i.complete));
assert.equal(await page.locator('#icon').evaluate(e=>e.classList.contains('recipe-fallback')),true);
assert.equal(await page.locator('#original').evaluate(e=>e.classList.contains('recipe-fallback')),false);
assert.equal(await page.locator('#original .recipe-category-label').isVisible(),false);
assert.match(await page.locator('#broken img').getAttribute('src'),/recipe-icons\/soup.svg/);
assert.equal(await page.locator('#broken .recipe-category-label').innerText(),'Soup / stew');
for(const axis of ['width','height'])assert.equal((await page.locator('#icon .recipe-image').boundingBox())[axis],(await page.locator('#original .recipe-image').boundingBox())[axis]);
const caption=await page.locator('#icon .recipe-category-label').boundingBox(),slot=await page.locator('#icon .recipe-image').boundingBox();assert.ok(caption.y>=slot.y&&caption.y+caption.height<=slot.y+slot.height);
assert.match(await page.locator('#icon img').getAttribute('alt'),/not a recipe photograph/);
await page.screenshot({path:'/tmp/recipe-icons-desktop.png',fullPage:true});
await page.setViewportSize({width:390,height:800});for(const axis of ['width','height'])assert.equal((await page.locator('#icon .recipe-image').boundingBox())[axis],(await page.locator('#original .recipe-image').boundingBox())[axis]);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:'/tmp/recipe-icons-mobile.png',fullPage:true});
assert.deepEqual(errors,[]);await browser.close();console.log('Recipe icons passed: category caption, original retention, failed-photo aligned fallback, desktop and mobile.');
