/* Small editable AND/OR grammar. AND binds tighter; parentheses preserve intent. */
(()=>{
  function format(node){if(!node)return '';if(node.op==='ingredient')return /\b(?:AND|OR)\b|[()"]/i.test(node.ingredient)?JSON.stringify(node.ingredient):node.ingredient;return '('+node.children.map(format).join(' '+node.op+' ')+')';}
  function parse(text){
    if(!text.trim())return null;
    const quoted=[];const source=text.replace(/"(?:[^"\\]|\\.)*"/g,value=>{quoted.push(JSON.parse(value));return '__ingredient_'+(quoted.length-1)+'__';});if(source.includes('"'))throw Error('Close each quoted ingredient name.');
    const tokens=source.split(/(\(|\)|\bAND\b|\bOR\b)/i).map(t=>t.trim()).filter(Boolean);let index=0;
    function atom(){const t=tokens[index++];if(!t)throw Error('Add an ingredient after AND / OR.');if(t==='('){const value=or();if(tokens[index++]!==')')throw Error('Close each ingredient group with ).');return value;}if(/^(AND|OR|\))$/i.test(t))throw Error('Expected an ingredient name.');const quote=/^__ingredient_(\d+)__$/.exec(t);return {op:'ingredient',ingredient:quote?quoted[Number(quote[1])]:t,children:[]};}
    function and(){let value=atom();while(tokens[index]?.toUpperCase()==='AND'){index++;value={op:'AND',ingredient:null,children:[value,atom()]};}return value;}
    function or(){let value=and();while(tokens[index]?.toUpperCase()==='OR'){index++;value={op:'OR',ingredient:null,children:[value,and()]};}return value;}
    const value=or();if(index!==tokens.length)throw Error('Check the ingredient grouping and operators.');return value;
  }
  function mandatory(node){if(!node)return null;if(node.op==='ingredient')return [node.ingredient];const groups=node.children.map(mandatory);return node.op==='AND'?[...new Set(groups.flat())]:groups[0].filter(name=>groups.every(g=>g.some(n=>n.toLowerCase()===name.toLowerCase())));}
  globalThis.RecipeRequired={parse,format,mandatory};
})();
