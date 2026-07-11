import assert from "node:assert/strict";

const baseUrl = process.env.BASE_URL || "http://127.0.0.1:4173";

async function json(path, init = {}) {
  const response = await fetch(`${baseUrl}${path}`, init);
  assert.equal(response.ok, true, `${path} returned ${response.status}`);
  return response.json();
}

if (baseUrl.includes("4173")) {
  await json("/__test__/state?mode=day&generation=pending&collected=false");
}

const childPage = await fetch(`${baseUrl}/child`);
assert.equal(childPage.ok, true);
assert.match(await childPage.text(), /灵灵的窗口/);

const world = await json("/api/child/world/now");
assert.equal(["day", "night", "sleeping"].includes(world.mode), true);
assert.equal(typeof world.doll?.name, "string");

const feed = await json("/api/child/feed");
assert.equal(Array.isArray(feed.items), true);
assert.equal(Array.isArray(feed.pending), true);

if (feed.pending.length) {
  const id = feed.pending[0].id;
  let moment = await json(`/api/moments/${id}`);
  for (let attempt = 0; moment.status === "rendering" && attempt < 12; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, Math.max(100, moment.poll_after_ms || 250)));
    moment = await json(`/api/moments/${id}`);
  }
  assert.equal(["published", "failed"].includes(moment.status), true);

  if (moment.status === "published" && moment.keepsake) {
    const result = await json(`/api/pocket/${moment.keepsake.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ collected: true }),
    });
    assert.equal(result.collected, true);
    const pocket = await json("/api/pocket");
    assert.equal(pocket.items.some((item) => String(item.id) === String(moment.keepsake.id)), true);
  }
}

console.log(`child HTTP smoke passed against ${baseUrl}`);
