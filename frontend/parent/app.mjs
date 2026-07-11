import { createParentApi } from "./api.mjs";
import {
  PARENT_TABS,
  createTabStore,
  guardianViewModel,
  growthViewModel,
  memoryViewModel,
  rightsDialogModel,
  setTabError,
  setTabLoading,
  setTabSuccess,
  todayViewModel,
} from "./model.mjs";

const api = createParentApi();
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

const viewModels = {
  today: todayViewModel,
  growth: growthViewModel,
  memory: memoryViewModel,
  guardian: guardianViewModel,
};

let tabStore = createTabStore();
let activeTab = "today";
let rightsTrigger = null;
const controllers = new Map();

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

function viewHeader(title, subtitle, badge = "") {
  const heading = element("div", { className: "view-header" });
  const row = element("div", { className: "section-heading" }, [
    element("h2", { text: title }),
    badge ? element("span", { className: "read-only-badge", text: badge }) : null,
  ]);
  heading.append(row);
  if (subtitle) heading.append(element("p", { className: "view-subtitle", text: subtitle }));
  return heading;
}

function metricGrid(metrics) {
  return element("div", { className: "metric-grid", attributes: { "aria-label": "关键数字" } },
    metrics.map((metric) => element("div", { className: "metric" }, [
      element("strong", { text: metric.display }),
      element("span", { text: metric.label }),
    ])),
  );
}

function contentSection(title, children = [], className = "content-section") {
  const section = element("section", { className });
  if (title) section.append(element("h3", { text: title }));
  section.append(...children.filter(Boolean));
  return section;
}

function emptyCard(title, copy) {
  return element("section", { className: "empty-card" }, [
    element("h3", { text: title }),
    element("p", { className: "empty-copy", text: copy }),
  ]);
}

function infoBand(label, copy) {
  return element("section", { className: "info-band" }, [
    element("strong", { text: label }),
    element("p", { text: copy }),
  ]);
}

function moodSection(mood) {
  return contentSection("心情速览", [
    element("div", { className: "section-heading" }, [
      element("span", { className: "disclaimer", text: mood.disclaimer }),
    ]),
    element("p", {
      className: mood.summary ? "" : "empty-copy",
      text: mood.summary || "今天还没有足够信息形成心情速览。",
    }),
  ]);
}

function renderLoading(panel, tab) {
  const stack = element("div", { className: "skeleton-stack", attributes: { "aria-hidden": "true" } }, [
    element("div", { className: "skeleton" }),
    element("div", { className: "skeleton" }),
    element("div", { className: "skeleton" }),
  ]);
  panel.replaceChildren(
    element("p", { className: "sr-only", text: `${tabButtons.get(tab).textContent}正在加载` }),
    stack,
  );
}

function renderError(panel, tab, message) {
  const retry = element("button", {
    className: "secondary-button",
    text: "重试",
    attributes: { type: "button", "data-retry": tab },
  });
  panel.replaceChildren(element("section", { className: "state-card", attributes: { role: "alert" } }, [
    element("h2", { text: "暂时没有加载出来" }),
    element("p", { className: "state-copy", text: message || "请稍后再试。" }),
    retry,
  ]));
}

