import { childApi, pollMomentUntilSettled } from "./api.mjs";
import {
  beginPocketChange,
  feedView,
  finishPocketChange,
  momentView,
  reconcileFeed,
  worldView,
} from "./model.mjs";

const view = document.querySelector("#view");
const announcer = document.querySelector("#announcer");
const modeChip = document.querySelector("#mode-chip");
const themeMeta = document.querySelector('meta[name="theme-color"]');
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const state = {
  world: null,
  feed: null,
  pocketItems: null,
  currentMoment: null,
  pocketBusy: false,
  routeController: null,
  pollControllers: new Map(),
  routeVersion: 0,
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function safeAssetUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value, window.location.origin);
    if (url.origin !== window.location.origin) return "";
    return escapeHtml(`${url.pathname}${url.search}${url.hash}`);
  } catch {
    return "";
  }
}

function announce(message) {
  announcer.textContent = "";
  window.setTimeout(() => {
    announcer.textContent = message;
  }, 20);
}

function routeInfo() {
  const raw = (window.location.hash || "#now").slice(1);
  if (raw.startsWith("moment/")) {
    return { name: "moment", id: decodeURIComponent(raw.slice("moment/".length)) };
  }
  if (["now", "adventures", "pocket"].includes(raw)) return { name: raw };
  return { name: "now" };
}

