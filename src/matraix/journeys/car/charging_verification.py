"""J2 observer checks. No provider calls, trajectory writes, or hidden SUT hints.

Reference estimates use raw fixture legs and the pinned native charging tool,
not case.plans/expected. A speculative calculator query is not an action error.
Natural-language claim interpretation is evidence-bound and remains separately
reviewable; cached legacy scores are never rewritten by this module.
"""

from datetime import datetime, timedelta
import math
import re

VERSION = "car-j2-v1.8"
CLAIM_SCHEMA_VERSION = "car-j2-claims-v2.3"
PUBLIC_CONTRACT = {
    "route_segments_include_detour": True,
    "description": "起点到充电站、充电站到终点两段路线已包含进出站绕行；相加后不要再加POI绕行时间。",
    "energy": "用到站路段的distance_km和公开能耗模型计算到站电量；路线上的公里标记不是实际到站距离。",
    "charging": "以到站电量作为充电起点；整数工具输入向下取整（浮点误差除外）。工具返回一分钟步长的近似充电时长，不保证真实电量严格达到目标。",
    "time": "总时间=两段驾驶时间+原生工具预计充电停留；本情境不模拟排队/插枪额外耗时，出发时间为公开模拟时刻。",
    "scope": "仅设置导航与估计未来充电，不模拟实际行驶或充电完成。",
}


def _minutes(route):
    return route["duration_hours"] * 60 + route["duration_minutes"]


def _native_minutes(result):
    if result.get("status") != "SUCCESS":
        raise ValueError("Native charging reference failed")
    values = list(result.get("result", {}).values())
    if len(values) != 1 or not re.fullmatch(r"\d+min", str(values[0])):
        raise ValueError("Unexpected native charging estimate")
    return int(values[0][:-3])


def reference_plans(case, *, target_soc=None):
    """Closed fixture contract: one plug / one matched leg pair per station.

    Fail closed on unsupported topology instead of inventing a feasible plan.
    The deadline is observer ground truth, never a source of SUT knowledge.
    """
    if case["task"] != "J2":
        return []
    from .native import Backend

    backend = Backend(case)
    fixed = case["fixed"]
    start = datetime(**fixed["current_datetime"])
    hour, minute = map(int, case["facts"]["deadline"].split(":"))
    deadline = start.replace(hour=hour, minute=minute)
    if deadline < start:
        raise ValueError(
            "J2 requires an explicit same-day deadline; do not guess next day"
        )
    usable = fixed["battery_capacity_kwh"] * fixed["useable_battery_percentage"] / 100
    target = case["facts"]["target_soc"] if target_soc is None else target_soc
    rows = []
    for pid, poi in sorted(case["pois"].items()):
        entering = [
            r
            for r in case["routes"]
            if r["start_id"] == case["origin"] and r["destination_id"] == pid
        ]
        leaving = [
            r
            for r in case["routes"]
            if r["start_id"] == pid and r["destination_id"] == case["destination"]
        ]
        plugs = poi.get("charging_plugs", [])
        if len(entering) != 1 or len(leaving) != 1 or len(plugs) != 1:
            raise ValueError("Unsupported J2 station topology")
        first, second, plug = entering[0], leaving[0], plugs[0]
        if first["base_route_id"] != second["base_route_id"]:
            raise ValueError("J2 legs cannot splice different base routes")
        if poi["opening_hours"] != "00:00h - 23:59h":
            raise ValueError("J2 reference currently supports only all-day fixtures")
        used = first["distance_km"] * fixed["energy_consumption"] / 100
        arrival_soc = fixed["state_of_charge"] - used / usable * 100
        tool_soc = math.floor(arrival_soc + 1e-9)
        reachable = arrival_soc >= 0
        native = None
        charge = None
        if reachable:
            if tool_soc > target:
                raise ValueError(
                    "J2 target below arrival SoC needs an explicit task contract"
                )
            native = backend.execute(
                "calculate_charging_time_by_soc",
                {
                    "charging_station_id": pid,
                    "charging_station_plug_id": plug["plug_id"],
                    "start_state_of_charge": tool_soc,
                    "target_state_of_charge": target,
                },
            )
            charge = _native_minutes(native)
        drive = _minutes(first) + _minutes(second)
        total = drive + charge if charge is not None else None
        arrival = start + timedelta(minutes=total) if total is not None else None
        station_arrival = start + timedelta(minutes=_minutes(first))
        station_departure = (
            station_arrival + timedelta(minutes=charge) if charge is not None else None
        )
        available = plug["availability"] == "available"
        rows.append(
            {
                "poi_id": pid,
                "station_name": poi["name"],
                "plug_id": plug["plug_id"],
                "routes": [first["route_id"], second["route_id"]],
                "distance_to_station_km": first["distance_km"],
                "energy_to_station_kwh": used,
                "departure_soc": fixed["state_of_charge"],
                "arrival_soc": round(arrival_soc, 10),
                "charging_start_soc": tool_soc,
                "charging_target_soc": target,
                "charge_minutes": charge,
                "native_result": native,
                "destination_arrival_soc": round(
                    target
                    - second["distance_km"] * fixed["energy_consumption"] / usable,
                    10,
                ),
                "departure_time": start.isoformat(" "),
                "station_arrival_time": station_arrival.isoformat(" "),
                "station_departure_time": station_departure.isoformat(" ")
                if station_departure
                else None,
                "first_leg_minutes": _minutes(first),
                "second_leg_minutes": _minutes(second),
                "plug_power_kw": plug["power_kw"],
                "drive_minutes": drive,
                "total_minutes": total,
                "arrival_time": arrival.isoformat(" ") if arrival else None,
                "deadline": deadline.isoformat(" "),
                "deadline_time": deadline.isoformat(" "),
                "deadline_margin_minutes": (deadline - arrival).total_seconds() / 60
                if arrival
                else None,
                "deadline_met": bool(arrival and arrival <= deadline),
                "late_minutes": max(0, (arrival - deadline).total_seconds() / 60)
                if arrival
                else None,
                "reachable": reachable,
                "plug_available": available,
                "feasible": bool(
                    reachable and available and arrival and arrival <= deadline
                ),
                "includes_toll": first["includes_toll"] or second["includes_toll"],
            }
        )
    return rows
