"""访问控制基础：身份模型、角色与单位归属、可见范围判定。

平台没有独立登录体系，调用方身份由请求头携带（网关注入或前端会话附带）：

    X-Operator-Id  操作人姓名（前端对中文做 percent-encode，这里负责解码）
    X-Role         admin / team_lead / contractor
    X-Unit-Id      归属单位编号，取值见 UNITS

可见范围规则：
- admin（矿级管理员）可见全矿，可处置任何单位的数据；
- team_lead（班组长）与 contractor（外委单位）只能看到并改动本单位名下的数据。

列表、明细、动作、概览共用这里的同一份判定，保证各处的取数口径一致。
本模块不依赖 store，保持纯函数，方便单测与复用。
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import unquote

ROLES: dict[str, str] = {
    "admin": "矿级管理员",
    "team_lead": "班组长",
    "contractor": "外委单位",
}

UNITS: dict[str, str] = {
    "mine-1": "一采区",
    "mine-2": "二采区",
    "contractor-1": "外委一队",
}


class IdentityError(ValueError):
    """请求头里的身份信息不合法。"""


@dataclass(frozen=True)
class Identity:
    operator: str
    role: str
    unit_id: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def role_label(self) -> str:
        return ROLES.get(self.role, self.role)

    @property
    def unit_label(self) -> str:
        return UNITS.get(self.unit_id, self.unit_id)


# 未携带身份头时的默认身份：保持平台原有行为（矿级视角，可见全矿）。
DEFAULT_IDENTITY = Identity(operator="值班管理员", role="admin", unit_id="mine-1")

# 当前请求身份与本次登记落单的目标单位，由中间件按请求设置。
current_identity: ContextVar[Identity] = ContextVar("current_identity", default=DEFAULT_IDENTITY)
current_create_unit: ContextVar[str | None] = ContextVar("current_create_unit", default=None)


def _decode_header(raw: str) -> str:
    """前端对中文姓名做了 percent-encode，这里解码；未编码的原样返回。"""
    return unquote(raw) if "%" in raw else raw


def resolve_identity(headers: Mapping[str, str]) -> Identity:
    """从请求头解析身份；缺省沿用默认身份，非法取值直接报错。"""
    operator = _decode_header(headers.get("x-operator-id", "")).strip() or DEFAULT_IDENTITY.operator
    role = headers.get("x-role", "").strip() or DEFAULT_IDENTITY.role
    unit_id = headers.get("x-unit-id", "").strip() or DEFAULT_IDENTITY.unit_id
    if role not in ROLES:
        raise IdentityError(f"角色「{role}」不合法，可选：{'、'.join(ROLES)}")
    if unit_id not in UNITS:
        raise IdentityError(f"归属单位「{unit_id}」不存在，可选：{'、'.join(UNITS)}")
    return Identity(operator=operator, role=role, unit_id=unit_id)


def row_visible(identity: Identity, row: dict[str, Any]) -> bool:
    """判断一条业务数据是否落在当前身份的可见范围内。"""
    if identity.is_admin:
        return True
    return row.get("unit_id") == identity.unit_id
