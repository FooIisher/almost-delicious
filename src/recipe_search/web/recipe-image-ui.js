/* One presentation policy for retrieved, generated and detail images. */
(() => {
  const generic='/assets/recipe-icons/default.svg';
  function isFallback(recipe={}){
    const url=recipe.display_image_url||'';
    return !url||String(recipe.image_source||'').startsWith('fallback:')||/\/(recipe-icons|recipe-images)\/|recipe-placeholder\.svg/.test(url);
  }
  function bind(image,container,recipe={},onChange=()=>{}){
    let fallback=isFallback(recipe),failed=false;
    const url=recipe.fallback_image_url||generic;
    const label=recipe.fallback_label||'Recipe';
    const mark=document.createElement('small');mark.className='recipe-category-label';mark.textContent=label;
    if(image.parentElement!==container)image.parentElement.append(mark);
    // A similar recipe's real photo: shown as a photo, but labelled so it is never mistaken for this recipe.
    const borrowed=recipe.borrowed_image&&String(recipe.image_source||'').startsWith('borrowed:')?recipe.borrowed_image:null;
    const borrowedMark=document.createElement('small');borrowedMark.className='recipe-borrowed-label';
    borrowedMark.textContent=borrowed?.label||'Similar recipe photo';
    if(borrowed){borrowedMark.title='Photo from a similar recipe: '+(borrowed.name||'');if(image.parentElement!==container)image.parentElement.append(borrowedMark);}
    function apply(){
      container.classList.toggle('recipe-fallback',fallback);mark.hidden=!fallback;
      borrowedMark.hidden=fallback||!borrowed;
      image.alt=fallback?`${label} category icon · not a recipe photograph`:borrowed?`Photo of a similar recipe (${borrowed.name||'similar dish'}) · not this recipe`:(recipe.name||'Recipe photograph');
      image.title=fallback?'Category icon · no recipe photo available':borrowed?'Photo from a similar recipe: '+(borrowed.name||''):'Recorded recipe photograph';
      onChange(fallback);
    }
    image.addEventListener('error',()=>{
      if(failed){image.hidden=true;return;}
      failed=true;fallback=true;apply();image.src=url;
    });
    apply();
    return {get fallback(){return fallback;}};
  }
  globalThis.RecipeImage={isFallback,bind,generic};
})();
