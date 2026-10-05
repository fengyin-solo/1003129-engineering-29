"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

可见范围规则：
- 每条记录都带 unit（归属单位）；矿级管理员看全矿，其他角色只看本单位；
- 概览、列表、导出共用 visible_rows 与同一套汇总口径，保证同一个数两边一致；
- 快照与操作日志只增不改：已落库的快照保留当时的口径与可见范围，不回头改写。
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from app import summary
from app.seed import SEED_ROWS
from app.security import PermissionDenied, current_operator
from app.users import OPERATORS, Operator

# 示例数据的单位归属：每个模块有一个主办单位，前两条记录归主办单位、第三条归
# 下一个单位，保证每个单位都有"看不到条数、只知道有无"的跨单位模块。
# 真实项目里归属来自业务登记，不来自编号规则。
UNIT_CYCLE = ["综采一队", "综采二队", "外委维修队"]
MODULE_PRIMARY_UNIT: dict[str, int] = {
    "minearea": 0, "gas": 0, "roof": 0, "waterhazard": 0, "rockburst": 0, "personnel": 0, "dust": 0,
    "ventilation": 1, "fireprevent": 1, "belt": 1, "shift": 1, "explosive": 1, "training": 1, "emergencydrill": 1,
    "hoist": 2, "power": 2, "rescue": 2, "roadway": 2, "monitorstation": 2, "certificate": 2,
}


def _seed_unit(module: str, entry_id: int) -> str:
    primary = MODULE_PRIMARY_UNIT.get(module, 0)
    offset = 0 if entry_id <= 2 else 1
    return UNIT_CYCLE[(primary + offset) % len(UNIT_CYCLE)]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {}
        for name, rows in SEED_ROWS.items():
            self._tables[name] = []
            for row in rows:
                entry = dict(row)
                entry.setdefault("unit", _seed_unit(name, int(entry.get("id", 1))))
                self._tables[name].append(entry)
        self._snapshots: list[dict[str, Any]] = []
        self._audit_logs: list[dict[str, Any]] = []

    # ---------- 基础表访问 ----------

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        """原始表（写路径用）；读路径一律走 visible_rows。"""
        return self._tables.setdefault(module, [])

    def visible_rows(self, module: str, operator: Operator | None = None) -> list[dict[str, Any]]:
        """按操作者可见范围过滤后的记录；未识别身份时默认拒绝（返回空）。"""
        operator = operator or current_operator()
        if operator is None:
            return []
        if operator.is_admin:
            return list(self.rows(module))
        return [row for row in self.rows(module) if row.get("unit") == operator.unit]

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    # ---------- 归属与口径 ----------

    def resolve_create_unit(self, values: dict[str, Any]) -> str:
        """新建记录的单位归属：普通角色强制落在本单位，冒充外单位直接拒绝。"""
        operator = current_operator()
        if operator is None:
            raise PermissionDenied("未识别操作者身份，登记被拒绝", category="越权访问")
        attempted = str(values.get("unit") or "").strip()
        if operator.is_admin:
            return attempted or operator.unit
        if attempted and attempted != operator.unit:
            raise PermissionDenied(
                f"{operator.name}（{operator.unit}）试图把记录登记到「{attempted}」名下，已拒绝",
                category="越权修改",
            )
        return operator.unit

    def summarize(self, module: str, operator: Operator | None = None) -> dict[str, int]:
        """按当前口径汇总某模块的可见记录；与列表 total 同源，保证两边同数。"""
        return summary.current_caliber().summarize(module, self.visible_rows(module, operator))

    # ---------- 运营概览 ----------

    def overview(self, operator: Operator | None = None) -> dict[str, Any]:
        """运营概览：本单位名下模块给条数，跨单位模块只给有无。"""
        operator = operator or current_operator()
        if operator is None:
            raise PermissionDenied("未识别操作者身份，概览被拒绝", category="越权访问")
        caliber = summary.current_caliber()
        own_modules: list[dict[str, Any]] = []
        cross_units: list[dict[str, Any]] = []
        for name in self.module_names():
            all_rows = self.rows(name)
            visible = self.visible_rows(name, operator)
            if visible:
                own_modules.append({"name": name, **caliber.summarize(name, visible)})
            else:
                # 跨单位数据不显示条数，只显示有无。
                cross_units.append({"name": name, "hasData": bool(all_rows)})
        cards = [
            {"label": "业务模块", "value": len(own_modules)},
            {"label": "今日新增", "value": sum(item["created"] for item in own_modules)},
            {"label": "待处理", "value": sum(item["pending"] for item in own_modules)},
            {"label": "异常量", "value": sum(item["abnormal"] for item in own_modules)},
        ]
        return {
            "operator": {
                "id": operator.operator_id,
                "name": operator.name,
                "role": operator.role,
                "roleLabel": operator.role_label,
                "unit": operator.unit,
            },
            "caliber": {"version": caliber.version, "label": caliber.label},
            "cards": cards,
            "modules": own_modules,
            "crossUnits": cross_units,
        }

    # ---------- 概览快照（只增不改） ----------

    def save_snapshot(self, label: str = "", operator: Operator | None = None) -> dict[str, Any]:
        """把当前概览按当前口径与当前可见范围落库；已落库的快照不再改写。"""
        operator = operator or current_operator()
        if operator is None:
            raise PermissionDenied("未识别操作者身份，快照被拒绝", category="越权访问")
        payload = self.overview(operator)
        snapshot = {
            "id": len(self._snapshots) + 1,
            "savedAt": _now(),
            "label": label or "运营概览快照",
            "caliber": payload["caliber"],
            "scope": {
                "operatorId": operator.operator_id,
                "operatorName": operator.name,
                "role": operator.role,
                "unit": operator.unit,
            },
            "payload": copy.deepcopy(payload),
        }
        self._snapshots.append(snapshot)
        self.log_audit(
            operator_id=operator.operator_id,
            category="快照",
            module=None,
            detail=f"保存概览快照 #{snapshot['id']}（口径 {payload['caliber']['version']}，范围 {operator.unit}）",
            result="已落库",
        )
        return copy.deepcopy(snapshot)

    def list_snapshots(self, operator: Operator | None = None) -> list[dict[str, Any]]:
        """快照按落库时的可见范围保留：普通角色只能看自己单位名下的快照。"""
        operator = operator or current_operator()
        if operator is None:
            raise PermissionDenied("未识别操作者身份，快照查询被拒绝", category="越权访问")
        if operator.is_admin:
            return copy.deepcopy(self._snapshots)
        return copy.deepcopy([s for s in self._snapshots if s["scope"]["unit"] == operator.unit])

    # ---------- 操作日志（只增不改） ----------

    def log_audit(
        self,
        *,
        operator_id: str,
        category: str,
        module: str | None,
        detail: str,
        result: str,
    ) -> None:
        known = OPERATORS.get(operator_id)
        self._audit_logs.append({
            "id": len(self._audit_logs) + 1,
            "time": _now(),
            "operatorId": operator_id,
            "operatorName": known.name if known else "未识别",
            "role": known.role_label if known else "未识别",
            "unit": known.unit if known else "未识别",
            "category": category,
            "module": module,
            "detail": detail,
            "result": result,
        })

    def list_audit_logs(self, operator: Operator | None = None) -> list[dict[str, Any]]:
        operator = operator or current_operator()
        if operator is None or not operator.is_admin:
            raise PermissionDenied("无权查看操作日志，已拒绝", category="越权访问")
        return copy.deepcopy(self._audit_logs)


store = Store()
