import test from "node:test";
import assert from "node:assert/strict";

import { createChildApi, pollMomentUntilSettled } from "../api.mjs";

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("child API uses only the five allowlisted business endpoints", async () => {
  const calls = [];
  const api = createChildApi(async (url, init = {}) => {
    calls.push({ url, init });
    return jsonResponse({ ok: true });
  });

  await api.world();
  await api.feed();
  await api.moment(9);
  await api.pocket();
  await api.setCollected("kite-token", true);

  assert.deepEqual(calls.map((call) => call.url), [
    "/api/child/world/now",
    "/api/child/feed",
    "/api/moments/9",
    "/api/pocket",
    "/api/pocket/kite-token",
  ]);
  assert.equal(calls[4].init.method, "PUT");
  assert.equal(calls[4].init.body, JSON.stringify({ collected: true }));
});

test("child API surfaces a display-safe error without leaking a response body", async () => {
  const api = createChildApi(async () => jsonResponse({ detail: "provider secret stack" }, 503));

  await assert.rejects(api.world(), (error) => {
    assert.equal(error.name, "ChildApiError");
    assert.equal(error.status, 503);
    assert.equal(error.message, "现在还连不上灵灵的世界，请再试一次。");
    assert.equal(String(error).includes("provider secret stack"), false);
    return true;
  });
});

test("moment polling follows server delay and stops after publication", async () => {
  const updates = [];
  const delays = [];
  const results = [
    { id: 9, kind: "personal", status: "rendering", poll_after_ms: 650 },
    { id: 9, kind: "personal", status: "published", title: "风筝终于飞起来啦" },
  ];
  const api = { moment: async () => results.shift() };

  const result = await pollMomentUntilSettled(api, 9, {
    wait: async (ms) => delays.push(ms),
    onUpdate: (moment) => updates.push(moment.status),
  });

  assert.equal(result.status, "published");
  assert.deepEqual(delays, [650]);
  assert.deepEqual(updates, ["rendering", "published"]);
});

test("moment polling honors an already-cancelled signal", async () => {
  const controller = new AbortController();
  let calls = 0;
  controller.abort();

  await assert.rejects(
    pollMomentUntilSettled({ moment: async () => { calls += 1; } }, 9, { signal: controller.signal }),
    (error) => error.name === "AbortError",
  );
  assert.equal(calls, 0);
});

test("moment polling times out without fabricating a server failure", async () => {
  const updates = [];
  const api = {
    moment: async () => ({ id: 9, kind: "personal", status: "rendering", poll_after_ms: 250 }),
  };

  const result = await pollMomentUntilSettled(api, 9, {
    maxAttempts: 1,
    wait: async () => {},
    onUpdate: (moment) => updates.push(moment.status),
  });

  assert.equal(result.status, "timed_out");
  assert.equal(result.retryable, true);
  assert.deepEqual(updates, ["rendering"]);
});
