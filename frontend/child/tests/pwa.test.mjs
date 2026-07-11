import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const readText = (name) => readFile(new URL(name, root), "utf8");

function cssRule(css, selector) {
  const start = css.indexOf(`${selector} {`);
  assert.ok(start >= 0, `expected ${selector} rule`);
  const bodyStart = css.indexOf("{", start) + 1;
  const end = css.indexOf("}", bodyStart);
  return css.slice(bodyStart, end);
}

function contrastRatio(first, second) {
  const luminance = (hex) => {
    const channels = hex.match(/[\da-f]{2}/gi).map((channel) => parseInt(channel, 16) / 255);
    const [red, green, blue] = channels.map((channel) => (
      channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
    ));
    return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue);
  };
  const [lighter, darker] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

test("PWA shell exposes only the three child tabs and an announcement region", async () => {
  const html = await readText("index.html");

  assert.match(html, /rel="manifest" href="\.\/manifest\.webmanifest"/);
  assert.match(html, /<script type="module" src="\.\/app\.mjs"><\/script>/);
  assert.match(html, /name="application-name" content="灵灵的窗口"/);
  assert.match(html, /name="mobile-web-app-capable" content="yes"/);
  assert.match(html, /name="apple-mobile-web-app-title" content="灵灵"/);
  assert.match(html, /aria-label="儿童端主导航"/);
  assert.match(html, />现在</);
  assert.match(html, />奇遇</);
  assert.match(html, />口袋</);
  assert.match(html, /id="announcer"[^>]*aria-live="polite"/);
  assert.doesNotMatch(html, /聊天|掌握度|家长控制台|管理|provider/i);
});

test("child source never requests forbidden memory or provider endpoints", async () => {
  const source = await Promise.all(["api.mjs", "model.mjs", "app.mjs"].map(readText));
  const joined = source.join("\n");

  for (const forbidden of ["/api/facts", "/api/diary", "/api/mastery", "/api/report", "/api/volcengine", "/api/admin"] ) {
    assert.equal(joined.includes(forbidden), false, `must not contain ${forbidden}`);
  }
});

