import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";

const ROOT = new URL("../", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");

function relativeLuminance(hex) {
  const channels = hex.match(/[0-9a-f]{2}/gi).map((channel) => parseInt(channel, 16) / 255);
  const [red, green, blue] = channels.map((channel) => (
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  ));
  return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue);
}

function contrastRatio(foreground, background) {
  const luminances = [relativeLuminance(foreground), relativeLuminance(background)].sort((a, b) => b - a);
  return (luminances[0] + 0.05) / (luminances[1] + 0.05);
}

async function loadServiceWorker({ cacheNames = [], cache = {}, caches = {}, fetchImplementation } = {}) {
  const listeners = new Map();
  const state = { claims: 0, deleted: [], skipWaitingCalls: 0 };
  const cacheInstance = {
    add: async () => {},
    addAll: async () => {},
    put: async () => {},
    ...cache,
  };
  const cacheStorage = {
    open: async () => cacheInstance,
    keys: async () => cacheNames,
    delete: async (name) => {
      state.deleted.push(name);
      return true;
    },
    match: async () => undefined,
    ...caches,
  };
  const self = {
    addEventListener: (type, listener) => listeners.set(type, listener),
    location: { origin: "https://ling.test" },
    skipWaiting: async () => { state.skipWaitingCalls += 1; },
    clients: { claim: async () => { state.claims += 1; } },
  };

  runInNewContext(await read("sw.js"), {
    URL,
    Request,
    Response,
    caches: cacheStorage,
    fetch: fetchImplementation || (async () => new Response("network")),
    self,
  }, { filename: "frontend/parent/sw.js" });

  return { cache: cacheInstance, caches: cacheStorage, listeners, state };
}

test("service worker activation only removes obsolete parent shell caches", async () => {
  const { listeners, state } = await loadServiceWorker({
    cacheNames: [
      "ling-parent-shell-v0",
      "ling-parent-shell-v1",
      "ling-parent-shell-v2",
      "ling-parent-shell-v3",
      "ling-parent-shell-v4",
      "ling-child-shell-v3",
      "runtime-images",
    ],
  });
  let activation;

  listeners.get("activate")({ waitUntil: (promise) => { activation = promise; } });
  await activation;

  assert.deepEqual(state.deleted, [
    "ling-parent-shell-v0",
    "ling-parent-shell-v1",
    "ling-parent-shell-v2",
    "ling-parent-shell-v3",
  ]);
  assert.equal(state.claims, 1);
});

test("service worker precaches the core shell atomically and rejects a failed install", async () => {
  let addAllAssets = null;
  const { listeners, state } = await loadServiceWorker({
    cache: {
      add: async () => { throw new Error("single asset failed"); },
      addAll: async (assets) => {
        addAllAssets = Array.from(assets);
        throw new Error("precache failed");
      },
    },
  });
  let installation;

  listeners.get("install")({ waitUntil: (promise) => { installation = promise; } });

  await assert.rejects(installation, /precache failed/);
  assert.ok(addAllAssets.includes("/parent/index.html"));
  assert.ok(addAllAssets.includes("/parent/app.mjs"));
  assert.equal(state.skipWaitingCalls, 0);
});

test("service worker navigation fallback always resolves to a Response", async () => {
  const { listeners } = await loadServiceWorker({
    caches: { match: async () => undefined },
    fetchImplementation: async () => { throw new Error("offline"); },
  });
  let responsePromise;

  listeners.get("fetch")({
    request: { method: "GET", mode: "navigate", url: "https://ling.test/parent/growth" },
    respondWith: (promise) => { responsePromise = promise; },
  });
  const response = await responsePromise;

  assert.ok(response instanceof Response);
  assert.equal(response.status, 503);
});

test("mobile shell exposes four real tabs and an accessible rights dialog", async () => {
  const html = await read("index.html");

  assert.match(html, /role="tablist"/);
  for (const tab of ["today", "growth", "memory", "guardian"]) {
    assert.match(html, new RegExp(`data-tab="${tab}"`));
  }
  assert.match(html, /<dialog[^>]+id="rights-dialog"/);
  assert.match(html, /aria-labelledby="rights-title"/);
});

test("tablist precedes its panels in DOM and panels expose a focus destination", async () => {
  const html = await read("index.html");
  const tablistPosition = html.indexOf('role="tablist"');
  const firstPanelPosition = html.indexOf('id="panel-today"');

  assert.ok(tablistPosition >= 0 && tablistPosition < firstPanelPosition);
  for (const tab of ["today", "growth", "memory", "guardian"]) {
    assert.match(html, new RegExp(`<section[^>]+id="panel-${tab}"[^>]+tabindex="0"`));
  }
});

