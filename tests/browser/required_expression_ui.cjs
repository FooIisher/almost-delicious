const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');const c={};vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../../src/recipe_search/web/constraint-expression.js'),'utf8'),c);
const {parse,format,mandatory}=c.RecipeRequired;
const expr=parse('(beef OR chicken) AND (potatoes OR rice)');assert.equal(expr.op,'AND');assert.equal(expr.children[0].op,'OR');assert.equal(format(expr),'((beef OR chicken) AND (potatoes OR rice))');assert.equal(mandatory(expr).length,0);
assert.deepEqual(JSON.parse(JSON.stringify(mandatory(parse('rice AND (beef OR chicken)')))),['rice']);
for(const text of ['beef AND','(beef OR chicken','beef OR )'])assert.throws(()=>parse(text));assert.equal(parse(''),null);console.log('Editable AND/OR grammar, precedence, round-trip and mandatory query terms passed');

const quoted=parse('"half and half" OR milk');assert.equal(quoted.children[0].ingredient,'half and half');assert.equal(format(quoted),'("half and half" OR milk)');
