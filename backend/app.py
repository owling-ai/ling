"""「灵」后端服务。

一套记忆服务，三个客户端：玩偶实时端（网页模拟）/ 线上 agent 分身 / 家长控制台。
启动：uvicorn backend.app:app --reload
"""
import json
import hmac
import ipaddress
import os
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from . import (  # noqa: E402
    db,
    engine,
    experience,
    jimeng_video,
    life,
    llm,
    media,
    media_worker,
    memory,
    realtime,
    seed,
    volcengine_rtc,
    workers,
)

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

_PROTECTED_API_PATHS = {
    "/api/state",
    "/api/onboarding",
    "/api/curriculum",
    "/api/diary",
    "/api/facts",
    "/api/growth",
    "/api/mastery",
    "/api/report",
    "/api/world",
}
_PROTECTED_API_PREFIXES = (
    "/api/admin/",
    "/api/facts/",
    "/api/session/",
    "/api/volcengine/",
    "/api/realtime/",
)


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or bool(mapped and mapped.is_loopback)


def _allow_unauthenticated() -> bool:
    return os.environ.get("LING_ALLOW_UNAUTHENTICATED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _has_proxy_headers(headers) -> bool:
    return any(
        headers.get(header)
        for header in ("forwarded", "x-forwarded-for", "x-real-ip")
    )


def _is_local_request(request: Request) -> bool:
    client_host = request.client.host if request.client else ""
    if client_host == "testclient":
        return True
    if _has_proxy_headers(request.headers):
        return False
    destination_host = request.url.hostname or ""
    return _is_loopback_host(client_host) and _is_loopback_host(destination_host)


def _has_debug_access(request: Request) -> bool:
    if _allow_unauthenticated():
        return True
    if _is_local_request(request):
        return True
    return _has_admin_token(request.headers)


def _has_admin_token(headers) -> bool:
    expected = os.environ.get("LING_ADMIN_TOKEN", "").strip()
    scheme, separator, supplied = headers.get("authorization", "").partition(" ")
    return bool(
        expected
        and separator
        and scheme.lower() == "bearer"
        and hmac.compare_digest(supplied.strip(), expected)
    )


def _has_websocket_debug_access(ws: WebSocket) -> bool:
    if _allow_unauthenticated():
        return True
    client_host = ws.client.host if ws.client else ""
    if client_host == "testclient":
        return True
    has_proxy_headers = _has_proxy_headers(ws.headers)
    destination_host = ws.url.hostname or ""
    if (
        not has_proxy_headers
        and _is_loopback_host(client_host)
        and _is_loopback_host(destination_host)
    ):
        return True
    return _has_admin_token(ws.headers)


def _is_protected_api(request: Request) -> bool:
    path = request.url.path
    return (
        request.method == "DELETE"
        or path in _PROTECTED_API_PATHS
        or path.startswith(_PROTECTED_API_PREFIXES)
    )


@app.middleware("http")
async def protect_private_apis(request: Request, call_next):
    is_api = request.url.path.startswith("/api/")
    if (
        is_api
        and request.method != "OPTIONS"
        and _is_protected_api(request)
        and not _has_debug_access(request)
    ):
        response = JSONResponse(
            status_code=403,
            content={"detail": "该接口仅允许本机访问或使用管理令牌"},
        )
    else:
        try:
            response = await call_next(request)
        except Exception:
            if not is_api:
                raise
            response = JSONResponse(
                status_code=500,
                content={"detail": "服务暂时不可用，请稍后重试"},
            )
    if is_api:
        response.headers["Cache-Control"] = "private, no-store"
    return response

CHILD_ID = db.CHILD_ID
FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")
DEMO_MEDIA = os.path.join(os.path.dirname(__file__), "demo_media")
GENERATED_MEDIA = str(jimeng_video.generated_media_root())
os.makedirs(GENERATED_MEDIA, exist_ok=True)


@app.on_event("startup")
def startup():
    db.init_db()
    media.default_catalog(reload=True)
    experience_service = experience.default_service(reload=True)
    if not seed.is_seeded():
        seed.seed()
    seed.ensure_experience_seeded()
    experience_service.backfill_published_asset_snapshots()
    media_worker.start_default(experience_service)
    media_mode = jimeng_video.provider_mode_info()
    info = llm.mode_info()
    rt = realtime.info()
    live = ", ".join(
        f"{name}={'on' if config['available'] else 'off'}"
        for name, config in rt["providers"].items()
    )
    degraded = (
        f" · degraded={media_mode['degraded_reason']}"
        if media_mode["degraded"]
        else ""
    )
    print(
        f"[realtime] 实时语音：{live} · default={rt['default_provider']}\n"
        f"[llm] 冷路径（记忆工人）：{info['worker_provider']} · {info['worker_model']}\n"
        f"[media] 视频生成：{experience_service.provider.name}{degraded}",
        flush=True,
    )


@app.on_event("shutdown")
def shutdown():
    media_worker.stop_default()


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
    started = engine.start_session(CHILD_ID)
    return {
        "session_id": started["session_id"],
        "opening": started["opening"],
        "review_items": started["memory_pack"].get("review_items", []),
    }


class EndBody(BaseModel):
    session_id: str


@app.post("/api/session/end")
def session_end(body: EndBody):
    def finalize(session: dict) -> dict:
        result = workers.process_session(session["db_id"])
        moment = experience.default_service().settle_session(session, result)
        return {**result, "moment": moment}

    result = engine.close_session(body.session_id, finalize)
    if result is None:
        raise HTTPException(404, "会话不存在")
    return result


# ---------------------------------------------------------------- 实时音视频（StepFun / Gemini Live / MiniCPM-o / Volcengine RTC）

@app.websocket("/api/realtime/ws")
async def realtime_ws(
    ws: WebSocket,
    session_id: str,
    provider: str | None = None,
    video: bool = False,
    voice_profile: str | None = None,
):
    """浏览器与选定 WebSocket 实时模型之间的代理。"""
    if not _has_websocket_debug_access(ws):
        await ws.close(code=1008, reason="该接口仅允许本机访问或使用管理令牌")
        return
    await realtime.bridge(
        ws,
        session_id,
        provider,
        video,
        voice_profile=voice_profile,
    )


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


# ---------------------------------------------------------------- 体验投影（孩子端 / 家长端）

class PocketBody(BaseModel):
    collected: bool


class DemoMomentBody(BaseModel):
    event_key: str
    event_value: str
    source_id: str = "rehearsal"


@app.get("/api/child/world/now")
def child_world_now():
    return experience.default_service().child_world_now(CHILD_ID)


@app.get("/api/child/feed")
def child_feed():
    return experience.default_service().child_feed(CHILD_ID)


@app.get("/api/moments/{moment_id}")
def moment_detail(moment_id: int):
    try:
        return experience.default_service().refresh_moment(moment_id)
    except experience.ExperienceNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/pocket")
def pocket():
    return experience.default_service().pocket(CHILD_ID)


@app.put("/api/pocket/{keepsake_id}")
def set_pocket(keepsake_id: int, body: PocketBody):
    try:
        return experience.default_service().set_pocket(
            CHILD_ID, keepsake_id, body.collected
        )
    except experience.ExperienceNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/parent/today")
def parent_today():
    return experience.default_service().parent_today(CHILD_ID)


@app.get("/api/parent/growth")
def parent_growth(period: str = "week"):
    return experience.default_service().parent_growth(CHILD_ID, period=period)


@app.get("/api/parent/memory")
def parent_memory(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
):
    return experience.default_service().parent_memory(
        CHILD_ID, cursor=cursor, limit=limit
    )


@app.get("/api/parent/guardian")
def parent_guardian():
    return experience.default_service().parent_guardian(CHILD_ID)


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


@app.post("/api/admin/demo-moment")
def admin_demo_moment(body: DemoMomentBody):
    field = experience.EVENT_VALUE_FIELDS.get(body.event_key)
    if not field:
        raise HTTPException(400, "不支持的演示事件")
    return experience.default_service().settle_candidate(
        CHILD_ID,
        "demo",
        body.source_id,
        body.event_key,
        {field: body.event_value},
    )


@app.get("/api/admin/media/jobs")
def admin_media_jobs(limit: int = Query(default=50, ge=1, le=200)):
    service = experience.default_service()
    worker = media_worker.default_worker()
    mode = jimeng_video.provider_mode_info()
    return {
        "provider": service.provider.name,
        "requested_provider": mode["requested_provider"],
        "api_key_configured": mode["api_key_configured"],
        "degraded": mode["degraded"],
        "degraded_reason": mode["degraded_reason"],
        "worker_running": bool(worker and worker.is_running),
        "jobs": media_worker.job_summaries(limit),
    }


@app.post("/api/admin/media/tick")
def admin_media_tick():
    service = experience.default_service()
    worker = media_worker.default_worker() or media_worker.MediaGenerationWorker(service)
    return worker.run_once()


@app.post("/api/admin/reseed")
def admin_reseed():
    return seed.seed()


# ---------------------------------------------------------------- 前端


app.mount("/demo-media", StaticFiles(directory=DEMO_MEDIA), name="demo-media")
app.mount(
    "/generated-media",
    StaticFiles(directory=GENERATED_MEDIA),
    name="generated-media",
)
app.mount("/child", StaticFiles(directory=os.path.join(FRONTEND, "child"), html=True), name="child-app")
app.mount("/parent", StaticFiles(directory=os.path.join(FRONTEND, "parent"), html=True), name="parent-app")
app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND, "assets")), name="assets")


@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND, "index.html"))
