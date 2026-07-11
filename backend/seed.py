"""预埋一周假数据 —— 黑客松工程学：demo 不能指望现场积累记忆。

跑完 seed 之后，三个 wow moment 立刻有内容可秀：
1. 纯问候后自然回忆：聊过两轮后择机提起「昨天那只三角龙起好名字了吗？」
2. 玩偶分享今天的生活事件（目标词自然出现）→ 互动拍请孩子做决定 → 写进正典
3. 家长控制台：成长曲线、被作废的旧事实（成长感）、本周报告
"""
import json
import os
from datetime import datetime, timedelta

from . import db, life, media, memory

CHILD_ID = db.CHILD_ID


def _d(days_ago: int, hm: str = "19:30") -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime(f"%Y-%m-%d {hm}:00")


def _day(days_ago: int) -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def load_curriculum():
    path = os.path.join(os.path.dirname(__file__), "curriculum", "pep_grade3_unit4.json")
    with open(path, encoding="utf-8") as f:
        pack = json.load(f)
    db.execute(
        "INSERT OR REPLACE INTO curriculum_packs(id,publisher,grade,semester,title,units_json) VALUES(?,?,?,?,?,?)",
        (pack["id"], pack["publisher"], pack["grade"], pack["semester"], pack["title"],
         json.dumps(pack["units"], ensure_ascii=False)))
    return pack["id"]


def wipe():
    conn = db.get_conn()
    for t in ["pocket_entries", "keepsakes", "generation_jobs", "moments", "world_assignments",
              "children", "core_cards", "diary_entries", "facts", "growth_snapshots",
              "learning_state", "item_mastery", "doll_canon", "doll_arcs", "doll_events",
              "session_agenda", "sessions"]:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()


