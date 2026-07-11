import { createParentApi } from "./api.mjs";
import {
  PARENT_TABS,
  createTabStore,
  displayableConversationSuggestion,
  guardianViewModel,
  growthViewModel,
  memoryViewModel,
  mergeMemoryViewModels,
  rightsDialogModel,
  setTabError,
  setTabLoading,
  setTabSuccess,
  todayViewModel,
} from "./model.mjs";

const WELCOME_KEY = "ling-parent-welcome-v1";
const BINDING_KEY = "ling-parent-binding-v1";
const INSTALLATION_KEY = "ling-parent-installation-v1";
const api = createParentApi();
const appShell = document.querySelector("#app-shell");
const welcomeView = document.querySelector("#welcome-view");
const startButton = document.querySelector("#start-app");
const bindingPanel = document.querySelector("#parent-binding");
const bindingSuccess = document.querySelector("#binding-success");
const bindingStatus = document.querySelector("#binding-status");
const bindingScanButton = document.querySelector("#scan-binding-code");
const bindingCodeForm = document.querySelector("#binding-code-form");
const bindingCodeInput = document.querySelector("#binding-code");
const bindingCamera = document.querySelector("#binding-camera");
const bindingVideo = document.querySelector("#binding-video");
const tabButtons = new Map(
  [...document.querySelectorAll('[role="tab"][data-tab]')].map((button) => [button.dataset.tab, button]),
);
const panels = new Map(
  PARENT_TABS.map((tab) => [tab, document.querySelector(`#panel-${tab}`)]),
);
const announcer = document.querySelector("#status-announcer");
const rightsDialog = document.querySelector("#rights-dialog");
const rightsTitle = document.querySelector("#rights-title");
const rightsBody = document.querySelector("#rights-body");
const rightsNotice = document.querySelector("#rights-notice");
const boundaryDialog = document.querySelector("#boundary-dialog");
const boundaryList = document.querySelector("#boundary-list");

const viewModels = {
  today: todayViewModel,
  growth: growthViewModel,
  memory: memoryViewModel,
  guardian: guardianViewModel,
};

let tabStore = createTabStore();
let activeTab = "today";
let dialogTrigger = null;
let latestRedLines = [];
let memoryPageLoading = false;
let memoryPageError = "";
const controllers = new Map();
let bindingStream = null;
let bindingScanFrame = null;
let bindingSubmitting = false;

function element(tag, { className = "", text = "", attributes = {} } = {}, children = []) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  for (const [name, value] of Object.entries(attributes)) {
    if (value !== undefined && value !== null) node.setAttribute(name, String(value));
  }
  for (const child of children.flat()) {
    if (child) node.append(child);
  }
  return node;
}

function announce(message) {
  announcer.textContent = "";
  window.requestAnimationFrame(() => {
    announcer.textContent = message;
  });
}

function pageHeader(title, subtitle = "") {
  return element("header", { className: "page-header" }, [
    element("h2", { text: title }),
    subtitle ? element("p", { text: subtitle }) : null,
  ]);
}

function sectionHeading(title, icon, copy = "") {
  return element("div", { className: "section-title" }, [
    element("span", { className: `section-icon ${icon}`, attributes: { "aria-hidden": "true" } }),
    element("div", {}, [
      element("h3", { text: title }),
      copy ? element("p", { text: copy }) : null,
    ]),
  ]);
}

function contentSection(title, children = [], className = "content-section", icon = "") {
  const section = element("section", { className });
  if (title) section.append(sectionHeading(title, icon));
  section.append(...children.filter(Boolean));
  return section;
}

function emptyState(title, copy) {
  return element("section", { className: "empty-state" }, [
    element("span", { className: "empty-light", attributes: { "aria-hidden": "true" } }),
    element("h3", { text: title }),
    element("p", { text: copy }),
  ]);
}

function formatDateLabel(value) {
  if (!value) return "今天";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(parsed);
}

