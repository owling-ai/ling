/* 灵 · 前端逻辑：hash 路由 + 六个视图。
   交互内核可切换 Gemini Live / StepFun / Volcengine RTC。 */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const responseJSON = async (response) => {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
};
const api = {
  get: (p) => fetch(`/api${p}`).then(responseJSON),
  post: (p, body) => fetch(`/api${p}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  }).then(responseJSON),
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
// 英文词高亮
const rich = (s) => esc(s).replace(/\b([A-Za-z][A-Za-z' !?.]{1,30})\b/g, '<span class="en">$1</span>');

const FOX = (size = 100) => `
<svg class="fox" width="${size}" height="${size}" viewBox="0 0 120 120" fill="none">
  <ellipse cx="60" cy="112" rx="34" ry="6" fill="rgba(94,66,41,.10)"/>
  <path d="M28 34 L20 8 Q34 12 42 26 Z" fill="#e8703f"/>
  <path d="M92 34 L100 8 Q86 12 78 26 Z" fill="#e8703f"/>
  <path d="M30 32 L25 15 Q34 18 39 27 Z" fill="#5e3a25"/>
  <path d="M90 32 L95 15 Q86 18 81 27 Z" fill="#5e3a25"/>
  <ellipse cx="60" cy="62" rx="38" ry="36" fill="#f5924f"/>
  <path d="M60 98 Q30 96 26 66 Q26 88 40 96 Z" fill="#e8703f"/>
  <ellipse cx="60" cy="76" rx="22" ry="18" fill="#fff4e4"/>
  <circle cx="45" cy="56" r="5" fill="#3d2b1c"/>
  <circle cx="75" cy="56" r="5" fill="#3d2b1c"/>
  <circle cx="46.6" cy="54.4" r="1.7" fill="#fff"/>
  <circle cx="76.6" cy="54.4" r="1.7" fill="#fff"/>
  <path d="M54 70 Q60 76 66 70" stroke="#3d2b1c" stroke-width="2.6" stroke-linecap="round" fill="none"/>
  <ellipse cx="60" cy="66" rx="5" ry="4" fill="#3d2b1c"/>
  <ellipse cx="36" cy="66" rx="5.5" ry="3.5" fill="rgba(232,112,63,.55)"/>
  <ellipse cx="84" cy="66" rx="5.5" ry="3.5" fill="rgba(232,112,63,.55)"/>
</svg>`;

const STAGE_ZH = { new_friend: "刚认识的朋友", good_friend: "好朋友", best_friend: "最好的朋友" };
const LEVEL_ZH = { new: "还没学", exposed: "听到过", recognized: "听懂了", produced: "会说了" };

let STATE = null;
let CHAT = null; // { sessionId, agenda:[], woven:[], produced:[] }

// ---------------------------------------------------------------- 路由

const VIEWS = {};
async function route() {
  const name = (location.hash || "#home").slice(1);
  document.querySelectorAll("#nav a").forEach(a =>
    a.classList.toggle("active", a.dataset.view === name));
  STATE = await api.get("/state");
  const badge = $("#llm-badge");
  const liveProviders = Object.entries(STATE.realtime?.providers || {})
    .filter(([, config]) => config.available)
    .map(([name]) => ({ gemini: "Gemini", stepfun: "StepFun", volcengine: "火山 RTC" })[name] || name);
  badge.textContent = liveProviders.length
    ? `📞 ${liveProviders.join(" + ")}`
    : "😴 未配置实时模型";
  badge.classList.toggle("live", liveProviders.length > 0);
  const view = VIEWS[name] || VIEWS.home;
  $("#view").innerHTML = '<div class="loading">加载中…</div>';
  await view();
}
window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", route);

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

// 冷路径记忆结算的成长卡片。挂到 body（不依赖某个页面），切页了也能弹出来。
function showColdResult(res) {
  const d = res.diary || {};
  const mask = document.createElement("div");
  mask.className = "modal-mask";
  mask.innerHTML = `<div class="modal">
    <h2>🌙 冷路径记忆工人干完活了</h2>
    <div class="sec"><h4>📔 新的一页日记（L2）</h4>
      <div style="background:var(--leaf-soft);border-radius:12px;padding:10px 14px;font-size:14px">${esc(d.summary || "")}</div>
      <div style="margin-top:6px">${(d.topics || []).map(t => `<span class="chip leaf">${esc(t)}</span>`).join("")}
      ${(d.emotions || []).map(t => `<span class="chip coral">${esc(t)}</span>`).join("")}</div>
      ${d.open_loop ? `<div style="font-size:13px;margin-top:6px;color:var(--ink-2)">🪝 明天的记忆钩子：「${esc(d.open_loop)}」</div>` : ""}
    </div>
    ${res.new_facts?.length ? `<div class="sec"><h4>💡 新记住的事实（L3）</h4>
      ${res.new_facts.map(f => `<span class="chip sky">${esc(f)}</span>`).join("")}</div>` : ""}
    ${res.mastery_updates?.length ? `<div class="sec"><h4>🎯 英语掌握度回写（SRS）</h4>
      ${res.mastery_updates.map(m => `<span class="chip ${m.result === 'produced' ? 'leaf' : 'gold'}">${esc(m.word)} → ${LEVEL_ZH[m.result] || m.result}</span>`).join("")}</div>` : ""}
    <div class="sec"><h4>💞 关系</h4>
      <span class="chip violet">${esc(STAGE_ZH[res.relationship?.stage] || "")} · ${res.relationship?.xp ?? 0} XP${res.relationship?.leveled_up ? " · 升级啦！" : ""}</span></div>
    <div style="display:flex;gap:10px;justify-content:flex-end">
      <button onclick="location.hash='parent';this.closest('.modal-mask').remove()">去家长控制台看看</button>
      <button class="primary" onclick="this.closest('.modal-mask').remove()">好耶</button>
    </div>
  </div>`;
  document.body.appendChild(mask);
}

// 结束通话后的冷路径结算：后台跑（写日记/抽事实/回写掌握度），可能慢。
// 不 await、不阻塞界面——孩子/家长可以随便切页面，干完活了照样把成长卡片弹出来通知到。
function runColdPath(sessionId) {
  if (!sessionId) return;
  toast("🌙 正在后台整理今天的记忆…可以先去别处逛逛");
  api.post("/session/end", { session_id: sessionId })
    .then(showColdResult)
    .catch(e => toast("整理记忆出错，稍后再试：" + (e?.message || e)));
}

// ---------------------------------------------------------------- 今天（首页）

VIEWS.home = async () => {
  const [report, world] = await Promise.all([api.get("/report"), api.get("/world")]);
  const child = STATE.child, doll = STATE.doll;
  const agenda = world.agenda ? JSON.parse(world.agenda.review_items_json) : [];
  const hookText = world.agenda?.memory_hook || "";
  $("#view").innerHTML = `
  <div class="hero">
    ${FOX(110)}
    <div>
      <h1>${esc(doll.name || "灵灵")}醒着呢，一直在惦记${esc(child.name || "小朋友")}。</h1>
      <p>它有自己的生活、自己的记忆，也偷偷把要复习的英语藏进了今天的故事里。</p>
      <div class="cta">
        <button class="primary" onclick="location.hash='chat'">🦊 开始今天的聊天</button>
        <button onclick="location.hash='parent'">📖 看看孩子的成长</button>
      </div>
    </div>
  </div>
  <div class="stat-tiles">
    <div class="tile coral"><div class="num">${report.mastery.exposed}/${report.mastery.total}</div><div class="lbl">本单元词已在生活里遇见</div></div>
    <div class="tile leaf"><div class="num">${report.mastery.produced}</div><div class="lbl">孩子已主动说出的词</div></div>
    <div class="tile sky"><div class="num">${report.diary_count}</div><div class="lbl">最近 7 天的记忆日记</div></div>
    <div class="tile violet"><div class="num">${esc(STAGE_ZH[doll.relationship_stage] || "新朋友")}</div><div class="lbl">和${esc(doll.name || "灵灵")}的关系</div></div>
  </div>
  <div class="grid-2">
    <div class="card">
      <h2>🌅 今日议程 <span class="hint">夜间规划器的产出 · 热路径纯 DB 读</span></h2>
      <p style="font-size:13.5px;color:var(--ink-2);margin-bottom:8px">关系记忆线索（纯问候后择机使用）：</p>
      <div style="background:var(--coral-soft);border-radius:12px;padding:10px 16px;font-weight:600;color:var(--coral-deep)">
        「${esc(hookText || "今天还没跑夜间规划器")}」
      </div>
      <p style="font-size:13.5px;color:var(--ink-2);margin:12px 0 6px">要悄悄复习的词（密度上限 3，孩子没兴趣立刻撤退）：</p>
      ${agenda.map(a => `<span class="chip gold">${esc(a.word)} · ${esc(a.zh)}</span>`).join("") || '<span class="chip ghost">无</span>'}
    </div>
    <div class="card">
      <h2>🧠 系统在做什么</h2>
      <div class="flow">
        <div class="step"><b>热路径</b>开场记忆包一次读入，实时对话零记忆延迟</div>
        <div class="step"><b>冷路径</b>会话后异步写日记、抽事实、更新掌握度</div>
        <div class="step"><b>生活时钟</b>每天推进玩偶自己的故事，复习词织进事件</div>
        <div class="step"><b>反思引擎</b>每周产出成长快照和玩偶视角日记</div>
      </div>
    </div>
  </div>`;
};

// ---------------------------------------------------------------- 聊天

VIEWS.chat = async () => {
  const doll = STATE.doll;
  const providers = STATE.realtime?.providers || {};
  const providerLabel = name => ({
    gemini: "Gemini Live", stepfun: "StepFun", volcengine: "火山引擎 RTC",
  })[name] || name;
  const providerButtonLabel = name => ({
    gemini: "Gemini", stepfun: "StepFun", volcengine: "火山 RTC",
  })[name] || name;
  let selectedProvider = localStorage.getItem("ling-realtime-provider") || STATE.realtime?.default_provider || "gemini";
  if (!providers[selectedProvider]?.available) {
    selectedProvider = Object.keys(providers).find(name => providers[name].available) || selectedProvider;
  }
  const selectedConfig = () => providers[selectedProvider] || {};

  if (!STATE.realtime?.available) {
    $("#view").innerHTML = `
    <h1 class="page-title">和${esc(doll.name || "灵灵")}聊天</h1>
    <div class="card" style="text-align:center;padding:40px">
      ${FOX(90)}
      <h2 style="margin-top:14px">玩偶还没醒</h2>
      <p style="color:var(--ink-2);max-width:440px;margin:8px auto 0">
        请配置 Gemini、StepFun，或火山引擎 RTC 的后端凭证，刷新页面后即可通话。</p>
    </div>`;
    return;
  }

  $("#view").innerHTML = `
  <h1 class="page-title">和${esc(doll.name || "灵灵")}打电话</h1>
  <p class="page-sub">网页即玩偶 —— 接通后直接说话，模型回复时开口即可打断。下方会同步显示双向转写。</p>
  <div class="chat-wrap">
    <div class="chat-panel">
      <div class="chat-head">
        ${FOX(52)}
        <div class="who">
          <b>${esc(doll.name || "灵灵")}</b>
          <div>${esc(STAGE_ZH[doll.relationship_stage] || "新朋友")} · 心情：开心 · Lv.${doll.growth_level || 1}</div>
        </div>
        <div class="actions">
          <div class="model-switch" role="group" aria-label="实时语音模型">
            ${["gemini", "stepfun", "volcengine"].map(name => `<button type="button" data-provider="${name}"
              ${providers[name]?.available ? "" : "disabled"}
              title="${providers[name]?.available ? esc(providers[name].model) : `${providerLabel(name)} 未配置后端凭证`}">
              ${providerButtonLabel(name)}</button>`).join("")}
          </div>
          <button id="video-btn" class="video-toggle" type="button" aria-pressed="false" title="开启摄像头">📹</button>
          <button id="call-btn" class="primary" title="连接所选实时模型">📞 接通</button>
          <button id="end-btn" title="挂电话 · 整理今天的记忆 · 看成长" hidden>📞 结束通话</button>
        </div>
      </div>
      <div class="chat-log" id="log"></div>
    </div>
    <div>
      <div class="side-card">
        <h3>🎯 今日编织进度</h3>
        <div id="agenda-box"><span class="chip ghost">开始会话后加载</span></div>
      </div>
      <div class="side-card">
        <h3>💡 试试对它说</h3>
        <div style="font-size:13px;color:var(--ink-2);display:flex;flex-direction:column;gap:7px">
          <span>「起好啦，叫大角！」</span>
          <span>「你今天做了什么呀？」</span>
          <span>「我觉得熊猫最可爱」</span>
          <span>「做橡果味的吧！」</span>
          <span>「我不想说英语」（看撤退规则）</span>
        </div>
      </div>
    </div>
  </div>`;

  const log = $("#log");
  const addMsg = (role, text) => {
    const div = document.createElement("div");
    div.className = "msg" + (role === "user" ? " mine" : "");
    div.innerHTML = `<div class="avatar">${role === "user" ? "🧒" : "🦊"}</div>
      <div><div class="bubble">${role === "user" ? esc(text) : rich(text)}</div></div>`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return $(".bubble", div);   // 转写增量要往里追加
  };

  // 三个上游共用记忆 session；火山使用 ByteRTC，其余使用内部 WebSocket 协议。
  const RT = { on: false, provider: null, ws: null, ctx: null, stream: null, node: null, src: null,
               playHead: 0, sources: [], buf: [], bufLen: 0, bubble: null, text: "", active: null,
               userBubble: null, videoStream: null, videoActive: false, videoEl: null,
               videoCanvas: null, videoTimer: null, rtcEngine: null, rtcInfo: null,
               volcSubtitleBubbles: new Map(), idleTimer: null, idleNudgesSent: 0,
               lastActivityAt: 0, userSpeaking: false, lastVoiceAt: 0 };
  const rtInputRate = () => selectedConfig().input_sample_rate || 24000;
  const rtOutputRate = () => selectedConfig().output_sample_rate || 24000;
  const IDLE_FIRST_MS = 20000, IDLE_NEXT_MS = 45000, IDLE_MAX_NUDGES = 2;
  const LOCAL_SPEECH_RMS = 0.018;
  let manualEnd = false;   // true = 用户主动结束/切页；意外断线（false）才自动重连

  // 进入页面只准备 UI；点击“接通”且拿到麦克风权限后才创建记忆会话和连接上游。
  CHAT = { sessionId: null, agenda: [], woven: [], produced: [] };
  renderAgenda();

  function renderAgenda() {
    if (!CHAT.sessionId) {
      $("#agenda-box").innerHTML = '<span class="chip ghost">接通后加载</span>';
      return;
    }
    $("#agenda-box").innerHTML = CHAT.agenda.filter(a => a.type === "word").map(a => {
      const st = CHAT.produced.includes(a.word) ? "produced" : (CHAT.woven.includes(a.word) ? "woven" : "");
      const stZh = st === "produced" ? "孩子说出来了!" : st === "woven" ? "已自然带出" : "待编织";
      return `<div class="agenda-word"><span class="w">${esc(a.word)}</span>
        <span class="zh">${esc(a.zh)}</span><span class="st ${st}">${stZh}</span></div>`;
    }).join("") || '<span class="chip ghost">今天没有复习议程</span>';
  }

  // 回合记账结果：后端把编织/正典/撤退状态随 ling.state 推回来。
  // ling.state 每回合都来、状态是累计的，所以只在「首次跃迁」时提示一次，别刷屏。
  const notified = { retreated: false, canonCount: 0 };
  const finalize = (res) => {
    CHAT.woven = res.woven || CHAT.woven;
    CHAT.produced = res.produced || CHAT.produced;
    renderAgenda();
    const n = res.canon_written?.length || 0;
    if (n > notified.canonCount) { notified.canonCount = n; toast("✍️ 孩子的决定已写进世界正典！去「灵灵的世界」看看"); }
    if (res.retreated && !notified.retreated) { notified.retreated = true; toast("🛟 撤退规则触发：今天不再复习，纯陪伴模式"); }
  };

  $("#call-btn").onclick = async () => {
    const button = $("#call-btn");
    manualEnd = false;
    button.disabled = true; button.textContent = "正在接通…";
    await startRealtime();
    button.disabled = false; button.textContent = "📞 接通";
    syncCallButtons();
  };

  // 结束通话 → 挂断语音 + 跑冷路径记忆工人。冷路径要调 LLM 写日记/抽事实，可能慢。
  $("#end-btn").onclick = () => {
    if (!CHAT.sessionId) return;
    manualEnd = true;
    endRealtime();
    const sid = CHAT.sessionId;
    CHAT.sessionId = null;
    CHAT.agenda = []; CHAT.woven = []; CHAT.produced = [];
    renderAgenda();
    syncCallButtons();
    runColdPath(sid);
  };

  // ---- 全双工语音：后端负责鉴权、协议转换和记忆注入
  // StepFun 上下行 24kHz；Gemini 上行 16kHz、下行 24kHz；均为 PCM16 单声道 base64。
  const b64FromInt16 = (i16) => {
    const u8 = new Uint8Array(i16.buffer, i16.byteOffset, i16.byteLength);
    let bin = "";
    for (let i = 0; i < u8.length; i += 0x8000)
      bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    return btoa(bin);
  };
  const int16FromB64 = (b64) => {
    const bin = atob(b64);
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return new Int16Array(u8.buffer);
  };
  const resample = (f32, from, to) => {   // 线性插值，ctx 采样率拿不到 24k 时兜底
    if (from === to) return f32;
    const out = new Float32Array(Math.round(f32.length * to / from));
    const step = from / to;
    for (let i = 0; i < out.length; i++) {
      const p = i * step, j = Math.floor(p), a = p - j;
      out[i] = (f32[j] || 0) * (1 - a) + (f32[j + 1] || f32[j] || 0) * a;
    }
    return out;
  };

  const setRtStatus = (msg) => { const el = $("#rt-status"); if (el) el.textContent = msg; };

  function clearIdleTimer() {
    if (RT.idleTimer) clearTimeout(RT.idleTimer);
    RT.idleTimer = null;
  }

  function scheduleIdleNudge() {
    clearIdleTimer();
    if (!RT.on || RT.idleNudgesSent >= IDLE_MAX_NUDGES) return;
    const delay = RT.idleNudgesSent === 0 ? IDLE_FIRST_MS : IDLE_NEXT_MS;
    const remaining = Math.max(500, delay - (Date.now() - RT.lastActivityAt));
    RT.idleTimer = setTimeout(async () => {
      RT.idleTimer = null;
      if (!RT.on || RT.active || RT.userSpeaking) return;
      if (RT.rtcEngine && RT.rtcInfo) {
        try {
          const result = await api.post("/volcengine/observe", { session_id: CHAT.sessionId });
          if (!result.ok) return;
        } catch (error) {
          console.warn("[volcengine] 画面观察触发失败", error);
          RT.lastActivityAt = Date.now();
          scheduleIdleNudge();
          return;
        }
      } else {
        if (!RT.ws || RT.ws.readyState !== 1) return;
        RT.ws.send(JSON.stringify({ type: "ling.idle_nudge" }));
      }
      RT.idleNudgesSent += 1;
      RT.lastActivityAt = Date.now();
      setRtStatus("有点安静，灵灵在看看怎么陪你…");
    }, remaining);
  }

  function noteActivity(schedule = false) {
    RT.lastActivityAt = Date.now();
    clearIdleTimer();
    if (schedule) scheduleIdleNudge();
  }

  function syncVideoButton() {
    const button = $("#video-btn");
    if (!button) return;
    const supported = !!selectedConfig().supports_video;
    const active = RT.videoActive;
    button.disabled = !supported || !RT.on;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.title = supported
      ? (active ? "关闭摄像头" : `开启摄像头，让${providerLabel(selectedProvider)}看见画面`)
      : `${providerLabel(selectedProvider)} 不支持视频输入`;
  }

  function stopVideo() {
    if (RT.videoTimer) clearInterval(RT.videoTimer);
    RT.videoTimer = null;
    if (RT.rtcEngine) {
      RT.rtcEngine.stopVideoCapture().catch(() => {});
      try { RT.rtcEngine.setLocalVideoPlayer(window.VERTC.StreamIndex.STREAM_INDEX_MAIN); } catch { }
    }
    RT.videoStream?.getTracks().forEach(track => track.stop());
    RT.videoStream = null;
    RT.videoActive = false;
    RT.videoEl?.remove();
    RT.videoEl = null;
    RT.videoCanvas = null;
    $("#rt-bar")?.classList.remove("has-video");
    syncVideoButton();
  }

  function sendVideoFrame() {
    const video = RT.videoEl;
    const ws = RT.ws;
    if (!video || video.readyState < 2 || !ws || ws.readyState !== 1 ||
        selectedProvider !== "gemini" || ws.bufferedAmount > 512000) return;
    const scale = Math.min(1, 512 / Math.max(video.videoWidth, video.videoHeight));
    const width = Math.max(1, Math.round(video.videoWidth * scale));
    const height = Math.max(1, Math.round(video.videoHeight * scale));
    const canvas = RT.videoCanvas || document.createElement("canvas");
    RT.videoCanvas = canvas;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width; canvas.height = height;
    }
    canvas.getContext("2d", { alpha: false }).drawImage(video, 0, 0, width, height);
    const data = canvas.toDataURL("image/jpeg", 0.72).split(",")[1];
    ws.send(JSON.stringify({ type: "ling.video_frame", mime_type: "image/jpeg", data }));
  }

  async function startVideo() {
    if (!selectedConfig().supports_video) {
      toast(`${providerLabel(selectedProvider)} 暂不支持视频输入`); return;
    }
    if (!RT.on) { toast("语音接通后才能开启摄像头"); return; }
    if (RT.videoActive) return;
    if (RT.rtcEngine) {
      const mount = document.createElement("div");
      mount.className = "rtc-local-video";
      mount.id = `rtc-local-${Date.now()}`;
      const bar = $("#rt-bar");
      if (bar) { bar.prepend(mount); bar.classList.add("has-video"); }
      try {
        await RT.rtcEngine.startVideoCapture();
        RT.rtcEngine.setLocalVideoMirrorType(window.VERTC.MirrorType.MIRROR_TYPE_RENDER);
        RT.rtcEngine.setLocalVideoPlayer(window.VERTC.StreamIndex.STREAM_INDEX_MAIN, { renderDom: mount });
        RT.videoEl = mount;
        RT.videoActive = true;
        syncVideoButton();
        setRtStatus("视频已开启，火山引擎正在看和听…");
      } catch (error) {
        mount.remove();
        toast("没拿到摄像头权限");
        console.warn("[volcengine] 开启视频失败", error);
      }
      return;
    }
    const providerAtStart = selectedProvider;
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
      });
    } catch { toast("没拿到摄像头权限"); return; }
    if (!RT.on || selectedProvider !== providerAtStart) {
      stream.getTracks().forEach(track => track.stop()); return;
    }
    const video = document.createElement("video");
    video.className = "live-video";
    video.srcObject = stream;
    video.autoplay = true; video.muted = true; video.playsInline = true;
    RT.videoStream = stream; RT.videoEl = video; RT.videoActive = true;
    const bar = $("#rt-bar");
    if (bar) { bar.prepend(video); bar.classList.add("has-video"); }
    await video.play();
    syncVideoButton();
    sendVideoFrame();
    RT.videoTimer = setInterval(sendVideoFrame, 1000);
    setRtStatus("视频已开启，Gemini 正在看和听…");
  }

  function rtStopPlayback() {
    RT.sources.forEach(s => { try { s.stop(); } catch { } });
    RT.sources = [];
    RT.playHead = 0;
  }

  function rtPlayDelta(b64) {
    const i16 = int16FromB64(b64);
    if (!i16.length || !RT.ctx) return;
    const f32 = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
    const buf = RT.ctx.createBuffer(1, f32.length, rtOutputRate());   // WebAudio 自动重采样到播放设备频率
    buf.getChannelData(0).set(f32);
    const src = RT.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(RT.ctx.destination);
    const t = Math.max(RT.ctx.currentTime + 0.06, RT.playHead || 0);
    src.start(t);
    RT.playHead = t + buf.duration;
    RT.sources.push(src);
    src.onended = () => { const i = RT.sources.indexOf(src); if (i >= 0) RT.sources.splice(i, 1); };
  }

  function rtSendChunk(f32) {   // 攒 ~100ms 再发，别把 WS 打成碎片雨
    if (!RT.on || !RT.ws || RT.ws.readyState !== 1) return;
    RT.buf.push(f32);
    RT.bufLen += f32.length;
    if (RT.bufLen < RT.ctx.sampleRate / 10) return;
    let all = new Float32Array(RT.bufLen), off = 0;
    RT.buf.forEach(b => { all.set(b, off); off += b.length; });
    RT.buf = []; RT.bufLen = 0;
    const now = Date.now();
    let energy = 0;
    for (let i = 0; i < all.length; i++) energy += all[i] * all[i];
    const rms = Math.sqrt(energy / Math.max(1, all.length));
    if (rms >= LOCAL_SPEECH_RMS) {
      RT.userSpeaking = true;
      RT.lastVoiceAt = now;
      noteActivity(false);
    } else if (RT.userSpeaking && now - RT.lastVoiceAt >= 900) {
      RT.userSpeaking = false;
      noteActivity(true);
    }

    all = resample(all, RT.ctx.sampleRate, rtInputRate());
    const i16 = new Int16Array(all.length);
    for (let i = 0; i < all.length; i++)
      i16[i] = Math.max(-32768, Math.min(32767, Math.round(all[i] * 32767)));
    RT.ws.send(JSON.stringify({ type: "input_audio_buffer.append", audio: b64FromInt16(i16) }));
  }

  function rtHandleEvent(ev) {
    switch (ev.type) {
      case "session.created":
      case "session.updated":   // 开场问候由后端注入人设后主动触发（realtime.py），前端不重复发
        noteActivity(false);
        setRtStatus("已接通，直接说话吧"); break;
      case "input_audio_buffer.speech_started":   // 孩子开口 → 立刻停播 + 掐断在讲的回复
        RT.userSpeaking = true;
        noteActivity(false);
        rtStopPlayback();
        if (RT.active) { RT.ws?.send(JSON.stringify({ type: "response.cancel" })); RT.active = null; }
        setRtStatus("在听你说…"); break;
      case "input_audio_buffer.speech_stopped":
        RT.userSpeaking = false;
        noteActivity(true);
        setRtStatus("正在想…");
        // 先占位孩子的气泡：ASR 转写常晚于 AI 回复到达，占位保证顺序（孩子说 → AI 答）
        if (!RT.userBubble) RT.userBubble = addMsg("user", "");
        break;
      case "conversation.item.input_audio_transcription.completed": {
        const t = ev.transcript?.trim();
        if (RT.userBubble) {
          if (t) RT.userBubble.textContent = t;
          else RT.userBubble.closest(".msg")?.remove();   // 没识别到内容，撤掉占位
          RT.userBubble = null;
        } else if (t) { addMsg("user", t); }
        noteActivity(true);
        log.scrollTop = log.scrollHeight; break;
      }
      case "response.created":
        clearIdleTimer();
        RT.active = ev.id || ev.response?.id || true;
        RT.bubble = null; RT.text = ""; break;
      case "response.audio.delta":
        rtPlayDelta(ev.delta || "");
        setRtStatus("正在说…"); break;
      case "response.audio_transcript.delta":
        if (!RT.bubble) RT.bubble = addMsg("assistant", "");
        RT.text += ev.delta || "";
        RT.bubble.innerHTML = rich(RT.text);
        log.scrollTop = log.scrollHeight; break;
      case "response.audio_transcript.done":
        if (RT.bubble && ev.transcript) RT.bubble.innerHTML = rich(ev.transcript); break;
      case "response.done":
        RT.active = null;
        noteActivity(true);
        setRtStatus("正在听…"); break;
      case "ling.state":   // 后端记账结果：编织进度/正典/撤退，与文字模式同一套
        finalize(ev); break;
      case "ling.error":
        toast(ev.message || "实时语音出错"); endRealtime(); break;
      case "error":   // 上游非致命 error（会话仍在）：记 console 供排查，不弹给孩子看
        console.warn("[realtime] 上游 error（非致命，忽略）", ev); break;
    }
  }

  async function ensureChatSession() {
    if (CHAT.sessionId) return true;
    try {
      const start = await api.post("/session/start");
      CHAT = { sessionId: start.session_id, agenda: start.review_items || [], woven: [], produced: [] };
      RT.idleNudgesSent = 0;
      renderAgenda();
      return true;
    } catch (error) {
      console.warn("[realtime] 会话创建失败", error);
      toast("会话创建失败，请重试");
      return false;
    }
  }

  function showCallBar() {
    $("#rt-bar")?.remove();
    const bar = document.createElement("div");
    bar.className = "call-bar"; bar.id = "rt-bar";
    bar.innerHTML = `${FOX(46)}
      <div class="call-status"><span class="call-dot"></span><b id="rt-status">正在接通…</b>
        <span class="hint">${providerLabel(selectedProvider)} · ${esc(selectedConfig().model || "")} · 直接说话，开口即可打断。戴耳机效果最好。</span></div>`;
    log.parentNode.insertBefore(bar, log);
  }

  function decodeVolcSubtitle(message) {
    let bytes;
    if (message instanceof ArrayBuffer) bytes = new Uint8Array(message);
    else if (ArrayBuffer.isView(message)) bytes = new Uint8Array(message.buffer, message.byteOffset, message.byteLength);
    else return null;
    if (bytes.length < 8 || new TextDecoder().decode(bytes.subarray(0, 4)) !== "subv") return null;
    const length = new DataView(bytes.buffer, bytes.byteOffset + 4, 4).getUint32(0, false);
    if (length + 8 > bytes.length) return null;
    try { return JSON.parse(new TextDecoder().decode(bytes.subarray(8, 8 + length))); }
    catch { return null; }
  }

  function handleVolcSubtitle(message) {
    const payload = decodeVolcSubtitle(message);
    if (!payload || payload.type !== "subtitle" || !RT.rtcInfo) return;
    for (const item of payload.data || []) {
      const role = item.userId === RT.rtcInfo.user_id ? "user"
        : item.userId === RT.rtcInfo.bot_id ? "assistant" : null;
      if (!role) continue;
      const text = String(item.text || "").trim();
      const key = `${role}:${item.roundId ?? 0}`;
      let bubble = RT.volcSubtitleBubbles.get(key);
      if (text) {
        if (!bubble) {
          bubble = addMsg(role, "");
          RT.volcSubtitleBubbles.set(key, bubble);
        }
        bubble.innerHTML = role === "user" ? esc(text) : rich(text);
      }
      if (role === "user") {
        RT.userSpeaking = !item.definite;
        setRtStatus(item.definite ? "正在想…" : "在听你说…");
      } else {
        RT.active = item.definite ? null : key;
        setRtStatus(item.definite ? "正在听…" : "正在说…");
      }
      noteActivity(!!item.definite);
      if (item.definite && text) {
        api.post("/volcengine/subtitle", {
          session_id: CHAT.sessionId,
          speaker_id: item.userId,
          text,
          sequence: item.sequence || 0,
          round_id: item.roundId || 0,
          definite: true,
        }).then(result => { if (result.state) finalize(result.state); })
          .catch(error => console.warn("[volcengine] 字幕记账失败", error));
      }
    }
  }

  async function startVolcengine() {
    if (!window.VERTC?.createEngine) {
      toast("火山 RTC SDK 加载失败");
      return false;
    }
    if (!await ensureChatSession()) return false;
    try {
      const info = await api.post("/volcengine/prepare", { session_id: CHAT.sessionId });
      const rtc = window.VERTC.createEngine(info.app_id);
      RT.rtcEngine = rtc;
      RT.rtcInfo = info;
      RT.provider = "volcengine";
      RT.volcSubtitleBubbles.clear();
      rtc.on(window.VERTC.events.onRoomBinaryMessageReceived, event => handleVolcSubtitle(event.message));
      rtc.on(window.VERTC.events.onUserJoined, event => {
        if (event.userInfo?.userId === info.bot_id) setRtStatus("已接通，直接说话吧");
      });
      rtc.on(window.VERTC.events.onUserPublishStream, event => {
        if (event.userId === info.bot_id) setRtStatus("已接通，正在听…");
      });
      rtc.on(window.VERTC.events.onAutoplayFailed, () => {
        rtc.play(info.bot_id, window.VERTC.MediaType.AUDIO).catch(() => {});
      });
      rtc.on(window.VERTC.events.onTokenWillExpire, async () => {
        try {
          const renewed = await api.post("/volcengine/prepare", { session_id: CHAT.sessionId });
          await rtc.updateToken(renewed.token);
        } catch (error) { console.warn("[volcengine] Token 更新失败", error); }
      });
      rtc.on(window.VERTC.events.onError, error => console.warn("[volcengine] RTC error", error));

      showCallBar();
      await rtc.joinRoom(info.token, info.room_id, { userId: info.user_id }, {
        isAutoPublish: true,
        isAutoSubscribeAudio: true,
        isAutoSubscribeVideo: false,
      });
      await rtc.startAudioCapture();
      RT.on = true;
      RT.userSpeaking = false;
      RT.lastVoiceAt = 0;
      syncCallButtons();
      await api.post("/volcengine/start", { session_id: CHAT.sessionId });
      noteActivity(true);
      setRtStatus("已接通，直接说话吧");
      toast(`📞 已接通 ${providerLabel(selectedProvider)}`);
      return true;
    } catch (error) {
      console.warn("[volcengine] 接通失败", error);
      toast("火山引擎接通失败：" + (error?.message || error));
      endRealtime();
      return false;
    }
  }

  async function startRealtime() {
    if (RT.on) return true;
    if (selectedProvider === "volcengine") return startVolcengine();
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch { toast("没拿到麦克风权限，语音通话需要它"); return false; }

    if (!await ensureChatSession()) {
      stream.getTracks().forEach(track => track.stop());
      return false;
    }

    RT.stream = stream;
    try { RT.ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: rtInputRate() }); }
    catch { RT.ctx = new (window.AudioContext || window.webkitAudioContext)(); }
    await RT.ctx.resume();

    RT.on = true;
    RT.provider = selectedProvider;
    RT.userSpeaking = false;
    RT.lastVoiceAt = 0;
    noteActivity(false);
    syncCallButtons();
    showCallBar();

    // 采集：AudioWorklet 优先，老浏览器退回 ScriptProcessor
    RT.src = RT.ctx.createMediaStreamSource(stream);
    const mute = RT.ctx.createGain(); mute.gain.value = 0;
    if (RT.ctx.audioWorklet) {
      const code = `class P extends AudioWorkletProcessor{process(inputs){const c=inputs[0][0];if(c)this.port.postMessage(c.slice(0));return true}}registerProcessor("ling-pcm",P)`;
      await RT.ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([code], { type: "application/javascript" })));
      RT.node = new AudioWorkletNode(RT.ctx, "ling-pcm");
      RT.node.port.onmessage = (e) => rtSendChunk(e.data);
    } else {
      RT.node = RT.ctx.createScriptProcessor(4096, 1, 1);
      RT.node.onaudioprocess = (e) => rtSendChunk(new Float32Array(e.inputBuffer.getChannelData(0)));
    }
    RT.src.connect(RT.node);
    RT.node.connect(mute).connect(RT.ctx.destination);

    const proto = location.protocol === "https:" ? "wss://" : "ws://";
    const ws = new WebSocket(`${proto}${location.host}/api/realtime/ws?session_id=${CHAT.sessionId}&provider=${selectedProvider}`);
    RT.ws = ws;
    ws.onmessage = (e) => { let ev; try { ev = JSON.parse(e.data); } catch { return; } rtHandleEvent(ev); };
    ws.onerror = () => { console.warn("[realtime] ws error（交给 onclose 处理）"); };
    ws.onclose = () => {
      if (RT.ws !== ws || !RT.on) return;
      endRealtime();
      // 意外断线（不是用户结束/切页）才自动重连。
      if (!manualEnd && CHAT.sessionId) { toast("语音断了，正在重连…"); setTimeout(() => { if (!manualEnd && CHAT.sessionId) startRealtime(); }, 800); }
    };
    toast(`📞 正在接通 ${providerLabel(selectedProvider)}…`);
    return true;
  }

  function endRealtime() {
    stopVideo();
    clearIdleTimer();
    if (!RT.on && !RT.rtcEngine) { syncCallButtons(); return; }
    RT.on = false;
    if (RT.rtcEngine) {
      const rtc = RT.rtcEngine;
      const sid = CHAT?.sessionId;
      RT.rtcEngine = null;
      RT.rtcInfo = null;
      RT.volcSubtitleBubbles.clear();
      if (sid) api.post("/volcengine/stop", { session_id: sid })
        .catch(error => console.warn("[volcengine] 停止 AI 失败", error));
      (async () => {
        try { await rtc.stopAudioCapture(); } catch { }
        try { await rtc.leaveRoom(); } catch { }
        try { window.VERTC.destroyEngine(rtc); } catch { }
      })();
    }
    rtStopPlayback();
    try { RT.node?.disconnect(); RT.src?.disconnect(); } catch { }
    if (RT.node?.port) RT.node.port.onmessage = null;
    RT.node = RT.src = null;
    RT.stream?.getTracks().forEach(t => t.stop());
    RT.stream = null;
    try { RT.ws?.close(); } catch { }
    RT.ws = null;
    RT.ctx?.close().catch(() => { });
    RT.ctx = null;
    RT.provider = null;
    RT.buf = []; RT.bufLen = 0; RT.bubble = null; RT.text = ""; RT.active = null; RT.userBubble = null;
    $("#rt-bar")?.remove();
    syncCallButtons();
  }

  function syncCallButtons() {
    const call = $("#call-btn"), end = $("#end-btn");
    if (call) call.hidden = RT.on;
    if (end) end.hidden = !RT.on;
    syncVideoButton();
  }

  function renderProviderSwitch() {
    document.querySelectorAll("[data-provider]").forEach(button =>
      button.classList.toggle("active", button.dataset.provider === selectedProvider));
    syncVideoButton();
  }
  $("#video-btn").onclick = () => RT.videoActive ? stopVideo() : startVideo();
  document.querySelectorAll("[data-provider]").forEach(button => button.onclick = async () => {
    const next = button.dataset.provider;
    if (next === selectedProvider || !providers[next]?.available) return;
    const reconnect = RT.on;
    selectedProvider = next;
    localStorage.setItem("ling-realtime-provider", next);
    endRealtime();
    renderProviderSwitch();
    if (reconnect) await startRealtime();
  });
  renderProviderSwitch();
  syncCallButtons();

  // 离开聊天页视为结束本次通话，并正常触发冷路径结算。
  window.addEventListener("hashchange", () => {
    manualEnd = true;
    endRealtime();
    const sid = CHAT?.sessionId;
    if (sid) {
      CHAT.sessionId = null;
      runColdPath(sid);
    }
  }, { once: true });
};

// ---------------------------------------------------------------- 灵灵的世界（线上分身）

VIEWS.world = async () => {
  const w = await api.get("/world");
  const arc = w.arcs.find(a => a.status === "active") || w.arcs[0];
  const beats = arc ? arc.beats : [];
  $("#view").innerHTML = `
  <h1 class="page-title">${esc(w.doll.name || "灵灵")}的世界</h1>
  <p class="page-sub">线上 agent 分身 —— 和玩偶共用同一套记忆。它每天都在生活，不管孩子来没来。</p>
  <div class="grid-2">
    <div>
      <div class="card">
        <h2>📜 进行中的故事弧 <span class="hint">生活时钟每天推进一拍</span></h2>
        <p style="font-weight:700;margin-bottom:12px">「${esc(arc ? arc.title : "平静的日常")}」</p>
        <div class="arc-beats">
          ${beats.map((b, i) => `
            <div class="beat ${i < (arc.current_beat) ? "done" : i === arc.current_beat ? "now" : "future"}">
              <div class="dot">${i < arc.current_beat ? "✓" : i + 1}</div>
              <div class="txt">${esc(b)}</div>
            </div>`).join("")}
        </div>
        <button class="primary" id="tick-btn" style="margin-top:8px">🕰️ 推进一天（生活时钟）</button>
      </div>
      <div class="card">
        <h2>🏛️ 世界正典 Canon <span class="hint">所有故事必须与它一致</span></h2>
        ${w.canon.map(c => `
          <div class="canon-item ${c.by_child ? "by-child" : ""}">
            <b>${esc(c.entity)}</b><span>${esc(c.fact_text)}</span>
            ${c.by_child ? '<span class="chip violet" style="margin-left:auto;flex:0 0 auto">孩子写下的</span>' : ""}
          </div>`).join("")}
      </div>
    </div>
    <div>
      <div class="card">
        <h2>🍂 ${esc(w.doll.name || "灵灵")}的生活事件</h2>
        ${w.events.map(e => `
          <div class="event">
            <div class="ts">${esc(e.ts.slice(5, 16))} ·
              ${e.share_status === "unshared" ? '<span class="chip gold">待分享</span>'
                : e.share_status === "shared" ? '<span class="chip leaf">已分享给孩子</span>'
                : '<span class="chip ghost">沉淀进日记</span>'}
              ${e.vocab.map(v => `<span class="chip sky">${esc(v)}</span>`).join("")}
            </div>
            <div style="font-size:14px;margin-top:4px">${rich(e.text)}</div>
            ${e.child_reaction ? `<div class="reaction">🧒 孩子的决定：「${esc(e.child_reaction)}」</div>` : ""}
          </div>`).join("") || "还没有事件"}
      </div>
    </div>
  </div>`;
  $("#tick-btn").onclick = async () => {
    const r = await api.post("/admin/life_tick");
    toast("🕰️ 新的一天：" + (r.text || "").slice(0, 30) + "…");
    route();
  };
};

// ---------------------------------------------------------------- 家长控制台

VIEWS.parent = async () => {
  const [report, facts, diary, mastery, growth] = await Promise.all([
    api.get("/report"), api.get("/facts"), api.get("/diary"), api.get("/mastery"), api.get("/growth"),
  ]);
  const snap = report.latest_snapshot;
  $("#view").innerHTML = `
  <h1 class="page-title">家长控制台</h1>
  <p class="page-sub">孩子接触的所有内容可见、可删 —— 透明是给家长的合规答卷，成长报告是给家长的惊喜。</p>
  <div class="stat-tiles">
    <div class="tile coral"><div class="num">${report.mastery.exposed}</div><div class="lbl">本单元复习过的词</div></div>
    <div class="tile gold" style="--num:#a86e14"><div class="num" style="color:#a86e14">${report.mastery.recognized}</div><div class="lbl">听懂了的词</div></div>
    <div class="tile leaf"><div class="num">${report.mastery.produced}</div><div class="lbl">主动说出的词 ⭐</div></div>
    <div class="tile sky"><div class="num">${report.sessions_this_week}</div><div class="lbl">累计陪伴会话</div></div>
  </div>
  <div class="grid-2">
    <div class="card">
      <h2>📈 英语成长曲线 <span class="hint">近 8 天累计</span></h2>
      <div id="chart-box" style="position:relative"></div>
    </div>
    <div class="card">
      <h2>🌱 成长时刻 <span class="hint">被新事实作废的旧事实 —— 成长感藏在这里</span></h2>
      ${report.growth_moments.map(g => `
        <div class="growth-moment">
          <span class="before">${esc(g.before)}</span>
          <span class="arrow">→</span><span><b>${esc(g.after)}</b></span>
        </div>`).join("") || '<p style="color:var(--ink-3)">还没有捕捉到成长时刻</p>'}
      ${snap ? `
        <h2 style="margin-top:18px">🦊 玩偶视角的日记 <span class="hint">${esc(snap.period)}</span></h2>
        <div class="doll-diary">“${esc(snap.doll_diary_text)}”</div>
        <div style="margin-top:10px">
          ${(snap.milestones || []).map(m => `<span class="chip gold">🏅 ${esc(m)}</span>`).join("")}
        </div>` : ""}
    </div>
  </div>
  <div class="card">
    <h2>🍃 一日一叶 · 记忆日记（L2）</h2>
    <div class="leafline">
      ${diary.slice(0, 10).map(d => `
        <div class="leaf-card">
          <div class="d">${esc(d.ts.slice(5, 10))} ${(d.emotions || []).join(" ")}</div>
          <div class="s">${esc(d.summary)}</div>
          ${(d.quotes || [])[0] ? `<div style="color:#6a8657">🗣 「${esc(d.quotes[0])}」</div>` : ""}
        </div>`).join("")}
    </div>
  </div>
  <div class="grid-2">
    <div class="card">
      <h2>💡 事实记忆（L3） <span class="hint">后续经历会保留更新脉络</span></h2>
      ${facts.map(f => `
        <div class="fact-row ${f.superseded_by ? "superseded" : ""}">
          <span class="chip ${({ interest: "coral", family: "sky", fear: "violet", friend: "leaf" })[f.category] || "gold"}">${esc(f.category)}</span>
          <span>${esc(f.text)}</span>
          ${f.superseded_by ? '<span class="chip ghost">已被更新</span>' : ""}
        </div>`).join("")}
      <p style="font-size:12.5px;color:var(--ink-3);margin-top:10px">家长设定的边界话题：
        ${(STATE.taboo || []).map(t => `<span class="chip violet">🚫 ${esc(t)}</span>`).join("") || "无"}</p>
    </div>
    <div class="card">
      <h2>🎯 本单元掌握度明细 <span class="hint">SRS-lite：听懂间隔翻倍，没反应重置</span></h2>
      <table class="mastery">
        <tr><th>学习项</th><th>释义</th><th>层级</th><th>曝光</th><th>成功</th></tr>
        ${mastery.items.filter(i => i.item_type === "word").map(i => `
          <tr><td><b>${esc(i.item_text)}</b></td><td>${esc(i.item_zh)}</td>
          <td><span class="lvl ${i.level}">${LEVEL_ZH[i.level]}</span></td>
          <td>${i.exposures}</td><td>${i.successes}</td></tr>`).join("")}
      </table>
    </div>
  </div>`;
  drawGrowthChart($("#chart-box"), report.vocab_curve);
};

// 成长曲线：双序列折线（累计听懂 / 累计说出），带十字线 tooltip
function drawGrowthChart(box, curve) {
  if (!curve || !curve.length) { box.innerHTML = "暂无数据"; return; }
  const W = 460, H = 210, P = { l: 30, r: 66, t: 14, b: 26 };
  const maxY = Math.max(2, ...curve.map(c => c.recognized)) + 1;
  const x = i => P.l + i * (W - P.l - P.r) / (curve.length - 1);
  const y = v => H - P.b - v * (H - P.t - P.b) / maxY;
  const line = key => curve.map((c, i) => `${i ? "L" : "M"}${x(i)},${y(c[key])}`).join("");
  const ticks = [];
  for (let v = 0; v <= maxY; v += Math.ceil(maxY / 4)) ticks.push(v);
  box.innerHTML = `
  <div class="viz-root">
    <div class="viz-legend">
      <span><span class="key" style="background:var(--series-1)"></span>累计听懂</span>
      <span><span class="key" style="background:var(--series-2)"></span>累计说出</span>
    </div>
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;display:block" id="growth-svg">
      ${ticks.map(v => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--chart-grid)" stroke-width="1"/>
        <text x="${P.l - 7}" y="${y(v) + 4}" font-size="10" fill="var(--chart-muted)" text-anchor="end">${v}</text>`).join("")}
      <line x1="${P.l}" x2="${W - P.r}" y1="${y(0)}" y2="${y(0)}" stroke="var(--chart-axis)" stroke-width="1"/>
      ${curve.map((c, i) => i % 2 === 0 ? `<text x="${x(i)}" y="${H - 8}" font-size="10" fill="var(--chart-muted)" text-anchor="middle">${c.date}</text>` : "").join("")}
      <path d="${line("recognized")}" fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round"/>
      <path d="${line("produced")}" fill="none" stroke="var(--series-2)" stroke-width="2" stroke-linejoin="round"/>
      <text x="${W - P.r + 8}" y="${y(curve.at(-1).recognized) + 4}" font-size="11" font-weight="600" fill="#52514e">听懂 ${curve.at(-1).recognized}</text>
      <text x="${W - P.r + 8}" y="${y(curve.at(-1).produced) + 14}" font-size="11" font-weight="600" fill="#52514e">说出 ${curve.at(-1).produced}</text>
      <line id="xhair" y1="${P.t}" y2="${H - P.b}" stroke="var(--chart-axis)" stroke-width="1" stroke-dasharray="3 3" visibility="hidden"/>
      <circle id="dot1" r="4" fill="var(--series-1)" stroke="var(--chart-surface)" stroke-width="2" visibility="hidden"/>
      <circle id="dot2" r="4" fill="var(--series-2)" stroke="var(--chart-surface)" stroke-width="2" visibility="hidden"/>
    </svg>
  </div>
  <div class="viz-tip" id="viz-tip"></div>`;
  const svg = $("#growth-svg", box), tip = $("#viz-tip", box);
  svg.addEventListener("mousemove", (e) => {
    const rect = svg.getBoundingClientRect();
    const mx = (e.clientX - rect.left) * W / rect.width;
    let best = 0, bd = 1e9;
    curve.forEach((c, i) => { const d = Math.abs(x(i) - mx); if (d < bd) { bd = d; best = i; } });
    const c = curve[best];
    $("#xhair", box).setAttribute("x1", x(best)); $("#xhair", box).setAttribute("x2", x(best));
    $("#xhair", box).setAttribute("visibility", "visible");
    const d1 = $("#dot1", box), d2 = $("#dot2", box);
    d1.setAttribute("cx", x(best)); d1.setAttribute("cy", y(c.recognized)); d1.setAttribute("visibility", "visible");
    d2.setAttribute("cx", x(best)); d2.setAttribute("cy", y(c.produced)); d2.setAttribute("visibility", "visible");
    tip.style.display = "block";
    tip.style.left = Math.min(e.clientX - box.getBoundingClientRect().left + 14, box.clientWidth - 130) + "px";
    tip.style.top = (e.clientY - box.getBoundingClientRect().top - 10) + "px";
    tip.innerHTML = `<b>${c.date}</b><br>听懂：${c.recognized} 个<br>说出：${c.produced} 个`;
  });
  svg.addEventListener("mouseleave", () => {
    tip.style.display = "none";
    ["#xhair", "#dot1", "#dot2"].forEach(s => $(s, box).setAttribute("visibility", "hidden"));
  });
}

// ---------------------------------------------------------------- 初始化（家长入口 Onboarding）

VIEWS.setup = async () => {
  const cur = await api.get("/curriculum");
  const pack = cur.packs[0];
  const child = STATE.child || {};
  let persona = "curious_explorer";
  $("#view").innerHTML = `
  <h1 class="page-title">初始化玩偶</h1>
  <p class="page-sub">家长入口：填基础信息、选教材进度、给玩偶起名 —— 这场相遇会成为记忆里的第一页日记。</p>
  <div class="card">
    <h2>🧒 孩子的信息</h2>
    <div class="form-grid">
      <div class="field"><label>孩子的名字</label><input id="f-name" value="${esc(child.name || "")}" placeholder="悠悠"></div>
      <div class="field"><label>年龄</label><input id="f-age" type="number" value="${child.age || 8}"></div>
      <div class="field"><label>年级</label><input id="f-grade" value="${esc(child.grade || "三年级")}"></div>
      <div class="field"><label>家庭成员（逗号分隔）</label><input id="f-family" value="${esc((child.family || []).join("，"))}" placeholder="妈妈，爸爸，小猫团团"></div>
      <div class="field"><label>兴趣种子（逗号分隔）</label><input id="f-interests" value="${esc((child.interests || []).join("，"))}" placeholder="恐龙，画画"></div>
      <div class="field"><label>禁忌话题（家长设边界，逗号分隔）</label><input id="f-taboo" value="${esc((STATE.taboo || []).join("，"))}" placeholder="恐怖故事"></div>
    </div>
  </div>
  <div class="card">
    <h2>📚 在学的教材 <span class="hint">三级联动：版本 → 年级学期 → 当前单元。以后扩科目 = 新增课程包</span></h2>
    <div class="form-grid">
      <div class="field"><label>教材版本</label>
        <select id="f-pack"><option value="${esc(pack.id)}">${esc(pack.title)}</option></select></div>
      <div class="field"><label>学到第几单元了</label>
        <select id="f-unit">${pack.units.map(u =>
          `<option value="${u.unit}" ${u.unit === (cur.learning_state?.current_unit || 4) ? "selected" : ""}>Unit ${u.unit} · ${esc(u.title)}（${u.words.length} 词）</option>`).join("")}</select></div>
    </div>
    <p style="font-size:12.5px;color:var(--ink-3);margin-top:8px">💡 进度不必精确：玩偶会从对话里自动校准（哪个单元的词全都秒懂、哪个完全没反应）。</p>
  </div>
  <div class="card">
    <h2>🦊 玩偶的人设</h2>
    <div class="form-grid" style="margin-bottom:14px">
      <div class="field"><label>给玩偶起个名字</label><input id="f-doll" value="${esc(STATE.doll.name || "灵灵")}"></div>
    </div>
    <div class="persona-pick" id="persona-pick">
      <div class="persona-card sel" data-p="curious_explorer"><b>🧭 好奇的探险家</b>爱收集橡果和新鲜事，胆子不大但嘴很硬</div>
      <div class="persona-card" data-p="gentle_listener"><b>🌙 温柔的倾听者</b>说话轻轻的，最会安慰人</div>
      <div class="persona-card" data-p="little_scientist"><b>🔬 小小科学家</b>什么都要问为什么</div>
    </div>
  </div>
  <button class="primary" id="f-submit" style="font-size:16px;padding:13px 34px">✨ 完成初始化，唤醒玩偶</button>`;
  document.querySelectorAll(".persona-card").forEach(c => c.onclick = () => {
    document.querySelectorAll(".persona-card").forEach(x => x.classList.remove("sel"));
    c.classList.add("sel"); persona = c.dataset.p;
  });
  const split = (v) => v.split(/[,，、]/).map(s => s.trim()).filter(Boolean);
  $("#f-submit").onclick = async () => {
    const body = {
      child_name: $("#f-name").value.trim() || "小朋友",
      age: +$("#f-age").value || 8,
      grade: $("#f-grade").value.trim(),
      family: split($("#f-family").value),
      interests: split($("#f-interests").value),
      taboo: split($("#f-taboo").value),
      pack_id: $("#f-pack").value,
      current_unit: +$("#f-unit").value,
      doll_name: $("#f-doll").value.trim() || "灵灵",
      doll_persona: persona,
    };
    await api.post("/onboarding", body);
    toast(`✨ ${body.doll_name}醒来了，记住了${body.child_name}`);
    location.hash = "home";
  };
};

// ---------------------------------------------------------------- 演示控制台

VIEWS.demo = async () => {
  $("#view").innerHTML = `
  <h1 class="page-title">演示控制台</h1>
  <p class="page-sub">冷路径任务手动触发（正式版是定时任务）。
    交互内核：${STATE.realtime?.available ? "📞 Gemini / StepFun / 火山 RTC" : "😴 实时模型未配置"}
    · 记忆工人：${esc(STATE.llm.worker_model)}</p>
  <div class="card">
    <h2>🌙 冷路径任务</h2>
    <div class="demo-btns">
      <button class="primary" data-act="night_planner">🌙 夜间规划器（挑到期词 + 记忆钩子 → 今日议程）</button>
      <button class="primary" data-act="life_tick">🕰️ 生活时钟（推进故事弧，生成明日事件）</button>
      <button class="primary" data-act="reflect">🪞 反思引擎（7 天日记 → 成长快照）</button>
      <button data-act="reseed" style="border-color:#f3c8c8;color:#b33">⚠️ 重置为预埋的一周演示数据</button>
    </div>
    <pre class="json" id="demo-out">点击上面的按钮，任务产出会显示在这里</pre>
  </div>
  <div class="card">
    <h2>🎬 三幕演示脚本（评委看的就是这个）</h2>
    <div class="script-step"><div class="n">1</div><div><b>纯问候后自然回忆</b> —— 接通时灵灵只简单打招呼；聊过两轮后，在自然相关或冷场时才可提起「昨天那只三角龙起好名字了吗？」。回答 <code>起好啦，叫大角！</code>，冷路径会把它记成新事实。</div></div>
    <div class="script-step"><div class="n">2</div><div><b>复习藏在生活里 + 孩子写正典</b> —— 问它 <code>你今天做了什么呀？</code>，它分享去动物园送请柬的事（zoo/panda/monkey/funny 自然出现），然后请孩子决定蛋糕口味：回答 <code>做橡果味的吧！</code>，决定写进世界正典，去「灵灵的世界」验证。</div></div>
    <div class="script-step"><div class="n">3</div><div><b>家长看到成长</b> —— 点「结束会话」看冷路径产出，再去「家长控制台」：成长曲线、主动说出 N 词、被作废的旧事实（以前怕黑 → 现在不怕了）、玩偶视角日记。</div></div>
    <div class="script-step"><div class="n">4</div><div><b>加分项</b> —— 说 <code>我不想说英语</code> 触发撤退规则（玩偶和点读机的分界线）；在「灵灵的世界」点生活时钟，看它「孩子不在时也在生活」。</div></div>
  </div>
  <div class="card">
    <h2>🏗️ 架构一图流</h2>
    <div class="flow">
      <div class="step"><b>L1 核心卡片</b>孩子卡 + 玩偶状态卡，常驻 prompt，性格稳定性的锚</div>
      <div class="step"><b>L2 情景日记</b>append-only，一日一叶 / 家长报告 / 记忆钩子全从这出</div>
      <div class="step"><b>L3 事实记忆</b>valid_from / superseded_by，成长感藏在被作废的旧事实里</div>
      <div class="step"><b>L4 反思成长</b>兴趣趋势、里程碑、玩偶视角日记</div>
      <div class="step"><b>热路径</b>开场记忆包一次 DB 读（&lt;50ms），实时对话零 LLM 记忆调用</div>
      <div class="step"><b>冷路径</b>会话后异步：写日记 / 抽事实 / SRS 回写</div>
      <div class="step"><b>数字生命</b>正典 Canon + 故事弧 + 生活时钟，复习词织进玩偶的一天</div>
      <div class="step"><b>两层世界</b>同一套记忆 API：玩偶端 / 线上分身 / 家长控制台</div>
    </div>
  </div>`;
  document.querySelectorAll("[data-act]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    const out = await api.post(`/admin/${b.dataset.act}`);
    $("#demo-out").textContent = JSON.stringify(out, null, 2);
    b.disabled = false;
    toast("任务完成 ✓");
  });
};
