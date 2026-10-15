const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const {chromium}=require('playwright');
const base=process.env.CURATION_REVIEW_URL||'http://127.0.0.1:8931';
const output=path.resolve('.papyrus-runs/curation-review-proof');fs.mkdirSync(output,{recursive:true});
(async()=>{const browser=await chromium.launch({channel:'chrome',headless:true,args:['--no-proxy-server']});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[],failed=[];page.on('pageerror',e=>errors.push(e.message));page.on('requestfailed',r=>failed.push(r.url()));
 await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
 await page.goto(base+'/newsroom/references');await page.getByText('Decision provenance and version').first().waitFor();
 assert(await page.getByRole('button',{name:'Submit review',exact:true}).isDisabled());
 await page.getByRole('button',{name:'not publish',exact:true}).click();await page.getByLabel('Explanation (required)',{exact:true}).fill('Synthetic operator: outside this publication scope.');await page.getByRole('button',{name:'Submit review',exact:true}).click();
 await page.waitForFunction(async()=>Object.values((await(await fetch('/review/proof')).json()).accounts)[0].operationalLabels===1);
 await page.getByLabel('Execution',{exact:true}).selectOption('remote');await page.getByText('Canonical classifier data owned by the shared remote lab.').waitFor();
 await page.getByRole('button',{name:'Curate reference examples (optional)'}).click();await page.getByRole('button',{name:'From reference / URL'}).click();
 await page.getByLabel('Source URL',{exact:true}).fill('https://example.invalid/web');await page.getByRole('button',{name:'Start curation'}).click();
 await page.getByRole('button',{name:'Accept examples and labels'}).waitFor();assert(await page.getByRole('button',{name:'Accept examples and labels'}).isDisabled());
 await page.getByRole('button',{name:/Explicit publication judgment: publish/}).click();assert(await page.getByRole('button',{name:'Accept examples and labels'}).isEnabled());
 let refuseOnce=true;
 await page.route('**/api/newsroom/curation/priming',async route=>{const body=route.request().postDataJSON();if(refuseOnce&&body.variables?.action==='accept'){refuseOnce=false;return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Synthetic acknowledgement failure; retry explicitly.'})});}return route.continue();});
 await page.getByRole('button',{name:'Accept examples and labels'}).click();await page.getByRole('alert').filter({hasText:'Synthetic acknowledgement failure'}).waitFor();
 assert.equal(await page.getByRole('button',{name:/Explicit publication judgment: publish/}).getAttribute('aria-pressed'),'true');
 assert.equal(await page.getByLabel('Explanation for Explicit publication judgment').inputValue(),'');
 await page.getByRole('button',{name:'Retry last request'}).click();await page.getByText('Examples and human labels saved.').waitFor();
 await page.getByLabel('Fixture account',{exact:true}).selectOption('22222222-2222-4222-8222-222222222222');await page.getByText('Decision provenance and version').first().waitFor();assert(!(await page.locator('body').innerText()).includes('Examples and human labels saved.'));
 await page.getByRole('button',{name:'Evaluate classifier proposal',exact:true}).click();await page.getByLabel('Proposed instructions').fill('Synthetic scoped evaluation rubric.');await page.getByLabel('Why make this change?').fill('Verify explicit evaluation before promotion.');await page.getByRole('button',{name:'Evaluate proposal',exact:true}).click();await page.getByText('Evaluation complete: no improvement was reported.').waitFor();assert(await page.getByRole('button',{name:'Promote evaluated proposal'}).isDisabled());
 await page.getByRole('button',{name:'Close proposal'}).click();
 for(const [width,height,theme,name] of [[1440,1000,'light','desktop-light'],[1440,1000,'dark','desktop-dark'],[375,812,'light','mobile-light'],[375,812,'dark','mobile-dark']]){
  await page.setViewportSize({width,height});await page.getByLabel('Appearance',{exact:true}).selectOption(theme);await page.emulateMedia({reducedMotion:'reduce'});await page.evaluate(()=>document.querySelectorAll('[data-curation-mode],.organizer-main').forEach(element=>element.scrollTop=0));await page.screenshot({path:path.join(output,name+'.png'),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' horizontal overflow');
 }
 await page.keyboard.press('Tab');assert(await page.evaluate(()=>document.activeElement!==document.body));
 const proof=await(await page.request.get(base+'/review/proof')).json();const values=Object.values(proof.accounts);assert.equal(values[0].operationalLabels,1);assert.equal(values[0].acceptedExamples,1);assert.equal(values[1].operationalLabels,0);assert.equal(values[1].acceptedExamples,0);assert.equal(values[1].steeringFixtureCalls,1);
 assert.deepEqual(errors,[]);assert.deepEqual(failed,[]);fs.writeFileSync(path.join(output,'browser-proof.json'),JSON.stringify({base,errors,failed,proof,reducedMotion:true,publishOnlyAcceptance:true,explicitRetryPreservesSelection:true,physicalIPadVerified:false},null,2));console.log('Shared UI to native store review, acceptance, account isolation, steering and four responsive screenshots passed.');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
