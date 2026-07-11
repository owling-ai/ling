const KIND_LABELS = {
  public: "灵灵自己的一天",
  personal: "专属瞬间，和你有关",
};

const idOf = (value) => String(value ?? "");

export function worldView(world = {}) {
  const mode = ["day", "night", "sleeping"].includes(world.mode) ? world.mode : "day";
  const isSleeping = mode === "sleeping";
  const event = world.event || {};

  return {
    mode,
    theme: mode === "day" ? "day" : "night",
    modeLabel: mode === "day" ? "积木日间" : isSleeping ? "休息时间" : "夜灯模式",
    isSleeping,
    headline: isSleeping ? world.sleep_message || "灵灵要睡了" : event.title || "灵灵正在准备今天的奇遇",
    summary: isSleeping
      ? "它睡着后这里也会变安静，明早再来看它。"
      : event.summary || "新的故事还在路上。",
    dollName: world.doll?.name || "灵灵",
    knownDays: Number(world.doll?.known_days || 0),
    media: isSleeping ? null : event.media || null,
    nextTransitionAt: world.next_transition_at || null,
    moments: Number(world.memory_summary?.moments || 0),
    keepsakes: Number(world.memory_summary?.keepsakes || 0),
  };
}

export function momentView(moment = {}) {
  const kind = moment.kind === "personal" ? "personal" : "public";
  const status = moment.status || "published";

  return {
    ...moment,
    id: idOf(moment.id),
    kind,
    status,
    kindLabel: status === "rendering" ? "专属瞬间，正在生成" : KIND_LABELS[kind],
    pollAfterMs: Math.max(250, Number(moment.poll_after_ms || 700)),
    title: moment.title || (status === "rendering" ? "灵灵正在画下这段回忆" : "一段新的奇遇"),
    summary: moment.summary || moment.story || "",
    media: moment.media || null,
    keepsake: moment.keepsake || null,
  };
}

function withPendingIds(feed) {
  return {
    ...feed,
    pendingIds: feed.pending.map((item) => item.id),
  };
}

export function feedView(payload = {}) {
  const items = Array.isArray(payload.items) ? payload.items : [];
  const pending = Array.isArray(payload.pending) ? payload.pending : [];

  return withPendingIds({
    items: items.filter((item) => item.status !== "failed").map(momentView),
    pending: pending.filter((item) => item.status !== "failed").map(momentView),
  });
}

export function reconcileFeed(feed, result = {}) {
  const resultId = idOf(result.id);
  const pending = feed.pending.filter((item) => item.id !== resultId);
  const existingItems = feed.items.filter((item) => item.id !== resultId);

  if (result.status === "published") {
    return withPendingIds({
      items: [momentView(result), ...existingItems],
      pending,
    });
  }

  if (result.status === "rendering") {
    return withPendingIds({
      items: existingItems,
      pending: [momentView(result), ...pending],
    });
  }

  return withPendingIds({ items: existingItems, pending });
}

export function beginPocketChange(items = [], keepsake = {}, collected) {
  const previous = items.map((item) => ({ ...item }));
  const keepsakeId = idOf(keepsake.id);
  const withoutKeepsake = previous.filter((item) => idOf(item.id) !== keepsakeId);
  const nextItems = collected
    ? [{ ...keepsake, id: keepsakeId, collected: true }, ...withoutKeepsake]
    : withoutKeepsake;

  return {
    previous,
    items: nextItems,
    keepsake: { ...keepsake, id: keepsakeId },
    collected: Boolean(collected),
  };
}

export function finishPocketChange(change, response = {}) {
  if (response.ok === false) return change.previous;

  const collected = typeof response.collected === "boolean" ? response.collected : change.collected;
  if (collected === change.collected) return change.items;

  return beginPocketChange(change.previous, change.keepsake, collected).items;
}
