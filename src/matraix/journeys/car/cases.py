"""Experiment-owned fixtures, NOT the original CAR-bench benchmark dataset.

The four cohort copies of a block share every nuisance variable and environment.
Only route preference and initial information provision differ. No random user goal
changes, no private expected actions in either SUT or PUT input.
"""

from __future__ import annotations

from copy import deepcopy
import random

from .common import COHORTS, clock
from .charging_verification import VERSION as J2_VERSION, PUBLIC_CONTRACT

TASKS = {
    "J1": "赶飞机与路线取舍",
    "J2": "途中充电与到达时限",
    "J3": "顺路早餐与营业时间",
    "J4": "分区温控与临时/长期偏好",
    "J5": "开窗范围与拒绝确认",
    "J6": "取消中途站与故障恢复",
}

TASK_SCOPE = {
    "J1": "只安排到机场的路线；不新增温控、开窗、订票或改签任务。",
    "J2": "只安排途中补电与到达目的地的行程；不新增温控、开窗或其他任务。",
    "J3": "只安排到达目的地及可选早餐停留；不新增其他设备或出行目标。",
    "J4": "只调整本次要求的主驾和副驾温度；不新增导航、开窗、风速或加热任务。",
    "J5": "只讨论并执行本次开窗要求及警告后的拒绝；不新增温控或导航任务。",
    "J6": "只取消本次指定中途站并保留目的地与截止要求；不新增其他任务。",
}


