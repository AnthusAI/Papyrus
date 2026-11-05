import assert from "node:assert/strict";
import { chromium } from "playwright";
import { listMcpAppResources, readMcpAppResource } from "../lib/mcp/cards";

async function main() {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    page.on("pageerror", error => console.error(error));
    page.setDefaultTimeout(5000);
    const html = readMcpAppResource(listMcpAppResources()[0].uri).contents[0].text;
    await page.setContent('<iframe title="card"></iframe>');
    await page.evaluate(() => { (window as any).__name = (value: unknown) => value; });
    await page.evaluate((source) => {
      const frame = document.querySelector('iframe')!;
      (window as any).calls = [];
      window.addEventListener('message', event => {
        const msg = event.data;
        (window as any).calls.push(msg);
        const reply = (result: unknown) => frame.contentWindow!.postMessage({jsonrpc:'2.0',id:msg.id,result},'*');
        if (msg.method === 'ui/initialize') reply({protocolVersion:'2026-01-26',hostCapabilities:{},hostInfo:{name:'fixture',version:'1'}});
        if (msg.method === 'ui/notifications/initialized') {
          frame.contentWindow!.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-input',params:{arguments:{lineageId:'r1'}}},'*');
          frame.contentWindow!.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{reference:{id:'v1',lineageId:'r1',updatedAt:'3',title:'<img src=x onerror=alert(1)>',storyLineageId:'s1'}},_meta:{papyrus:{availableTools:['reference_decide','story_evidence','story_next']}}}},'*');
        }
        if (msg.method === 'tools/call') {
          if (msg.params.name === 'reference_decide') reply({isError:true,structuredContent:{code:'stale_revision',message:'Changed'}});
          else if (msg.params.name === 'reference_get') reply({structuredContent:{reference:{id:'v2',lineageId:'r1',updatedAt:'4',title:'Refreshed'}}});
          else if (msg.params.name === 'story_get') reply({structuredContent:{story:{id:'s1v1',lineageId:'s1',title:'Story'}},_meta:{papyrus:{availableTools:['story_evidence','story_next']}}});
          else reply({structuredContent:{evidence:[{referenceLineageId:'r1'}]}});
        }
      });
      frame.srcdoc = source;
    }, html);
    const frame = page.frameLocator('iframe');
    await frame.getByRole('heading', {name:'<img src=x onerror=alert(1)>'}).waitFor();
    assert.equal(await frame.locator('img').count(), 0);
    await frame.getByRole('button',{name:'Open story'}).click();
    await frame.getByRole('heading',{name:'Story',exact:true}).waitFor();
    await frame.getByRole('button',{name:'Evidence'}).click();
    await frame.getByRole('heading',{name:'Evidence'}).waitFor();
    await frame.getByRole('button',{name:'Next step'}).click();
    await frame.getByRole('heading',{name:'Next step'}).waitFor();
    await frame.getByRole('button',{name:'Back'}).click();
    await frame.getByRole('button',{name:'Accept'}).click();
    await frame.getByRole('heading',{name:'Refreshed'}).waitFor();
    assert.match(await frame.locator('#status').innerText(), /changed/i);
    const calls = await page.evaluate(() => (window as any).calls);
    const decision = calls.find((x: any) => x.params?.name === 'reference_decide');
    assert.deepEqual(decision.params.arguments,{lineageId:'r1',expectedCurrentVersionId:'v1',expectedRevision:'3',decision:'accept'});
    assert.ok(calls.some((x: any) => x.params?.name === 'reference_get'));
    assert.doesNotMatch(JSON.stringify(calls), /Bearer|authorization/i);
    const storyHtml = readMcpAppResource(listMcpAppResources()[1].uri).contents[0].text;
    const reviewPage = await browser.newPage();
    reviewPage.setDefaultTimeout(5000);
    reviewPage.on("pageerror", error => console.error(error));
    await reviewPage.setContent('<iframe title="review card"></iframe>');
    await reviewPage.evaluate(() => { (window as any).__name = (value: unknown) => value; });
    await reviewPage.evaluate((source) => {
      const frame = document.querySelector('iframe')!; let revision = 'r1'; let answers = 0;
      (window as any).calls = [];
      window.addEventListener('message', event => {
        const msg = event.data; (window as any).calls.push(msg);
        const reply = (result: unknown) => frame.contentWindow!.postMessage({ jsonrpc:'2.0', id:msg.id, result }, '*');
        if (msg.method === 'ui/initialize') reply({ protocolVersion:'2026-01-26', hostCapabilities:{}, hostInfo:{name:'fixture',version:'1'} });
        if (msg.method === 'ui/notifications/initialized') {
          frame.contentWindow!.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-input',params:{arguments:{lineageId:'s1'}}},'*');
          frame.contentWindow!.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{story:{id:'v1',lineageId:'s1',title:'Story',updatedAt:'date-1',revision:'opaque-revision'}},_meta:{papyrus:{availableTools:['reviews_list','review_answer','story_star']}}}},'*');
        }
        if (msg.method === 'tools/call' && msg.params.name === 'story_star') reply({structuredContent:{story:{id:'v1',lineageId:'s1',title:'Story',revision:'opaque-revision'}}});
        if (msg.method === 'tools/call' && msg.params.name === 'story_get') reply({structuredContent:{story:{id:'v1',lineageId:'s1',title:'Story',revision:'next-revision'}},_meta:{papyrus:{availableTools:['reviews_list','review_answer','story_star']}}});
        if (msg.method === 'tools/call' && msg.params.name === 'reviews_list') reply({structuredContent:{reviews: [
          {id:'review-1',state:'open',raisedBy:'editor',mode:'soft_review',updatedAt:revision,reason:'Check'},
          {id:'publish',state:'open',raisedBy:'publish-gate',mode:'hard_gate',updatedAt:'g1',reason:'Publish gate'},
          {id:'missing',state:'open',raisedBy:'editor',mode:'soft_review',reason:'Missing revision'},
        ]}});
        if (msg.method === 'tools/call' && msg.params.name === 'review_answer') {
          if (++answers === 1) { revision = 'r2'; reply({isError:true,structuredContent:{code:'stale_revision',message:'Changed'}}); }
          else reply({structuredContent:{review:{id:'review-1',state:'answered'}}});
        }
      }); frame.srcdoc = source;
    }, storyHtml);
    const reviewFrame = reviewPage.frameLocator('iframe');
    await reviewFrame.getByLabel('Stars (1–5)').fill('4');
    await reviewFrame.getByRole('button',{name:'Save stars'}).click();
    await reviewFrame.getByText('Saved.').waitFor();
    await reviewFrame.getByRole('button',{name:'Reviews'}).click();
    await reviewFrame.getByRole('heading',{name:'Reviews'}).waitFor();
    assert.equal(await reviewFrame.getByRole('button',{name:'Accept'}).count(), 1);
    await reviewFrame.getByRole('button',{name:'Accept'}).click();
    await reviewFrame.getByText(/This review changed/).waitFor();
    await reviewFrame.getByLabel('Feedback (optional)').fill('Looks good');
    await reviewFrame.getByRole('button',{name:'Accept'}).click();
    await reviewFrame.getByText('Saved.').waitFor();
    const reviewCalls = await reviewPage.evaluate(() => (window as any).calls);
    assert.deepEqual(reviewCalls.find((x: any) => x.params?.name === 'story_star').params.arguments, {lineageId:'s1',expectedCurrentVersionId:'v1',expectedRevision:'opaque-revision',stars:4});
    const answers = reviewCalls.filter((x: any) => x.params?.name === 'review_answer');
    assert.deepEqual(answers.map((x: any) => x.params.arguments), [
      {id:'review-1',expectedRevision:'r1',decision:'approve'},
      {id:'review-1',expectedRevision:'r2',decision:'approve',feedback:'Looks good'},
    ]);
    await reviewPage.close();
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
