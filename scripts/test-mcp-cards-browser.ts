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
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
