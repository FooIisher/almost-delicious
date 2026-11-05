const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.listeners={};}
  append(...children){this.children.push(...children);}
  replaceChildren(){this.children=[];}
  setAttribute(){}
  addEventListener(name,callback){this.listeners[name]=callback;}
}
const container=new Element();
const help=new Element();
const context={document:{getElementById:id=>id==='numeric-bounds'?container:help,
  createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text})}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/numeric-bounds.js'),'utf8'),context);
context.RecipeBounds.render([
  {field:'total_time',operator:'lt',value:30,basis:'not_applicable',evidence:'under 30 minutes'},
  {field:'calories',operator:'lt',value:500,basis:'per_serving',evidence:'under 500 cal per serving'},
  {field:'protein',operator:'gte',value:20,basis:'unspecified',evidence:'at least 20g protein'},
]);
const collect=()=>JSON.parse(JSON.stringify(context.RecipeBounds.collect()));
assert.deepEqual(collect(),[
  {field:'total_time',operator:'lt',value:30,basis:'not_applicable'},
  {field:'calories',operator:'lt',value:500,basis:'per_serving'}]);
const proteinRow=container.children[2];
assert.match(proteinRow.children[2].textContent,/Not applied.*unspecified/);
const confirmation=proteinRow.children[1].children[0];
confirmation.checked=true;confirmation.listeners.change();
assert.equal(collect().length,3);
const timeInput=container.children[0].children[0].children[1];
timeInput.value='60';timeInput.listeners.input();
assert.equal(collect()[0].value,60);
context.RecipeBounds.render([{field:'calories',operator:'lt',value:1500,basis:'per_day'}]);
assert.deepEqual(collect(),[]);
context.RecipeBounds.render([]);
assert.deepEqual(collect(),[]);
console.log('Numeric controls: operators, values, confirmation, daily basis and clearing passed');
