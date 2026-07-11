import test from "node:test";
import assert from "node:assert/strict";
import * as model from "../model.mjs";

import {
  beginPocketChange,
  childRoute,
  feedView,
  finishPocketChange,
  isPocketMutationCurrent,
  momentView,
  reconcileFeed,
  shouldShowWelcome,
  worldRefreshDelay,
  worldView,
} from "../model.mjs";

const media = {
  kind: "video",
  src: "/demo-media/hill-wind-a.mp4",
  poster: "/demo-media/hill-wind-a.png",
  mime_type: "video/mp4",
  width: 720,
  height: 900,
  duration_ms: 4000,
  alt: "灵灵在山坡上等风",
};

test("day mode keeps the server world event in the block-toy theme", () => {
  const view = worldView({
    mode: "day",
    doll: { name: "灵灵", known_days: 12 },
    event: {
      title: "去山坡等风",
      summary: "灵灵带着积木风筝去等风。",
      timeline: [{ at: "08:30", text: "风筝线绕好了" }],
      media,
    },
    memory_summary: { moments: 8, keepsakes: 3 },
  });

  assert.equal(view.theme, "day");
  assert.equal(view.headline, "去山坡等风");
  assert.equal(view.dollName, "灵灵");
  assert.equal(view.knownDays, 12);
  assert.deepEqual(view.media, media);
  assert.deepEqual(view.timeline, [{ at: "08:30", text: "风筝线绕好了" }]);
});

test("welcome appears once by default and supports deterministic demo overrides", () => {
  assert.equal(shouldShowWelcome("", false), true);
  assert.equal(shouldShowWelcome("", true), false);
  assert.equal(shouldShowWelcome("?welcome=1", true), true);
  assert.equal(shouldShowWelcome("?welcome=0", false), false);
});

test("night mode is selected by server state rather than color preference", () => {
  const view = worldView({
    mode: "night",
    event: { title: "灵灵在数星星", summary: "第七颗星星叫 seven。", media },
  });

  assert.equal(view.theme, "night");
  assert.equal(view.mode, "night");
  assert.equal(view.modeLabel, "夜灯模式");
  assert.equal(view.headline, "灵灵在数星星");
});

test("sleeping mode uses the world-state message", () => {
  const view = worldView({ mode: "sleeping", sleep_message: "灵灵要睡了" });

  assert.equal(view.theme, "night");
  assert.equal(view.headline, "灵灵要睡了");
  assert.equal(view.isSleeping, true);
});

test("public and personal moments have explicit text labels", () => {
  assert.equal(momentView({ id: "public:1", kind: "public" }).kindLabel, "灵灵自己的一天");
  assert.equal(momentView({ id: 9, kind: "personal" }).kindLabel, "专属瞬间，和你有关");
});

test("feed exposes rendering moment ids for polling", () => {
  const feed = feedView({
    items: [{ id: "public:1", kind: "public", status: "published", title: "去山坡等风" }],
    pending: [{ id: 9, kind: "personal", status: "rendering", title: "我学会了新词", poll_after_ms: 700 }],
  });

  assert.deepEqual(feed.pendingIds, ["9"]);
  assert.equal(feed.pending[0].pollAfterMs, 700);
  assert.equal(feed.pending[0].kindLabel, "专属瞬间，正在生成");
});

test("a published poll result replaces its pending card", () => {
  const initial = feedView({
    items: [{ id: "public:1", kind: "public", status: "published", title: "去山坡等风" }],
    pending: [{ id: 9, kind: "personal", status: "rendering", title: "我学会了新词" }],
  });

  const next = reconcileFeed(initial, {
    id: 9,
    kind: "personal",
    status: "published",
    title: "风筝终于飞起来啦",
    story: "小柚教会灵灵 kite。",
    media,
  });

  assert.deepEqual(next.pendingIds, []);
  assert.equal(next.pending.length, 0);
  assert.equal(next.items[0].id, "9");
  assert.equal(next.items[0].title, "风筝终于飞起来啦");
});

test("a failed poll result removes its pending card without publishing it", () => {
  const initial = feedView({
    items: [{ id: "public:1", kind: "public", status: "published" }],
    pending: [{ id: 9, kind: "personal", status: "rendering" }],
  });

  const next = reconcileFeed(initial, { id: 9, kind: "personal", status: "failed" });

  assert.deepEqual(next.pendingIds, []);
  assert.equal(next.pending.length, 0);
  assert.deepEqual(next.items.map((item) => item.id), ["public:1"]);
});

test("a client polling timeout keeps the pending card available for retry", () => {
  const initial = feedView({
    items: [{ id: "public:1", kind: "public", status: "published" }],
    pending: [{ id: 9, kind: "personal", status: "rendering", title: "灵灵正在画" }],
  });

  const next = reconcileFeed(initial, { id: 9, kind: "personal", status: "timed_out" });

  assert.deepEqual(next.pendingIds, ["9"]);
  assert.equal(next.pending[0].status, "rendering");
  assert.equal(next.pending[0].pollError, true);
  assert.deepEqual(next.items.map((item) => item.id), ["public:1"]);
});