function formatMomentTime(value) {
  if (!value) return "时间未标注";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function renderLoading(panel, tab) {
  panel.replaceChildren(
    pageHeader(tabButtons.get(tab).textContent),
    element("p", { className: "sr-only", text: `${tabButtons.get(tab).textContent}正在加载` }),
    element("div", { className: "skeleton-stack", attributes: { "aria-hidden": "true" } }, [
      element("div", { className: "skeleton skeleton-hero" }),
      element("div", { className: "skeleton" }),
      element("div", { className: "skeleton" }),
    ]),
  );
}

function renderError(panel, tab, message) {
  panel.replaceChildren(
    pageHeader(tabButtons.get(tab).textContent),
    element("section", { className: "state-card", attributes: { role: "alert" } }, [
      element("span", { className: "state-light", attributes: { "aria-hidden": "true" } }),
      element("h3", { text: "暂时没有加载出来" }),
      element("p", { text: message || "请稍后再试。" }),
      element("button", {
        className: "secondary-button",
        text: "重新加载",
        attributes: { type: "button", "data-retry": tab },
      }),
    ]),
  );
}

function todayScene() {
  return element("div", { className: "today-scene", attributes: { "aria-hidden": "true" } }, [
    element("span", { className: "scene-cloud cloud-left" }),
    element("span", { className: "scene-cloud cloud-right" }),
    element("span", { className: "scene-hill hill-back" }),
    element("span", { className: "scene-hill hill-front" }),
    element("span", { className: "scene-kite" }),
    element("span", { className: "kite-tail" }),
  ]);
}

function safeConversationSuggestion(model) {
  return displayableConversationSuggestion(model);
}

function renderToday(panel, model) {
  const hasActivity = model.hasActivity === true;
  const calm = !model.attention;
  const childName = model.childName === "孩子" ? "她" : model.childName;
  const suggestion = safeConversationSuggestion(model);
  const summary = hasActivity
    ? `${childName}和${model.dollName}今天有了新的共同经历。`
    : "今天还没有新的共同经历。";

  panel.replaceChildren(
    pageHeader("今日", formatDateLabel(model.date)),
    todayScene(),
    element("section", { className: `today-conclusion${calm ? " calm" : " attention"}` }, [
      element("span", { className: "conclusion-mark", attributes: { "aria-hidden": "true" } }),
      element("h3", { text: calm ? (hasActivity ? "今天很安稳" : "今天还很安静") : "有一件事值得留意" }),
      element("p", { text: model.attention?.summary || summary }),
    ]),
    contentSection("今晚可以聊什么", [
      suggestion
        ? element("div", { className: "conversation-card" }, [
            element("span", { className: "conversation-blocks", attributes: { "aria-hidden": "true" } }),
            element("p", { text: suggestion }),
          ])
        : element("div", { className: "conversation-empty" }, [
            element("p", { text: "今天没有新的建议" }),
          ]),
      element("p", {
        className: "today-meta",
        text: hasActivity ? "今天有新的共同经历" : "今天没有待处理事项",
      }),
    ], "conversation-section", "talk"),
  );
}

function firstGrowthStory(model) {
  return model.growthMoments.find((story) => story.before && story.after) || null;
}

function wordGrowthCopy(model) {
  const word = model.words.find((item) => item.text.toLowerCase() === "kite")
    || model.words.find((item) => item.level === "produced")
    || model.words[0];
  if (!word) return "新的生活词会在自然相处里慢慢出现，不需要额外测试。";
  if (word.level === "produced") return `从听懂 ${word.text}，到相处时自然说出来`;
  if (word.level === "recognized") return `从第一次听到 ${word.text}，到现在已经能听懂`;
  return `最近在生活里第一次遇见 ${word.text}`;
}

function renderGrowth(panel, model) {
  const story = firstGrowthStory(model);
  panel.replaceChildren(
    pageHeader("成长", model.periodLabel),
    contentSection("最近的变化", [
      story
        ? element("article", { className: "growth-story" }, [
            element("div", { className: "growth-row before" }, [
              element("span", { className: "growth-object lamp-object", attributes: { "aria-hidden": "true" } }),
              element("div", {}, [
                element("b", { text: "以前" }),
                element("p", { text: story.before }),
              ]),
            ]),
            element("div", { className: "story-divider", attributes: { "aria-hidden": "true" } }),
            element("div", { className: "growth-row now" }, [
              element("span", { className: "growth-object dinosaur-object", attributes: { "aria-hidden": "true" } }),
              element("div", {}, [
                element("b", { text: "现在" }),
                element("p", { text: story.after }),
              ]),
            ]),
            element("p", { className: "evidence-line", text: "来自已记录的「以前 / 现在」变化" }),
          ])
        : emptyState("还没有新的变化", "这周还没有形成可确认的「以前 / 现在」变化。"),
      element("article", { className: "word-growth" }, [
        element("span", { className: "mini-kite", attributes: { "aria-hidden": "true" } }),
        element("div", {}, [
          element("b", { text: "生活里的英语" }),
          element("p", { text: wordGrowthCopy(model) }),
        ]),
      ]),
      model.retreat
        ? element("p", { className: "quiet-note", text: `${model.retreat.summary} ${model.retreat.explanation}` })
        : null,
    ], "growth-section", "leaf"),
  );
}

function renderMemoryItem(item) {
  const article = element("article", {
    className: "memory-entry",
    attributes: { "data-projection-id": item.id || "" },
  }, [
    element("div", { className: `memory-symbol ${item.kind}`, attributes: { "aria-hidden": "true" } }),
    element("div", { className: "memory-copy" }, [
      element("div", { className: "timeline-meta" }, [
        element("span", { className: `memory-label ${item.kind}`, text: item.label || "共同经历" }),
        element("time", {
          text: formatMomentTime(item.occurredAt),
          attributes: item.occurredAt ? { datetime: item.occurredAt } : {},
        }),
      ]),
      item.title ? element("h3", { text: item.title }) : null,
      item.summary ? element("p", { text: item.summary }) : null,
    ]),
  ]);

  if (item.transition) {
    article.querySelector(".memory-copy").append(element("div", { className: "growth-transition" }, [
      item.transition.before ? element("span", { text: item.transition.before }) : null,
      item.transition.after ? element("span", { text: item.transition.after }) : null,
    ]));
  }
  if (item.childChoice || item.keepsake) {
    article.querySelector(".memory-copy").append(element("div", { className: "choice-card" }, [
      item.childChoice ? element("p", {}, [
        element("span", { text: item.childChoice.label }),
        element("b", { text: item.childChoice.value }),
      ]) : null,
      item.keepsake ? element("p", {}, [
        element("span", { text: "共同信物" }),
        element("b", { text: item.keepsake.label || "未命名信物" }),
      ]) : null,
    ]));
  }
  return element("li", {}, [article]);
}

function actionRow(label, value, action, className = "") {
  return element("button", {
    className: `action-row ${className}`.trim(),
    attributes: { type: "button", [action]: "true" },
  }, [
    element("span", { text: label }),
    element("span", { className: "action-value", text: value }),
    element("span", { className: "chevron", text: "›", attributes: { "aria-hidden": "true" } }),
  ]);
}

function renderMemory(panel, model) {
  latestRedLines = model.redLines;
  const content = [pageHeader("记忆", "共同经历会被整理，而不是逐字保存")];
  if (model.items.length) {
    content.push(element("ol", { className: "timeline", attributes: { "aria-label": "共同经历时间线" } },
      model.items.map(renderMemoryItem),
    ));
  } else {
    content.push(emptyState("还没有记忆片段", "共同经历会在相处结束后整理到这里。"));
  }

  if (model.nextCursor) {
    content.push(element("div", { className: "memory-pagination" }, [
      element("p", {
        className: "memory-more-status",
        text: memoryPageLoading ? "正在读取更早记忆" : "还有更早记忆",
        attributes: { "aria-live": "polite" },
      }),
      element("button", {
        className: "secondary-button memory-more-button",
        text: memoryPageLoading ? "正在加载…" : "加载更早记忆",
        attributes: {
          type: "button",
          "data-load-more-memory": "true",
          disabled: memoryPageLoading ? "" : null,
          "aria-busy": memoryPageLoading ? "true" : "false",
        },
      }),
      memoryPageError
        ? element("p", { className: "memory-page-error", text: memoryPageError, attributes: { role: "alert" } })
        : null,
    ]));
  }

  content.push(contentSection("关系与数据边界", [
    element("div", { className: "settings-list light-settings" }, [
      actionRow("红线话题", model.redLines.length ? `${model.redLines.length} 项` : "未设置", "data-open-boundaries"),
      actionRow("数据权利", model.rights.statusNote || "导出与注销说明", "data-open-rights"),
    ]),
    element("p", { className: "boundary-note", text: model.redLineExplanation }),
  ], "memory-boundaries", "shield"));
  panel.replaceChildren(...content);
}

function timeValue(start, end) {
  if (!start && !end) return "未设置";
  return [start, end].filter(Boolean).join("–");
}

function staticRow(label, value, className = "") {
  return element("div", { className: `setting-row ${className}`.trim() }, [
    element("span", { text: label }),
    element("strong", { text: value }),
  ]);
}

function guardianTimeRows(model) {
  const details = model.windowDetails || [];
  const bedtimeWindow = details.find((window) => /睡前|夜灯/.test(window.label));
  const availableWindow = details.find((window) => window !== bedtimeWindow) || details[0];
  return [
    staticRow("可用时段", availableWindow ? timeValue(availableWindow.start, availableWindow.end) : "未设置"),
    staticRow("睡前时段", bedtimeWindow
      ? timeValue(bedtimeWindow.start, bedtimeWindow.end)
      : model.bedtime ? `${model.bedtime} 前` : "未设置"),
    staticRow("每日相处", model.dailyLimitMinutes ? `最多 ${model.dailyLimitMinutes} 分钟` : model.dailyLimit),
  ];
}

function renderGuardian(panel, model) {
  latestRedLines = model.redLines;
  panel.replaceChildren(
    element("header", { className: "page-header guardian-header" }, [
      element("div", {}, [
        element("h2", { text: "守护" }),
        element("p", { text: "这些边界在相处之外生效" }),
      ]),
      element("span", { className: "device-status", text: model.device.status }),
    ]),
    contentSection("相处时间", [
      element("div", { className: "settings-list" }, guardianTimeRows(model)),
    ], "guardian-group", "time"),
    contentSection("关系边界", [
      element("div", { className: "settings-list" }, [
        actionRow("红线话题", model.redLines.length ? `${model.redLines.length} 项` : "未设置", "data-open-boundaries"),
        staticRow("AI 身份", model.aiIdentity.message, "identity-row"),
      ]),
    ], "guardian-group", "heart"),
    contentSection("数据权利", [
      element("div", { className: "settings-list" }, [
        actionRow("导出共同经历", "流程说明", "data-open-rights"),
        actionRow("账户注销与彻底销毁", "", "data-open-rights", "destructive-row"),
      ]),
    ], "guardian-group", "data"),
    ...(model.notifications.length ? [contentSection("提醒偏好", [
      element("div", { className: "settings-list" },
        model.notifications.map((notification) => staticRow(notification.label, notification.value, "notification-row")),
      ),
    ], "guardian-group", "bell")] : []),
    element("p", { className: "night-note" }, [
      element("span", { className: "tiny-lamp", attributes: { "aria-hidden": "true" } }),
      element("span", { text: "睡前时段会自然变慢、变暗、变安静" }),
    ]),
    element("button", {
      className: "welcome-replay",
      text: "重新查看欢迎设置",
      attributes: { type: "button", "data-show-welcome": "true" },
    }),
  );
}

const renderers = {
  today: renderToday,
  growth: renderGrowth,
  memory: renderMemory,
  guardian: renderGuardian,
};

function renderTab(tab) {
  const panel = panels.get(tab);
  const state = tabStore[tab];
  if (state.status === "loading") {
    panel.setAttribute("aria-busy", "true");
    renderLoading(panel, tab);
    return;
  }
  panel.removeAttribute("aria-busy");
  if (state.status === "error") {
    renderError(panel, tab, state.error);
    return;
  }
  if (state.status === "ready") renderers[tab](panel, state.data);
}

async function loadTab(tab, { force = false } = {}) {
  const current = tabStore[tab];
  if (!force && ["loading", "ready"].includes(current.status)) return;

  if (tab === "memory" && force) {
    controllers.get("memory-page")?.abort();
    memoryPageLoading = false;
    memoryPageError = "";
  }

  controllers.get(tab)?.abort();
  const controller = new AbortController();
  controllers.set(tab, controller);
  tabStore = setTabLoading(tabStore, tab);
  renderTab(tab);
  announce(`${tabButtons.get(tab).textContent}正在加载`);

  try {
    const payload = await api.load(tab, { signal: controller.signal });
    const model = viewModels[tab](payload);
    tabStore = setTabSuccess(tabStore, tab, model);
    renderTab(tab);
    announce(`${tabButtons.get(tab).textContent}已更新`);
  } catch (error) {
    if (error?.name === "AbortError") return;
    tabStore = setTabError(tabStore, tab, error);
    renderTab(tab);
    announce(`${tabButtons.get(tab).textContent}加载失败`);
  } finally {
    if (controllers.get(tab) === controller) controllers.delete(tab);
  }
}

async function loadMoreMemory() {
  const current = tabStore.memory;
  const cursor = current.data?.nextCursor;
  if (memoryPageLoading || current.status !== "ready" || !cursor) return;

  controllers.get("memory-page")?.abort();
  const controller = new AbortController();
  controllers.set("memory-page", controller);
  memoryPageLoading = true;
  memoryPageError = "";
  renderTab("memory");

  try {
    const payload = await api.load("memory", { signal: controller.signal, cursor });
    const nextPage = memoryViewModel(payload);
    const merged = mergeMemoryViewModels(current.data, nextPage);
    const newItemCount = merged.items.length - current.data.items.length;
    tabStore = setTabSuccess(tabStore, "memory", merged);
    announce(newItemCount ? `已加载 ${newItemCount} 条更早记忆` : "没有更多可显示的记忆");
  } catch (error) {
    if (error?.name === "AbortError") return;
    memoryPageError = error instanceof Error ? error.message : "更早记忆暂时没有加载出来";
    announce("更早记忆加载失败");
  } finally {
    if (controllers.get("memory-page") === controller) controllers.delete("memory-page");
    memoryPageLoading = false;
    if (tabStore.memory.status === "ready") renderTab("memory");
  }
}

function activateTab(tab, { focus = false, updateHash = true } = {}) {
  if (!PARENT_TABS.includes(tab)) return;
  const changed = activeTab !== tab;
  activeTab = tab;
  document.body.classList.toggle("night-mode", tab === "guardian");
  appShell.dataset.activeTab = tab;
  for (const candidate of PARENT_TABS) {
    const selected = candidate === tab;
    const button = tabButtons.get(candidate);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    panels.get(candidate).hidden = !selected;
  }
  if (focus) tabButtons.get(tab).focus();
  if (changed) window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  if (updateHash && window.location.hash !== `#${tab}`) {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${tab}`);
  }
  loadTab(tab);
}

function moveTabFocus(event) {
  const currentIndex = PARENT_TABS.indexOf(event.currentTarget.dataset.tab);
  let nextIndex = currentIndex;
  if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % PARENT_TABS.length;
  else if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + PARENT_TABS.length) % PARENT_TABS.length;
  else if (event.key === "Home") nextIndex = 0;
  else if (event.key === "End") nextIndex = PARENT_TABS.length - 1;
  else return;
  event.preventDefault();
  activateTab(PARENT_TABS[nextIndex], { focus: true });
}

function storageGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Private browsing can deny storage; the current session still proceeds.
  }
}

function storageRemove(key) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // The binding flow still works for the current page without persistent storage.
  }
}

function resetBindingFromQuery() {
  const url = new URL(window.location.href);
  if (url.searchParams.get("binding") !== "reset") return;
  storageRemove(BINDING_KEY);
  storageRemove(WELCOME_KEY);
  url.searchParams.delete("binding");
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

function installationId() {
  const existing = storageGet(INSTALLATION_KEY);
  if (existing) return existing;
  const created = globalThis.crypto?.randomUUID?.()
    || `parent-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  storageSet(INSTALLATION_KEY, created);
  return created;
}

function hasBinding() {
  return storageGet(BINDING_KEY) === "active";
}

function shouldShowWelcome() {
  const forced = new URLSearchParams(window.location.search).get("welcome");
  if (forced === "1") return true;
  if (forced === "0" && hasBinding()) return false;
  return !hasBinding() || storageGet(WELCOME_KEY) !== "complete";
}

function showWelcome() {
  appShell.hidden = true;
  welcomeView.hidden = false;
  document.body.classList.remove("night-mode");
  if (hasBinding()) showBindingSuccess();
}

function showApp() {
  welcomeView.hidden = true;
  appShell.hidden = false;
  document.body.classList.toggle("night-mode", activeTab === "guardian");
}

function completeWelcome() {
  if (!hasBinding()) return;
  storageSet(WELCOME_KEY, "complete");
  const url = new URL(window.location.href);
  url.searchParams.delete("welcome");
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash || `#${activeTab}`}`);
  showApp();
  document.querySelector("#app-main").focus({ preventScroll: true });
  announce("欢迎设置已完成，已进入成长手册");
}

function stopBindingCamera() {
  if (bindingScanFrame !== null) cancelAnimationFrame(bindingScanFrame);
  bindingScanFrame = null;
  bindingStream?.getTracks().forEach((track) => track.stop());
  bindingStream = null;
  bindingVideo.srcObject = null;
  bindingCamera.hidden = true;
}

function showBindingSuccess() {
  stopBindingCamera();
  bindingPanel.hidden = true;
  bindingSuccess.hidden = false;
  startButton.hidden = false;
  bindingStatus.textContent = "已和悠悠绑定";
}

function setBindingBusy(busy) {
  bindingSubmitting = busy;
  bindingScanButton.disabled = busy;
  bindingCodeInput.disabled = busy;
  bindingCodeForm.querySelector("button").disabled = busy;
}

async function submitBindingCode(qrToken) {
  const normalized = String(qrToken || "").trim();
  if (!normalized || bindingSubmitting) return;
  setBindingBusy(true);
  bindingStatus.textContent = "正在确认孩子端";
  try {
    const result = await api.bindParent(normalized, installationId());
    if (result.status !== "active") throw new Error("孩子端还没有准备好，请先让孩子扫码。");
    storageSet(BINDING_KEY, "active");
    showBindingSuccess();
    announce("已和悠悠绑定");
  } catch (error) {
    stopBindingCamera();
    bindingStatus.textContent = error instanceof Error ? error.message : "暂时没有绑定成功，请再试一次。";
    bindingScanButton.hidden = false;
  } finally {
    setBindingBusy(false);
  }
}

async function startBindingCamera() {
  const hasNativeDetector = "BarcodeDetector" in window;
  const hasFallbackDetector = typeof globalThis.jsQR === "function";
  if ((!hasNativeDetector && !hasFallbackDetector) || !navigator.mediaDevices?.getUserMedia) {
    bindingStatus.textContent = "当前浏览器无法打开扫码器，请输入 Demo 码。";
    bindingCodeInput.focus();
    return;
  }
  stopBindingCamera();
  try {
    bindingStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    });
    bindingVideo.srcObject = bindingStream;
    bindingCamera.hidden = false;
    bindingScanButton.hidden = true;
    bindingStatus.textContent = "将二维码放入取景框";
    await bindingVideo.play();
    const detector = hasNativeDetector ? new BarcodeDetector({ formats: ["qr_code"] }) : null;
    const canvas = detector ? null : document.createElement("canvas");
    const context = canvas?.getContext("2d", { willReadFrequently: true });
    const detect = async () => {
      if (!bindingStream || bindingSubmitting) return;
      try {
        let rawValue = "";
        if (detector) {
          const codes = await detector.detect(bindingVideo);
          rawValue = codes[0]?.rawValue || "";
        } else if (context && bindingVideo.videoWidth > 0) {
          const scale = Math.min(1, 640 / bindingVideo.videoWidth);
          canvas.width = Math.max(1, Math.round(bindingVideo.videoWidth * scale));
          canvas.height = Math.max(1, Math.round(bindingVideo.videoHeight * scale));
          context.drawImage(bindingVideo, 0, 0, canvas.width, canvas.height);
          const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
          rawValue = globalThis.jsQR(pixels.data, pixels.width, pixels.height, {
            inversionAttempts: "dontInvert",
          })?.data || "";
        }
        if (rawValue) {
          await submitBindingCode(rawValue);
          return;
        }
      } catch {
        bindingStatus.textContent = "没有识别到二维码，请再对准一次。";
      }
      bindingScanFrame = requestAnimationFrame(detect);
    };
    bindingScanFrame = requestAnimationFrame(detect);
  } catch {
    stopBindingCamera();
    bindingStatus.textContent = "没有打开相机，请输入 Demo 码。";
    bindingScanButton.hidden = false;
    bindingCodeInput.focus();
  }
}

function openDialog(dialog, trigger) {
  dialogTrigger = trigger;
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

function openRightsDialog(trigger) {
  const copy = rightsDialogModel();
  rightsTitle.textContent = copy.title;
  rightsBody.textContent = copy.body;
  rightsNotice.textContent = copy.demoNotice;
  openDialog(rightsDialog, trigger);
}

function openBoundaryDialog(trigger) {
  boundaryList.replaceChildren(...(
    latestRedLines.length
      ? latestRedLines.map((line) => element("span", { text: line }))
      : [element("p", { className: "secondary", text: "当前没有设置红线话题。" })]
  ));
  openDialog(boundaryDialog, trigger);
}

function restoreDialogFocus() {
  dialogTrigger?.focus();
  dialogTrigger = null;
}

for (const [tab, button] of tabButtons) {
  button.addEventListener("click", () => activateTab(tab));
  button.addEventListener("keydown", moveTabFocus);
}

document.querySelector("#app-main").addEventListener("click", (event) => {
  const loadMore = event.target.closest("[data-load-more-memory]");
  if (loadMore) {
    loadMoreMemory();
    return;
  }
  const retry = event.target.closest("[data-retry]");
  if (retry) {
    loadTab(retry.dataset.retry, { force: true });
    return;
  }
  const rights = event.target.closest("[data-open-rights]");
  if (rights) {
    openRightsDialog(rights);
    return;
  }
  const boundaries = event.target.closest("[data-open-boundaries]");
  if (boundaries) {
    openBoundaryDialog(boundaries);
    return;
  }
  if (event.target.closest("[data-show-welcome]")) showWelcome();
});

startButton.addEventListener("click", completeWelcome);
bindingScanButton.addEventListener("click", startBindingCamera);
bindingCodeForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitBindingCode(bindingCodeInput.value);
});
rightsDialog.addEventListener("close", restoreDialogFocus);
boundaryDialog.addEventListener("close", restoreDialogFocus);

window.addEventListener("hashchange", () => {
  const requested = window.location.hash.slice(1);
  if (PARENT_TABS.includes(requested) && requested !== activeTab) {
    activateTab(requested, { updateHash: false });
  }
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopBindingCamera();
});

resetBindingFromQuery();
const requestedTab = window.location.hash.slice(1);
activateTab(PARENT_TABS.includes(requestedTab) ? requestedTab : "today");
if (shouldShowWelcome()) showWelcome();
else showApp();
document.documentElement.classList.add("app-ready");

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/parent/sw.js", { scope: "/parent/" }).catch(() => {});
  }, { once: true });
}
