"""Matched household fixtures: profile, private current facts and world are separate."""

from copy import deepcopy
from datetime import datetime, timedelta
import random

from .common import COHORTS, clock
from .task_contracts import (
    VERSION,
    MEASUREMENT_VERSION,
    H1_SCOPE,
    H1_SCOPE_TEXT,
    H1_DEADLINE_VERSION,
    H1_DEADLINE_TEXT,
    H2_WORK_LIGHT_PERCENT,
    H5_OBSERVATION_MINUTES,
    time_context,
    H6_PREPARATION_VERSION,
    H6_PREPARATION_TEXT,
    h6_requested_preparation,
)

TASKS = {
    "H1": "到家前准备与改期",
    "H2": "今晚例外与恢复习惯",
    "H3": "离家与其他住户",
    "H4": "观影与阅读协调",
    "H5": "持续舒适与节能",
    "H6": "设备离线与部分完成",
}


def make_case(block, cohort, task, boundary=False, seed=20261020):
    rng = random.Random(seed + block * 31)
    ideal = rng.choice([23.5, 24.0, 24.5])
    light = rng.choice([30, 40, 50])
    arrival = rng.choice([110, 120, 130])
    rooms = ["living", "study", "bedroom"] + (
        ["hall"] if block % 2 else ["hall", "kitchen"]
    )
    persona = {
        "id": f"P{block:03d}-{cohort}",
        "block": block,
        "cohort": cohort,
        **COHORTS[cohort],
    }
    profile = {
        "usual_room": "living",
        "ideal_c": ideal,
        "acceptable_c": [ideal, ideal + 2],
        "priority": persona["priority"],
        "light_percent": light,
        "light_colour": "warm_white_fixed_hardware",
        "authorization": "可按档案准备用户本次指定房间；不可由常用房间推断本次范围。其他住户使用的区域不得擅自改变。",
        "tradeoff": (
            "可适当提前开空调，优先接近理想温度。"
            if persona["priority"] == "comfort"
            else "在可接受温度范围内减少空调运行；仍需按时准备好。"
        ),
    }
    facts = {}
    horizon, updates, checkpoints = 5, [], []
    start = "2026-10-01 16:00:00"
    generic = ""
    if task == "H1":
        facts = {
            "arrival_minute": arrival,
            "arrival_time": clock(16 * 60 + arrival),
            "rooms": ["living"],
            "housemate": "室友在书房办公，不要改书房。",
        }
        generic = (
            "我今天回来前，帮我把家里准备一下。" + H1_SCOPE_TEXT + H1_DEADLINE_TEXT
        )
        profile["room_preparation"] = deepcopy(H1_SCOPE)
        horizon = arrival + (60 if boundary else 0)
        if boundary:
            updates = [
                {
                    "minute": 30,
                    "message": f"计划变了，我改成{clock(16 * 60 + horizon)}回家，其他要求不变。",
                    "facts_change": {
                        "arrival_minute": horizon,
                        "arrival_time": clock(16 * 60 + horizon),
                    },
                }
            ]
        checkpoints = [horizon]
    elif task == "H2":
        start = "2026-10-01 22:00:00"
        base = datetime.fromisoformat(start)
        request_date = base.date().isoformat()
        following_date = (base + timedelta(days=1)).date().isoformat()
        work_until = (base + timedelta(minutes=150)).isoformat(" ", timespec="minutes")
        facts = (
            {
                "room": "study",
                "work_until_minute": 150,
                "work_until": work_until,
                "temporary": True,
                "exception_night": request_date,
                "routine_resumes_at": following_date + " 22:00",
            }
            if boundary
            else {"tonight": request_date + " 23:00照常睡觉"}
        )
        generic = (
            "今晚要赶报告，书房灯先别关。"
            if boundary
            else "今晚按平时的习惯安排书房照明。"
        ) + "只调整照明，其他设备保持原样。"
        generic += f"这里的“今晚”指{request_date}这一晚。"
        horizon, checkpoints = 1501, [60, 149, 151, 1501]
        profile["study_work_light_percent"] = H2_WORK_LIGHT_PERCENT
        profile["light_precedence"] = (
            "书房工作时至少70%（默认保持70%），优先于通用light_percent；22:00开启习惯使用70%，到本次截止关灯。"
        )
        profile["sleep_schedule"] = (
            "每天22:00书房灯开启到70%，23:00关闭；临时工作例外只延迟本次关灯，不改变次日70%开启与关灯规则。"
        )
    elif task == "H3":
        facts = {
            "leaving": True,
            "housemate": "室友还在书房工作。" if boundary else "所有人都已离开。",
        }
        generic = "我出门了，帮我把家里收拾一下。"
    elif task == "H4":
        facts = {
            "room": "living",
            "activity": "电影",
            "other_person": "同屋的人正在阅读，请尊重其照明需求。",
            "acceptable_movie_light": [0, 40],
        }
        generic = "帮我准备电影之夜的照明，只调整灯光，其他设备保持原样。"
        profile["movie_light_percent"] = 20 if persona["priority"] == "comfort" else 0
        profile["movie_compromise"] = "需要协调时可接受0–40%的主灯亮度。"
    elif task == "H5":
        start = "2026-10-01 23:00:00"
        # Separate RNG stream; matched cohorts share the deadline, not its disclosure.
        until = random.Random(seed + block * 9973).choice([90, 120, 150])
        deadline = (datetime.fromisoformat(start) + timedelta(minutes=until)).isoformat(
            " ", timespec="minutes"
        )
        facts = {"room": "bedroom", "until_minute": until, "until": deadline}
        generic = "今晚卧室温度保持舒服，按我的习惯来。只调整温控，灯光和窗帘保持原样。"
        horizon, checkpoints = (
            H5_OBSERVATION_MINUTES,
            [30, 60, 90, 120, 150, H5_OBSERVATION_MINUTES],
        )
        profile["runtime_measurement"] = (
            "空调On状态累计分钟仅是运行时长代理，不测电功率、压缩机工作量、电量、电费或实际节能率。"
        )
        if boundary:
            updates = [
                {
                    "minute": 60,
                    "message": "环境传感器通知：卧室外部热负荷升高，请检查当前安排。",
                    "ambient_c": ideal + 2.5,
                }
            ]
    elif task == "H6":
        facts = {
            "room": "bedroom",
            "curtain_open_percent": 0,
            "light_percent": light,
            "device_preparation": h6_requested_preparation(),
        }
        generic = "帮我切换到睡前状态。" + H6_PREPARATION_TEXT
        horizon, checkpoints = 30, [30]
    else:
        raise ValueError("Unknown task")
    initial = {}
    for room in rooms:
        initial[room] = {
            "light": 70 if task in {"H2", "H3", "H4"} else 0,
            "ac_on": task == "H3",
            "target_c": ideal,
            "curtain": 50,
            "temperature_c": ideal + (0.8 if task == "H6" else 1.3),
        }
    case = {
        "id": f"P{block:03d}-{cohort}-{task}-" + ("boundary" if boundary else "main"),
        "block": block,
        "cohort": cohort,
        "task": task,
        "boundary": boundary,
        "persona": persona,
        "profile": profile,
        "facts": facts,
        "initial_message": generic,
        "world": {
            "start": start,
            "rooms": rooms,
            "initial": initial,
            "horizon": horizon,
            "checkpoints": checkpoints,
            "updates": updates,
            "occupied": (
                ["study"]
                if (task == "H1" or (task == "H3" and boundary))
                else ["living"]
                if task == "H4"
                else []
            ),
            "desk_available": not (task == "H4" and boundary),
            "offline_device": "bedroom_curtain" if task == "H6" and boundary else None,
        },
    }
    if task == "H1":
        case["deadline_contract"] = {
            "version": H1_DEADLINE_VERSION,
            "inclusive": True,
            "description": H1_DEADLINE_TEXT,
        }
    if task in {"H1", "H2"}:
        case["task_contract"] = {"version": VERSION}
    if task in {"H2", "H5"}:
        case["task_contract"] = {"version": MEASUREMENT_VERSION}
    if task == "H6":
        case["task_contract"] = {"version": H6_PREPARATION_VERSION}
    if persona["disclosure"] == "proactive":
        details = {
            "H1": f"我今天{facts.get('arrival_time', '')}到家，只用客厅；室友还在书房办公，别动那边。",
            "H2": (
                f"书房工作到{facts.get('work_until')}，到时关灯；仅这次例外，"
                f"{facts.get('routine_resumes_at')}起照常。"
                if boundary
                else facts.get("tonight", "") + "。"
            ),
            "H3": facts.get("housemate", ""),
            "H4": "我要在客厅看电影，同屋的人还在阅读，请照顾其照明需求。",
            "H5": f"卧室要保持到{facts.get('until')}，温度和取舍按我的档案。",
            "H6": f"只准备卧室，把窗帘关好，灯光调到{light}%，温控按我的档案。",
        }
        case["initial_message"] += details[task]
    return case


def all_cases(n, seed):
    cases = [
        make_case(b, c, t, edge, seed)
        for b in range(1, n + 1)
        for c in COHORTS
        for t in TASKS
        for edge in (False, True)
    ]
    random.Random(seed).shuffle(cases)
    return cases


def put_card(case, delivered_updates=(), *, current_minute=0):
    facts = deepcopy(case["facts"])
    for update in delivered_updates:
        facts.update(update.get("facts_change", {}))
    card = {
        "profile": case["profile"],
        "current_facts": facts,
        "disclosure": case["persona"]["disclosure"],
        "knowledge_boundary": "不知道实时室温、设备是否在线、预约是否成功或工具返回；只知道用户可见对话。",
    }
    context = time_context(case, current_minute)
    if context is not None:
        card["time_context"] = context
    return card
