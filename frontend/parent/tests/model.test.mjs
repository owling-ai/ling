import test from "node:test";
import assert from "node:assert/strict";

import {
  MOOD_DISCLAIMER,
  RED_LINE_EXPLANATION,
  assertProjectionSafe,
  formatMetric,
  guardianViewModel,
  growthViewModel,
  memoryViewModel,
  mergeMemoryViewModels,
  rightsDialogModel,
  createTabStore,
  displayableConversationSuggestion,
  setTabError,
  setTabLoading,
  setTabSuccess,
  todayViewModel,
} from "../model.mjs";

test("formats parent metrics without inventing precision", () => {
  assert.equal(formatMetric(18, "分钟"), "18 分钟");
  assert.equal(formatMetric(0, "个"), "0 个");
  assert.equal(formatMetric(null, "次"), "- 次");
});

test("today mood always carries the mandatory non-diagnostic disclaimer", () => {
  const view = todayViewModel({
    date: "2026-07-11",
    child_display_name: "小柚",
    doll_display_name: "灵灵",
    metrics: { minutes_together: 18, topics_count: 3, new_words_spoken: 1 },
    mood: { summary: "整体放松，讲风筝时话变多了。", disclaimer: "可忽略" },
    attention: null,
    tonight: null,
  });

  assert.equal(view.mood.summary, "整体放松，讲风筝时话变多了。");
  assert.equal(view.mood.disclaimer, MOOD_DISCLAIMER);
  assert.equal(view.metrics[0].display, "18 分钟");
  assert.equal(view.minutesTogether, 18);
  assert.equal(view.topicsCount, 3);
  assert.equal(view.newWordsSpoken, 1);
  assert.equal(view.hasActivity, true);
});

test("today mood empty state still carries the non-diagnostic disclaimer", () => {
  const view = todayViewModel({ mood: null });

  assert.deepEqual(view.mood, {
    summary: "",
    disclaimer: MOOD_DISCLAIMER,
  });
  assert.equal(view.minutesTogether, null);
  assert.equal(view.hasActivity, false);
});

test("today treats explicit zero metrics as an honest quiet state", () => {
  const view = todayViewModel({
    metrics: { minutes_together: 0, topics_count: 0, new_words_spoken: 0 },
    tonight: { summary: "下次可以聊聊月亮。" },
  });

  assert.equal(view.minutesTogether, 0);
  assert.equal(view.topicsCount, 0);
  assert.equal(view.newWordsSpoken, 0);
  assert.equal(view.hasActivity, false);
});

test("conversation suggestion never replaces an unsafe template with invented copy", () => {
  assert.equal(displayableConversationSuggestion({
    attention: { conversationPrompt: "问问孩子 It's so {adj}!" },
    tonight: { summary: "聊聊今天最喜欢的积木。" },
  }), "聊聊今天最喜欢的积木。");
  assert.equal(displayableConversationSuggestion({
    attention: { conversationPrompt: "试试 {topic}" },
    tonight: { summary: "下次说 noun" },
  }), "");
  assert.equal(displayableConversationSuggestion({}), "");
});

test("growth keeps the three controlled language exposure levels", () => {
  const view = growthViewModel({
    period_label: "本周",
    metrics: { spoken_attempts: 9, new_words: 3, mastered_words: 1 },
    words: [
      { text: "seed", meaning: "种子", level: "exposed" },
      { text: "wind", meaning: "风", level: "recognized" },
      { text: "kite", meaning: "风筝", level: "produced" },
    ],
    growth_moments: [],
  });

  assert.deepEqual(view.words.map((word) => word.levelLabel), ["听过", "听懂了", "会说了"]);
  assert.deepEqual(Object.keys(view.levelLabels), ["exposed", "recognized", "produced"]);
  assert.deepEqual(view.growthMoments, []);
});

test("memory preserves an old-to-new growth transition without exposing a deletion target", () => {
  const view = memoryViewModel({
    items: [{
      id: "projection:growth:1",
      occurred_at: "2026-07-11T12:00:00+08:00",
      label: "成长",
      kind: "growth",
      title: "不怕黑了",
      summary: "有恐龙小夜灯就行",
      before: "睡觉要开灯",
      after: "有恐龙小夜灯就行",
    }],
    next_cursor: null,
    boundary_summary: { red_lines: ["恐龙电影"] },
    rights: { export_available: true, deletion_request_available: true },
  });

  assert.deepEqual(view.items[0].transition, {
    before: "以前：睡觉要开灯",
    after: "现在：有恐龙小夜灯就行",
  });
  assert.equal(view.redLineExplanation, RED_LINE_EXPLANATION);
  assert.equal("deleteUrl" in view.items[0], false);
});

test("memory exposes only controlled child choices and keepsakes", () => {
  const view = memoryViewModel({
    items: [{
      id: "projection:moment:2",
      occurred_at: "2026-07-11T20:10:00+08:00",
      kind: "moment",
      title: "给灵灵选了夜灯积木",
      summary: "孩子把月亮积木放到灵灵旁边，当作睡前信号。",
      child_choice: "今天选择月亮积木",
      keepsake: { label: "月亮积木", description: "睡前放在枕边的信物" },
    }],
  });

  assert.deepEqual(view.items[0].childChoice, {
    label: "孩子选择",
    value: "今天选择月亮积木",
  });
  assert.deepEqual(view.items[0].keepsake, {
    label: "月亮积木",
    description: "睡前放在枕边的信物",
  });
  assert.equal("childMessage" in view.items[0], false);
  assert.equal("rawConversation" in view.items[0], false);
});