function formatDateLabel(value) {
  if (!value) return "";
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

function renderToday(panel, model) {
  const hasMetric = model.metrics.some((metric) => !metric.display.startsWith("-"));
  const hasNarrative = model.mood.summary || model.attention || model.tonight;
  const content = [
    viewHeader(`${model.childName}和${model.dollName}，今天`, formatDateLabel(model.date)),
  ];

  if (!hasMetric && !hasNarrative) {
    content.push(emptyCard("今天还很安静", "完成一次陪伴后，这里会出现可行动的今日速览。"));
  } else {
    content.push(metricGrid(model.metrics));
  }

  content.push(moodSection(model.mood));

  if (model.attention) {
    const attentionChildren = [element("p", { text: model.attention.summary })];
    if (model.attention.conversationPrompt) {
      attentionChildren.push(element("p", {
        className: "attention-prompt",
        text: `今晚可以问问：${model.attention.conversationPrompt}`,
      }));
    }
    content.push(contentSection("值得留意", attentionChildren, "attention-section"));
  }

  if (model.tonight) content.push(infoBand("今晚一起", model.tonight.summary));
  panel.replaceChildren(...content);
}

function renderWords(words) {
  const list = element("ul", { className: "word-list", attributes: { "aria-label": "英语掌握层级" } });
  for (const word of words) {
    list.append(element("li", { className: "word-row" }, [
      element("div", {}, [
        element("b", { text: word.text }),
        word.meaning ? element("span", { className: "secondary", text: word.meaning }) : null,
      ]),
      element("span", { className: `level-badge ${word.level}`, text: word.levelLabel }),
    ]));
  }
  return list;
}

function renderGrowth(panel, model) {
  const content = [
    viewHeader("英语成长", model.periodLabel),
    metricGrid(model.metrics),
  ];
  const hasDetails = model.words.length || model.growthMoments.length || model.nextReview || model.retreat;

  if (!hasDetails) {
    content.push(emptyCard("还没有新的成长记录", "灵灵会在自然对话后更新这里，不需要额外测试孩子。"));
  }

  if (model.words.length) content.push(contentSection("本周接触的词", [renderWords(model.words)]));

  if (model.growthMoments.length) {
    const list = element("ul", { className: "transition-list", attributes: { "aria-label": "成长变化文字摘要" } });
    for (const moment of model.growthMoments) {
      list.append(element("li", {}, [
        moment.before ? element("div", { className: "transition-before", text: `以前：${moment.before}` }) : null,
        moment.after ? element("div", { className: "transition-after", text: `现在：${moment.after}` }) : null,
      ]));
    }
    content.push(contentSection("成长时刻", [list]));
  }

  if (model.nextReview) content.push(infoBand("下次自然出现", model.nextReview));

  if (model.retreat) {
    content.push(contentSection("撤退记录", [
      model.retreat.dateLabel ? element("p", { className: "secondary", text: model.retreat.dateLabel }) : null,
      element("p", { text: model.retreat.summary }),
      element("p", { className: "attention-prompt", text: model.retreat.explanation }),
    ]));
  }
  panel.replaceChildren(...content);
}

function renderMemoryItem(item) {
  const label = item.label || ({ moment: "专属瞬间", attention: "留意", growth: "成长" }[item.kind]);
  const article = element("article", { attributes: { "data-projection-id": item.id || "" } });
  article.append(element("div", { className: "timeline-meta" }, [
    element("span", { className: `memory-label ${item.kind}`, text: label }),
    element("time", { text: formatMomentTime(item.occurredAt), attributes: item.occurredAt ? { datetime: item.occurredAt } : {} }),
  ]));
  if (item.title) article.append(element("h3", { text: item.title }));
  if (item.summary) article.append(element("p", { text: item.summary }));
  if (item.transition) {
    article.append(element("div", { className: "growth-transition", attributes: { "aria-label": "成长前后变化" } }, [
      item.transition.before ? element("div", { className: "transition-before", text: item.transition.before }) : null,
      item.transition.after ? element("div", { className: "transition-after", text: item.transition.after }) : null,
    ]));
  }
  if (item.childChoice || item.keepsake) {
    article.append(element("div", { className: "choice-card", attributes: { "aria-label": "孩子公开选择与信物" } }, [
      item.childChoice ? element("div", { className: "choice-row" }, [
        element("span", { text: item.childChoice.label }),
        element("b", { text: item.childChoice.value }),
      ]) : null,
      item.keepsake ? element("div", { className: "keepsake-row" }, [
        element("span", { text: "信物" }),
        element("b", { text: item.keepsake.label || "未命名信物" }),
        item.keepsake.description ? element("em", { text: item.keepsake.description }) : null,
      ]) : null,
    ]));
  }
  return element("li", {}, [article]);
}

function renderMemory(panel, model) {
  const content = [
    viewHeader("记忆库", "重要共同经历的家长可读时间线"),
  ];

  if (model.items.length) {
    content.push(element("ol", { className: "timeline", attributes: { "aria-label": "统一记忆时间线" } },
      model.items.map(renderMemoryItem),
    ));
  } else {
    content.push(emptyCard("还没有记忆片段", "共同经历会在会话结束后整理成家长可读的时间线。"));
  }

  const boundaryChildren = [element("p", { text: model.redLineExplanation })];
  if (model.redLines.length) {
    boundaryChildren.push(element("div", { className: "red-lines", attributes: { "aria-label": "当前红线话题" } },
      model.redLines.map((line) => element("span", { className: "red-line", text: line })),
    ));
  } else {
    boundaryChildren.push(element("p", { className: "secondary", text: "当前没有设置红线话题。" }));
  }

  const rightsButton = element("button", {
    className: "secondary-button",
    text: "查看说明",
    attributes: { type: "button", "data-open-rights": "true" },
  });
  boundaryChildren.push(element("div", { className: "rights-entry" }, [
    element("div", {}, [
      element("b", { text: "数据权利" }),
      element("p", { text: model.rights.statusNote || "导出与账户注销走独立流程。" }),
    ]),
    rightsButton,
  ]));
  content.push(contentSection("边界", boundaryChildren));
  panel.replaceChildren(...content);
}

function policyList(rows, label) {
  const list = element("ul", { className: "policy-list", attributes: { "aria-label": label } });
  for (const row of rows) {
    list.append(element("li", { className: "policy-row" }, [
      element("b", { text: row.label }),
      element("span", { text: row.value }),
    ]));
  }
  return list;
}

function renderGuardian(panel, model) {
  const content = [viewHeader("守护", "时间、话题、身份与通知", "只读")];
  const hasPolicies = model.windows.length || model.redLines.length || model.notifications.length || model.bedtime;
  if (!hasPolicies) {
    content.push(emptyCard("守护策略还未准备好", "策略可用后会在这里以只读摘要显示。"));
  }

  const timeRows = model.windows.map((window) => ({ label: "可用时段", value: window }));
  timeRows.push({ label: "每日相处", value: model.dailyLimit });
  if (model.bedtime) timeRows.push({ label: "夜间休眠", value: `${model.bedtime} 后休息` });
  content.push(contentSection("时间", [policyList(timeRows, "时间守护策略")]));

  content.push(contentSection("设备", [policyList([{
    label: model.device.label,
    value: model.device.status,
  }], "设备守护状态")]));

  content.push(contentSection("话题红线", [
    element("p", { text: "红线限制未来主动提起，不会删除或改写已经发生的经历。" }),
    model.redLines.length
      ? element("div", { className: "red-lines", attributes: { "aria-label": "红线话题" } },
          model.redLines.map((line) => element("span", { className: "red-line", text: line })))
      : element("p", { className: "secondary", text: "当前没有设置红线话题。" }),
  ]));

  content.push(contentSection("AI 身份说明", [
    element("div", { className: "section-heading" }, [
      element("p", { text: model.aiIdentity.message }),
      model.aiIdentity.fixed ? element("span", { className: "fixed-badge", text: "系统固定" }) : null,
    ]),
  ]));

  if (model.notifications.length) {
    content.push(contentSection("通知偏好", [policyList(model.notifications, "通知策略摘要")]));
  }
  panel.replaceChildren(...content);
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

function activateTab(tab, { focus = false, updateHash = true } = {}) {
  if (!PARENT_TABS.includes(tab)) return;
  activeTab = tab;
  for (const candidate of PARENT_TABS) {
    const selected = candidate === tab;
    const button = tabButtons.get(candidate);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    panels.get(candidate).hidden = !selected;
  }
  if (focus) tabButtons.get(tab).focus();
  if (updateHash && window.location.hash !== `#${tab}`) {
    window.history.replaceState(null, "", `#${tab}`);
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

function openRightsDialog(trigger) {
  const copy = rightsDialogModel();
  rightsTrigger = trigger;
  rightsTitle.textContent = copy.title;
  rightsBody.textContent = copy.body;
  rightsNotice.textContent = copy.demoNotice;
  if (typeof rightsDialog.showModal === "function") rightsDialog.showModal();
  else rightsDialog.setAttribute("open", "");
}

for (const [tab, button] of tabButtons) {
  button.addEventListener("click", () => activateTab(tab));
  button.addEventListener("keydown", moveTabFocus);
}

document.querySelector("#app-main").addEventListener("click", (event) => {
  const retry = event.target.closest("[data-retry]");
  if (retry) {
    loadTab(retry.dataset.retry, { force: true });
    return;
  }
  const rights = event.target.closest("[data-open-rights]");
  if (rights) openRightsDialog(rights);
});

rightsDialog.addEventListener("close", () => {
  rightsTrigger?.focus();
  rightsTrigger = null;
});

window.addEventListener("hashchange", () => {
  const requested = window.location.hash.slice(1);
  if (PARENT_TABS.includes(requested) && requested !== activeTab) {
    activateTab(requested, { updateHash: false });
  }
});

const requestedTab = window.location.hash.slice(1);
activateTab(PARENT_TABS.includes(requestedTab) ? requestedTab : "today");

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/parent/sw.js", { scope: "/parent/" }).catch(() => {});
  }, { once: true });
}
