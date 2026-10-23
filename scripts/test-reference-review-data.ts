import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { build } from "esbuild";
import { chromium } from "playwright";

async function bundle() {
  const result = await build({
    stdin: { contents: `
      import React, {useState} from 'react';
      import {createRoot} from 'react-dom/client';
      import {useReferenceReviewData} from './lib/use-reference-review-data';
      window.fixture = {calls: 0, fail: false};
      const loadRelations = () => { window.fixture.calls++; return new Promise((resolve,reject) => {
        window.fixture.finish = () => window.fixture.fail ? reject(new Error('Session expired')) : resolve([{id:'prediction'}]);
      }); };
      const loadMessages = async () => [{id:'review'}];
      function App() {
        const [relations,setRelations] = useState([]), [messages,setMessages] = useState([]), [render,setRender] = useState(0);
        const state = useReferenceReviewData({enabled:true, loadRelations, loadMessages, onRelations:setRelations, onMessages:setMessages});
        return <main><p role="status">{state.state}</p><p>{state.error}</p><p>Predictions: {relations.length}</p><p>Reviews: {messages.length}</p>
          <button onClick={()=>setRender(render+1)}>Rerender {render}</button><button onClick={state.retry}>Retry</button>
          <button onClick={()=>window.fixture.finish()}>Finish read</button><button onClick={()=>window.fixture.fail=!window.fixture.fail}>Toggle failure</button></main>;
      }
      createRoot(document.getElementById('root')).render(<App/>);`, resolveDir: process.cwd(), loader: "tsx" },
    bundle: true, write: false, format: "iife", platform: "browser", jsx: "automatic",
    define: { "process.env.NODE_ENV": '"development"' }, absWorkingDir: path.resolve("."), logLevel: "silent",
  });
  return result.outputFiles[0].text;
}

test("asynchronous predictions survive rerenders and a failed read offers an effective retry", async () => {
  const script = await bundle();
  const browser = await chromium.launch({ executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined, args: ["--no-proxy-server"] });
  try {
    const page = await browser.newPage();
    await page.setContent('<div id="root"></div>');
    await page.addScriptTag({ content: script });
    await page.getByRole("status").filter({ hasText: "loading" }).waitFor();
    await page.getByRole("button", { name: "Rerender 0" }).click();
    await page.getByRole("button", { name: "Finish read" }).click();
    await page.getByRole("status").filter({ hasText: "ready" }).waitFor();
    assert.equal(await page.getByText("Predictions: 1").count(), 1);
    assert.equal(await page.getByText("Reviews: 1").count(), 1);
    assert.equal(await page.evaluate(() => (window as any).fixture.calls), 1);
    await page.getByRole("button", { name: "Toggle failure" }).click();
    await page.getByRole("button", { name: "Retry" }).click();
    await page.getByRole("button", { name: "Finish read" }).click();
    await page.getByRole("status").filter({ hasText: "error" }).waitFor();
    assert.equal(await page.getByText(/Session expired/).count(), 1);
    await page.getByRole("button", { name: "Toggle failure" }).click();
    await page.getByRole("button", { name: "Retry" }).click();
    await page.getByRole("button", { name: "Finish read" }).click();
    await page.getByRole("status").filter({ hasText: "ready" }).waitFor();
    assert.equal(await page.getByText(/Session expired/).count(), 0);
    assert.equal(await page.evaluate(() => (window as any).fixture.calls), 3);
  } finally { await browser.close(); }
});
