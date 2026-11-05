/* One consistent, locally authored 24px outline icon vocabulary. */
(() => {
  const paths = {
    send:'<path d="m12 19 0-14m-6 6 6-6 6 6"/>',
    analyze:'<path d="M5 3v4H1m22 10h-4v4M3 7a10 10 0 0 1 17-2M21 17a10 10 0 0 1-17 2"/><path d="m9 12 2 2 4-4"/>',
    search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    next:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
    generate:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3ZM20 2v4m-2-2h4"/>',
    download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    loading:'<path d="M21 12a9 9 0 1 1-9-9"/>'
  };
  globalThis.RecipeActionIcon = (button, icon, label, busy=false) => {
    if (!button) return;
    const guided=button.id!=='download-intent';
    if(guided){
      if(button.id==='submit-request') label='Start analysis';
      if(button.id==='analyze-intent'&&!busy&&button.closest('.workflow-card')?.dataset.state==='complete') label='Analyze again';
      if(button.id==='submit-button'&&!globalThis.RecipeRetrievalTabs&&!busy&&button.closest('.workflow-card')?.dataset.state==='complete') label='Retrieve again';
      if(button.id==='submit-button'&&globalThis.RecipeRetrievalTabs)label=(busy?'Running ':'Refresh ')+(RecipeRetrievalTabs.active==='hybrid'?'Hybrid':RecipeRetrievalTabs.active.toUpperCase());
      else if(busy) label=button.id==='analyze-intent'?'Analyzing…':button.id==='submit-button'?'Retrieving…':'Generating…';
    }
    button.classList.add('icon-action');button.classList.toggle('guided-action',guided);
    button.setAttribute('aria-label',label); button.title=label;
    button.setAttribute('aria-busy',String(busy));
    button.innerHTML=`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"${busy ? ' class="action-spinner"' : ''}>${paths[busy ? 'loading' : icon] || paths.next}</svg>`;
    if(guided){const text=document.createElement('span');text.className='action-label';text.textContent=label;button.append(text);}
  };
  for (const [id,icon,label] of [['analyze-intent','analyze','Analyze intent'],['submit-button','search','Retrieve recipes'],['download-intent','download','Download interpretation JSON']]) RecipeActionIcon(document.getElementById(id),icon,label);
})();
