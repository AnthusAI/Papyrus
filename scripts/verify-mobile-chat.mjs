import assert from "node:assert/strict";

export async function verifyMobileChat(page, origin) {
  const trigger = page.getByRole("button", { name: "Open private chat" });
  const close = page.getByRole("button", { name: "Close console" });
  const composer = page.getByRole("textbox", { name: "Message input" });
  const fits = async (locator, width, height, top = 0) => {
    await locator.waitFor({ state: "visible" });
    const box = await locator.boundingBox();
    assert.ok(box && box.width > 0 && box.height > 0 && box.x >= 0 && box.x + box.width <= width + 1 && box.y >= top && box.y + box.height <= top + height + 1, JSON.stringify(box));
  };
  for (const [width, height] of [[320, 568], [375, 667], [390, 844], [430, 932], [844, 390]]) {
    console.log(`Checking mobile chat at ${width}x${height}`);
    await page.setViewportSize({ width, height });
    await fits(trigger, width, height);
    if (width === 375 && process.env.PAPYRUS_CHAT_TEST_ARTIFACT_DIR) await page.screenshot({ path: `${process.env.PAPYRUS_CHAT_TEST_ARTIFACT_DIR}/mobile-chat-entry-375.png` });
    assert.equal(await page.getByRole("button", { name: "Open console", exact: true }).isVisible(), false);
    await trigger.click();
    await page.getByRole("dialog", { name: "Papyrus console" }).waitFor();
    await composer.waitFor();
    await fits(close, width, height);
    await fits(composer, width, height);
    if (width === 375 && process.env.PAPYRUS_CHAT_TEST_ARTIFACT_DIR) await page.screenshot({ path: `${process.env.PAPYRUS_CHAT_TEST_ARTIFACT_DIR}/mobile-chat-375.png` });
    await close.focus();
    await page.keyboard.press("Shift+Tab");
    assert.equal(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]')), true);
    await page.keyboard.press("Escape");
    await trigger.waitFor();
    await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label") === "Open private chat");
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.organizer-main a[href="#references"]').click();
  await trigger.click();
  await composer.waitFor();
  await composer.fill("Synthetic mobile layout test draft");
  await page.evaluate(() => {
    const viewport = new EventTarget();
    viewport.height = 310;
    viewport.offsetTop = 20;
    Object.defineProperty(window, "visualViewport", { configurable: true, value: viewport });
  });
  await close.click();
  await trigger.click();
  await composer.waitFor();
  await page.waitForFunction(() => document.querySelector(".papyrus-console").style.height === "310px");
  await composer.fill("Synthetic keyboard viewport test draft");
  await fits(composer, 390, 310, 20);
  await fits(close, 390, 310, 20);
  if (process.env.PAPYRUS_CHAT_TEST_ARTIFACT_DIR) await page.screenshot({ path: `${process.env.PAPYRUS_CHAT_TEST_ARTIFACT_DIR}/mobile-chat-keyboard.png` });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  assert.equal(await page.locator('.papyrus-console').evaluate(panel => {
    const scrollable = [...panel.querySelectorAll('*')].find(element => /auto|scroll/.test(getComputedStyle(element).overflowY) && element.scrollHeight > element.clientHeight);
    if (!scrollable) return false;
    scrollable.scrollTop = 0;
    const before = scrollable.scrollTop;
    scrollable.scrollTop = 50;
    return scrollable.scrollTop > before;
  }), true, "transcript remains scrollable in the keyboard viewport");
  await close.click();
  assert.equal(new URL(page.url()).hash, "#references");
  await page.goBack();
  await trigger.waitFor();
  assert.equal(new URL(page.url()).hash, "");
  await page.setViewportSize({ width: 1280, height: 800 });
  assert.equal(await trigger.isVisible(), false);
  await page.getByRole("button", { name: "Open console", exact: true }).click();
  await close.waitFor();
  assert.equal(await page.locator('[aria-modal="true"]').count(), 0);
  assert.equal(await page.locator('.papyrus-console-page[inert]').count(), 0);
  await close.click();
  await page.goto(`${origin}/?unauthorized=1`);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await trigger.count(), 0);
  assert.equal(await page.locator('.papyrus-console').count(), 0);
  console.log("PASS: mobile chat entry, phone/landscape geometry, keyboard viewport, focus, close/return navigation, desktop and unauthorized boundary");
}