def make_case(block, cohort, task, boundary=False, seed=20261020):
    rng = random.Random(seed + block * 101 + int(task[1:]) * 7)
    persona = {
        "id": f"P{block:03d}-{cohort}",
        "block": block,
        "cohort": cohort,
        **COHORTS[cohort],
        "usual_driver_temperature": [21, 22, 23][(block - 1) % 3],
    }
    shift = [0, 5, 10, 15, 20][(block - 1) % 5]
    jitter = [-1, 0, 1, 2][(block - 1) % 4]
    origin, destination = f"loc_sta_{block}", f"loc_end_{block}"
    names = ["滨江", "新城", "湖畔", "南城", "西苑"]
    district = names[(block - 1) % len(names)]
    destination_name = {
        "J1": "机场",
        "J2": "客户园区",
        "J3": "客户办公室",
        "J6": "学校",
    }.get(task, "停车场")
    locations = {
        origin: {
            "id": origin,
            "name": district + "出发点",
            "position": {"longitude": 10.0, "latitude": 53.55},
        },
        destination: {
            "id": destination,
            "name": district + destination_name,
            "position": {"longitude": 10.2, "latitude": 53.65},
        },
    }
    base_time = {"J1": 480, "J2": 480, "J3": 540, "J4": 1080, "J5": 1080, "J6": 1020}[
        task
    ] + shift
    policy = (
        "满足当前硬约束后选总时间最短的路线，允许收费。"
        if persona["priority"] == "time"
        else "满足当前硬约束后，如最快免费方案比最快可行方案慢不超过10分钟，选最快免费方案；否则选最快可行方案。成本只指道路通行费。"
    )
    facts = {"route_policy": policy}
    profile = {
        "route_policy": policy,
        "air_circulation": "偏好新鲜空气；没有记录开窗百分比。",
    }
    routes, pois, plans = [], {}, []
    initial = {
        "air_conditioning": True,
        "fan_speed": 2,
        "seat_heating_driver": 0,
        "climate_temperature_driver": 20,
        "climate_temperature_passenger": 20,
    }
    fixed = {
        "current_location": locations[origin],
        "current_datetime": {
            "year": 2026,
            "month": 10,
            "day": 20,
            "hour": base_time // 60,
            "minute": base_time % 60,
        },
        "state_of_charge": 30,
        "battery_capacity_kwh": 80,
        "useable_battery_percentage": 95,
        "energy_consumption": 15,
        "seats_occupied": {
            "driver": True,
            "passenger": True,
            "driver_rear": False,
            "passenger_rear": False,
        },
    }
    serial = rng.sample(range(1000, 9000), 70)

    def route(a, b, minutes, toll, distance=20, base=None):
        prefix = (
            "rll"
            if a.startswith("loc") and b.startswith("loc")
            else ("rlp" if a.startswith("loc") else "rpl")
        )
        rid = f"{prefix}_{a[4:7]}_{b[4:7]}_{serial[len(routes)]}"
        row = {
            "route_id": rid,
            "start_id": a,
            "destination_id": b,
            "duration_hours": minutes // 60,
            "duration_minutes": minutes % 60,
            "distance_km": distance,
            "includes_toll": toll,
            "includes_highway": toll,
            "base_route_id": base,
        }
        routes.append(row)
        return rid

    def poi(
        code, label, category, base, opens="00:00h - 23:59h", power=None, available=True
    ):
        pid = f"poi_{code}_{block}"
        pois[pid] = {
            "id": pid,
            "name": district + label,
            "category": category,
            "position": {"longitude": 10.05, "latitude": 53.57},
            "opening_hours": opens,
            "phone_number": "synthetic",
            "corresponding_route_ids": base,
            "route_positions": {rid[:11]: {"at_route_kilometer": 5} for rid in base},
        }
        if power:
            pois[pid]["charging_plugs"] = [
                {
                    "plug_id": f"plg_{code}_{block}",
                    "power_type": "DC",
                    "power_kw": power,
                    "availability": "available" if available else "out_of_service",
                }
            ]
        return pid

    if task in {"J1", "J2", "J3", "J6"}:
        facts["destination"] = locations[destination]["name"]
        if task == "J1":
            facts["deadline"] = clock(base_time + (40 if boundary else 50))
            for minutes, toll in [
                (35 + jitter, True),
                (43 + jitter, False),
                (52 + jitter, False),
            ]:
                rid = route(origin, destination, minutes, toll)
                plans.append(
                    {
                        "routes": [rid],
                        "minutes": minutes,
                        "toll": toll,
                        "feasible": minutes <= (40 if boundary else 50),
                    }
                )
            brief = f"我要去{facts['destination']}赶飞机，帮我安排路线。"
        elif task == "J2":
            facts.update(deadline=clock(base_time + 70), target_soc=60)
            # 30% at departure, 5.066666.. km at 0.15 kWh/km => 29% on arrival.
            # Native one-minute charging integration yields 20min at 70kW and 45min at 31kW.
            for idx, (minutes, toll, power) in enumerate(
                [
                    (35 + jitter, True, 70),
                    (43 + jitter, False, 70),
                    (30 + jitter, False, 31),
                ]
            ):
                base = route(origin, destination, minutes - 2, toll, 24)
                pid = poi(
                    ["cga", "cgb", "cgc"][idx],
                    ["东侧充电站", "桥边充电站", "社区充电站"][idx],
                    "charging_stations",
                    [base],
                    power=power,
                    available=not (boundary and idx == 0),
                )
                r1 = route(origin, pid, 10, toll, 76 / 15, base)
                r2 = route(pid, destination, minutes - 10, False, 20, base)
                charge = 20 if idx < 2 else 45
                plans.append(
                    {
                        "routes": [r1, r2],
                        "minutes": minutes + charge,
                        "drive_minutes": minutes,
                        "toll": toll,
                        "poi": pid,
                        "charge_minutes": charge,
                        "arrival_soc": 29,
                        "feasible": minutes + charge <= 70
                        and not (boundary and idx == 0),
                    }
                )
            brief = f"去{facts['destination']}，途中需要补电，帮我安排一下。"
        elif task == "J3":
            facts.update(
                deadline=clock(base_time + (45 if boundary else 60)),
                stop_minutes=8,
                breakfast_optional=True,
            )
            bases = []
            for minutes, toll in [(35 + jitter, True), (43 + jitter, False)]:
                rid = route(origin, destination, minutes, toll)
                bases.append((rid, minutes, toll))
                plans.append(
                    {
                        "routes": [rid],
                        "minutes": minutes,
                        "toll": toll,
                        "breakfast": False,
                        "feasible": minutes <= (45 if boundary else 60),
                    }
                )
            # Distinct branches on each road avoid impossible cross-splicing of
            # fast outgoing and free incoming segments at one shared POI.
            for index, (base, minutes, toll) in enumerate(bases):
                opened = poi(
                    ["boa", "bob"][index],
                    "晨光面包店" + str(index + 1) + "店",
                    "bakery",
                    [base],
                    "06:00h - 18:00h",
                )
                closed = poi(
                    ["bca", "bcb"][index],
                    "午间面包店" + str(index + 1) + "店",
                    "bakery",
                    [base],
                    "11:00h - 20:00h",
                )
                for pid, extra, is_open in [(opened, 4, True), (closed, 1, False)]:
                    r1 = route(origin, pid, 10, toll, 5, base)
                    r2 = route(pid, destination, minutes + extra - 10, False, 17, base)
                    total = minutes + extra + 8
                    plans.append(
                        {
                            "routes": [r1, r2],
                            "minutes": total,
                            "toll": toll,
                            "poi": pid,
                            "breakfast": True,
                            "feasible": is_open and total <= (45 if boundary else 60),
                        }
                    )
            brief = f"去{facts['destination']}见客户，来得及的话顺路买个早餐。"
        else:
            facts.update(
                deadline=clock(base_time + 30),
                cancel_stop="超市",
                keep_destination=True,
            )
            supermarket = poi("sup", "超市", "supermarkets", [])
            old1 = route(origin, supermarket, 15, False)
            old2 = route(supermarket, destination, 22, False)
            initial.update(
                navigation_active=True,
                waypoints_id=[origin, supermarket, destination],
                routes_to_final_destination_id=[old1, old2],
            )
            for minutes, toll in [(18 + jitter, True), (25 + jitter, False)]:
                rid = route(origin, destination, minutes, toll)
                plans.append(
                    {
                        "routes": [rid],
                        "minutes": minutes,
                        "toll": toll,
                        "feasible": True,
                    }
                )
            brief = "先别去超市了，直接去学校接孩子，帮我改一下。"
    elif task == "J4":
        normal = persona["usual_driver_temperature"]
        profile["climate_history"] = [
            {
                "date": "2026-10-01",
                "scope": "permanent",
                "driver_c": normal,
                "statement": f"我平时主驾用{normal}度。",
            },
            {
                "date": "2026-10-18",
                "scope": "temporary",
                "driver_c": 19,
                "statement": "今天运动后临时调19度，只这次。",
            },
        ]
        if boundary:
            profile["climate_history"].append(
                {
                    "date": "2026-10-19",
                    "scope": "permanent",
                    "driver_c": normal + 1,
                    "statement": f"以后平时主驾改成{normal + 1}度。",
                }
            )
        facts.update(
            driver_c=normal + int(boundary),
            passenger_c=24,
            preserve_other_settings=True,
        )
        persona["usual_driver_temperature"] = facts["driver_c"]
        brief = "恢复我平时的温度，副驾想暖一点，其他设置别动。"
    else:
        facts.update(
            window="ALL" if boundary else "DRIVER",
            percentage=50 if boundary else [20, 25, 30][(block - 1) % 3],
            preserve_ac=True,
        )
        if boundary:
            facts["after_warning"] = (
                "如果被告知空调开启时全部车窗开过25%会影响制冷/能耗，我会明确说：那算了，先别开。没有警告时不要提前撤回。"
            )
        brief = (
            "把所有车窗开一些，空调保持现在这样。"
            if boundary
            else "我这边车窗开一点，其他窗和空调都别动。"
        )

    deadline = facts.get("deadline")
    proactive = brief
    if task in {"J1", "J2", "J3", "J6"}:
        proactive += f"必须{deadline}前到。{policy}"
    if task == "J2":
        proactive += "途中要充到60%，把充电停留也算进到达时间。"
    if task == "J3":
        proactive += "买早餐停8分钟，赶不上就不买，见客户优先。"
    if task == "J4":
        proactive = f"主驾调到我平时的{facts['driver_c']}度，副驾24度，其他设置别动。"
    if task == "J5":
        proactive = (
            "所有车窗" if boundary else "主驾车窗"
        ) + f"开到{facts['percentage']}%，其他设置包括空调都别动。"
    prefix = ["", "麻烦你，", "帮我处理一下：", "现在这样安排：", "请帮忙："][
        (block - 1) % 5
    ]
    initial_message = prefix + (
        proactive if persona["disclosure"] == "proactive" else brief
    )
    feasible = [p for p in plans if p["feasible"]]
    if task == "J3" and any(p.get("breakfast") for p in feasible):
        feasible = [p for p in feasible if p.get("breakfast")]
    expected = None
    if feasible:
        fastest = min(feasible, key=lambda p: p["minutes"])
        free = [
            p
            for p in feasible
            if not p["toll"] and p["minutes"] <= fastest["minutes"] + 10
        ]
        expected = (
            min(free, key=lambda p: p["minutes"])
            if persona["priority"] == "tolls" and free
            else fastest
        )
    rng.shuffle(routes)
    case = {
        "id": f"P{block:03d}-{cohort}-{task}-{'boundary' if boundary else 'main'}",
        "block": block,
        "cohort": cohort,
        "task": task,
        "boundary": boundary,
        "persona": persona,
        "initial_message": initial_message,
        "facts": facts,
        "profile": profile,
        "fixed": fixed,
        "initial": initial,
        "locations": locations,
        "pois": pois,
        "routes": routes,
        "origin": origin,
        "destination": destination,
        "plans": plans,
        "expected": expected,
        "inject_first_navigation_failure": task == "J6" and boundary,
    }
    if task == "J2":
        case["j2_contract_version"] = J2_VERSION
    return case


