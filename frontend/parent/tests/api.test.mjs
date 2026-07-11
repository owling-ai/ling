import test from "node:test";
import assert from "node:assert/strict";

import { createParentApi, endpointFor } from "../api.mjs";

test("maps every parent tab to an allowlisted projection endpoint", () => {
  assert.equal(endpointFor("today"), "/api/parent/today");
  assert.equal(endpointFor("growth"), "/api/parent/growth?period=week");
  assert.equal(endpointFor("memory"), "/api/parent/memory?limit=20");
  assert.equal(endpointFor("memory", { cursor: "20" }), "/api/parent/memory?limit=20&cursor=20");
  assert.equal(endpointFor("memory", { cursor: "20/next" }), "/api/parent/memory?limit=20&cursor=20%2Fnext");
  assert.equal(endpointFor("guardian"), "/api/parent/guardian");
  assert.throws(() => endpointFor("facts"), /Unknown parent projection/);
});

test("loads the next controlled memory page through the supported cursor", async () => {
  const requests = [];
  const parentApi = createParentApi(async (url, options) => {
    requests.push({ url, options });
    return {
      ok: true,
      json: async () => ({ items: [], next_cursor: null }),
    };
  });

  await parentApi.load("memory", { cursor: "20" });

  assert.equal(requests[0].url, "/api/parent/memory?limit=20&cursor=20");
  assert.deepEqual(requests[0].options, {
    headers: { Accept: "application/json" },
    signal: undefined,
  });
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

test("rejects a 2xx non-JSON response as a projection contract error", async () => {
  const parentApi = createParentApi(async () => ({
    ok: true,
    status: 200,
    json: async () => { throw new SyntaxError("Unexpected token '<'"); },
  }));

  await assert.rejects(() => parentApi.load("today"), /JSON 契约/);
});

test("preserves a useful projection error message for retry UI", async () => {
  const parentApi = createParentApi(async () => ({
    ok: false,
    status: 503,
    json: async () => ({ detail: "家长投影正在准备" }),
  }));

  await assert.rejects(() => parentApi.load("guardian"), /家长投影正在准备/);
});

test("normalizes browser network failures without leaking English internals", async () => {
  const parentApi = createParentApi(async () => {
    throw new TypeError("Failed to fetch");
  });

  await assert.rejects(
    () => parentApi.load("today"),
    (error) => error.message === "暂时无法连接灵灵，请检查网络后重试。",
  );
});

test("submits the parent scan with the installation identity", async () => {
  const requests = [];
  const parentApi = createParentApi(async (url, options) => {
    requests.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ status: "active", child_name: "悠悠" }),
    };
  });

  const result = await parentApi.bindParent("ling://bind/demo", "parent-installation");

  assert.equal(result.status, "active");
  assert.equal(requests[0].url, "/api/bindings/parent-scan");
  assert.equal(requests[0].options.method, "POST");
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    qr_token: "ling://bind/demo",
    installation_id: "parent-installation",
  });
});

test("keeps the child-first backend message for an early parent scan", async () => {
  const parentApi = createParentApi(async () => ({
    ok: false,
    status: 409,
    json: async () => ({ detail: "请先让孩子端扫描同一个二维码" }),
  }));

  await assert.rejects(
    () => parentApi.bindParent("demo", "parent-installation"),
    /请先让孩子端扫描/,
  );
});
