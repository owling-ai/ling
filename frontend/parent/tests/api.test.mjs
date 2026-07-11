import test from "node:test";
import assert from "node:assert/strict";

import { createParentApi, endpointFor } from "../api.mjs";

test("maps every parent tab to an allowlisted projection endpoint", () => {
  assert.equal(endpointFor("today"), "/api/parent/today");
  assert.equal(endpointFor("growth"), "/api/parent/growth?period=week");
  assert.equal(endpointFor("memory"), "/api/parent/memory?limit=20");
  assert.equal(endpointFor("guardian"), "/api/parent/guardian");
  assert.throws(() => endpointFor("facts"), /Unknown parent projection/);
});

test("loads display-ready data through the requested parent projection only", async () => {
  const requests = [];
  const parentApi = createParentApi(async (url, options) => {
    requests.push({ url, options });
    return {
      ok: true,
      json: async () => ({ metrics: { minutes_together: 18 } }),
    };
  });

  const result = await parentApi.load("today");

  assert.deepEqual(requests, [{
    url: "/api/parent/today",
    options: { headers: { Accept: "application/json" }, signal: undefined },
  }]);
  assert.equal(result.metrics.minutes_together, 18);
});

test("rejects a successful response when it leaks an internal field", async () => {
  const parentApi = createParentApi(async () => ({
    ok: true,
    json: async () => ({ nested: { transcript: "raw child words" } }),
  }));

  await assert.rejects(() => parentApi.load("memory"), /transcript/i);
});

test("preserves a useful projection error message for retry UI", async () => {
  const parentApi = createParentApi(async () => ({
    ok: false,
    status: 503,
    json: async () => ({ detail: "家长投影正在准备" }),
  }));

  await assert.rejects(() => parentApi.load("guardian"), /家长投影正在准备/);
});
