import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const ROOT = new URL("../", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");

test("mobile shell exposes four real tabs and an accessible rights dialog", async () => {
  const html = await read("index.html");

  assert.match(html, /role="tablist"/);
  for (const tab of ["today", "growth", "memory", "guardian"]) {
    assert.match(html, new RegExp(`data-tab="${tab}"`));
  }
  assert.match(html, /<dialog[^>]+id="rights-dialog"/);
  assert.match(html, /aria-labelledby="rights-title"/);
});

test("source never requests legacy raw child-memory APIs", async () => {
  const source = `${await read("api.mjs")}\n${await read("app.mjs")}`;

  for (const path of ["/api/facts", "/api/diary", "/api/mastery", "/api/report", "/api/state"]) {
    assert.doesNotMatch(source, new RegExp(path.replaceAll("/", "\\/")));
  }
  assert.match(source, /\/api\/parent\//);
});

test("PWA manifest, service worker, and mobile accessibility constraints are present", async () => {
  const [manifestText, serviceWorker, styles] = await Promise.all([
    read("manifest.webmanifest"),
    read("sw.js"),
    read("styles.css"),
  ]);
  const manifest = JSON.parse(manifestText);

  assert.equal(manifest.start_url, "/parent");
  assert.equal(manifest.display, "standalone");
  assert.deepEqual(manifest.icons.map((icon) => icon.sizes), ["192x192", "512x512"]);
  assert.match(serviceWorker, /icon-192\.png/);
  assert.match(serviceWorker, /manifest\.webmanifest/);
  assert.match(styles, /env\(safe-area-inset-bottom/);
  assert.match(styles, /:focus-visible/);
  assert.match(styles, /min-height:\s*44px/);
  assert.match(styles, /prefers-reduced-motion:\s*reduce/);
  assert.match(styles, /@media\s*\(max-width:\s*360px\)/);
});

test("PWA icons are valid PNG files at their declared dimensions", async () => {
  for (const size of [192, 512]) {
    const image = await readFile(new URL(`icon-${size}.png`, ROOT));
    assert.deepEqual([...image.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
    assert.equal(image.readUInt32BE(16), size);
    assert.equal(image.readUInt32BE(20), size);
  }
});
