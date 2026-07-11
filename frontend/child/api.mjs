export class ChildApiError extends Error {
  constructor(status, message = "现在还连不上灵灵的世界，请再试一次。") {
    super(message);
    this.name = "ChildApiError";
    this.status = status;
  }
}

export function createChildApi(fetchImpl = globalThis.fetch?.bind(globalThis)) {
  if (!fetchImpl) throw new TypeError("A fetch implementation is required");

  async function request(path, init = {}) {
    let response;
    try {
      response = await fetchImpl(path, init);
    } catch (error) {
      if (error?.name === "AbortError") throw error;
      throw new ChildApiError(0);
    }

    if (!response.ok) {
      throw new ChildApiError(response.status);
    }

    return response.json();
  }

  return Object.freeze({
    world: (options = {}) => request("/api/child/world/now", { signal: options.signal }),
    feed: (options = {}) => request("/api/child/feed", { signal: options.signal }),
    moment: (id, options = {}) => request(`/api/moments/${encodeURIComponent(id)}`, { signal: options.signal }),
    pocket: (options = {}) => request("/api/pocket", { signal: options.signal }),
    setCollected: (id, collected, options = {}) => request(`/api/pocket/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ collected: Boolean(collected) }),
      signal: options.signal,
    }),
  });
}

function abortError() {
  return new DOMException("The operation was aborted", "AbortError");
}

function waitFor(ms, signal) {
  if (signal?.aborted) return Promise.reject(abortError());

  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError());
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export async function pollMomentUntilSettled(api, id, options = {}) {
  const {
    signal,
    onUpdate = () => {},
    wait = waitFor,
    maxAttempts = 20,
  } = options;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (signal?.aborted) throw abortError();

    const moment = await api.moment(id, { signal });
    onUpdate(moment);
    if (moment.status !== "rendering") return moment;

    await wait(Math.max(250, Number(moment.poll_after_ms || 700)), signal);
  }

  return { id, kind: "personal", status: "timed_out", reason: "poll_timeout", retryable: true };
}

export const childApi = createChildApi();