test("failed pocket mutation rolls optimistic collection back", () => {
  const keepsake = {
    id: "kite-token",
    name: "风筝牌牌",
    description: "第一次把 kite 说出口",
    appearance: "amber",
    source_moment_id: 9,
  };
  const change = beginPocketChange([], keepsake, true);

  assert.equal(change.items.length, 1);
  assert.equal(change.items[0].collected, true);
  assert.deepEqual(finishPocketChange(change, { ok: false }), []);
});

test("successful uncollect uses the server final state without deleting the keepsake source", () => {
  const keepsake = {
    id: "kite-token",
    name: "风筝牌牌",
    source_moment_id: 9,
    collected: true,
  };
  const change = beginPocketChange([keepsake], keepsake, false);

  assert.deepEqual(change.items, []);
  assert.deepEqual(finishPocketChange(change, { ok: true, collected: false }), []);
  assert.equal(change.keepsake.source_moment_id, 9);
});

test("malformed encoded moment routes fall back safely instead of throwing", () => {
  assert.deepEqual(childRoute("#moment/9"), { name: "moment", id: "9" });
  assert.deepEqual(childRoute("#moment/%E0%A4%A"), { name: "now" });
  assert.deepEqual(childRoute("#something-else"), { name: "now" });
});

test("world refresh delay follows the server transition and avoids an immediate loop", () => {
  const now = Date.parse("2026-07-11T17:59:58.000+08:00");

  assert.equal(worldRefreshDelay("2026-07-11T18:00:00.000+08:00", now), 2000);
  assert.equal(worldRefreshDelay("2026-07-11T17:00:00.000+08:00", now), 1000);
  assert.equal(worldRefreshDelay("not-a-date", now), null);
  assert.equal(worldRefreshDelay(null, now), null);
});

test("pocket mutation results apply only to the same route version and moment", () => {
  const mutation = { token: "m1", momentId: "9", routeVersion: 4 };
  const current = { token: "m1", momentId: "9", routeVersion: 4, routeName: "moment" };

  assert.equal(isPocketMutationCurrent(mutation, current), true);
  assert.equal(isPocketMutationCurrent(mutation, { ...current, routeVersion: 5 }), false);
  assert.equal(isPocketMutationCurrent(mutation, { ...current, momentId: "10" }), false);
  assert.equal(isPocketMutationCurrent(mutation, { ...current, routeName: "pocket" }), false);
  assert.equal(isPocketMutationCurrent(mutation, { ...current, token: "m2" }), false);
});

test("child media URLs allow only demo media and exact child icons", () => {
  const origin = "https://ling.test";
  const { safeMediaUrl } = model;

  assert.equal(typeof safeMediaUrl, "function");

  assert.equal(safeMediaUrl("/demo-media/hill-wind-a.mp4", origin), "/demo-media/hill-wind-a.mp4");
  assert.equal(
    safeMediaUrl("https://ling.test/demo-media/hill-wind-a.png?v=2", origin),
    "/demo-media/hill-wind-a.png?v=2",
  );
  assert.equal(safeMediaUrl("/child/icon-192.png", origin), "/child/icon-192.png");
  assert.equal(safeMediaUrl("/child/icon-512.png", origin), "/child/icon-512.png");

  for (const rejected of [
    "/api/facts",
    "/parent/icon-192.png",
    "/child/app.mjs",
    "/demo-mediaevil/video.mp4",
    "https://elsewhere.test/demo-media/video.mp4",
    "//elsewhere.test/demo-media/video.mp4",
    "data:video/mp4;base64,AAAA",
    "blob:https://ling.test/asset-id",
    "https://user:pass@ling.test/demo-media/video.mp4",
    "/demo-media/%2F..%2Fapi%2Ffacts",
    "/demo-media/%E0%A4%A",
    "http://%",
  ]) {
    assert.equal(safeMediaUrl(rejected, origin), "", `must reject ${rejected}`);
  }
});

test("pending cards change only when a visible field changes", () => {
  const { pendingCardChanged } = model;
  const pending = momentView({
    id: 9,
    kind: "personal",
    status: "rendering",
    title: "灵灵正在画下风筝的故事",
    poll_after_ms: 700,
  });

  assert.equal(typeof pendingCardChanged, "function");
  assert.equal(pendingCardChanged(pending, { ...pending }), false);
  assert.equal(pendingCardChanged(pending, { ...pending, pollAfterMs: 1200 }), false);
  assert.equal(pendingCardChanged(pending, { ...pending, summary: "不会显示的内部变化" }), false);
  assert.equal(pendingCardChanged(pending, { ...pending, title: "画面快完成了" }), true);
  assert.equal(pendingCardChanged(pending, { ...pending, pollError: true }), true);
  assert.equal(pendingCardChanged(pending, { ...pending, kindLabel: "新的可见标签" }), true);
});
