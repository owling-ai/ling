"""「灵」后端服务。

一套记忆服务，三个客户端：玩偶实时端（网页模拟）/ 线上 agent 分身 / 家长控制台。
启动：uvicorn backend.app:app --reload
"""
import json
import os
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from . import db, engine, life, llm, memory, realtime, seed, volcengine_rtc, workers  # noqa: E402

app = FastAPI(title="灵 · 共同成长玩偶记忆服务")

# 允许通过反代域名访问（默认放行 mm.liaoxingyi.com 和本机，可用 LING_CORS_ORIGINS 覆盖）
_ORIGINS = os.environ.get(
    "LING_CORS_ORIGINS",
    "https://mm.liaoxingyi.com,http://mm.liaoxingyi.com,"
    "http://localhost:8888,http://127.0.0.1:8888",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CHILD_ID = db.CHILD_ID
FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")
DESIGN = os.path.join(os.path.dirname(__file__), "..", "design")


@app.on_event("startup")
def startup():
    db.init_db()
    if not seed.is_seeded():
        seed.seed()
    info = llm.mode_info()
    rt = realtime.info()
    live = ", ".join(
        f"{name}={'on' if config['available'] else 'off'}"
        for name, config in rt["providers"].items()
    )
    print(f"[realtime] 实时语音：{live} · default={rt['default_provider']}\n"
          f"[llm] 冷路径（记忆工人）：{info['worker_provider']} · {info['worker_model']}",
          flush=True)


# ---------------------------------------------------------------- 基本状态

@app.get("/api/state")
def state():
    child = db.q1("SELECT * FROM children WHERE id=?", (CHILD_ID,))
    agenda = db.q1("SELECT * FROM session_agenda WHERE child_id=? AND date=?", (CHILD_ID, db.today()))
    return {
        "onboarded": child is not None,
        "child": memory.get_card(CHILD_ID, "child"),
        "doll": memory.get_card(CHILD_ID, "doll"),
        "taboo": db.jloads(child["taboo_json"]) if child else [],
        "agenda_ready": agenda is not None and agenda["status"] == "ready",
        "llm": llm.mode_info(),
        "realtime": realtime.info(),
    }


# ---------------------------------------------------------------- Onboarding（家长入口）

class OnboardingBody(BaseModel):
    child_name: str
    age: int
    grade: str
    family: list[str] = []
    interests: list[str] = []
    taboo: list[str] = []
    pack_id: str = "pep-en-g3a"
    current_unit: int = 4
    doll_name: str = "灵灵"
    doll_persona: str = "curious_explorer"


PERSONAS = {
    "curious_explorer": "好奇的探险家：爱收集橡果和新鲜事，胆子不大但嘴很硬，最怕痒",
    "gentle_listener": "温柔的倾听者：说话轻轻的，最会安慰人，喜欢收集好听的故事",
    "little_scientist": "小小科学家：什么都要问为什么，口头禅是「我们来做个实验！」",
}


@app.post("/api/onboarding")
def onboarding(body: OnboardingBody):
    db.execute("DELETE FROM children WHERE id=?", (CHILD_ID,))
    db.execute(
        "INSERT INTO children(id,name,age,grade,family_json,interests_json,taboo_json,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (CHILD_ID, body.child_name, body.age, body.grade,
         json.dumps(body.family, ensure_ascii=False),
         json.dumps(body.interests, ensure_ascii=False),
         json.dumps(body.taboo, ensure_ascii=False), db.now()))
    memory.update_card(CHILD_ID, "child", {
        "name": body.child_name, "age": body.age, "grade": body.grade,
        "family": body.family, "interests": body.interests,
        "language_level": f"在学{body.pack_id}第{body.current_unit}单元",
    })
    memory.update_card(CHILD_ID, "doll", {
        "name": body.doll_name,
        "persona": PERSONAS.get(body.doll_persona, PERSONAS["curious_explorer"]),
    })
    db.execute(
        "INSERT OR REPLACE INTO learning_state(child_id,pack_id,current_unit) VALUES(?,?,?)",
        (CHILD_ID, body.pack_id, body.current_unit))
    life.ensure_mastery_rows(CHILD_ID)
    # 这场初始化本身就是 L2 的第一篇日记：「我们认识的那天」
    memory.add_diary(CHILD_ID, f"{body.doll_name}和{body.child_name}认识的那天：家长填好了介绍，"
                               f"{body.doll_name}把{body.child_name}喜欢的{('、'.join(body.interests)) or '事情'}都记在了小本本上。",
                     ["开心"], ["初次见面"], [], "")
    return {"ok": True, "child": memory.get_card(CHILD_ID, "child"),
            "doll": memory.get_card(CHILD_ID, "doll")}


