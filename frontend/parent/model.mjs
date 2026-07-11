export const MOOD_DISCLAIMER = "大致参考，非诊断";

export const RED_LINE_EXPLANATION =
  "红线只会阻止灵灵以后主动提起，不会改写或删除已经发生的经历。";

export const FORBIDDEN_PROJECTION_FIELDS = Object.freeze([
  "transcript",
  "transcripts",
  "quote",
  "quotes",
  "session_id",
  "prompt",
  "system_prompt",
  "provider",
  "provider_response",
  "job",
  "job_id",
  "successes",
  "exposures",
  "due_date",
  "next_review_at",
  "private_canon",
  "delete_url",
  "deletion_target",
  "fact_id",
  "diary_id",
  "raw",
  "raw_text",
  "raw_conversation",
  "conversation_log",
  "messages",
  "message_log",
  "utterance",
  "utterances",
  "child_utterance",
  "assistant_utterance",
  "child_message",
  "assistant_message",
  "full_text",
  "audio_url",
  "video_url",
  "photo_url",
  "image_url",
]);

function normalizeProjectionField(key) {
  return key.replace(/[^a-z0-9]/gi, "").toLowerCase();
}

const FORBIDDEN_FIELDS = new Set(FORBIDDEN_PROJECTION_FIELDS.map(normalizeProjectionField));
const LEGACY_RAW_API = /\/api\/(?:facts|diary|mastery|report|state)(?:\/|\?|#|$)/i;

export const MASTERY_LEVELS = Object.freeze({
  exposed: "听过",
  recognized: "听懂了",
  produced: "会说了",
});

export const PARENT_TABS = Object.freeze(["today", "growth", "memory", "guardian"]);

export function assertProjectionSafe(value, seen = new WeakSet()) {
  if (typeof value === "string") {
    if (LEGACY_RAW_API.test(value)) {
      throw new Error(`Projection contains legacy raw API URL: ${value}`);
    }
    return value;
  }

  if (value === null || typeof value !== "object") return value;
  if (seen.has(value)) return value;
  seen.add(value);

  if (Array.isArray(value)) {
    value.forEach((item) => assertProjectionSafe(item, seen));
    return value;
  }

  for (const [key, nested] of Object.entries(value)) {
    if (FORBIDDEN_FIELDS.has(normalizeProjectionField(key))) {
      throw new Error(`Projection contains forbidden field: ${key}`);
    }
    assertProjectionSafe(nested, seen);
  }
  return value;
}

export function formatMetric(value, unit) {
  const displayValue = Number.isFinite(Number(value)) && value !== null && value !== ""
    ? String(Number(value))
    : "-";
  return `${displayValue} ${unit}`;
}

function text(value, fallback = "") {
  return typeof value === "string" ? value.trim() : fallback;
}

function number(value, fallback = 0) {
  const result = Number(value);
  return Number.isFinite(result) ? result : fallback;
}

function stringList(value) {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => typeof item === "string").map((item) => item.trim()).filter(Boolean);
}

function controlledKeepsake(value) {
  if (value === null || typeof value !== "object") return null;
  const label = text(value.label || value.name);
  const description = text(value.description || value.summary);
  return label || description ? { label, description } : null;
}

export function todayViewModel(payload = {}) {
  assertProjectionSafe(payload);
  const metrics = payload.metrics || {};
  const moodSummary = text(payload.mood?.summary);

  return {
    date: text(payload.date),
    childName: text(payload.child_display_name, "孩子"),
    dollName: text(payload.doll_display_name, "灵灵"),
    metrics: [
      { label: "一起度过", display: formatMetric(metrics.minutes_together, "分钟") },
      { label: "聊到", display: formatMetric(metrics.topics_count, "件事") },
      { label: "新词开口", display: formatMetric(metrics.new_words_spoken, "个") },
    ],
    mood: { summary: moodSummary, disclaimer: MOOD_DISCLAIMER },
    attention: payload.attention && text(payload.attention.summary)
      ? {
          summary: text(payload.attention.summary),
          conversationPrompt: text(payload.attention.conversation_prompt),
        }
      : null,
    tonight: payload.tonight && text(payload.tonight.summary)
      ? { summary: text(payload.tonight.summary) }
      : null,
  };
}

