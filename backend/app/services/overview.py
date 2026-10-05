"""运营概览汇总：按当前身份的可见范围出数，口径版本化，快照落库后不改写。

汇总口径（criteria）说明：
- v1（旧口径，2026-09 前线上版本）：各模块条数取全量行数，不按归属单位过滤，
  班组长、外委单位也能看到全矿条数——正是本次要收掉的口径。
- v2（现行口径）：只统计当前身份可见范围内的行，与各模块列表接口的取数口径
  完全一致，同一个数在概览和列表里相同。

口径再调整时：新增一个 _counts_vN 函数登记进 CRITERIA，并把 CURRENT_CRITERIA
指向新版本。概览实时按新口径重算；已落库的旧快照保留当时的口径版本号与数值，
不回头改写。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from app.security import UNITS, Identity
from app.store import store

CURRENT_CRITERIA = "v2"

MODULE_LABELS: dict[str, str] = {
    "minearea": "矿区台账",
    "gas": "瓦斯监测",
    "ventilation": "通风系统",
    "roof": "顶板管理",
    "waterhazard": "水害防治",
    "rockburst": "冲击地压",
    "personnel": "人员定位",
    "dust": "粉尘防治",
    "fireprevent": "防灭火",
    "belt": "皮带运输",
    "hoist": "提升系统",
    "power": "供电系统",
    "rescue": "应急救援",
    "training": "安全培训",
    "shift": "入井管理",
    "explosive": "爆破管理",
    "roadway": "巷道维修",
    "monitorstation": "监测分站",
    "certificate": "持证管理",
    "emergencydrill": "应急演练",
}


class UnknownUnitError(ValueError):
    """请求指定的归属单位不存在。"""


class ForbiddenUnitError(PermissionError):
    """非矿级角色尝试查看其他单位的概览。"""


class SnapshotForbiddenError(PermissionError):
    """非矿级角色尝试查看其他单位的快照。"""


def _tally(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "created": len(rows),
        "pending": sum(1 for row in rows if row.get("pending")),
        "abnormal": sum(1 for row in rows if row.get("abnormal")),
    }


def _counts_v1(module: str, units: set[str] | None) -> dict[str, int]:
    """旧口径：全模块行数，不看归属单位。"""
    return _tally(list(store.rows(module)))


def _counts_v2(module: str, units: set[str] | None) -> dict[str, int]:
    """现行口径：只统计可见范围内的行，与模块列表接口同口径。"""
    rows = store.rows(module)
    if units is not None:
        rows = [row for row in rows if row.get("unit_id") in units]
    return _tally(list(rows))


CRITERIA: dict[str, Callable[[str, "set[str] | None"], dict[str, int]]] = {
    "v1": _counts_v1,
    "v2": _counts_v2,
}


def _resolve_scope_units(identity: Identity, unit_id: str | None) -> set[str] | None:
    """确定本次概览的可见单位集合；None 表示全矿。"""
    if unit_id:
        if unit_id not in UNITS:
            raise UnknownUnitError(f"归属单位「{unit_id}」不存在")
        if not identity.is_admin and unit_id != identity.unit_id:
            raise ForbiddenUnitError(f"尝试查看其他单位（{unit_id}）的概览")
        return {unit_id}
    if identity.is_admin:
        return None
    return {identity.unit_id}


def build_overview(identity: Identity, unit_id: str | None = None) -> dict[str, Any]:
    """按身份可见范围汇总概览；跨单位模块只报有无、不报条数。"""
    units = _resolve_scope_units(identity, unit_id)
    count = CRITERIA[CURRENT_CRITERIA]
    modules: list[dict[str, Any]] = []
    for name in store.module_names():
        counts = count(name, units)
        has_own = counts["created"] > 0
        has_any = len(store.rows(name)) > 0
        if has_own or not has_any:
            modules.append({
                "name": name,
                "label": MODULE_LABELS.get(name, name),
                "scope": "own",
                "has_data": has_own,
                **counts,
            })
        else:
            # 本单位名下没有数据、其他单位有：只显示有无，不显示条数。
            modules.append({
                "name": name,
                "label": MODULE_LABELS.get(name, name),
                "scope": "cross",
                "has_data": True,
                "created": None,
                "pending": None,
                "abnormal": None,
            })
    own = [item for item in modules if item["scope"] == "own"]
    cards = [
        {"label": "业务模块", "value": len(own)},
        {"label": "今日新增", "value": sum(int(item["created"]) for item in own)},
        {"label": "待处理", "value": sum(int(item["pending"]) for item in own)},
        {"label": "异常量", "value": sum(int(item["abnormal"]) for item in own)},
    ]
    if units is None:
        scope_label = "全矿"
    else:
        scope_label = "、".join(UNITS[unit] for unit in sorted(units))
    return {
        "cards": cards,
        "modules": modules,
        "criteria_version": CURRENT_CRITERIA,
        "scope": {
            "role": identity.role,
            "role_label": identity.role_label,
            "unit_id": identity.unit_id,
            "unit_label": scope_label,
            "whole_mine": units is None,
        },
    }


# ---- 快照：按保存时的可见范围与口径落库，之后一律不改写 ----


def save_snapshot(identity: Identity, unit_id: str | None = None) -> dict[str, Any]:
    """把当前概览按现行口径落库为快照。"""
    overview = build_overview(identity, unit_id)
    snapshot = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "operator": identity.operator,
        "role": identity.role,
        "role_label": identity.role_label,
        "unit_id": unit_id or identity.unit_id,
        "unit_label": overview["scope"]["unit_label"],
        "criteria_version": overview["criteria_version"],
        "cards": overview["cards"],
        "modules": overview["modules"],
    }
    return store.add_snapshot(snapshot)


def list_snapshots(identity: Identity) -> list[dict[str, Any]]:
    """矿级看全部快照；其他角色只看本单位名下的快照。"""
    snapshots = store.snapshots()
    if identity.is_admin:
        return snapshots
    return [snap for snap in snapshots if snap["unit_id"] == identity.unit_id]


def get_snapshot(identity: Identity, snapshot_id: int) -> dict[str, Any] | None:
    """读取单条快照：按落库时的内容原样返回，不按新口径重算。"""
    for snap in store.snapshots():
        if int(snap["id"]) == snapshot_id:
            if not identity.is_admin and snap["unit_id"] != identity.unit_id:
                raise SnapshotForbiddenError(f"快照 {snapshot_id} 属于其他单位")
            return snap
    return None