def _seed_experience() -> dict:
    """Give child/parent demos useful projection content before live memory exists."""
    now = datetime.now().astimezone()
    specs = [
        {
            "source_id": "acorn-cake-fork",
            "event_key": "canon_choice",
            "event_value": "橡果味",
            "idempotency_key": "seed:moment:birthday-party:v1",
            "job_key": "seed:job:birthday-party:1",
            "asset_id": "choice-cake-v1",
            "asset_group": "moment-choice-cake",
            "days_ago": 2,
            "minutes_ago": 21,
            "title": "橡果味的生日蛋糕",
            "story": (
                "你帮灵灵选了橡果味。第一口蛋糕切下来时，它把小叉子擦干净，"
                "说这口要留给你。"
            ),
            "keepsake": {
                "name": "橡果蛋糕的小叉子",
                "description": "松鼠先生生日会那天",
                "appearance": "cake clay fork",
                "image_url": None,
            },
        },
        {
            "source_id": "kite-ribbon",
            "event_key": "word_taught",
            "event_value": "kite",
            "idempotency_key": "seed:moment:kite:v1",
            "job_key": "seed:job:kite:1",
            "asset_id": "word-kite-v1",
            "asset_group": "moment-word-kite",
            "days_ago": 3,
            "minutes_ago": 46,
            "title": "蓝色尾带追上了风",
            "story": (
                "山坡上的风刚刚好。灵灵把蓝色尾带系到风筝上，跟着你小声念："
                "kite, fly!"
            ),
            "keepsake": {
                "name": "蓝色风筝尾带",
                "description": "山坡上的风刚刚好",
                "appearance": "mist blue kite ribbon",
                "image_url": None,
            },
        },
        {
            "source_id": "bedtime-lamp",
            "event_key": "growth_change",
            "event_value": "fear_dark",
            "idempotency_key": "seed:moment:bedtime-lamp:v1",
            "job_key": "seed:job:bedtime-lamp:1",
            "asset_id": "growth-stars-v1",
            "asset_group": "moment-growth-stars",
            "days_ago": 4,
            "minutes_ago": 78,
            "title": "晚安灯芯亮起来",
            "story": (
                "夜里风声很轻。灵灵把小夜灯调到星星一样的亮度，陪你一起把"
                "今天收好。"
            ),
            "keepsake": {
                "name": "晚安灯芯",
                "description": "第一次一起收好夜晚",
                "appearance": "star light candle gold",
                "image_url": None,
            },
        },
        {
            "source_id": "bridge-leaf",
            "event_key": "story_beat",
            "event_value": "bridge_leaf",
            "idempotency_key": "seed:moment:bridge-leaf:v1",
            "job_key": "seed:job:bridge-leaf:1",
            "asset_id": "story-party-v1",
            "asset_group": "moment-story-party",
            "days_ago": 5,
            "minutes_ago": 112,
            "title": "雨停后的小木桥",
            "story": (
                "雨停以后，橡树村的小木桥还亮着水光。灵灵捡起一片叶子，说"
                "它像一张回家的小地图。"
            ),
            "keepsake": {
                "name": "小木桥的叶子",
                "description": "雨停以后",
                "appearance": "green leaf pea bridge",
                "image_url": None,
            },
        },
        {
            "source_type": "world_seed",
            "source_id": "dinner-cooking",
            "event_key": "story_beat",
            "event_value": "dinner_cooking",
            "idempotency_key": "seed:moment:dinner-cooking:v1",
            "job_key": "seed:job:dinner-cooking:1",
            "asset_id": "dinner-cooking-v1",
            "asset_group": "moment-dinner-cooking",
            "local_time": "18:32",
            "title": "晚餐时间的橡果饭",
            "story": (
                "同一天晚餐时，灵灵把炉火调小，用木勺把热乎乎的橡果饭盛进"
                "盘子里。它说要先尝一口，看看够不够香。"
            ),
            "keepsake": None,
        },
    ]

    moment_ids: list[int] = []
    for spec in specs:
        if "local_time" in spec:
            hour, minute = (int(part) for part in spec["local_time"].split(":", 1))
            published_dt = now.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if published_dt > now:
                published_dt -= timedelta(days=1)
        else:
            published_dt = now - timedelta(
                days=spec["days_ago"], minutes=spec["minutes_ago"]
            )
        created_dt = published_dt - timedelta(minutes=1)
        published_at = published_dt.isoformat(timespec="seconds")
        created_at = created_dt.isoformat(timespec="seconds")
        local_date = published_dt.date().isoformat()
        asset = media.default_catalog().asset(spec["asset_id"])
        asset_json = json.dumps(
            media.asset_snapshot(asset, provider="mock"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        db.execute(
            "INSERT INTO moments("
            "child_id,source_type,source_id,event_key,event_value,semantic_version,"
            "idempotency_key,local_date,title,story,status,published_asset_id,"
            "published_asset_json,created_at,published_at,error_code) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,'published',?,?,?,?, '') "
            "ON CONFLICT(idempotency_key) DO UPDATE SET "
            "source_type=excluded.source_type,source_id=excluded.source_id,"
            "event_key=excluded.event_key,event_value=excluded.event_value,"
            "semantic_version=excluded.semantic_version,local_date=excluded.local_date,"
            "title=excluded.title,story=excluded.story,status='published',"
            "published_asset_id=excluded.published_asset_id,"
            "published_asset_json=excluded.published_asset_json,"
            "published_at=excluded.published_at,error_code=''",
            (
                CHILD_ID,
                spec.get("source_type", "seed"),
                spec["source_id"],
                spec["event_key"],
                spec["event_value"],
                1,
                spec["idempotency_key"],
                local_date,
                spec["title"],
                spec["story"],
                spec["asset_id"],
                asset_json,
                created_at,
                published_at,
            ),
        )
        moment_id = db.q1(
            "SELECT id FROM moments WHERE idempotency_key=?",
            (spec["idempotency_key"],),
        )["id"]
        moment_ids.append(moment_id)
        db.execute(
            "INSERT INTO generation_jobs("
            "moment_id,attempt,media_kind,provider,asset_group,status,asset_id,"
            "idempotency_key,created_at,ready_at,updated_at) "
            "VALUES(?,?,?,?,?,'succeeded',?,?,?, ?, ?) "
            "ON CONFLICT(idempotency_key) DO UPDATE SET "
            "moment_id=excluded.moment_id,media_kind=excluded.media_kind,"
            "provider=excluded.provider,asset_group=excluded.asset_group,"
            "status='succeeded',asset_id=excluded.asset_id,"
            "ready_at=excluded.ready_at,updated_at=excluded.updated_at,error_code=''",
            (
                moment_id,
                1,
                asset["media_kind"],
                "mock",
                spec["asset_group"],
                spec["asset_id"],
                spec["job_key"],
                created_at,
                published_at,
                published_at,
            ),
        )
        keepsake = spec.get("keepsake")
        if keepsake is not None:
            db.execute(
                "INSERT INTO keepsakes("
                "child_id,moment_id,name,description,appearance,image_url,created_at) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(moment_id) DO UPDATE SET "
                "name=excluded.name,description=excluded.description,"
                "appearance=excluded.appearance,image_url=excluded.image_url",
                (
                    CHILD_ID,
                    moment_id,
                    keepsake["name"],
                    keepsake["description"],
                    keepsake["appearance"],
                    keepsake["image_url"],
                    published_at,
                ),
            )
            keepsake_id = db.q1(
                "SELECT id FROM keepsakes WHERE moment_id=?", (moment_id,)
            )["id"]
            db.execute(
                "INSERT INTO pocket_entries("
                "child_id,keepsake_id,collected,collected_at,updated_at) "
                "VALUES(?,?,1,?,?) ON CONFLICT(child_id,keepsake_id) DO UPDATE SET "
                "collected=1,"
                "collected_at=COALESCE(pocket_entries.collected_at,excluded.collected_at),"
                "updated_at=excluded.updated_at",
                (CHILD_ID, keepsake_id, published_at, published_at),
            )
    _retire_stale_experience_seed(
        {
            spec["idempotency_key"]
            for spec in specs
        }
    )
    return {
        "published_moment_id": moment_ids[0],
        "published_moment_ids": moment_ids,
        "seeded_keepsakes": sum(1 for spec in specs if spec.get("keepsake") is not None),
        "rendering_moment_id": None,
    }


def _retire_stale_experience_seed(active_keys: set[str]) -> None:
    stale_keys = {
        "seed:moment:star-lamp:v1",
        "seed:moment:oak-bridge:v1",
    } - active_keys
    if not stale_keys:
        return
    placeholders = ",".join("?" for _ in stale_keys)
    params = tuple(sorted(stale_keys))
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    db.execute(
        f"UPDATE pocket_entries SET collected=0,collected_at=NULL,updated_at=? "
        f"WHERE keepsake_id IN ("
        f"SELECT k.id FROM keepsakes k JOIN moments m ON m.id=k.moment_id "
        f"WHERE m.idempotency_key IN ({placeholders}))",
        (now, *params),
    )
    db.execute(
        f"UPDATE moments SET status='failed',error_code='retired_seed' "
        f"WHERE idempotency_key IN ({placeholders})",
        params,
    )


def ensure_experience_seeded() -> dict:
    """Backfill only demo projection objects; never touch the memory fact source."""
    return _seed_experience()


def seed():
    wipe()
    pack_id = load_curriculum()

    # ---- 孩子 + 双卡（L1）
    db.execute(
        "INSERT INTO children(id,name,age,grade,family_json,interests_json,taboo_json,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (CHILD_ID, "悠悠", 8, "三年级",
         json.dumps(["妈妈", "爸爸", "小猫团团"], ensure_ascii=False),
         json.dumps(["恐龙", "画画", "动物"], ensure_ascii=False),
         json.dumps(["恐怖故事", "考试成绩比较"], ensure_ascii=False), db.now()))
    memory.save_card(CHILD_ID, "child", {
        "name": "悠悠", "age": 8, "grade": "三年级",
        "family": ["妈妈", "爸爸", "小猫团团"],
        "interests": ["恐龙", "画画", "动物"],
        "fears": ["打雷"],
        "language_level": "在学人教PEP三年级上册，能听懂简单英语词",
    })
    memory.save_card(CHILD_ID, "doll", {
        "name": "灵灵", "species": "小狐狸",
        "persona": "好奇的探险家：爱收集橡果和新鲜事，胆子不大但嘴很硬，最怕痒",
        "mood": "elated", "energy": "满格",
        "relationship_stage": "good_friend", "relationship_xp": 62,
        "growth_level": 3,
        "running_gags": ["数橡果比赛我从来没赢过松鼠先生", "蓝秋千是悠悠选的颜色"],
    })

    # ---- 教材进度 + 掌握度（有历史，曲线才好看）
    db.execute("INSERT INTO learning_state(child_id,pack_id,current_unit) VALUES(?,?,4)",
               (CHILD_ID, pack_id))
    life.ensure_mastery_rows(CHILD_ID)
    history = [
        ("u4:word:cat", "produced", 5, 4, 8, 1),
        ("u4:word:dog", "produced", 5, 4, 8, 2),
        ("u4:word:duck", "produced", 4, 3, 4, 1),
        ("u4:word:panda", "produced", 4, 3, 4, 2),
        ("u4:word:monkey", "recognized", 3, 2, 2, 1),
        ("u4:word:bird", "recognized", 3, 2, 2, 3),
        ("u4:word:bear", "exposed", 2, 0, 1, 0),
        ("u4:word:funny", "exposed", 2, 1, 2, 2),
        ("u4:word:zoo", "exposed", 1, 0, 1, 0),
    ]
    for item_id, level, exp, suc, interval, last_days in history:
        db.execute(
            "UPDATE item_mastery SET level=?,exposures=?,successes=?,interval_days=?,last_seen=?,due_date=? "
            "WHERE child_id=? AND item_id=?",
            (level, exp, suc, interval, _d(last_days), _day(0), CHILD_ID, item_id))
    # tiger / elephant / 句型保持 new、今天到期 → 夜间规划器有的挑

    # ---- L3 事实（含被作废的旧事实 —— 成长感藏在这里）
    old_fear = memory.add_fact(CHILD_ID, "有点怕黑，睡觉要开灯", "fear", "dark",
                               0.9, "session:seed", valid_from=_day(21))
    new_fear = memory.add_fact(CHILD_ID, "已经不怕黑了，因为有了恐龙小夜灯", "fear", "dark",
                               0.9, "session:seed", valid_from=_day(4))
    db.execute("UPDATE facts SET superseded_by=? WHERE id=?", (new_fear, old_fear))
    for text, cat, key, days in [
        ("最喜欢三角龙，觉得它的三只角很帅", "interest", "dinosaur", 12),
        ("家里有一只小猫叫团团", "family", "pet-cat", 18),
        ("最好的朋友叫朵朵，两人常一起跳皮筋", "friend", "duoduo", 15),
        ("喜欢画画，尤其爱画动物", "interest", "drawing", 10),
        ("妈妈喜欢烤饼干", "family", "mom-baking", 6),
    ]:
        memory.add_fact(CHILD_ID, text, cat, key, 0.85, "session:seed", valid_from=_day(days))

    # ---- L2 七天日记（最后一条带 open_loop → 会话后段可用的关系线索）
    diaries = [
        (7, "悠悠第一次给灵灵讲了幼儿园的朵朵，两人约好周末跳皮筋。", ["开心"], ["朋友"],
         ["朵朵跳皮筋可厉害了"], ""),
        (6, "聊了小猫团团打翻水杯的事，悠悠学团团叫，笑个不停。", ["开心"], ["家人", "动物"],
         ["团团超级调皮的"], ""),
        (5, "悠悠说白天打雷有点怕，灵灵陪她数了雷声，后来就不怕了。", ["害怕", "平静"], ["情绪"],
         ["打雷的时候我抱着团团"], ""),
        (4, "悠悠骄傲地宣布自己不怕黑了，因为有了恐龙小夜灯。", ["骄傲"], ["恐龙", "成长"],
         ["我现在自己关灯睡觉！"], ""),
        (3, "一起看了动物图鉴，悠悠用英语说出了 panda 和 duck，特别得意。", ["兴奋", "骄傲"], ["动物", "英语"],
         ["panda！我还会说 duck！"], ""),
        (2, "悠悠画了一张三角龙在橡树村荡秋千的画，说要贴在床头。", ["开心"], ["恐龙", "画画", "玩偶的世界"],
         ["三角龙也想玩你们的蓝秋千"], ""),
        (1, "悠悠说朵朵送了她一只三角龙玩具，她要给它起一个最帅的名字。", ["兴奋"], ["恐龙", "朋友"],
         ["我要给它起个全世界最帅的名字"], "昨天你说要给那只三角龙起名字，起好了吗？"),
    ]
    for days, summary, emotions, topics, quotes, loop in diaries:
        memory.add_diary(CHILD_ID, summary, emotions, topics, quotes, loop, ts=_d(days))

    # ---- L4 成长快照（上周的，作为对照）
    memory.add_snapshot(
        CHILD_ID, f"上周（{_day(13)} ~ {_day(7)}）",
        interests=["动物", "画画"], new_vocab=["cat（猫）", "dog（狗）"],
        emotions=["开心", "平静"],
        milestones=["第一次主动用英语说出 cat 和 dog", "开始每天主动找灵灵聊天"],
        doll_diary_text="这个星期悠悠教我认识了她的朋友朵朵。我发现她说英语的时候会先看看我，"
                        "我就使劲点头。她在长大，我也在长大。")

    # ---- 世界正典（Canon）：没有这张账本，数字生命三天就穿帮
    for entity, fact, by_child, days in [
        ("橡树村", "灵灵住在橡树村最高的那棵橡树下", 0, 30),
        ("松鼠先生", "灵灵最好的朋友，数橡果从来没输过", 0, 28),
        ("刺猬阿姨", "村里的面包师，烤的橡果饼干全村最香", 0, 25),
        ("蓝秋千", "灵灵和松鼠先生修好的旧秋千，悠悠决定漆成蓝色，现在大家都叫它蓝秋千", 1, 9),
        ("数橡果比赛", "橡树村每月一次的传统比赛，灵灵至今没赢过", 0, 20),
    ]:
        db.execute(
            "INSERT INTO doll_canon(child_id,entity,fact_text,by_child,established_at) VALUES(?,?,?,?,?)",
            (CHILD_ID, entity, fact, by_child, _d(days)))

    # ---- 故事弧：进行到第 3 拍
    arc_id = db.execute(
        "INSERT INTO doll_arcs(child_id,title,beats_json,current_beat,status) VALUES(?,?,?,?, 'active')",
        (CHILD_ID, "帮松鼠先生筹备生日会",
         json.dumps([
             "发现松鼠先生的生日快到了，偷偷开了个小会",
             "和刺猬阿姨定制橡果蛋糕，差点被松鼠先生撞见",
             "去森林动物园(zoo)请动物朋友们来参加，路上看到了 panda 和 monkey",
             "布置蓝秋千旁边的场地，挂上悠悠画里那样的彩带",
             "生日会当天！给松鼠先生一个大惊喜",
         ], ensure_ascii=False), 3))

    # ---- 玩偶生活事件：两条已分享的历史 + 一条今天待分享（含目标词 + 互动拍）
    for text, days, vocab, status in [
        ("我和松鼠先生终于把旧秋千修好啦！悠悠说漆成蓝色，现在全村都叫它蓝秋千。", 9, [], "shared"),
        ("我们发现松鼠先生的生日快到了！我和刺猬阿姨躲在面包房里开了个秘密小会。", 3, [], "shared"),
    ]:
        db.execute(
            "INSERT INTO doll_events(child_id,ts,text,arc_id,vocab_json,share_status) VALUES(?,?,?,?,?,?)",
            (CHILD_ID, _d(days), text, arc_id, json.dumps(vocab, ensure_ascii=False), status))
    today_event = db.execute(
        "INSERT INTO doll_events(child_id,ts,text,arc_id,vocab_json,share_status,interactive_question) "
        "VALUES(?,?,?,?,?,?,?)",
        (CHILD_ID, _d(0, "07:10"),
         "为了松鼠先生的生日会，我今天去了森林动物园（zoo）送请柬！我见到了 panda（就是熊猫呀），"
         "还有一只 monkey（猴子）一直学我走路，太 funny 啦，就是特别好笑！",
         arc_id, json.dumps(["zoo", "panda", "monkey", "funny"], ensure_ascii=False), "unshared",
         "生日会的蛋糕，你说是做橡果味的还是蜂蜜味的呀？"))

    # ---- 今日议程（夜间规划器的产出，热路径开场直接用）
    review_items = [
        {"item_id": "u4:word:zoo", "word": "zoo", "zh": "动物园", "type": "word", "level": "exposed"},
        {"item_id": "u4:word:monkey", "word": "monkey", "zh": "猴子", "type": "word", "level": "recognized"},
        {"item_id": "u4:word:funny", "word": "funny", "zh": "滑稽的、好笑的", "type": "word", "level": "exposed"},
        {"item_id": "u4:word:panda", "word": "panda", "zh": "熊猫", "type": "word", "level": "produced"},
    ]
    db.execute(
        "INSERT OR REPLACE INTO session_agenda(child_id,date,review_items_json,share_event_id,memory_hook,status) "
        "VALUES(?,?,?,?,?,'ready')",
        (CHILD_ID, db.today(), json.dumps(review_items, ensure_ascii=False), today_event,
         "昨天你说要给那只三角龙起名字，起好了吗？"))

    experience_seed = _seed_experience()
    return {"child": "悠悠", "doll": "灵灵", "diaries": len(diaries),
            "seeded": True, **experience_seed}


def is_seeded() -> bool:
    return db.q1("SELECT id FROM children LIMIT 1") is not None
