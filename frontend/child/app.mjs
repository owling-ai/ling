import { childApi, loadPocketAfterMutation, pollMomentUntilSettled } from "./api.mjs";
import {
  cameraQrIsSupported,
  childBindingIsActive,
  forgetActiveChildBinding,
  getOrCreateInstallationId,
  normalizeQrToken,
  rememberActiveChildBinding,
  startCameraQrScanner,
} from "./scanner.mjs";
import {
  beginPocketChange,
  childRoute,
  feedView,
  finishPocketChange,
  isPocketMutationCurrent,
  momentView,
  pendingCardChanged,
  reconcileFeed,
  safeMediaUrl,
  shouldShowWelcome,
  worldRefreshDelay,
  worldView,
} from "./model.mjs";

const view = document.querySelector("#view");
const announcer = document.querySelector("#announcer");
const navigation = document.querySelector(".tab-bar");
const toast = document.querySelector("#toast");
const themeMeta = document.querySelector('meta[name="theme-color"]');
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const WELCOME_KEY = "ling-child-welcome-v1";
const BINDING_POLL_MS = 1200;

const state = {
  world: null,
  feed: null,
  pocketItems: null,
  currentMoment: null,
  pocketBusy: false,
  pocketMutation: null,
  routeController: null,
  pollControllers: new Map(),
  routeVersion: 0,
  worldRefreshTimer: null,
  showingWelcome: false,
  soundEnabled: false,
  toastTimer: null,
  bindingGate: true,
  bindingVersion: 0,
  bindingPollTimer: null,
  bindingPollController: null,
  bindingSubmitController: null,
  bindingScannerStop: null,
  bindingSubmitting: false,
  installationId: null,
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

function announce(message) {
  announcer.textContent = "";
  window.setTimeout(() => {
    announcer.textContent = message;
  }, 20);
}

function routeInfo() {
  return childRoute(window.location.hash);
}

function updateNavigation(route) {
  const activeTab = route.name === "moment" ? "adventures" : route.name;
  document.body.dataset.route = route.name;
  navigation.hidden = route.name === "moment";
  document.querySelectorAll("[data-tab]").forEach((link) => {
    if (link.dataset.tab === activeTab) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function focusHeading() {
  window.requestAnimationFrame(() => view.querySelector("h1")?.focus({ preventScroll: true }));
}

function commit(markup, title, { focus = true } = {}) {
  view.innerHTML = markup;
  document.title = `${title} | 灵灵的窗口`;
  if (focus) focusHeading();
}

function renderLoading(label = "正在打开灵灵的窗口") {
  view.innerHTML = `
    <section class="loading-view" aria-label="${escapeHtml(label)}" aria-busy="true">
      <div class="loading-blocks" aria-hidden="true"><i></i><i></i><i></i></div>
      <p>${escapeHtml(label)}</p>
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
  themeMeta.content = model.theme === "day" ? "#F2F2EF" : "#171822";
  return model;
}

function welcomeWasSeen() {
  try {
    return window.localStorage.getItem(WELCOME_KEY) === "seen";
  } catch {
    return false;
  }
}

function rememberWelcome() {
  try {
    window.localStorage.setItem(WELCOME_KEY, "seen");
  } catch {
    // The welcome still works when storage is unavailable for privacy reasons.
  }
}

function resetLocalDemoState() {
  const url = new URL(window.location.href);
  if (url.searchParams.get("binding") !== "reset") return false;
  forgetActiveChildBinding();
  try {
    window.localStorage.removeItem(WELCOME_KEY);
  } catch {
    // The reset link still opens the scanner when storage is unavailable.
  }
  url.searchParams.delete("binding");
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  return true;
}

function showToast(message) {
  if (state.toastTimer !== null) window.clearTimeout(state.toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  state.toastTimer = window.setTimeout(() => {
    toast.hidden = true;
    toast.textContent = "";
    state.toastTimer = null;
  }, 2600);
}

function stopBindingScanner() {
  state.bindingScannerStop?.();
  state.bindingScannerStop = null;
}

function stopBindingPolling() {
  if (state.bindingPollTimer !== null) window.clearTimeout(state.bindingPollTimer);
  state.bindingPollTimer = null;
  state.bindingPollController?.abort();
  state.bindingPollController = null;
}

function stopBindingRuntime() {
  stopBindingScanner();
  stopBindingPolling();
  state.bindingSubmitController?.abort();
  state.bindingSubmitController = null;
}

function prepareBindingView() {
  stopBindingRuntime();
  state.bindingGate = true;
  state.showingWelcome = false;
  state.bindingSubmitting = false;
  navigation.hidden = true;
  document.body.dataset.route = "binding";
  document.body.dataset.worldMode = "day";
  themeMeta.content = "#F2F2EF";
  return ++state.bindingVersion;
}

function setScannerState(cameraState, message) {
  const scanner = view.querySelector("[data-binding-scanner]");
  const status = view.querySelector("[data-scanner-status]");
  if (scanner) scanner.dataset.cameraState = cameraState;
  if (status) status.textContent = message;
}

async function startBindingCamera(version) {
  if (!cameraQrIsSupported()) {
    setScannerState("unavailable", "这台手机暂时不能直接扫码，请输入 Demo 码");
    return;
  }

  const video = view.querySelector("[data-binding-video]");
  if (!video) return;
  setScannerState("starting", "正在打开相机");

  try {
    const stop = await startCameraQrScanner(video, {
      onResult: (token) => submitChildBinding(token),
      onError: () => setScannerState("ready", "把二维码放进方框里"),
    });
    if (version !== state.bindingVersion || !state.bindingGate || state.bindingSubmitting) {
      stop();
      return;
    }
    state.bindingScannerStop = stop;
    setScannerState("ready", "把二维码放进方框里");
  } catch {
    if (version !== state.bindingVersion) return;
    setScannerState("unavailable", "相机没有打开，请输入 Demo 码");
  }
}

function renderBindingScan(errorMessage = "") {
  const version = prepareBindingView();
  commit(`
    <section class="binding-view binding-scan-view" aria-labelledby="binding-title">
      <header class="binding-copy">
        <span class="binding-step">第 1 步</span>
        <h1 id="binding-title" tabindex="-1">先认识一下灵灵</h1>
        <p>扫描玩偶卡片上的二维码</p>
      </header>

      <div class="binding-scanner" data-binding-scanner data-camera-state="starting">
        <video class="binding-video" data-binding-video playsinline muted aria-label="二维码扫描相机"></video>
        <div class="binding-scan-guide" aria-hidden="true"><i></i><i></i><i></i><i></i><span></span></div>
        <p class="binding-scanner-status" data-scanner-status aria-live="polite">正在打开相机</p>
        <button class="binding-camera-retry" type="button" data-action="retry-binding-camera">重新打开相机</button>
      </div>

      <form class="binding-code-form" data-binding-code-form>
        <label for="binding-code">Demo 码</label>
        <div>
          <input id="binding-code" name="qr-token" type="text" inputmode="text"
            autocomplete="off" autocapitalize="characters" spellcheck="false"
            placeholder="LING-DEMO-2026" aria-describedby="binding-form-message">
          <button type="submit">继续</button>
        </div>
        <p id="binding-form-message" class="binding-form-message" aria-live="polite">${escapeHtml(errorMessage)}</p>
      </form>
    </section>`, "绑定灵灵");
  startBindingCamera(version);
}

function updateBindingWaitStatus(message) {
  const status = view.querySelector("[data-binding-wait-status]");
  if (status) status.textContent = message;
}

function scheduleBindingPoll(version, delay = BINDING_POLL_MS) {
  if (version !== state.bindingVersion || !state.bindingGate) return;
  if (state.bindingPollTimer !== null) window.clearTimeout(state.bindingPollTimer);
  state.bindingPollTimer = window.setTimeout(() => pollBindingStatus(version), delay);
}

async function pollBindingStatus(version) {
  if (version !== state.bindingVersion || !state.bindingGate) return;
  state.bindingPollTimer = null;
  const controller = new AbortController();
  state.bindingPollController = controller;

  try {
    const binding = await childApi.bindingStatus(state.installationId, { signal: controller.signal });
    if (version !== state.bindingVersion) return;
    if (binding.status === "active") {
      completeChildBinding();
      return;
    }
    updateBindingWaitStatus("正在等家长扫码...");
  } catch (error) {
    if (error.name === "AbortError" || version !== state.bindingVersion) return;
    if (error.status === 404) {
      renderBindingScan("刚才的配对已经结束，请重新扫码");
      return;
    }
    updateBindingWaitStatus("网络有点慢，正在继续等待...");
  } finally {
    if (state.bindingPollController === controller) state.bindingPollController = null;
  }
  scheduleBindingPoll(version);
}

function renderBindingWaiting(binding = {}) {
  const version = prepareBindingView();
  const dollName = escapeHtml(binding.doll_name || "灵灵");
  commit(`
    <section class="binding-view binding-wait-view" aria-labelledby="binding-wait-title">
      <header class="binding-copy">
        <span class="binding-step">第 2 步</span>
        <h1 id="binding-wait-title" tabindex="-1">我准备好啦</h1>
        <p>等家长扫描同一张卡片</p>
      </header>

      <div class="binding-pair-scene" role="img" aria-label="${dollName}正在等待家长加入">
        <span class="binding-phone binding-phone-child"><i></i></span>
        <span class="binding-pair-line"><i></i><i></i><i></i></span>
        <span class="binding-toy"><i class="binding-toy-ear left"></i><i class="binding-toy-ear right"></i><b>灵</b></span>
        <span class="binding-pair-line reverse"><i></i><i></i><i></i></span>
        <span class="binding-phone binding-phone-parent"><i></i></span>
      </div>

      <div class="binding-wait-footer">
        <p class="binding-wait-status" data-binding-wait-status aria-live="polite">正在等家长扫码...</p>
        <button class="binding-text-button" type="button" data-action="restart-binding">重新扫码</button>
      </div>
    </section>`, "等待家长");
  scheduleBindingPoll(version, 350);
}

function launchChildExperience() {
  stopBindingRuntime();
  state.bindingGate = false;
  if (shouldShowWelcome(window.location.search, welcomeWasSeen())) renderWelcome();
  else route();
}

function completeChildBinding() {
  rememberActiveChildBinding();
  announce("绑定成功，欢迎来到灵灵的世界。");
  launchChildExperience();
}

async function submitChildBinding(rawToken) {
  const token = normalizeQrToken(rawToken);
  if (!token || state.bindingSubmitting) {
    if (!token) {
      const message = view.querySelector(".binding-form-message");
      if (message) message.textContent = "请输入卡片上的 Demo 码";
    }
    return;
  }

  state.bindingSubmitting = true;
  stopBindingScanner();
  const version = state.bindingVersion;
  const controller = new AbortController();
  state.bindingSubmitController = controller;
  setScannerState("submitting", "正在认识灵灵...");
  view.querySelectorAll(".binding-code-form input, .binding-code-form button").forEach((control) => {
    control.disabled = true;
  });

  try {
    const binding = await childApi.childScan(token, state.installationId, { signal: controller.signal });
    if (version !== state.bindingVersion) return;
    if (binding.status === "active") completeChildBinding();
    else renderBindingWaiting(binding);
  } catch (error) {
    if (error.name === "AbortError" || version !== state.bindingVersion) return;
    renderBindingScan(error.status === 404
      ? "没有找到这个灵灵码，请检查后再试"
      : "刚才没有扫成功，请再试一次");
  } finally {
    if (state.bindingSubmitController === controller) state.bindingSubmitController = null;
    state.bindingSubmitting = false;
  }
}

async function beginBindingGate() {
  state.installationId = getOrCreateInstallationId();
  if (resetLocalDemoState()) {
    renderBindingScan();
    return;
  }
  if (childBindingIsActive()) {
    launchChildExperience();
    return;
  }

  prepareBindingView();
  renderLoading("正在确认灵灵的卡片");
  try {
    const binding = await childApi.bindingStatus(state.installationId);
    if (binding.status === "active") completeChildBinding();
    else if (["pending", "waiting_parent"].includes(binding.status)) renderBindingWaiting(binding);
    else renderBindingScan();
  } catch (error) {
    renderBindingScan(error.status === 404 ? "" : "暂时没有连上，可以直接扫码重试");
  }
}

function renderWelcome() {
  state.showingWelcome = true;
  navigation.hidden = true;
  document.body.dataset.route = "welcome";
  document.body.dataset.worldMode = "day";
  themeMeta.content = "#F2F2EF";
  commit(`
    <section class="welcome-view" aria-labelledby="welcome-title">
      <div class="welcome-copy">
        <h1 id="welcome-title" tabindex="-1">你好，我是灵灵</h1>
        <p>一起看看我的世界</p>
      </div>

      <div class="hatch-scene" role="img" aria-label="积木蛋轻轻打开，灵灵从里面探出头">
        <span class="egg-piece egg-piece-blue" aria-hidden="true"></span>
        <span class="egg-piece egg-piece-clay" aria-hidden="true"></span>
        <span class="egg-piece egg-piece-pea" aria-hidden="true"></span>
        <span class="egg-piece egg-piece-amber" aria-hidden="true"></span>
        <span class="egg-piece egg-piece-cream" aria-hidden="true"></span>
        <span class="hatch-glow" aria-hidden="true"></span>
        <span class="lingling-figure" aria-hidden="true">
          <i class="lingling-ear left"></i><i class="lingling-ear right"></i>
          <i class="lingling-eye left"></i><i class="lingling-eye right"></i>
          <i class="lingling-cheek"></i><i class="lingling-light"></i>
        </span>
      </div>

      <button class="welcome-button" type="button" data-action="enter-world">
        <span>一起看看</span><span aria-hidden="true">→</span>
      </button>
    </section>`, "欢迎", { focus: false });
}

function mediaMarkup(media, { className = "media-frame", autoplay = false } = {}) {
  if (!media) return `<div class="media-fallback">这段画面暂时还没准备好。</div>`;

  const src = escapeHtml(safeMediaUrl(media.src, window.location.origin));
  const poster = escapeHtml(safeMediaUrl(media.poster, window.location.origin));
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

function worldMediaMarkup(media) {
  if (!media) return `<div class="quiet-scene" role="img" aria-label="灵灵的世界已经安静入睡"><span class="night-light" aria-hidden="true"></span></div>`;

  const src = escapeHtml(safeMediaUrl(media.src, window.location.origin));
  const poster = escapeHtml(safeMediaUrl(media.poster, window.location.origin));
  const alt = escapeHtml(media.alt || "灵灵此刻的世界");
  if (!src) return `<div class="world-media-fallback">灵灵正在把今天的风收好</div>`;

  if (media.kind === "video") {
    return `<video class="world-video" data-world-video playsinline muted loop
      ${reduceMotion.matches ? "" : "autoplay"} preload="metadata"
      ${poster ? `poster="${poster}"` : ""} aria-label="${alt}">
      <source src="${src}" type="${escapeHtml(media.mime_type || "video/mp4")}">
    </video>`;
  }

  return `<img class="world-video" src="${src}" alt="${alt}"
    width="${Number(media.width) || 720}" height="${Number(media.height) || 1280}">`;
}

function renderNow(world) {
  const model = applyWorld(world);
  state.soundEnabled = false;
  const timeline = model.timeline.length
    ? `<ol class="world-timeline">${model.timeline.slice(-4).reverse().map((entry, index) => `
        <li${index ? ' class="past"' : ""}>
          ${entry.at ? `<time>${escapeHtml(entry.at)}</time>` : ""}
          ${entry.text ? `<span>${escapeHtml(entry.text)}</span>` : ""}
        </li>`).join("")}</ol>`
    : `<p class="world-summary">${escapeHtml(model.summary)}</p>`;

  commit(`
    <section class="now-view" aria-labelledby="now-title">
      <div class="world-stage">
        <div class="world-media-layer">${worldMediaMarkup(model.media)}</div>
        <div class="world-overlay">
          <div class="scene-copy">
            <div class="scene-status">${model.isSleeping ? "晚安" : "此刻"}</div>
            <h1 id="now-title" tabindex="-1">${escapeHtml(model.headline)}</h1>
            ${timeline}
          </div>

          <div class="now-actions">
            ${model.media?.kind === "video" ? `
              <button class="sound-button" type="button" data-action="toggle-sound"
                aria-label="打开世界声音" aria-pressed="false">
                <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 9.5v5h3.5L13 18V6L8.5 9.5Z"/><path class="sound-wave" d="M16 9c1.8 1.8 1.8 4.2 0 6M18.5 6.5c3.2 3.2 3.2 7.8 0 11"/></svg>
              </button>` : `<span></span>`}
            ${model.isSleeping ? `
              <span class="sleep-note">${escapeHtml(model.summary)}</span>` : `
              <button class="meet-button" type="button" data-action="meet-ling">去找灵灵</button>`}
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
    <article class="pending-card" aria-busy="${String(!item.pollError)}" data-pending-id="${escapeHtml(item.id)}">
      <span class="kind-label personal">${escapeHtml(item.kindLabel)}</span>
      <h2>${escapeHtml(item.title)}</h2>
      <p>${item.pollError ? "刚才没连上，再试一次就好。" : "灵灵正在把这段共同经历画下来。"}</p>
      ${item.pollError ? "" : '<div class="pending-bar" aria-hidden="true"></div>'}
      ${item.pollError ? `<button class="secondary-button" type="button" data-action="retry-poll" data-id="${escapeHtml(item.id)}">继续生成</button>` : ""}
    </article>`;
}

function updatePendingCard(previous, item) {
  if (!pendingCardChanged(previous, item)) return;
  const card = [...view.querySelectorAll("[data-pending-id]")]
    .find((candidate) => candidate.dataset.pendingId === String(item.id));
  if (!card) return;

  const template = document.createElement("template");
  template.innerHTML = pendingCard(item).trim();
  card.replaceWith(template.content.firstElementChild);
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
        <span class="section-eyebrow">我们走过的地方</span>
        <h1 id="feed-title" tabindex="-1">奇遇</h1>
        <p>${knownDays ? `你和灵灵认识的第 ${knownDays} 天` : "共同经历会慢慢长成故事"}</p>
      </header>
      ${feed.pending.length ? `<div class="pending-list" aria-live="polite">${feed.pending.map(pendingCard).join("")}</div>` : ""}
      ${published}
    </section>`, "奇遇", { focus });
}

function appearance(value) {
  return ["clay", "amber", "pea", "blue"].includes(value) ? value : "amber";
}

function keepsakeVisual(item) {
  const image = escapeHtml(safeMediaUrl(item.image_url, window.location.origin));
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
    : `<div class="empty-state"><h2>口袋还是空的</h2><p>等你和灵灵一起遇到一件值得留下的事。</p></div>`;

  commit(`
    <section aria-labelledby="pocket-title">
      <header class="view-header">
        <span class="section-eyebrow">每一件都有来历</span>
        <h1 id="pocket-title" tabindex="-1">口袋</h1>
        <p>从共同经历里留下的小东西</p>
      </header>
      ${content}
    </section>`, "口袋", { focus });
}

function detailPending(moment, { focus = true } = {}) {
  commit(`
    <section class="detail-view" aria-labelledby="detail-pending-title">
      <a class="back-link" href="#adventures">返回奇遇</a>
      <div class="pending-card" aria-busy="${String(!moment.pollError)}" data-detail-pending-id="${escapeHtml(moment.id)}">
        <span class="kind-label personal">专属瞬间，正在生成</span>
        <h1 id="detail-pending-title" tabindex="-1">${escapeHtml(moment.title || "灵灵正在画下这段回忆")}</h1>
        <p>${moment.pollError ? "生成状态暂时没连上，可以继续重试。" : "画面很快就会出现。"}</p>
        ${moment.pollError ? `<button class="secondary-button" type="button" data-action="retry-detail-poll" data-id="${escapeHtml(moment.id)}">继续生成</button>` : '<div class="pending-bar" aria-hidden="true"></div>'}
      </div>
    </section>`, "瞬间生成中", { focus });
}

function updateDetailPending(moment) {
  const card = view.querySelector("[data-detail-pending-id]");
  if (!card || card.dataset.detailPendingId !== String(moment.id)) return;
  const heading = card.querySelector("h1");
  if (heading && moment.title) heading.textContent = moment.title;
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
      <a class="back-link" href="#adventures"><span aria-hidden="true">←</span> 奇遇</a>
      <div class="detail-meta">${item.kind === "personal" ? "我们一起" : "灵灵的现在"} · ${escapeHtml(formatDate(item.occurred_at))}</div>
      <h1 id="detail-title" class="detail-title" tabindex="-1">${escapeHtml(item.title)}</h1>
      ${mediaMarkup(item.media)}
      <p class="detail-story">${escapeHtml(item.story || item.summary || "这段共同经历已经被灵灵好好收下了。")}</p>
      ${keepsake ? `
        <section class="detail-keepsake" data-appearance="${appearance(keepsake.appearance)}" aria-label="这段经历留下的信物">
          ${keepsakeVisual(keepsake)}
          <span>
            <b>${escapeHtml(keepsake.name || "一件信物")}</b>
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

function clearWorldRefresh() {
  if (state.worldRefreshTimer !== null) window.clearTimeout(state.worldRefreshTimer);
  state.worldRefreshTimer = null;
}

function scheduleWorldRefresh(world, version) {
  clearWorldRefresh();
  const delay = worldRefreshDelay(world?.next_transition_at);
  if (delay === null) return;

  state.worldRefreshTimer = window.setTimeout(() => {
    state.worldRefreshTimer = null;
    if (state.routeVersion !== version || routeInfo().name !== "now") return;
    route();
  }, delay);
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
      const previous = state.feed.pending.find((candidate) => candidate.id === String(moment.id));
      state.feed = reconcileFeed(state.feed, moment);
      if (moment.status === "rendering") {
        const pending = state.feed.pending.find((candidate) => candidate.id === String(moment.id));
        if (pending && routeInfo().name === "adventures") updatePendingCard(previous, pending);
        return;
      }
      if (routeInfo().name === "adventures") renderFeed(state.feed, { focus: false });
      if (moment.status === "published") announce("新的专属瞬间已经画好了。");
      if (moment.status === "failed") announce("这段画面没有生成好，已经从奇遇中移除。");
    },
  }).then((moment) => {
    if (moment.status === "timed_out" && state.feed) {
      const previous = state.feed.pending.find((candidate) => candidate.id === String(moment.id));
      state.feed = reconcileFeed(state.feed, moment);
      const pending = state.feed.pending.find((candidate) => candidate.id === String(moment.id));
      if (pending && routeInfo().name === "adventures") updatePendingCard(previous, pending);
      announce("生成还在继续，可以稍后重试查看。");
    }
  }).catch((error) => {
    if (error.name === "AbortError" || !state.feed) return;
    const previous = state.feed.pending.find((candidate) => candidate.id === String(item.id));
    state.feed = reconcileFeed(state.feed, { id: item.id, status: "timed_out" });
    const pending = state.feed.pending.find((candidate) => candidate.id === String(item.id));
    if (pending && routeInfo().name === "adventures") updatePendingCard(previous, pending);
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
      if (next.status === "rendering") {
        state.currentMoment = momentView(next);
        updateDetailPending(state.currentMoment);
        return;
      }
      renderDetail(next);
      if (next.status === "published") announce("专属瞬间已经画好了。");
    },
  }).then((next) => {
    if (next.status !== "timed_out" || routeInfo().name !== "moment" || routeInfo().id !== String(moment.id)) return;
    state.currentMoment = momentView({ ...moment, status: "rendering", pollError: true });
    detailPending(state.currentMoment, { focus: false });
    announce("生成还在继续，可以稍后重试查看。");
  }).catch((error) => {
    if (error.name !== "AbortError") renderError("暂时看不到生成进度", "返回奇遇页后可以继续查看。");
  }).finally(() => state.pollControllers.delete(key));
}

async function loadWorld(signal, version) {
  const world = await childApi.world({ signal });
  if (version !== state.routeVersion) return null;
  applyWorld(world);
  return world;
}

async function route() {
  state.showingWelcome = false;
  const current = routeInfo();
  const pendingPocketMutation = current.name === "pocket"
    ? state.pocketMutation?.completion
    : null;
  const version = ++state.routeVersion;
  state.routeController?.abort();
  clearWorldRefresh();
  stopPollers();
  state.pocketMutation = null;
  state.pocketBusy = false;
  state.routeController = new AbortController();
  const { signal } = state.routeController;
  updateNavigation(current);
  renderLoading(current.name === "pocket" ? "正在打开口袋" : current.name === "adventures" ? "正在打开奇遇" : "正在看看灵灵在做什么");

  const backgroundWorld = current.name === "now"
    ? null
    : loadWorld(signal, version).catch((error) => {
      if (error.name !== "AbortError") return null;
      throw error;
    });

  try {
    if (current.name === "now") {
      const world = await loadWorld(signal, version);
      if (!world || version !== state.routeVersion) return;
      renderNow(world);
      scheduleWorldRefresh(world, version);
    } else if (current.name === "adventures") {
      const feed = feedView(await childApi.feed({ signal }));
      if (version !== state.routeVersion) return;
      await backgroundWorld;
      if (version !== state.routeVersion) return;
      renderFeed(feed);
      startFeedPolls(feed);
    } else if (current.name === "pocket") {
      const payload = await loadPocketAfterMutation(childApi, pendingPocketMutation, { signal });
      if (version !== state.routeVersion) return;
      await backgroundWorld;
      if (version !== state.routeVersion) return;
      renderPocket(Array.isArray(payload.items) ? payload.items : []);
    } else {
      const moment = await childApi.moment(current.id, { signal });
      if (version !== state.routeVersion) return;
      await backgroundWorld;
      if (version !== state.routeVersion) return;
      renderDetail(moment);
      if (moment.status === "rendering") startDetailPoll(moment);
    }
  } catch (error) {
    if (error.name === "AbortError" || version !== state.routeVersion) return;
    renderError("暂时打不开这里", error.message || "请稍后再试一次。");
  }
}

function enterWorld() {
  rememberWelcome();
  state.showingWelcome = false;
  navigation.hidden = false;
  route();
}

function toggleWorldSound(button) {
  const video = view.querySelector("[data-world-video]");
  if (!video) return;

  state.soundEnabled = video.muted;
  video.muted = !state.soundEnabled;
  button.setAttribute("aria-pressed", String(state.soundEnabled));
  button.setAttribute("aria-label", state.soundEnabled ? "关闭世界声音" : "打开世界声音");
  button.classList.toggle("is-on", state.soundEnabled);
  if (state.soundEnabled) video.play().catch(() => {});
  announce(state.soundEnabled ? "世界声音已打开。" : "世界声音已关闭。");
}

async function togglePocket() {
  const item = state.currentMoment;
  const keepsake = item?.keepsake;
  if (!keepsake || state.pocketBusy) return;

  const desired = !Boolean(keepsake.collected);
  let resolveCompletion;
  const mutation = {
    token: `${item.id}:${keepsake.id}:${state.routeVersion}`,
    momentId: item.id,
    routeVersion: state.routeVersion,
    completion: new Promise((resolve) => {
      resolveCompletion = resolve;
    }),
  };
  state.pocketMutation = mutation;
  const originalMoment = state.currentMoment;
  const baseItems = state.pocketItems || [];
  const change = beginPocketChange(baseItems, keepsake, desired);
  state.currentMoment = momentView({ ...item, keepsake: { ...keepsake, collected: desired } });
  state.pocketBusy = true;
  renderDetail(state.currentMoment, { focus: false });

  try {
    const response = await childApi.setCollected(keepsake.id, desired);
    const current = {
      token: state.pocketMutation?.token,
      momentId: state.currentMoment?.id,
      routeVersion: state.routeVersion,
      routeName: routeInfo().name,
    };
    if (!isPocketMutationCurrent(mutation, current)) return;
    const settled = { ok: true, ...response };
    const finalCollected = Boolean(settled.collected ?? desired);
    state.pocketItems = finishPocketChange(change, settled);
    state.currentMoment = momentView({
      ...state.currentMoment,
      keepsake: { ...state.currentMoment.keepsake, collected: finalCollected },
    });
    announce(finalCollected ? "已经收进口袋。" : "已经移出口袋。");
  } catch {
    const current = {
      token: state.pocketMutation?.token,
      momentId: state.currentMoment?.id,
      routeVersion: state.routeVersion,
      routeName: routeInfo().name,
    };
    if (!isPocketMutationCurrent(mutation, current)) return;
    state.pocketItems = finishPocketChange(change, { ok: false });
    state.currentMoment = originalMoment;
    announce("刚才没有收好，已经恢复原来的状态。");
  } finally {
    resolveCompletion();
    if (state.pocketMutation?.token !== mutation.token) return;
    const shouldRender = isPocketMutationCurrent(mutation, {
      token: state.pocketMutation.token,
      momentId: state.currentMoment?.id,
      routeVersion: state.routeVersion,
      routeName: routeInfo().name,
    });
    state.pocketBusy = false;
    state.pocketMutation = null;
    if (shouldRender) renderDetail(state.currentMoment, { focus: false });
  }
}

view.addEventListener("click", (event) => {
  const action = event.target.closest("[data-action]");
  if (!action) return;

  if (action.dataset.action === "retry-binding-camera") {
    stopBindingScanner();
    startBindingCamera(state.bindingVersion);
  }
  if (action.dataset.action === "restart-binding") renderBindingScan();
  if (action.dataset.action === "enter-world") enterWorld();
  if (action.dataset.action === "toggle-sound") toggleWorldSound(action);
  if (action.dataset.action === "meet-ling") {
    const message = "灵灵在等你回到它身边。";
    showToast(message);
    announce(message);
  }
  if (action.dataset.action === "retry-route") route();
  if (action.dataset.action === "retry-poll") {
    const pending = state.feed?.pending.find((item) => item.id === action.dataset.id);
    if (pending) {
      const retrying = { ...pending, pollError: false, pollState: "rendering" };
      state.feed = {
        ...state.feed,
        pending: state.feed.pending.map((item) => item.id === retrying.id ? retrying : item),
      };
      updatePendingCard(pending, retrying);
      startFeedPoll(retrying);
    }
  }
  if (action.dataset.action === "retry-detail-poll" && state.currentMoment) {
    state.currentMoment = momentView({ ...state.currentMoment, status: "rendering", pollError: false });
    detailPending(state.currentMoment, { focus: false });
    startDetailPoll(state.currentMoment);
  }
  if (action.dataset.action === "toggle-pocket") togglePocket();
});

view.addEventListener("submit", (event) => {
  const form = event.target.closest("[data-binding-code-form]");
  if (!form) return;
  event.preventDefault();
  submitChildBinding(new FormData(form).get("qr-token"));
});

view.addEventListener("error", (event) => {
  const target = event.target.tagName === "SOURCE" ? event.target.parentElement : event.target;
  if (!(target instanceof HTMLMediaElement) && !(target instanceof HTMLImageElement)) return;

  const worldLayer = target.closest(".world-media-layer");
  if (worldLayer) {
    worldLayer.innerHTML = '<div class="world-media-fallback">灵灵正在把今天的风收好</div>';
    announce("这段世界画面暂时无法播放。");
    return;
  }

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

window.addEventListener("hashchange", () => {
  if (!state.showingWelcome && !state.bindingGate) route();
});
window.addEventListener("pagehide", () => {
  stopBindingRuntime();
  clearWorldRefresh();
  stopPollers();
  if (state.toastTimer !== null) window.clearTimeout(state.toastTimer);
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js", { scope: "/child/" }).catch(() => {});
}

if (!window.location.hash) {
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#now`);
}
beginBindingGate();
