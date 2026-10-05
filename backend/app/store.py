"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

可见范围与操作日志也收在这里：
- visible_rows：按当前请求身份过滤后的行集，列表接口与运营概览共用，保证同数一致；
- 操作日志：越权访问、跨单位改动的尝试逐条落库，只增不删；
- 概览快照：落库即冻结，后续口径调整不回头改写旧快照。
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from app.security import Identity, current_create_unit, current_identity, row_visible
from app.seed import SEED_ROWS


class Table(list):
    """模块数据表：登记新行时按当前请求身份补记归属单位。

    中间件在登记请求上设置 current_create_unit；缺省时落当前身份所在单位，
    保证任何入口写入的行都带 unit_id，不会出现"无归属"数据。
    """

    def append(self, item: dict[str, Any]) -> None:
        if isinstance(item, dict) and "unit_id" not in item:
            unit_id = current_create_unit.get() or current_identity.get().unit_id
            item["unit_id"] = unit_id
        super().append(item)


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, Table] = {
            name: Table(dict(row) for row in rows) for name, rows in SEED_ROWS.items()
        }
        self._audit_logs: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> Table:
        """原始数据表（不按可见范围过滤）；登记追加、中间件核查归属时用。"""
        return self._tables.setdefault(module, Table())

    def visible_rows(self, module: str) -> list[dict[str, Any]]:
        """当前请求身份可见的行集：模块列表与运营概览的统一取数口径。"""
        return self.visible_rows_for(module, current_identity.get())

    def visible_rows_for(self, module: str, identity: Identity) -> list[dict[str, Any]]:
        return [row for row in self.rows(module) if row_visible(identity, row)]

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    # ---- 操作日志：越权访问、跨单位改动逐条落库，只增不删 ----

    def log_audit(
        self,
        *,
        identity: Identity,
        action: str,
        module: str,
        target: str,
        result: str,
        detail: str,
    ) -> dict[str, Any]:
        entry = {
            "id": len(self._audit_logs) + 1,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "operator": identity.operator,
            "role": identity.role,
            "role_label": identity.role_label,
            "unit_id": identity.unit_id,
            "unit_label": identity.unit_label,
            "action": action,
            "module": module,
            "target": target,
            "result": result,
            "detail": detail,
        }
        self._audit_logs.append(entry)
        return dict(entry)

    def audit_logs(self) -> list[dict[str, Any]]:
        """最新的在前，返回副本避免外部改动。"""
        return [dict(entry) for entry in reversed(self._audit_logs)]

    # ---- 概览快照：落库即冻结，口径调整后旧快照不回头改写 ----

    def add_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        frozen = copy.deepcopy(snapshot)
        frozen["id"] = len(self._snapshots) + 1
        self._snapshots.append(frozen)
        return copy.deepcopy(frozen)

    def snapshots(self) -> list[dict[str, Any]]:
        """返回深拷贝：快照只增不改，调用方拿不到可改写的内部引用。"""
        return copy.deepcopy(self._snapshots)


store = Store()
