import { assertProjectionSafe } from "./model.mjs";

const PARENT_ENDPOINTS = Object.freeze({
  today: "/api/parent/today",
  growth: "/api/parent/growth?period=week",
  memory: "/api/parent/memory?limit=20",
  guardian: "/api/parent/guardian",
});

export function endpointFor(tab) {
  const endpoint = PARENT_ENDPOINTS[tab];
  if (!endpoint) throw new Error(`Unknown parent projection: ${tab}`);
  return endpoint;
}

async function responseJson(response) {
  try {
    return await response.json();
  } catch {
    if (response.ok) {
      throw new Error("家长投影响应不符合 JSON 契约");
    }
    return {};
  }
}

export function createParentApi(fetchImplementation = globalThis.fetch?.bind(globalThis)) {
  if (typeof fetchImplementation !== "function") {
    throw new Error("Fetch is unavailable");
  }

  return {
    async load(tab, { signal } = {}) {
      const response = await fetchImplementation(endpointFor(tab), {
        headers: { Accept: "application/json" },
        signal,
      });
      const data = await responseJson(response);
      if (!response.ok) {
        throw new Error(data.detail || data.message || `家长投影暂时不可用（HTTP ${response.status}）`);
      }
      assertProjectionSafe(data);
      return data;
    },
  };
}