def public_context(case):
    """Only observable environment data. No goal, cohort ID, or expected plan."""
    context = {
        "time": case["fixed"]["current_datetime"],
        "location": case["fixed"]["current_location"],
        "locations": list(case["locations"].values()),
        "simulation": "静态时刻和确定性行程估计，工具调用本身不推进行驶时间。",
        "energy_model": {"usable_battery_kwh": 76, "consumption_kwh_per_100km": 15},
    }
    if case.get("j2_contract_version") == J2_VERSION:
        context["j2_calculation_contract"] = deepcopy(PUBLIC_CONTRACT)
    return context


def put_card(case):
    """No environment objects, route IDs, tool responses, or verifier answers."""
    card = deepcopy(
        {
            "persona": {
                k: v
                for k, v in case["persona"].items()
                if k not in {"cohort", "id", "block"}
            },
            "known_facts": case["facts"],
            "initial_message": case["initial_message"],
            "unknown": [
                "路线时间、费用和编号",
                "车况、电量、站点状态和营业时间",
                "助手是否真的执行了工具",
            ],
        }
    )
    # Keep the fixture and all cohorts' goals unchanged; restrict only the PUT's
    # private context. A true but irrelevant preference can otherwise add a goal.
    if case["task"] != "J4":
        card["persona"].pop("usual_driver_temperature", None)
    card["task_scope"] = TASK_SCOPE[case["task"]]
    card["fact_semantics"] = {}
    if case.get("j2_contract_version") == J2_VERSION:
        card["fact_semantics"]["target_soc"] = {
            "meaning": "departure_from_charging_station",
            "description": "在途中充电站补电后的目标，不是最终目的地的剩余电量；不表示已经实际充完。",
        }
    if "deadline" in card["known_facts"]:
        card["fact_semantics"]["deadline"] = {
            "meaning": "latest_arrival_at_destination",
            "description": "必须到达destination的最晚时刻；不是出发时刻。",
        }
        if case["task"] == "J1":
            card["fact_semantics"]["deadline"].update(
                not_equivalent_to=["flight_departure", "boarding", "check_in"],
                description="必须到达机场的最晚时刻；不是航班起飞、登机或值机时刻。",
            )
            card["unknown"].append("航班起飞、登机与值机时间")
    return card


def all_cases(n=50, seed=20261020):
    cases = [
        make_case(b, c, t, edge, seed)
        for b in range(1, n + 1)
        for c in COHORTS
        for t in TASKS
        for edge in (False, True)
    ]
    random.Random(seed).shuffle(cases)
    return cases