test("memory keeps pagination state and appends every unique controlled item", () => {
  const current = memoryViewModel({
    items: Array.from({ length: 20 }, (_, index) => ({
      id: `projection:${index}`,
      title: `共同经历 ${index}`,
    })),
    next_cursor: "20",
  });
  const nextPage = memoryViewModel({
    items: [
      { id: "projection:19", title: "重复边界项" },
      { id: "projection:20", title: "更早的共同经历" },
    ],
    next_cursor: null,
  });

  const merged = mergeMemoryViewModels(current, nextPage);

  assert.equal(current.items.length, 20);
  assert.equal(current.nextCursor, "20");
  assert.equal(merged.items.length, 21);
  assert.equal(merged.items[20].title, "更早的共同经历");
  assert.equal(merged.nextCursor, null);
});

test("data-rights copy distinguishes red lines from account closure and offers no fake action", () => {
  const dialog = rightsDialogModel();

  assert.match(dialog.body, /红线只限制未来主动召回/);
  assert.match(dialog.body, /账户注销才是独立的数据销毁流程/);
  assert.match(dialog.demoNotice, /只展示入口和流程说明/);
  assert.deepEqual(Object.keys(dialog).sort(), ["body", "demoNotice", "title"]);
});

test("guardian policy is summarized as read-only display text", () => {
  const view = guardianViewModel({
    availability_windows: [
      { label: "放学后", start: "16:00", end: "19:00" },
      { label: "睡前夜灯", start: "20:00", end: "21:00" },
    ],
    daily_limit_minutes: 40,
    used_today_minutes: 18,
    bedtime: "21:00",
    device: { sleep_switch_label: "玩偶尾巴物理开关", status: "醒着" },
    red_lines: ["恐龙电影", "大伯家的狗"],
    ai_identity: { message: "孵化时与使用中定期说明", fixed: true },
    notifications: {
      sms: "只发安全与设备提醒",
      card: "每晚一条摘要",
      child_push: "每天至多一条，只在放学窗口",
    },
  });

  assert.equal(view.readOnly, true);
  assert.equal(view.windows[0], "放学后 16:00-19:00");
  assert.deepEqual(view.windowDetails[1], {
    label: "睡前夜灯",
    start: "20:00",
    end: "21:00",
  });
  assert.equal(view.dailyLimitMinutes, 40);
  assert.equal(view.usedTodayMinutes, 18);
  assert.equal(view.dailyLimit, "上限 40 分钟，今天已用 18 分钟");
  assert.equal(view.aiIdentity.fixed, true);
  assert.equal(view.notifications.length, 3);
});

test("recursive projection guard normalizes snake_case and camelCase forbidden fields", () => {
  const forbiddenFieldsUnderTest = [
    "transcript",
    "transcripts",
    "quote",
    "quotes",
    "session_id",
    "sessionId",
    "prompt",
    "system_prompt",
    "systemPrompt",
    "provider",
    "provider_response",
    "providerResponse",
    "job",
    "job_id",
    "jobId",
    "successes",
    "exposures",
    "due_date",
    "dueDate",
    "next_review_at",
    "nextReviewAt",
    "private_canon",
    "privateCanon",
    "delete_url",
    "deleteUrl",
    "deletion_target",
    "deletionTarget",
    "fact_id",
    "factId",
    "diary_id",
    "diaryId",
    "raw",
    "raw_text",
    "rawText",
    "raw_conversation",
    "rawConversation",
    "conversation_log",
    "conversationLog",
    "messages",
    "message_log",
    "messageLog",
    "utterance",
    "utterances",
    "child_utterance",
    "childUtterance",
    "assistant_utterance",
    "assistantUtterance",
    "child_message",
    "childMessage",
    "assistant_message",
    "assistantMessage",
    "full_text",
    "fullText",
    "audio_url",
    "audioUrl",
    "video_url",
    "videoUrl",
    "photo_url",
    "photoUrl",
    "image_url",
    "imageUrl",
  ];

  for (const field of forbiddenFieldsUnderTest) {
    assert.throws(
      () => assertProjectionSafe({ safe: [{ nested: { [field]: "secret" } }] }),
      new RegExp(field, "i"),
      `expected ${field} to be rejected`,
    );
  }
});

test("recursive projection guard rejects legacy raw API URLs at any depth", () => {
  for (const path of ["/api/facts", "/api/diary", "/api/mastery", "/api/report", "/api/state"]) {
    assert.throws(
      () => assertProjectionSafe({ nested: [{ href: path }] }),
      /legacy raw API/i,
    );
  }
});

test("recursive projection guard accepts the display-ready parent contract", () => {
  const payload = {
    items: [{ id: "projection:1", title: "教会灵灵 kite", summary: "生成了一个专属瞬间" }],
    rights: { export_available: true, deletion_request_available: true, status_note: "流程说明" },
  };

  assert.equal(assertProjectionSafe(payload), payload);
});

test("tab state transitions stay independent and retry returns only one tab to idle", () => {
  const initial = createTabStore();
  const loading = setTabLoading(initial, "today");
  const failed = setTabError(loading, "today", new Error("暂时不可用"));
  const growthReady = setTabSuccess(failed, "growth", { words: [] });

  assert.equal(growthReady.today.status, "error");
  assert.equal(growthReady.today.error, "暂时不可用");
  assert.equal(growthReady.growth.status, "ready");
  assert.equal(growthReady.memory.status, "idle");
  assert.equal(growthReady.guardian.status, "idle");
});