test("tabs expose an explicit roving focus path and standard navigation keys", async () => {
  const [html, app] = await Promise.all([read("index.html"), read("app.mjs")]);

  assert.match(html, /id="tab-today"[^>]+tabindex="0"/);
  for (const tab of ["growth", "memory", "guardian"]) {
    assert.match(html, new RegExp(`id="tab-${tab}"[^>]+tabindex="-1"`));
  }
  for (const key of ["ArrowRight", "ArrowLeft", "Home", "End"]) {
    assert.match(app, new RegExp(`event\\.key === "${key}"`));
  }
  assert.match(app, /event\.preventDefault\(\)/);
  assert.match(app, /activateTab\(PARENT_TABS\[nextIndex\], \{ focus: true \}\)/);
});

test("today renderer keeps the mood disclaimer visible in an empty state", async () => {
  const app = await read("app.mjs");

  assert.match(app, /function moodSection\(mood\)/);
  assert.match(app, /mood\.summary \|\| "今天还没有足够信息形成心情速览。"/);
  assert.match(app, /content\.push\(moodSection\(model\.mood\)\)/);
});

test("memory renderer shows controlled child choices and keepsakes instead of raw text", async () => {
  const app = await read("app.mjs");

  assert.match(app, /className: "choice-card"/);
  assert.match(app, /item\.childChoice/);
  assert.match(app, /item\.keepsake/);
  assert.doesNotMatch(app, /childMessage/);
  assert.doesNotMatch(app, /rawConversation/);
});

test("12px timeline timestamps meet normal-text contrast", async () => {
  const styles = await read("styles.css");
  const rule = styles.match(/\.timeline time\s*\{([^}]+)\}/)?.[1] || "";
  const colorToken = rule.match(/color:\s*var\((--[a-z-]+)\)/)?.[1];
  const foreground = styles.match(new RegExp(`${colorToken}:\\s*(#[0-9a-f]{6})`, "i"))?.[1];
  const background = styles.match(/--surface:\s*(#[0-9a-f]{6})/i)?.[1];

  assert.match(rule, /font-size:\s*12px/);
  assert.ok(foreground && background);
  assert.ok(contrastRatio(foreground, background) >= 4.5);
});

test("source never requests legacy raw child-memory APIs", async () => {
  const source = `${await read("api.mjs")}\n${await read("app.mjs")}`;

  for (const path of ["/api/facts", "/api/diary", "/api/mastery", "/api/report", "/api/state"]) {
    assert.doesNotMatch(source, new RegExp(path.replaceAll("/", "\\/")));
  }
  assert.match(source, /\/api\/parent\//);
});

test("PWA launch URL, manifest scope, and service-worker registration are coherent", async () => {
  const [manifestText, app, serviceWorker] = await Promise.all([
    read("manifest.webmanifest"),
    read("app.mjs"),
    read("sw.js"),
  ]);
  const manifest = JSON.parse(manifestText);

  assert.equal(manifest.id, "/parent/");
  assert.equal(manifest.start_url, "/parent/");
  assert.equal(manifest.scope, "/parent/");
  assert.match(app, /serviceWorker\.register\("\/parent\/sw\.js", \{ scope: "\/parent\/" \}\)/);
  assert.doesNotMatch(serviceWorker, /"\/parent",/);
  assert.match(serviceWorker, /"\/parent\/"/);
  assert.match(serviceWorker, /pathname\.startsWith\("\/parent\/"\)/);
});

test("PWA install metadata is mobile first and names the parent manual consistently", async () => {
  const [html, manifestText] = await Promise.all([
    read("index.html"),
    read("manifest.webmanifest"),
  ]);
  const manifest = JSON.parse(manifestText);

  assert.match(html, /name="apple-mobile-web-app-title" content="训练师手册"/);
  assert.match(html, /name="application-name" content="训练师手册"/);
  assert.match(html, /name="theme-color" media="\(prefers-color-scheme: light\)"/);
  assert.match(html, /name="theme-color" media="\(prefers-color-scheme: dark\)"/);
  assert.deepEqual(manifest.display_override, ["standalone", "minimal-ui"]);
  assert.deepEqual(manifest.categories, ["education", "lifestyle", "parenting"]);
});

test("visual system keeps the block-and-night-light direction explicit", async () => {
  const styles = await read("styles.css");

  assert.match(styles, /--block-shadow:/);
  assert.match(styles, /--lamp-glow:/);
  assert.match(styles, /body::before/);
  assert.match(styles, /\.brand-mark::after/);
  assert.match(styles, /\.tab-list button\[aria-selected="true"\]::before/);
  assert.match(styles, /touch-action:\s*manipulation/);
});

test("PWA manifest does not force a device orientation", async () => {
  const manifest = JSON.parse(await read("manifest.webmanifest"));

  assert.equal(Object.hasOwn(manifest, "orientation"), false);
});

test("PWA manifest, service worker, and mobile accessibility constraints are present", async () => {
  const [manifestText, serviceWorker, styles] = await Promise.all([
    read("manifest.webmanifest"),
    read("sw.js"),
    read("styles.css"),
  ]);
  const manifest = JSON.parse(manifestText);

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