test("app routes every server-provided media URL through the strict allowlist", async () => {
  const source = await readText("app.mjs");
  const guardedUrls = source.match(
    /safeMediaUrl\((?:media\.src|media\.poster|item\.image_url),\s*window\.location\.origin\)/g,
  ) || [];

  assert.equal(guardedUrls.length, 3);
  assert.doesNotMatch(source, /function safeAssetUrl\(/);
});

test("now scene status copy stays in-world and hides generation mechanics", async () => {
  const source = await readText("app.mjs");
  const sceneStatusLines = source.split("\n").filter((line) => line.includes('class="scene-status"'));

  assert.ok(sceneStatusLines.length > 0, "expected a visible now-scene status badge");
  assert.doesNotMatch(source, /AI\s*生成|AI生成|\bprovider\b/i);
  assert.doesNotMatch(sceneStatusLines.join("\n"), /生成中/);
});

test("rendering polls update only their pending card until a terminal state", async () => {
  const source = await readText("app.mjs");
  const start = source.indexOf("function startFeedPoll(item)");
  const end = source.indexOf("function startFeedPolls(feed)");
  const pollSource = source.slice(start, end);

  assert.ok(start >= 0 && end > start, "expected startFeedPoll implementation");
  assert.match(pollSource, /moment\.status === "rendering"[\s\S]*updatePendingCard/);
  const renderingStart = pollSource.indexOf('moment.status === "rendering"');
  const localUpdate = pollSource.indexOf("updatePendingCard", renderingStart);
  const earlyReturn = pollSource.indexOf("return;", localUpdate);
  const terminalRender = pollSource.indexOf("renderFeed(", earlyReturn);
  assert.ok(renderingStart < localUpdate && localUpdate < earlyReturn && earlyReturn < terminalRender);
});

test("identical rendering updates leave the pending DOM and aria-live region untouched", async () => {
  const source = await readText("app.mjs");
  const updateStart = source.indexOf("function updatePendingCard(");
  const updateEnd = source.indexOf("function momentCard", updateStart);
  const updateSource = source.slice(updateStart, updateEnd);
  const pollStart = source.indexOf("function startFeedPoll(item)");
  const pollEnd = source.indexOf("function startFeedPolls(feed)", pollStart);
  const pollSource = source.slice(pollStart, pollEnd);

  assert.match(updateSource, /function updatePendingCard\(previous, item\)/);
  assert.match(updateSource, /if \(!pendingCardChanged\(previous, item\)\) return;/);
  assert.match(
    pollSource,
    /const previous = state\.feed\.pending\.find[\s\S]*state\.feed = reconcileFeed[\s\S]*updatePendingCard\(previous, pending\)/,
  );
  assert.match(pollSource, /moment\.status === "published"[\s\S]*announce\("新的专属瞬间已经画好了。"\)/);
});

test("world transition refresh is scheduled only for now and cleared on navigation", async () => {
  const source = await readText("app.mjs");

  assert.match(source, /worldRefreshTimer/);
  assert.match(source, /worldRefreshDelay\(/);
  assert.match(source, /function clearWorldRefresh\(/);
  assert.match(source, /if \(current\.name === "now"\)[\s\S]*scheduleWorldRefresh/);
  assert.match(source, /state\.routeController\?\.abort\(\);\s*clearWorldRefresh\(\);/);
});

test("navigation rechecks route version after background world loading", async () => {
  const source = await readText("app.mjs");
  const guardedAwaits = source.match(/await backgroundWorld;\s*if \(version !== state\.routeVersion\) return;/g) || [];

  assert.equal(guardedAwaits.length, 3);
});

test("pocket responses are bound to their mutation, moment, and route version", async () => {
  const source = await readText("app.mjs");
  const start = source.indexOf("async function togglePocket()");
  const end = source.indexOf('view.addEventListener("click"', start);
  const toggleSource = source.slice(start, end);

  assert.match(toggleSource, /momentId:\s*item\.id/);
  assert.match(toggleSource, /routeVersion:\s*state\.routeVersion/);
  assert.match(toggleSource, /isPocketMutationCurrent\(/);
  assert.match(toggleSource, /if \(!isPocketMutationCurrent/);
});

test("pocket success announcements follow the server-settled collection state", async () => {
  const source = await readText("app.mjs");
  const start = source.indexOf("async function togglePocket()");
  const end = source.indexOf('view.addEventListener("click"', start);
  const toggleSource = source.slice(start, end);

  assert.match(toggleSource, /const finalCollected = Boolean\(settled\.collected \?\? desired\);/);
  assert.match(toggleSource, /announce\(finalCollected \? "已经收进口袋。" : "已经移出口袋。"\);/);
  assert.doesNotMatch(toggleSource, /announce\(desired \?/);
});

test("pocket navigation waits for an in-flight collection before its GET", async () => {
  const source = await readText("app.mjs");
  const routeStart = source.indexOf("async function route()");
  const routeEnd = source.indexOf("async function togglePocket()", routeStart);
  const routeSource = source.slice(routeStart, routeEnd);
  const toggleStart = source.indexOf("async function togglePocket()");
  const toggleEnd = source.indexOf('view.addEventListener("click"', toggleStart);
  const toggleSource = source.slice(toggleStart, toggleEnd);

  assert.match(
    routeSource,
    /const pendingPocketMutation = current\.name === "pocket"\s*\? state\.pocketMutation\?\.completion\s*:\s*null;/,
  );
  assert.match(
    routeSource,
    /loadPocketAfterMutation\(childApi, pendingPocketMutation, \{ signal \}\)/,
  );
  assert.match(toggleSource, /completion:\s*new Promise/);
  assert.match(toggleSource, /resolveCompletion\(\);/);
});

test("manifest installs the child app in its own standalone scope", async () => {
  const manifest = JSON.parse(await readText("manifest.webmanifest"));

  assert.equal(manifest.name, "灵灵的窗口");
  assert.equal(manifest.id, "/child/");
  assert.equal(manifest.start_url, "/child/");
  assert.equal(manifest.scope, "/child/");
  assert.equal(manifest.display, "standalone");
  assert.deepEqual(manifest.icons.map((icon) => icon.sizes), ["192x192", "512x512"]);
});

test("service worker caches only the child shell and does not cache business APIs", async () => {
  const source = await readText("sw.js");
  const app = await readText("app.mjs");

  for (const path of [
    "/child/",
    "/child/index.html",
    "/child/styles.css",
    "/child/app.mjs",
    "/child/api.mjs",
    "/child/model.mjs",
    "/child/manifest.webmanifest",
    "/child/icon-192.png",
    "/child/icon-512.png",
  ]) {
    assert.ok(source.includes(`"${path}"`), `expected absolute shell path ${path}`);
  }
  assert.match(source, /CACHE_NAME\s*=\s*`\$\{CACHE_PREFIX\}-v4`/);
  assert.match(source, /pathname\.startsWith\("\/api\/"\)/);
  assert.doesNotMatch(source, /cache\.put\([^\n]*\/api\//);
  assert.match(app, /serviceWorker\.register\("\.\/sw\.js",\s*\{\s*scope:\s*"\/child\/"\s*\}\)/);
});

test("styles preserve child readability, touch size, safe area, and reduced motion", async () => {
  const css = await readText("styles.css");
  const rootRule = cssRule(css, ":root");
  const page = rootRule.match(/--page:\s*(#[\dA-F]{6})/i)?.[1];
  const faint = rootRule.match(/--faint:\s*(#[\dA-F]{6})/i)?.[1];

  assert.match(css, /font-size:\s*16px/);
  assert.match(css, /min-height:\s*44px/);
  assert.match(css, /env\(safe-area-inset-bottom\)/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.match(css, /@media\s*\(max-width:\s*320px\)/);
  assert.ok(page && faint, "expected day page and faint colors");
  assert.ok(contrastRatio(page, faint) >= 4.5, "day faint text must meet WCAG AA contrast");
});

test("now scene keeps text outside the fixed media surface and native controls", async () => {
  const source = await readText("app.mjs");
  const css = await readText("styles.css");
  const start = source.indexOf("function renderNow(world)");
  const end = source.indexOf("function formatDate", start);
  const nowSource = source.slice(start, end);
  const worldScene = cssRule(css, ".world-scene");
  const worldMedia = cssRule(css, ".world-media");
  const sceneCopy = cssRule(css, ".scene-copy");

  assert.match(
    nowSource,
    /class="world-media"[\s\S]*class="scene-status"[\s\S]*<\/div>`\}\s*<\/div>\s*<div class="scene-copy">/,
  );
  assert.match(worldScene, /height:\s*auto/);
  assert.match(worldScene, /overflow:\s*visible/);
  assert.doesNotMatch(worldScene, /(?:min-)?height:\s*\d/);
  assert.match(worldMedia, /position:\s*relative/);
  assert.match(worldMedia, /height:\s*390px/);
  assert.match(worldMedia, /overflow:\s*hidden/);
  assert.match(sceneCopy, /position:\s*static/);
  assert.doesNotMatch(sceneCopy, /position:\s*absolute/);

  const mobileRules = css.slice(css.indexOf("@media (max-width: 320px)"));
  const mobileWorldScene = cssRule(mobileRules, ".world-scene");
  const mobileWorldMedia = cssRule(mobileRules, ".world-media");
  assert.doesNotMatch(mobileWorldScene, /(?:min-)?height:\s*330px/);
  assert.match(mobileWorldMedia, /height:\s*330px/);
});

for (const size of [192, 512]) {
  test(`icon-${size}.png is a real ${size}px PNG`, async () => {
    const png = await readFile(new URL(`icon-${size}.png`, root));

    assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
    assert.equal(png.readUInt32BE(16), size);
    assert.equal(png.readUInt32BE(20), size);
  });
}