@app.get("/api/curriculum")
def curriculum():
    packs = db.q("SELECT * FROM curriculum_packs")
    for p in packs:
        p["units"] = db.jloads(p.pop("units_json"))
    state_row = db.q1("SELECT * FROM learning_state WHERE child_id=?", (CHILD_ID,))
    return {"packs": packs, "learning_state": state_row}


# ---------------------------------------------------------------- 会话（热路径）

@app.post("/api/session/start")
def session_start():
    if not seed.is_seeded():
        raise HTTPException(400, "请先完成初始化")
    return engine.start_session(CHILD_ID)


class EndBody(BaseModel):
    session_id: str


@app.post("/api/session/end")
def session_end(body: EndBody):
    s = engine.get_session(body.session_id)
    if not s:
        raise HTTPException(404, "会话不存在")
    result = workers.process_session(s["db_id"])
    engine.SESSIONS.pop(body.session_id, None)
    return result


# ---------------------------------------------------------------- 实时音视频（StepFun / Gemini Live / Volcengine RTC）

@app.websocket("/api/realtime/ws")
async def realtime_ws(ws: WebSocket, session_id: str, provider: str | None = None):
    """浏览器与选定 WebSocket 实时模型之间的代理。"""
    await realtime.bridge(ws, session_id, provider)


class VolcSessionBody(BaseModel):
    session_id: str


class VolcSubtitleBody(BaseModel):
    session_id: str
    speaker_id: str
    text: str = ""
    sequence: int = 0
    round_id: int = 0
    definite: bool = False


