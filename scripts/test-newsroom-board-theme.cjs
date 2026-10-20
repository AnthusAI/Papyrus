const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const { build } = require('esbuild');
const { chromium } = require('playwright');

async function main() {
  const root = path.resolve(__dirname, '..');
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'papyrus-board-theme-'));
  const shots = process.env.PAPYRUS_QA_SCREENSHOTS;
  if (shots) fs.mkdirSync(shots, { recursive: true });
  const source = fs.readFileSync(path.join(root, 'components/newsroom-board-view.tsx'), 'utf8');
  assert(!source.includes('styles/organizer.css') && !source.includes('kb-theme-organizer'));
  assert(source.includes('./newsroom-theme') && !source.includes('newsprint'));
  const THEMES = ['refined-newsprint', 'newspaper-gothic', 'night-desk', 'broadsheet-green'];
  await build({
    absWorkingDir: root, bundle: true, outfile: path.join(output, 'fixture.js'),
    loader: { '.ttf': 'file' }, jsx: 'automatic',
    stdin: { resolveDir: root, loader: 'tsx', contents: `
      import {useState} from 'react';
      import {createRoot} from 'react-dom/client';
      import {IssueCollection,IssueDetailPanel} from '@kanbus/ui';
      import '@kanbus/ui/styles/kanban.css';
      import '@kanbus/ui/styles/themes/index.css';
      import './components/newsroom-organizer.css';
      import './components/newsroom-theme.css';
      const issues=[{id:'article:fixture',title:'A clearer view of the newsroom',type:'article',status:'draft',priority:2,description:'Synthetic component test. No CMS data.'},{id:'reference:fixture',title:'Sources worth a closer look',type:'reference',status:'review',priority:2}];
      const config={hierarchy:[],types:['article','reference'],statuses:[{key:'draft',name:'Draft',category:'native'},{key:'review',name:'Review',category:'native'}],categories:[{name:'native'}],priorities:{},type_colors:{},workflows:{}};
      function Fixture(){const [selected,setSelected]=useState(null);const issue=issues.find(i=>i.id===selected);return <main className="newsroom-organizer" data-kanbus-theme={new URLSearchParams(location.search).get("theme")} style={{display:'block',padding:16}}><p>Synthetic shared-component theme regression fixture</p><section className="organizer-native-board" style={{height:'calc(100% - 60px)'}}><div className="organizer-board-body" data-detail-open={!!issue}><IssueCollection issues={issues} config={config} view="board" query={{}} initialScroll="start" selectedIssueId={selected} detailOpen={!!issue} onSelectIssue={i=>setSelected(i.id)} motion={{mode:'static'}}/>{issue&&<IssueDetailPanel issue={issue} onClose={()=>setSelected(null)}/>}</div></section></main>};
      createRoot(document.getElementById('app')).render(<Fixture/>);
    ` },
  });
  const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/fixture.css"><style>:root{--background:#f9f9fb;--foreground:#1c2024;--border:#cdced6;--muted-foreground:#64666a;--muted:#eeedef}body{margin:0}@media(prefers-color-scheme:dark){:root{--background:#17191b;--foreground:#eeedeb;--border:#55565b;--muted-foreground:#b6b5ba;--muted:#28292d}}</style></head><body><div id="app"></div><script src="/fixture.js"></script></body></html>`;
  const server = http.createServer((req,res) => {
    const filename = path.basename(new URL(req.url,'http://localhost').pathname);
    if (!filename) { res.setHeader('Content-Type','text/html');res.end(html);return; }
    const file = path.join(output,filename);
    if (!fs.existsSync(file)) { res.writeHead(404);res.end();return; }
    res.setHeader('Content-Type',filename.endsWith('.css')?'text/css':filename.endsWith('.js')?'text/javascript':'font/ttf');res.end(fs.readFileSync(file));
  });
  let browser;
  try {
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    const executablePath = process.env.PAPYRUS_CHROME_PATH || (process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : undefined);
    browser = await chromium.launch({headless:true,executablePath});
    const page = await browser.newPage();
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    for (const theme of THEMES) for (const width of [1440,375]) for (const colorScheme of ['light','dark']) {
      await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme,reducedMotion:'reduce'});
      await page.goto(`http://127.0.0.1:${server.address().port}/?theme=${theme}`);await page.locator('.issue-card').first().waitFor();await page.evaluate(()=>document.fonts.ready);
      const styles=await page.evaluate(()=>{
        const card=document.querySelector('.issue-card'), title=card.querySelector('h3'),header=document.querySelector('.kb-column-header');
        const c=getComputedStyle(card),t=getComputedStyle(title),h=getComputedStyle(header);
        const root=document.querySelector('.newsroom-organizer');return {ink:getComputedStyle(root).getPropertyValue('--kb-theme-ink').trim(),orgInk:getComputedStyle(root).getPropertyValue('--org-ink').trim(),radius:c.borderRadius,shadow:c.boxShadow,font:t.fontFamily,size:t.fontSize,weight:t.fontWeight,clip:h.clipPath,paper:getComputedStyle(document.documentElement).getPropertyValue('--background').trim(),background:getComputedStyle(document.querySelector('.newsroom-organizer')).backgroundColor,overflow:document.documentElement.scrollWidth>innerWidth+1};
      });
      assert.equal(styles.radius,'0px');assert.equal(styles.shadow,'none');assert.equal(styles.clip,'none');assert.equal(styles.weight,'600');assert.equal(styles.overflow,false);
      assert(styles.font.length>0);assert(styles.ink.startsWith('oklch'),`${theme} ink token`);assert.equal(styles.orgInk,styles.ink,'shell --org-ink is the theme ink');assert.notEqual(styles.background,'rgba(0, 0, 0, 0)');
      const overlays=await page.evaluate(()=>['organizer-menu','organizer-account-popup'].map(className=>{
        const probe=document.createElement('div');probe.className=className;probe.style.cssText='position:fixed;visibility:hidden;animation:motion-probe 1s linear infinite;transition:transform 1s';document.body.append(probe);
        const style=getComputedStyle(probe),result={className,animation:style.animationName,transition:style.transitionProperty};probe.remove();return result;
      }));
      for(const overlay of overlays){assert.equal(overlay.animation,'none',overlay.className);assert.equal(overlay.transition,'none',overlay.className);}
      if(shots) await page.screenshot({path:path.join(shots,`shared-board-${theme}-${width}-${colorScheme}.png`)});
      await page.locator('.issue-card').first().click();await page.locator('.kb-issue-detail').waitFor();await page.keyboard.press('Escape');await page.locator('.kb-issue-detail').waitFor({state:'detached'});
      const toggle=page.locator('button.kb-column-header').first();await toggle.click();assert.equal(await toggle.getAttribute('aria-expanded'),'false');await toggle.click();assert.equal(await toggle.getAttribute('aria-expanded'),'true');
    }
    assert.deepEqual(errors,[]);console.log('PASS actual shared Board: four Kanbus editorial themes, 4 viewports/modes, selection/Escape, collapse');
  } finally { if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));fs.rmSync(output,{recursive:true,force:true}); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
