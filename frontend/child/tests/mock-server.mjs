import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = normalize(join(fileURLToPath(new URL(".", import.meta.url)), ".."));
const fixtures = join(root, "tests", "fixtures");
const port = Number(process.env.PORT || 4173);

const mime = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".mp4": "video/mp4",
  ".png": "image/png",
  ".webmanifest": "application/manifest+json",
};

let worldMode = "day";
let generationMode = "pending";
let momentPolls = 0;
let collected = false;

const media = {
  kind: "video",
  src: "/demo-media/world.mp4",
  poster: "/demo-media/world-poster.png",
  mime_type: "video/mp4",
  width: 720,
  height: 900,
  duration_ms: 4000,
  alt: "灵灵带着积木风筝在山坡上等风",
};

function json(response, payload, status = 200) {
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  response.end(JSON.stringify(payload));
}

function serveFile(response, path) {
  if (!existsSync(path) || !statSync(path).isFile()) return false;
  response.writeHead(200, { "Content-Type": mime[extname(path)] || "application/octet-stream" });
  createReadStream(path).pipe(response);
  return true;
}

function publishedMoment() {
  return {
    id: 9,
    kind: "personal",
    status: "published",
    title: "风筝终于飞起来啦",
    summary: "你教它的 kite，它一整天都挂在嘴边。",
    story: "小柚教了灵灵一个新词：kite。风一来，灵灵就喊 kite, fly! 现在它把风筝挂在床头，准备在梦里继续飞。",
    occurred_at: "2026-07-11T08:45:00+08:00",
    with_label: "和小柚一起",
    media,
    keepsake: {
      id: "kite-token",
      name: "风筝牌牌",
      description: "第一次把 kite 说出口",
      appearance: "amber",
      image_url: "/child/icon-192.png",
      source_moment_id: 9,
      collected,
    },
  };
}

const server = createServer((request, response) => {
  const url = new URL(request.url, `http://${request.headers.host}`);

  if (url.pathname === "/__test__/state") {
    worldMode = ["day", "night", "sleeping"].includes(url.searchParams.get("mode"))
      ? url.searchParams.get("mode")
      : "day";
    generationMode = ["pending", "published", "failed"].includes(url.searchParams.get("generation"))
      ? url.searchParams.get("generation")
      : "pending";
    collected = url.searchParams.get("collected") === "true";
    momentPolls = 0;
    return json(response, { worldMode, generationMode, collected });
  }

  if (url.pathname === "/api/child/world/now") {
    const night = worldMode !== "day";
    return json(response, {
      mode: worldMode,
      timezone: "Asia/Shanghai",
      next_transition_at: "2026-07-11T21:00:00+08:00",
      doll: { id: "lingling", name: "灵灵", known_days: 12 },
      event: worldMode === "sleeping" ? null : {
        event_id: night ? "count-stars" : "hill-wind",
        event_version: 1,
        variant_id: night ? "count-stars-a" : "hill-wind-a",
        title: night ? "灵灵还醒着，在数星星" : "在山坡上等一阵风",
        summary: night ? "第七颗星星，它取名叫 seven。" : "灵灵把 kite 举过了头顶，就差一阵风。",
        media,
      },
      sleep_message: worldMode === "sleeping" ? "灵灵要睡了" : null,
      memory_summary: { moments: 9, keepsakes: collected ? 4 : 3 },
    });
  }

  if (url.pathname === "/api/child/feed") {
    const pending = generationMode === "pending"
      ? [{ id: 9, kind: "personal", status: "rendering", title: "灵灵正在画下风筝的故事", poll_after_ms: 120 }]
      : [];
    const personal = generationMode === "published" ? [publishedMoment()] : [];
    return json(response, {
      items: [
        ...personal,
        {
          id: "public:market:1",
          kind: "public",
          status: "published",
          title: "菜市场遇到老乡",
          summary: "灵灵混进蘑菇堆里，差点没被认出来。",
          occurred_at: "2026-07-10T10:20:00+08:00",
          media,
        },
      ],
      pending,
    });
  }

  if (url.pathname === "/api/moments/9") {
    momentPolls += 1;
    if (generationMode === "failed") return json(response, { id: 9, kind: "personal", status: "failed" });
    if (generationMode === "pending" && momentPolls < 2) {
      return json(response, { id: 9, kind: "personal", status: "rendering", title: "灵灵正在画下风筝的故事", poll_after_ms: 120 });
    }
    generationMode = "published";
    return json(response, publishedMoment());
  }

  if (url.pathname === "/api/pocket" && request.method === "GET") {
    return json(response, {
      items: collected ? [{
        id: "kite-token",
        name: "风筝牌牌",
        description: "第一次把 kite 说出口",
        appearance: "amber",
        image_url: "/child/icon-192.png",
        source_moment_id: 9,
        collected_at: "2026-07-11T08:48:00+08:00",
      }] : [],
    });
  }

  if (url.pathname === "/api/pocket/kite-token" && request.method === "PUT") {
    let body = "";
    request.on("data", (chunk) => { body += chunk; });
    request.on("end", () => {
      collected = Boolean(JSON.parse(body || "{}").collected);
      json(response, { id: "kite-token", collected });
    });
    return;
  }

  if (url.pathname === "/demo-media/world.mp4") return serveFile(response, join(fixtures, "world.mp4"));
  if (url.pathname === "/demo-media/world-poster.png") return serveFile(response, join(fixtures, "world-poster.png"));

  if (url.pathname === "/child" || url.pathname === "/child/") {
    return serveFile(response, join(root, "index.html"));
  }
  if (url.pathname.startsWith("/child/")) {
    const relative = normalize(url.pathname.slice("/child/".length));
    if (!relative.startsWith("..")) return serveFile(response, join(root, relative)) || json(response, { detail: "not found" }, 404);
  }

  return json(response, { detail: "not found" }, 404);
});

server.listen(port, "127.0.0.1", () => {
  console.log(`Child mock server listening on http://127.0.0.1:${port}/child`);
});
