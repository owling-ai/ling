/* 灵 · 前端逻辑：hash 路由 + 六个视图 + 语音（Web Speech API，纯软件模拟玩偶硬件） */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const api = {
  get: (p) => fetch(`/api${p}`).then(r => r.json()),
  post: (p, body) => fetch(`/api${p}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  }).then(r => r.json()),
  del: (p) => fetch(`/api${p}`, { method: "DELETE" }).then(r => r.json()),
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
let CHAT = null; // { sessionId, agenda:[], woven:[], ttsOn }

// ---------------------------------------------------------------- 路由

const VIEWS = {};
async function route() {
  const name = (location.hash || "#home").slice(1);
  document.querySelectorAll("#nav a").forEach(a =>
    a.classList.toggle("active", a.dataset.view === name));
  STATE = await api.get("/state");
  const badge = $("#llm-badge");
  const modelShort = (STATE.llm.chat_model || "").split("/").pop();
  badge.textContent = {
    openai: `${STATE.llm.vision ? "🎥 全模态" : "☁️ 云端"} · ${modelShort}`,
    anthropic: `☁️ 云端模型 · ${STATE.llm.chat_model}`,
    mock: "🛟 离线兜底 · 规则引擎",
  }[STATE.llm.provider] || "🛟 离线兜底";
  badge.classList.toggle("live", STATE.llm.mode === "live");
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
      <h2>🌅 今日议程 <span class="hint">夜间规划器的产出 · 开场纯 DB 读</span></h2>
      <p style="font-size:13.5px;color:var(--ink-2);margin-bottom:8px">开场记忆钩子：</p>
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
  const doll = STATE.doll, child = STATE.child;
  $("#view").innerHTML = `
  <h1 class="page-title">和${esc(doll.name || "灵灵")}聊天</h1>
  <p class="page-sub">网页即玩偶 —— 没有硬件时，麦克风 🎤 和朗读 🔈 就是它的耳朵和嘴巴。</p>
  <div class="chat-wrap">
    <div class="chat-panel">
      <div class="chat-head">
        ${FOX(52)}
        <div class="who">
          <b>${esc(doll.name || "灵灵")}</b>
          <div>${esc(STAGE_ZH[doll.relationship_stage] || "新朋友")} · 心情：开心 · Lv.${doll.growth_level || 1}</div>
        </div>
        <div class="actions">
          <button id="tts-btn" title="朗读回复">🔈</button>
          <button id="end-btn">结束会话</button>
        </div>
      </div>
      <div class="chat-log" id="log"></div>
      <div id="pending-img-bar"></div>
      <div class="chat-input">
        <button class="mic" id="mic-btn" title="按住说话（浏览器语音识别）">🎤</button>
        <button class="mic" id="cam-btn" title="给玩偶看一样东西（摄像头，需要全模态引擎）">📷</button>
        <input id="chat-input" placeholder="以${esc(child.name || '孩子')}的身份说点什么…" autocomplete="off">
        <button class="primary" id="send-btn">发送</button>
      </div>
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
  const addMsg = (role, text, imgDataUrl) => {
    const div = document.createElement("div");
    div.className = "msg" + (role === "user" ? " mine" : "");
    div.innerHTML = `<div class="avatar">${role === "user" ? "🧒" : "🦊"}</div>
      <div><div class="bubble">${imgDataUrl ? `<img src="${imgDataUrl}" class="bubble-img" alt="">` : ""}${role === "user" ? esc(text) : rich(text)}</div></div>`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  };
  const typing = (on) => {
    $(".typing")?.remove();
    if (on) {
      const d = document.createElement("div");
      d.className = "typing"; d.textContent = `${doll.name || "灵灵"}正在想…`;
      log.appendChild(d); log.scrollTop = log.scrollHeight;
    }
  };

  // 开场：热路径记忆包 + 预生成开场白
  const start = await api.post("/session/start");
  CHAT = { sessionId: start.session_id, agenda: start.memory_pack.review_items || [], woven: [], produced: [], ttsOn: false };
  renderAgenda();
  addMsg("assistant", start.opening);
  speak(start.opening);

  function renderAgenda() {
    $("#agenda-box").innerHTML = CHAT.agenda.filter(a => a.type === "word").map(a => {
      const st = CHAT.produced.includes(a.word) ? "produced" : (CHAT.woven.includes(a.word) ? "woven" : "");
      const stZh = st === "produced" ? "孩子说出来了!" : st === "woven" ? "已自然带出" : "待编织";
      return `<div class="agenda-word"><span class="w">${esc(a.word)}</span>
        <span class="zh">${esc(a.zh)}</span><span class="st ${st}">${stZh}</span></div>`;
    }).join("") || '<span class="chip ghost">今天没有复习议程</span>';
  }

  async function send(text) {
    text = (text || "").trim();
    if ((!text && !CHAT.pendingImage) || !CHAT.sessionId) return;
    text = text || "你看这个！";
    const img = CHAT.pendingImage;
    CHAT.pendingImage = null;
    renderPendingImg();
    addMsg("user", text, img);
    $("#chat-input").value = "";
    // 孩子主动说出目标词 → 立刻点亮
    CHAT.agenda.forEach(a => {
      if (a.type === "word" && new RegExp(`\\b${a.word}\\b`, "i").test(text) && !CHAT.produced.includes(a.word))
        CHAT.produced.push(a.word);
    });
    typing(true);
    const res = await api.post("/session/message", {
      session_id: CHAT.sessionId, text,
      image_b64: img ? img.split(",")[1] : null,
    });
    typing(false);
    CHAT.woven = res.woven || CHAT.woven;
    renderAgenda();
    addMsg("assistant", res.reply);
    speak(res.reply);
    if (res.canon_written?.length) toast("✍️ 孩子的决定已写进世界正典！去「灵灵的世界」看看");
    if (res.retreated) toast("🛟 撤退规则触发：今天不再复习，纯陪伴模式");
  }

  $("#send-btn").onclick = () => send($("#chat-input").value);
  $("#chat-input").addEventListener("keydown", e => { if (e.key === "Enter") send(e.target.value); });

  // 结束会话 → 冷路径
  $("#end-btn").onclick = async () => {
    if (!CHAT.sessionId) return;
    const res = await api.post("/session/end", { session_id: CHAT.sessionId });
    CHAT.sessionId = null;
    showColdResult(res);
  };

  // 语音：浏览器 ASR + TTS，纯软件替代玩偶麦克风/喇叭
  $("#tts-btn").onclick = (e) => {
    CHAT.ttsOn = !CHAT.ttsOn;
    e.target.textContent = CHAT.ttsOn ? "🔊" : "🔈";
    toast(CHAT.ttsOn ? "已开启玩偶朗读" : "已关闭朗读");
  };
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const micBtn = $("#mic-btn");
  if (SR) {
    const rec = new SR();
    rec.lang = "zh-CN"; rec.interimResults = false;
    let recording = false;
    micBtn.onclick = () => {
      if (recording) { rec.stop(); return; }
      recording = true; micBtn.classList.add("rec"); rec.start();
    };
    rec.onresult = (e) => send(e.results[0][0].transcript);
    rec.onend = () => { recording = false; micBtn.classList.remove("rec"); };
    rec.onerror = () => { recording = false; micBtn.classList.remove("rec"); toast("语音识别不可用，请打字"); };
  } else {
    micBtn.onclick = () => toast("此浏览器不支持语音识别（试试 Chrome），先打字吧");
  }
  // 摄像头：拍一帧给玩偶看（MiniCPM-o 这类全模态引擎能真的"看见"；离线引擎会好奇地追问）
  function renderPendingImg() {
    $("#pending-img-bar").innerHTML = CHAT.pendingImage
      ? `<div class="pending-img"><img src="${CHAT.pendingImage}" alt="">
         <span>将随下一条消息给${esc(doll.name || "灵灵")}看</span>
         <button id="drop-img">✕</button></div>`
      : "";
    const drop = $("#drop-img");
    if (drop) drop.onclick = () => { CHAT.pendingImage = null; renderPendingImg(); };
  }
  $("#cam-btn").onclick = async () => {
    if (!navigator.mediaDevices?.getUserMedia) { toast("此浏览器不支持摄像头"); return; }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640 } });
    } catch { toast("没拿到摄像头权限"); return; }
    const video = document.createElement("video");
    video.srcObject = stream; video.playsInline = true;
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `<div class="modal" style="max-width:520px">
      <h2>📷 给${esc(doll.name || "灵灵")}看一样东西</h2>
      <div id="cam-slot" style="border-radius:14px;overflow:hidden;background:#000"></div>
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:14px">
        <button id="cam-cancel">算了</button>
        <button class="primary" id="cam-snap">咔嚓，就它了</button>
      </div></div>`;
    document.body.appendChild(mask);
    $("#cam-slot", mask).appendChild(video);
    video.style.width = "100%";
    await video.play();
    const cleanup = () => { stream.getTracks().forEach(t => t.stop()); mask.remove(); };
    $("#cam-cancel", mask).onclick = cleanup;
    $("#cam-snap", mask).onclick = () => {
      const c = document.createElement("canvas");
      const scale = Math.min(1, 448 / video.videoWidth);
      c.width = Math.round(video.videoWidth * scale);
      c.height = Math.round(video.videoHeight * scale);
      c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
      CHAT.pendingImage = c.toDataURL("image/jpeg", 0.82);
      cleanup(); renderPendingImg();
      if (!STATE.llm.vision) toast("当前是离线引擎，玩偶看不清画面，但会好奇地问你 😉");
    };
  };

  function speak(text) {
    if (!CHAT.ttsOn || !window.speechSynthesis) return;
    const u = new SpeechSynthesisUtterance(text.replace(/[（(].*?[)）]/g, ""));
    u.lang = "zh-CN"; u.rate = 1.02; u.pitch = 1.25;
    speechSynthesis.cancel(); speechSynthesis.speak(u);
  }

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
        <button class="primary" onclick="this.closest('.modal-mask').remove();window.dispatchEvent(new HashChangeEvent('hashchange'))">好耶</button>
      </div>
    </div>`;
    document.body.appendChild(mask);
  }
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
      <h2>💡 事实记忆（L3） <span class="hint">点删除即从玩偶记忆里抹去</span></h2>
      ${facts.map(f => `
        <div class="fact-row ${f.superseded_by ? "superseded" : ""}">
          <span class="chip ${({ interest: "coral", family: "sky", fear: "violet", friend: "leaf" })[f.category] || "gold"}">${esc(f.category)}</span>
          <span>${esc(f.text)}</span>
          ${f.superseded_by ? '<span class="chip ghost">已被更新</span>' : ""}
          <button class="del" data-id="${f.id}">删除</button>
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
  document.querySelectorAll(".fact-row .del").forEach(b => b.onclick = async () => {
    await api.del(`/facts/${b.dataset.id}`);
    toast("已从记忆里删除"); route();
  });
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
  <p class="page-sub">冷路径任务手动触发（正式版是定时任务）。当前引擎：${{
    openai: (STATE.llm.vision ? "🎥 " : "☁️ ") + esc(STATE.llm.chat_model)
      + (STATE.llm.vision ? "（全模态端点，支持摄像头画面）" : "（OpenAI 兼容端点）"),
    anthropic: "☁️ " + esc(STATE.llm.chat_model),
    mock: "🛟 规则引擎（无 API key 纯软件兜底，全流程照跑）",
  }[STATE.llm.provider]}</p>
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
    <div class="script-step"><div class="n">1</div><div><b>开场无提示回忆</b> —— 打开「和灵灵聊天」，它主动说：「昨天你说要给那只三角龙起名字，起好了吗？」回答 <code>起好啦，叫大角！</code>，冷路径会把它记成新事实。</div></div>
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
