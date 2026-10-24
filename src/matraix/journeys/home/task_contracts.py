"""Prospective task definitions. Never retrofit a contract onto saved cases."""

from datetime import datetime, timedelta

VERSION = "home-task-v1.6"
MEASUREMENT_VERSION = "home-task-v1.7"
H6_PREPARATION_VERSION = "home-h6-preparation-v1.9"
H6_PREPARATION_TEXT = (
    "这是本次设备的一次性准备：请把我指定房间的空调开启，"
    "设定温度默认设为已授权档案的理想温度；可接受范围不表示可以自行改选设定温度。"
    "若我本次明确提出温度，则以本次要求为准。灯光和窗帘按本次要求设置。"
    "本次没有要求持续温控、自动关机或预约时长。"
)


def h6_requested_preparation():
    """Typed user goal, never a reading or a report of execution."""
    return {
        "kind": "current_user_intent",
        "operation": "one_time_preparation",
        "requested_ac_on": True,
        "temperature_source": "authorized_profile_ideal_unless_current_explicit_override",
        "default_target_source": "authorized_profile_ideal",
        "current_explicit_temperature_has_priority": True,
        "acceptable_range_is_setpoint_permission": False,
        "duration_requested": False,
        "meaning": "要求空调开启并设置温度；不是描述当前已开启或实际室温。",
    }


H5_OBSERVATION_MINUTES = 180
H2_WORK_LIGHT_PERCENT = 70
H1_SCOPE_TEXT = "这次只准备所用房间的主灯和空调；独立台灯、窗帘和其他设备保持原样。"
H1_SCOPE = {
    "included_kinds": ["light", "ac"],
    "preserve_kinds": ["desk", "curtain"],
    "rule": H1_SCOPE_TEXT,
}
H1_DEADLINE_VERSION = "home-h1-inclusive-deadline-v2.0"
H1_DEADLINE_TEXT = (
    "本任务的回家准备期限采用“不晚于回家时刻”：恰好在该时刻完成也算按时。"
    "普通口语“回家前准备好”采用同一含义；若另有明确的更早具体时刻或提前分钟数，则按明确要求核验。"
)
TIME_RULE = (
    "本次“今晚”固定指request_date这一晚及紧接的次日凌晨；“明天照常”指request_date的次日晚间。"
    "跨日核验不改变原请求日期或截止时间。截止已过时只回顾原安排，不新增下一晚的任务；"
    "若确实改变需求，必须有新的明确日期指令。答复和报告涉及日期时使用完整日期及时间。"
)


def has_contract(case):
    return case.get("task_contract", {}).get("version") in {
        VERSION,
        MEASUREMENT_VERSION,
    }


def has_measurement_contract(case):
    return case.get("task_contract", {}).get("version") == MEASUREMENT_VERSION


def h2_light_minimum(case):
    # Native 254-step light quantization: retain legacy 69 only for old fixtures.
    return (
        case["profile"]["study_work_light_percent"] - 0.6
        if has_measurement_contract(case)
        else 69
    )


def h2_light_protected_at(case, minute):
    if not has_measurement_contract(case):
        return case["boundary"] and minute < 150
    cutoff = case["facts"]["work_until_minute"] if case["boundary"] else 60
    return 0 <= minute < cutoff or 1440 <= minute < 1500


def time_context(case, minute=0):
    """Shared clock only: no hidden deadline, future notice or device readings."""
    if not (
        (case["task"] == "H2" and has_contract(case))
        or (case["task"] == "H5" and has_measurement_contract(case))
    ):
        return None
    if type(minute) is not int or minute < 0:
        raise ValueError("Clock context requires a nonnegative integer minute")
    start = datetime.fromisoformat(case["world"]["start"])
    return {
        "request_time": start.isoformat(" "),
        "request_date": start.date().isoformat(),
        "following_date": (start + timedelta(days=1)).date().isoformat(),
        "current_time": (start + timedelta(minutes=minute)).isoformat(" "),
        "rule": TIME_RULE
        if case["task"] == "H2"
        else "本次温控截止使用原始完整日期，不随跨日或核验时间顺延；观察窗口不是用户需求截止。截止已过时回顾原需求，不编造新任务。",
    }
