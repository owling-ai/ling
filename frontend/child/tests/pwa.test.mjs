import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const readText = (name) => readFile(new URL(name, root), "utf8");

test("PWA shell exposes only the three child tabs and an announcement region", async () => {
  const html = await readText("index.html");

  assert.match(html, /rel="manifest" href="\.\/manifest\.webmanifest"/);
  assert.match(html, /<script type="module" src="\.\/app\.mjs"><\/script>/);
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

test("manifest installs the child app in its own standalone scope", async () => {
  const manifest = JSON.parse(await readText("manifest.webmanifest"));

  assert.equal(manifest.name, "灵灵的窗口");
  assert.equal(manifest.start_url, "/child");
  assert.equal(manifest.scope, "/child");
  assert.equal(manifest.display, "standalone");
  assert.deepEqual(manifest.icons.map((icon) => icon.sizes), ["192x192", "512x512"]);
});

test("service worker caches only the child shell and does not cache business APIs", async () => {
  const source = await readText("sw.js");

  assert.match(source, /\.\/index\.html/);
  assert.match(source, /\.\/styles\.css/);
  assert.match(source, /\.\/app\.mjs/);
  assert.match(source, /pathname\.startsWith\("\/api\/"\)/);
  assert.doesNotMatch(source, /cache\.put\([^\n]*\/api\//);
});

test("styles preserve child readability, touch size, safe area, and reduced motion", async () => {
  const css = await readText("styles.css");

  assert.match(css, /font-size:\s*16px/);
  assert.match(css, /min-height:\s*44px/);
  assert.match(css, /env\(safe-area-inset-bottom\)/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.match(css, /@media\s*\(max-width:\s*320px\)/);
});

for (const size of [192, 512]) {
  test(`icon-${size}.png is a real ${size}px PNG`, async () => {
    const png = await readFile(new URL(`icon-${size}.png`, root));

    assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
    assert.equal(png.readUInt32BE(16), size);
    assert.equal(png.readUInt32BE(20), size);
  });
}