function updateNavigation(route) {
  const activeTab = route.name === "moment" ? "adventures" : route.name;
  document.querySelectorAll("[data-tab]").forEach((link) => {
    if (link.dataset.tab === activeTab) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function focusHeading() {
  window.requestAnimationFrame(() => view.querySelector("h1")?.focus());
}

function commit(markup, title, { focus = true } = {}) {
  view.innerHTML = markup;
  document.title = `${title} | 灵灵的窗口`;
  if (focus) focusHeading();
}

function renderLoading(label = "正在打开灵灵的窗口") {
  view.innerHTML = `
    <section class="loading-view" aria-label="${escapeHtml(label)}" aria-busy="true">
      <div class="skeleton skeleton-media"></div>
      <div class="skeleton skeleton-line wide"></div>
      <div class="skeleton skeleton-line"></div>
    </section>`;
}

function renderError(title, message) {
  commit(`
    <section class="error-state" role="alert">
      <h1 tabindex="-1">${escapeHtml(title)}</h1>
      <p>${escapeHtml(message)}</p>
      <button class="secondary-button" type="button" data-action="retry-route">再试一次</button>
    </section>`, title);
}

function applyWorld(world) {
  state.world = world;
  const model = worldView(world);
  document.body.dataset.worldMode = model.mode;
  modeChip.textContent = model.modeLabel;
  themeMeta.content = model.theme === "day" ? "#F2F2EF" : "#171822";
  return model;
}

function mediaMarkup(media, { className = "media-frame", autoplay = false } = {}) {
  if (!media) return `<div class="media-fallback">这段画面暂时还没准备好。</div>`;

  const src = safeAssetUrl(media.src);
  const poster = safeAssetUrl(media.poster);
  const alt = escapeHtml(media.alt || "灵灵的奇遇画面");
  if (!src) return `<div class="media-fallback">这段画面暂时还没准备好。</div>`;

  if (media.kind === "video") {
    const canAutoplay = autoplay && !reduceMotion.matches;
    return `
      <div class="${escapeHtml(className)}">
        <video controls playsinline ${canAutoplay ? "autoplay muted" : ""}
          preload="metadata" ${poster ? `poster="${poster}"` : ""} aria-label="${alt}">
          <source src="${src}" type="${escapeHtml(media.mime_type || "video/mp4")}">
          你的浏览器暂时不能播放这段视频。
        </video>
      </div>`;
  }

  return `
    <div class="${escapeHtml(className)}">
      <img src="${src}" alt="${alt}" width="${Number(media.width) || 720}"
        height="${Number(media.height) || 900}" loading="lazy">
    </div>`;
}

function renderNow(world) {
  const model = applyWorld(world);
  const scene = model.media
    ? mediaMarkup(model.media, { autoplay: true })
    : `<div class="quiet-scene" role="img" aria-label="灵灵的世界已经安静入睡"><span>晚安，明早见</span></div>`;

  commit(`
    <section aria-labelledby="now-title">
      <div class="world-scene">
        ${scene}
        ${model.isSleeping ? "" : `
          <div class="scene-status"><span class="live-dot" aria-hidden="true"></span>此刻，AI 生成</div>`}
        <div class="scene-copy">
          <h1 id="now-title" tabindex="-1">${escapeHtml(model.headline)}</h1>
          <p>${escapeHtml(model.summary)}</p>
        </div>
      </div>

      <div class="now-sheet">
        <aside class="whisper-card" aria-label="回到实体玩偶的提醒">
          <span class="whisper-light" aria-hidden="true"></span>
          <span>
            <b>${model.isSleeping ? "灵灵已经睡着了" : model.theme === "night" ? "睡前悄悄话攒好了" : "灵灵有话想当面说"}</b>
            <span>${model.isSleeping ? "明早再来看看它" : model.theme === "night" ? "摸摸它，说完就睡哦" : "回家摸摸它，就能听到"}</span>
          </span>
        </aside>

        <div class="memory-grid" aria-label="一起留下的回忆">
          <div class="memory-card">
            <b>${model.knownDays || "新"}</b>
            <span>${model.knownDays ? `认识第 ${model.knownDays} 天` : "刚刚认识"}</span>
          </div>
          <div class="memory-card">
            <b>${model.moments}</b>
            <span>一起攒下的瞬间</span>
          </div>
        </div>
      </div>
    </section>`, "现在");
}

function formatDate(value) {
  if (!value) return "最近";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "最近";
  return new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric" }).format(date);
}

function pendingCard(item) {
  return `
    <article class="pending-card" aria-busy="true" data-pending-id="${escapeHtml(item.id)}">
      <span class="kind-label personal">${escapeHtml(item.kindLabel)}</span>
      <h2>${escapeHtml(item.title)}</h2>
      <p>${item.pollError ? "刚才没连上，再试一次就好。" : "灵灵正在把这段共同经历画下来。"}</p>
      <div class="pending-bar" aria-hidden="true"></div>
      ${item.pollError ? `<button class="secondary-button" type="button" data-action="retry-poll" data-id="${escapeHtml(item.id)}">继续生成</button>` : ""}
    </article>`;
}

function momentCard(item) {
  const personal = item.kind === "personal";
  const titleId = `moment-${item.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  return `
    <article class="moment-card ${personal ? "personal" : "public"}" aria-labelledby="${titleId}">
      ${item.media ? mediaMarkup(item.media, { className: "moment-media" }) : ""}
      <div class="moment-body">
        <div class="moment-meta">
          <span class="kind-label ${personal ? "personal" : "public"}">${escapeHtml(item.kindLabel)}</span>
          <time class="secondary" datetime="${escapeHtml(item.occurred_at || "")}">${escapeHtml(formatDate(item.occurred_at))}</time>
        </div>
        <h2 id="${titleId}">${escapeHtml(item.title)}</h2>
        ${item.summary ? `<p>${escapeHtml(item.summary)}</p>` : ""}
        ${personal ? `<a class="moment-link" href="#moment/${encodeURIComponent(item.id)}">打开这段瞬间</a>` : ""}
      </div>
    </article>`;
}

function renderFeed(feed, { focus = true } = {}) {
  state.feed = feed;
  const knownDays = worldView(state.world || {}).knownDays;
  const published = feed.items.length
    ? `<div class="feed-list">${feed.items.map(momentCard).join("")}</div>`
    : `<div class="empty-state"><h2>奇遇还在路上</h2><p>回到灵灵身边说说话，特别的共同经历会在这里长出来。</p></div>`;

  commit(`
    <section aria-labelledby="feed-title">
      <header class="view-header">
        <h1 id="feed-title" tabindex="-1">灵灵的奇遇</h1>
        <p>${knownDays ? `认识第 ${knownDays} 天` : "共同经历会慢慢长成故事"}</p>
      </header>
      ${feed.pending.length ? `<div class="pending-list" aria-live="polite">${feed.pending.map(pendingCard).join("")}</div>` : ""}
      ${published}
    </section>`, "奇遇", { focus });
}

function appearance(value) {
  return ["clay", "amber", "pea", "blue"].includes(value) ? value : "amber";
}

function keepsakeVisual(item) {
  const image = safeAssetUrl(item.image_url);
  if (image) {
    return `<img src="${image}" alt="${escapeHtml(item.name || "信物")}" width="96" height="96" loading="lazy">`;
  }
  const firstCharacter = escapeHtml((item.name || "信").slice(0, 1));
  return `<span class="keepsake-swatch" data-appearance="${appearance(item.appearance)}" aria-hidden="true">${firstCharacter}</span>`;
}

function renderPocket(items, { focus = true } = {}) {
  state.pocketItems = items.map((item) => ({ ...item, collected: true }));
  const content = items.length
    ? `<div class="pocket-grid">${items.map((item) => {
      const body = `
        ${keepsakeVisual(item)}
        <span class="keepsake-copy">
          <b>${escapeHtml(item.name || "一件信物")}</b>
          <span>${escapeHtml(item.description || "一段共同经历留下的纪念")}</span>
        </span>`;
      const momentId = item.source_moment_id;
      return `
        <article class="keepsake-card" data-appearance="${appearance(item.appearance)}">
          ${momentId ? `<a href="#moment/${encodeURIComponent(momentId)}" aria-label="${escapeHtml(item.name || "信物")}，打开来源瞬间">${body}</a>` : `<div class="keepsake-static">${body}</div>`}
        </article>`;
    }).join("")}</div>`
    : `<div class="empty-state"><h2>口袋还是空的</h2><p>只有你和灵灵共同经历的特别故事，才会留下信物。</p></div>`;

  commit(`
    <section aria-labelledby="pocket-title">
      <header class="view-header">
        <h1 id="pocket-title" tabindex="-1">我的口袋</h1>
        <p>从共同经历里留下的信物</p>
      </header>
      ${content}
    </section>`, "口袋", { focus });
}

function detailPending(moment, { focus = true } = {}) {
  commit(`
    <section class="detail-view" aria-labelledby="detail-pending-title">
      <a class="back-link" href="#adventures">返回奇遇</a>
      <div class="pending-card" aria-busy="true">
        <span class="kind-label personal">专属瞬间，正在生成</span>
        <h1 id="detail-pending-title" tabindex="-1">${escapeHtml(moment.title || "灵灵正在画下这段回忆")}</h1>
        <p>画面很快就会出现。</p>
        <div class="pending-bar" aria-hidden="true"></div>
      </div>
    </section>`, "瞬间生成中", { focus });
}

function detailFailed({ focus = true } = {}) {
  commit(`
    <section class="detail-view">
      <a class="back-link" href="#adventures">返回奇遇</a>
      <div class="error-state" role="alert">
        <h1 tabindex="-1">这段画面没有生成好</h1>
        <p>它不会用不相关的画面替代。回到奇遇页看看其他故事吧。</p>
        <a class="button-link" href="#adventures">回到奇遇</a>
      </div>
    </section>`, "瞬间暂不可用", { focus });
}

function renderDetail(moment, { focus = true } = {}) {
  const item = momentView(moment);
  state.currentMoment = item;
  if (item.status === "rendering") return detailPending(item, { focus });
  if (item.status === "failed") return detailFailed({ focus });

  const keepsake = item.keepsake;
  const collected = Boolean(keepsake?.collected);
  const collectLabel = state.pocketBusy
    ? collected ? "正在移出口袋" : "正在收进口袋"
    : collected ? "移出口袋" : "收进口袋";

  commit(`
    <article class="detail-view" aria-labelledby="detail-title">
      <a class="back-link" href="#adventures">返回奇遇</a>
      ${mediaMarkup(item.media)}
      <div class="detail-meta">${escapeHtml(formatDate(item.occurred_at))}${item.with_label ? `，${escapeHtml(item.with_label)}` : ""}</div>
      <h1 id="detail-title" class="detail-title" tabindex="-1">${escapeHtml(item.title)}</h1>
      <p class="detail-story">${escapeHtml(item.story || item.summary || "这段共同经历已经被灵灵好好收下了。")}</p>
      ${keepsake ? `
        <section class="detail-keepsake" data-appearance="${appearance(keepsake.appearance)}" aria-label="这段经历留下的信物">
          ${keepsakeVisual(keepsake)}
          <span>
            <b>收获：${escapeHtml(keepsake.name || "一件信物")}</b>
            <span>${escapeHtml(keepsake.description || "一段共同经历留下的纪念")}</span>
          </span>
        </section>
        <button class="primary-button" type="button" data-action="toggle-pocket"
          aria-pressed="${String(collected)}" aria-busy="${String(state.pocketBusy)}"
          ${state.pocketBusy ? "disabled" : ""}>${collectLabel}</button>` : ""}
    </article>`, item.title, { focus });
}

function stopPollers() {
  state.pollControllers.forEach((controller) => controller.abort());
  state.pollControllers.clear();
}

function startFeedPoll(item) {
  const key = `feed:${item.id}`;
  if (state.pollControllers.has(key)) return;
  const controller = new AbortController();
  state.pollControllers.set(key, controller);

  pollMomentUntilSettled(childApi, item.id, {
    signal: controller.signal,
    onUpdate: (moment) => {
      if (!state.feed) return;
      state.feed = reconcileFeed(state.feed, moment);
      if (routeInfo().name === "adventures") renderFeed(state.feed, { focus: false });
      if (moment.status === "published") announce("新的专属瞬间已经画好了。");
      if (moment.status === "failed") announce("这段画面没有生成好，已经从奇遇中移除。");
    },
  }).then((moment) => {
    if (moment.status === "failed" && state.feed) {
      state.feed = reconcileFeed(state.feed, moment);
      if (routeInfo().name === "adventures") renderFeed(state.feed, { focus: false });
    }
  }).catch((error) => {
    if (error.name === "AbortError" || !state.feed) return;
    state.feed = {
      ...state.feed,
      pending: state.feed.pending.map((pending) => pending.id === item.id ? { ...pending, pollError: true } : pending),
    };
    if (routeInfo().name === "adventures") renderFeed(state.feed, { focus: false });
    announce("生成状态暂时没连上，可以继续重试。");
  }).finally(() => {
    state.pollControllers.delete(key);
  });
}

function startFeedPolls(feed) {
  feed.pending.forEach(startFeedPoll);
}

function startDetailPoll(moment) {
  const key = `detail:${moment.id}`;
  if (state.pollControllers.has(key)) return;
  const controller = new AbortController();
  state.pollControllers.set(key, controller);

  pollMomentUntilSettled(childApi, moment.id, {
    signal: controller.signal,
    onUpdate: (next) => {
      if (routeInfo().name !== "moment" || routeInfo().id !== String(moment.id)) return;
      renderDetail(next, { focus: next.status !== "rendering" });
      if (next.status === "published") announce("专属瞬间已经画好了。");
    },
  }).catch((error) => {
    if (error.name !== "AbortError") renderError("暂时看不到生成进度", "返回奇遇页后可以继续查看。");
  }).finally(() => state.pollControllers.delete(key));
}

async function loadWorld(signal) {
  const world = await childApi.world({ signal });
  applyWorld(world);
  return world;
}

async function route() {
  const current = routeInfo();
  const version = ++state.routeVersion;
  state.routeController?.abort();
  stopPollers();
  state.routeController = new AbortController();
  const { signal } = state.routeController;
  updateNavigation(current);
  renderLoading(current.name === "pocket" ? "正在打开口袋" : current.name === "adventures" ? "正在打开奇遇" : "正在看看灵灵在做什么");

  const backgroundWorld = current.name === "now"
    ? null
    : loadWorld(signal).catch((error) => {
      if (error.name !== "AbortError") return null;
      throw error;
    });

  try {
    if (current.name === "now") {
      renderNow(await loadWorld(signal));
    } else if (current.name === "adventures") {
      const feed = feedView(await childApi.feed({ signal }));
      if (version !== state.routeVersion) return;
      await backgroundWorld;
      renderFeed(feed);
      startFeedPolls(feed);
    } else if (current.name === "pocket") {
      const payload = await childApi.pocket({ signal });
      if (version !== state.routeVersion) return;
      await backgroundWorld;
      renderPocket(Array.isArray(payload.items) ? payload.items : []);
    } else {
      const moment = await childApi.moment(current.id, { signal });
      if (version !== state.routeVersion) return;
      await backgroundWorld;
      renderDetail(moment);
      if (moment.status === "rendering") startDetailPoll(moment);
    }
  } catch (error) {
    if (error.name === "AbortError" || version !== state.routeVersion) return;
    renderError("暂时打不开这里", error.message || "请稍后再试一次。");
  }
}

async function togglePocket() {
  const item = state.currentMoment;
  const keepsake = item?.keepsake;
  if (!keepsake || state.pocketBusy) return;

  const desired = !Boolean(keepsake.collected);
  const originalMoment = state.currentMoment;
  const baseItems = state.pocketItems || [];
  const change = beginPocketChange(baseItems, keepsake, desired);
  state.pocketItems = change.items;
  state.currentMoment = momentView({ ...item, keepsake: { ...keepsake, collected: desired } });
  state.pocketBusy = true;
  renderDetail(state.currentMoment, { focus: false });

  try {
    const response = await childApi.setCollected(keepsake.id, desired);
    const settled = { ok: true, ...response };
    state.pocketItems = finishPocketChange(change, settled);
    state.currentMoment = momentView({
      ...state.currentMoment,
      keepsake: { ...state.currentMoment.keepsake, collected: Boolean(settled.collected ?? desired) },
    });
    announce(desired ? "已经收进口袋。" : "已经移出口袋。");
  } catch {
    state.pocketItems = finishPocketChange(change, { ok: false });
    state.currentMoment = originalMoment;
    announce("刚才没有收好，已经恢复原来的状态。");
  } finally {
    state.pocketBusy = false;
    if (routeInfo().name === "moment") renderDetail(state.currentMoment, { focus: false });
  }
}

view.addEventListener("click", (event) => {
  const action = event.target.closest("[data-action]");
  if (!action) return;

  if (action.dataset.action === "retry-route") route();
  if (action.dataset.action === "retry-poll") {
    const pending = state.feed?.pending.find((item) => item.id === action.dataset.id);
    if (pending) {
      pending.pollError = false;
      renderFeed(state.feed, { focus: false });
      startFeedPoll(pending);
    }
  }
  if (action.dataset.action === "toggle-pocket") togglePocket();
});

view.addEventListener("error", (event) => {
  const target = event.target.tagName === "SOURCE" ? event.target.parentElement : event.target;
  if (!(target instanceof HTMLMediaElement) && !(target instanceof HTMLImageElement)) return;

  const frame = target.closest(".media-frame, .moment-media");
  if (frame) {
    frame.innerHTML = '<div class="media-fallback">这段画面暂时无法播放。</div>';
    announce("这段画面暂时无法播放。");
    return;
  }

  if (target instanceof HTMLImageElement && target.closest(".keepsake-card, .detail-keepsake")) {
    const fallback = document.createElement("span");
    fallback.className = "keepsake-swatch";
    fallback.setAttribute("aria-hidden", "true");
    fallback.textContent = (target.alt || "信").slice(0, 1);
    target.replaceWith(fallback);
  }
}, true);

window.addEventListener("hashchange", route);
window.addEventListener("pagehide", stopPollers);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js", { scope: "/child/" }).catch(() => {});
}

if (!window.location.hash) window.history.replaceState(null, "", "#now");
route();
