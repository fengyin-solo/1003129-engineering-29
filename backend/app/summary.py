"""汇总口径：运营概览与各模块列表共用同一套取数定义，保证同一个数两边一致。

口径按版本管理，调整口径就是切换当前版本：
- v1 标记口径：待处理、异常直接按记录上的 pending / abnormal 标记统计（历史口径）；
- v2 状态口径：待处理按"状态未办结"判定（不看人工标记），异常仍按 abnormal 标记。

口径调整后，新的概览请求与新快照立即按新口径重算；已经落库的快照保留
当时的口径版本与可见范围，不回头改写。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import settings

# 各模块状态序列的终态（与各服务 STATUS_ORDER 末位保持一致），用于"是否办结"判定。
TERMINAL_STATUSES: dict[str, str] = {
    "minearea": "已闭坑",
    "gas": "已处置",
    "ventilation": "已更换",
    "roof": "已加固",
    "waterhazard": "已控制",
    "rockburst": "已解危",
    "personnel": "已更换",
    "dust": "已治理",
    "fireprevent": "已处置",
    "belt": "已修复",
    "hoist": "检修中",
    "power": "已修复",
    "rescue": "已报废",
    "training": "已归档",
    "shift": "已联系",
    "explosive": "已检查",
    "roadway": "已竣工",
    "monitorstation": "已停用",
    "certificate": "已注销",
    "emergencydrill": "已复盘",
}


@dataclass(frozen=True)
class SummaryCaliber:
    """一套汇总口径：created 始终等于列表无过滤时的 total，保证概览与列表同数。"""

    version: str
    label: str

    def is_pending(self, module: str, row: dict[str, Any]) -> bool:
        raise NotImplementedError

    def is_abnormal(self, module: str, row: dict[str, Any]) -> bool:
        return bool(row.get("abnormal"))

    def summarize(self, module: str, rows: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "created": len(rows),
            "pending": sum(1 for row in rows if self.is_pending(module, row)),
            "abnormal": sum(1 for row in rows if self.is_abnormal(module, row)),
        }


class FlagCaliber(SummaryCaliber):
    """v1 标记口径：直接按记录上的 pending 标记统计待处理。"""

    def __init__(self) -> None:
        super().__init__(version="v1", label="标记口径（按记录标记统计）")

    def is_pending(self, module: str, row: dict[str, Any]) -> bool:
        return bool(row.get("pending"))


class StatusCaliber(SummaryCaliber):
    """v2 状态口径：状态未办结即待处理，与人工标记解耦。"""

    def __init__(self) -> None:
        super().__init__(version="v2", label="状态口径（未办结即待处理）")

    def is_pending(self, module: str, row: dict[str, Any]) -> bool:
        return row.get("status") != TERMINAL_STATUSES.get(module)


CALIBERS: dict[str, SummaryCaliber] = {c.version: c for c in (FlagCaliber(), StatusCaliber())}

_current_version = settings.summary_caliber_version


def current_caliber() -> SummaryCaliber:
    return CALIBERS.get(_current_version, CALIBERS[settings.summary_caliber_version])


def set_current_caliber(version: str) -> SummaryCaliber | None:
    """切换当前口径；版本不存在时返回 None，调用方负责说明原因。"""
    global _current_version
    caliber = CALIBERS.get(version)
    if caliber is None:
        return None
    _current_version = version
    return caliber