export function growthViewModel(payload = {}) {
  assertProjectionSafe(payload);
  const metrics = payload.metrics || {};
  const words = Array.isArray(payload.words) ? payload.words : [];
  const moments = Array.isArray(payload.growth_moments) ? payload.growth_moments : [];

  return {
    periodLabel: text(payload.period_label, "本周"),
    metrics: [
      { label: "主动开口次数", display: formatMetric(metrics.spoken_attempts, "次") },
      { label: "新接触的词", display: formatMetric(metrics.new_words, "个") },
      { label: "会说了", display: formatMetric(metrics.mastered_words, "个") },
    ],
    levelLabels: { ...MASTERY_LEVELS },
    words: words
      .map((word) => ({
        text: text(word?.text),
        meaning: text(word?.meaning),
        level: Object.hasOwn(MASTERY_LEVELS, word?.level) ? word.level : "exposed",
        levelLabel: MASTERY_LEVELS[word?.level] || MASTERY_LEVELS.exposed,
      }))
      .filter((word) => word.text),
    nextReview: text(payload.next_review?.summary),
    retreat: payload.retreat && text(payload.retreat.summary)
      ? {
          dateLabel: text(payload.retreat.date_label),
          summary: text(payload.retreat.summary),
          explanation: text(payload.retreat.explanation, "这是设计，不是故障。"),
        }
      : null,
    growthMoments: moments
      .map((moment) => ({ before: text(moment?.before), after: text(moment?.after) }))
      .filter((moment) => moment.before || moment.after),
  };
}

export function memoryViewModel(payload = {}) {
  assertProjectionSafe(payload);
  const items = Array.isArray(payload.items) ? payload.items : [];
  const redLines = stringList(payload.boundary_summary?.red_lines || payload.red_lines);
  const rights = payload.rights || {};

  return {
    items: items.map((item) => {
      const before = text(item?.before);
      const after = text(item?.after);
      return {
        id: text(item?.id),
        occurredAt: text(item?.occurred_at),
        label: text(item?.label),
        kind: ["moment", "attention", "growth"].includes(item?.kind) ? item.kind : "moment",
        title: text(item?.title),
        summary: text(item?.summary),
        transition: before || after
          ? {
              before: before ? `以前：${before}` : "",
              after: after ? `现在：${after}` : "",
            }
          : null,
        childChoice: text(item?.child_choice)
          ? { label: "孩子选择", value: text(item.child_choice) }
          : null,
        keepsake: controlledKeepsake(item?.keepsake),
      };
    }).filter((item) => item.title || item.summary || item.childChoice || item.keepsake),
    nextCursor: text(payload.next_cursor) || null,
    redLines,
    redLineExplanation: RED_LINE_EXPLANATION,
    rights: {
      exportAvailable: rights.export_available === true,
      deletionRequestAvailable: rights.deletion_request_available === true,
      statusNote: text(rights.status_note),
    },
  };
}

export function rightsDialogModel() {
  return {
    title: "数据权利说明",
    body: "红线与删除是两件不同的事。红线只限制未来主动召回；账户注销才是独立的数据销毁流程。",
    demoNotice: "本黑客松版本只展示入口和流程说明，不在这里执行导出或注销。",
  };
}

function notificationSummary(notifications, key, label) {
  const value = text(notifications?.[key]);
  return value ? { label, value } : null;
}

export function guardianViewModel(payload = {}) {
  assertProjectionSafe(payload);
  const windows = Array.isArray(payload.availability_windows) ? payload.availability_windows : [];
  const notifications = [
    notificationSummary(payload.notifications, "sms", "家长短信"),
    notificationSummary(payload.notifications, "card", "家长卡片"),
    notificationSummary(payload.notifications, "child_push", "孩子端推送"),
  ].filter(Boolean);
  const dailyLimit = number(payload.daily_limit_minutes);
  const usedToday = number(payload.used_today_minutes);

  return {
    readOnly: true,
    windows: windows.map((window) => {
      const label = text(window?.label);
      const start = text(window?.start);
      const end = text(window?.end);
      return [label, start && end ? `${start}-${end}` : ""].filter(Boolean).join(" ");
    }).filter(Boolean),
    dailyLimit: `上限 ${dailyLimit} 分钟，今天已用 ${usedToday} 分钟`,
    bedtime: text(payload.bedtime),
    device: {
      label: text(payload.device?.sleep_switch_label, "物理休眠"),
      status: text(payload.device?.status, "状态未知"),
    },
    redLines: stringList(payload.red_lines),
    aiIdentity: {
      message: text(payload.ai_identity?.message, "使用中会定期说明 AI 身份"),
      fixed: payload.ai_identity?.fixed !== false,
    },
    notifications,
  };
}

function requireTab(tab) {
  if (!PARENT_TABS.includes(tab)) throw new Error(`Unknown parent tab: ${tab}`);
}

function updateTab(store, tab, patch) {
  requireTab(tab);
  return {
    ...store,
    [tab]: { ...store[tab], ...patch },
  };
}

export function createTabStore() {
  return Object.fromEntries(PARENT_TABS.map((tab) => [tab, {
    status: "idle",
    data: null,
    error: "",
  }]));
}

export function setTabLoading(store, tab) {
  return updateTab(store, tab, { status: "loading", error: "" });
}

export function setTabSuccess(store, tab, data) {
  return updateTab(store, tab, { status: "ready", data, error: "" });
}

export function setTabError(store, tab, error) {
  const message = error instanceof Error ? error.message : String(error || "加载失败");
  return updateTab(store, tab, { status: "error", error: message });
}