@app.post("/api/volcengine/prepare")
def volcengine_prepare(body: VolcSessionBody):
    """Issue a short-lived ByteRTC token after the user clicks Connect."""
    try:
        return volcengine_rtc.prepare(body.session_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/volcengine/start")
def volcengine_start(body: VolcSessionBody):
    """Start the AI after the browser has joined and published audio."""
    try:
        return volcengine_rtc.start(body.session_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/volcengine/observe")
def volcengine_observe(body: VolcSessionBody):
    """Use one idle budget to inspect cached video without interrupting."""
    try:
        return volcengine_rtc.observe(body.session_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/volcengine/subtitle")
def volcengine_subtitle(body: VolcSubtitleBody):
    try:
        return volcengine_rtc.record_subtitle(
            body.session_id,
            body.speaker_id,
            body.text,
            body.sequence,
            body.round_id,
            body.definite,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/volcengine/stop")
def volcengine_stop(body: VolcSessionBody):
    try:
        return volcengine_rtc.stop(body.session_id)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


# ---------------------------------------------------------------- 记忆读取（家长控制台 / 线上分身共用）

@app.get("/api/diary")
def diary():
    return memory.list_diary(CHILD_ID, 50)


@app.get("/api/facts")
def facts():
    rows = memory.list_facts(CHILD_ID)
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        if r["superseded_by"]:
            r["superseded_by_text"] = by_id.get(r["superseded_by"], {}).get("text", "")
    return rows


@app.delete("/api/facts/{fact_id}")
def delete_fact(fact_id: int):
    """家长可见可删 —— 合规答卷的一部分。"""
    db.execute("DELETE FROM facts WHERE id=? AND child_id=?", (fact_id, CHILD_ID))
    return {"ok": True}


@app.get("/api/growth")
def growth():
    return memory.list_snapshots(CHILD_ID)


@app.get("/api/mastery")
def mastery():
    rows = db.q("SELECT * FROM item_mastery WHERE child_id=? ORDER BY item_id", (CHILD_ID,))
    words = [r for r in rows if r["item_type"] == "word"]
    summary = {
        "total": len(words),
        "exposed": sum(1 for r in words if r["level"] in ("exposed", "recognized", "produced")),
        "recognized": sum(1 for r in words if r["level"] in ("recognized", "produced")),
        "produced": sum(1 for r in words if r["level"] == "produced"),
    }
    return {"items": rows, "summary": summary}


@app.get("/api/report")
def report():
    """家长周报：付费按钮所在。"""
    m = mastery()
    diaries = memory.list_diary(CHILD_ID, 7)
    snaps = memory.list_snapshots(CHILD_ID)
    return {
        "mastery": m["summary"],
        "sessions_this_week": db.q1("SELECT COUNT(*) n FROM sessions WHERE child_id=?", (CHILD_ID,))["n"],
        "diary_count": len(diaries),
        "latest_snapshot": snaps[0] if snaps else None,
        "growth_moments": [
            {"before": f["text"], "after": f.get("superseded_by_text", "")}
            for f in facts() if f["superseded_by"]
        ],
        "diary_series": [
            {"date": d["ts"][:10], "topics": d["topics"], "emotions": d["emotions"]}
            for d in reversed(diaries)
        ],
        "vocab_curve": _vocab_curve(),
    }


def _vocab_curve():
    """近 8 天「累计听懂 / 累计说出」曲线，按掌握度表的 last_seen 归到天。"""
    rows = db.q("SELECT level, last_seen FROM item_mastery WHERE child_id=? AND last_seen IS NOT NULL",
                (CHILD_ID,))
    days = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7, -1, -1)]
    curve = []
    for day in days:
        rec = sum(1 for r in rows if r["level"] in ("recognized", "produced") and r["last_seen"][:10] <= day)
        prod = sum(1 for r in rows if r["level"] == "produced" and r["last_seen"][:10] <= day)
        curve.append({"date": day[5:], "recognized": rec, "produced": prod})
    return curve


# ---------------------------------------------------------------- 玩偶的世界（线上分身）

@app.get("/api/world")
def world():
    return {
        "doll": memory.get_card(CHILD_ID, "doll"),
        "canon": db.q("SELECT * FROM doll_canon WHERE child_id=? ORDER BY id DESC", (CHILD_ID,)),
        "arcs": [
            {**a, "beats": db.jloads(a.pop("beats_json"))}
            for a in db.q("SELECT * FROM doll_arcs WHERE child_id=? ORDER BY id DESC", (CHILD_ID,))
        ],
        "events": [
            {**e, "vocab": db.jloads(e.pop("vocab_json"))}
            for e in db.q("SELECT * FROM doll_events WHERE child_id=? ORDER BY ts DESC LIMIT 20", (CHILD_ID,))
        ],
        "agenda": db.q1("SELECT * FROM session_agenda WHERE child_id=? AND date=?", (CHILD_ID, db.today())),
    }


# ---------------------------------------------------------------- 演示控制台（冷路径手动触发）

@app.post("/api/admin/night_planner")
def admin_night_planner():
    return life.night_planner(CHILD_ID)


@app.post("/api/admin/life_tick")
def admin_life_tick():
    return life.life_tick(CHILD_ID)


@app.post("/api/admin/reflect")
def admin_reflect():
    return workers.reflect(CHILD_ID)


@app.post("/api/admin/reseed")
def admin_reseed():
    return seed.seed()


# ---------------------------------------------------------------- 前端

app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND, "assets")), name="assets")


@app.get("/design")
def design():
    return FileResponse(os.path.join(DESIGN, "owling-app-design.html"))


@app.head("/design")
def design_head():
    return FileResponse(os.path.join(DESIGN, "owling-app-design.html"))


@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND, "index.html"))
