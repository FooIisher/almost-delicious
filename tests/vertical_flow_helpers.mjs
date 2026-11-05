import assert from 'node:assert/strict';
// Verify the user's central requirement against rendered geometry, not CSS names.
export async function verifyVerticalFlow(page){
  await page.waitForTimeout(220);
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const layout=await page.evaluate(()=>{
    const graph=document.querySelector('#retrieval-flow'),grid=graph.querySelector('.flow-grid');
    const rect=n=>{const b=n.getBoundingClientRect();return {left:b.left,right:b.right,top:b.top,bottom:b.bottom,width:b.width,height:b.height};};
    const nodes=[...grid.querySelectorAll('.flow-node')].filter(n=>getComputedStyle(n).display!=='none').map(n=>({name:n.className,contentLeft:n.querySelector('strong').getBoundingClientRect().left,state:n.dataset.state,...rect(n)}));
    const caption=graph.querySelector('.flow-caption');
    return {nodes,cards:[...grid.querySelectorAll(':scope > .flow-stage-card')].map(rect),grid:rect(grid),caption:rect(caption),paths:[...grid.querySelectorAll('.flow-wire')].map(p=>p.getAttribute('d')),overflow:document.documentElement.scrollWidth>innerWidth};
  });
  assert.equal(layout.overflow,false,'Flow must not overflow the page');
  const horizontal=await page.evaluate(()=>innerWidth>760);
  assert.ok(layout.grid.height<1300,'Expanded recall graph should stay compact');
  assert.ok(layout.grid.top-layout.caption.bottom<25,'No hidden-field blank space above the diagram');
  for(let i=0;i<layout.nodes.length;i++)for(let j=i+1;j<layout.nodes.length;j++){
    const a=layout.nodes[i],b=layout.nodes[j];
    assert.ok(a.right<=b.left+1||b.right<=a.left+1||a.bottom<=b.top+1||b.bottom<=a.top+1,`Nodes overlap: ${a.name} / ${b.name}`);
  }
  for(let i=1;i<layout.cards.length;i++){const a=layout.cards[i-1],b=layout.cards[i];assert.ok(horizontal?b.left>=a.right:b.top>=a.bottom,'Stage cards follow the reading direction');}
  for(const n of layout.nodes)assert.notEqual(n.state,'waiting','Future placeholders must remain detached');
  for(const d of layout.paths){
    assert.match(d,horizontal?/^M[\d.\-]+ [\d.\-]+ H[\d.\-]+ V[\d.\-]+ H[\d.\-]+$/:/^M[\d.\-]+ [\d.\-]+ V[\d.\-]+$/,'Connectors follow the current reading direction');
    const nums=d.match(/-?\d+(?:\.\d+)?/g).map(Number);
    assert.ok(horizontal?nums[4]>nums[0]:nums[2]>nums[1],'Connectors never reverse');
  }
  return layout;
}
