"""操作者目录：角色与单位归属。

真实项目里这里会换成统一认证（SSO / 签名 token）；当前用请求头 X-Operator-Id
标识操作者，后端按目录解析角色与单位，所有可见范围判断都以解析结果为准，
前端传什么身份只是演示入口，越权判断不依赖前端自觉。
"""
from __future__ import annotations

from dataclasses import dataclass

ROLE_LABELS = {"admin": "矿级管理员", "teamlead": "班组长", "contractor": "外委单位"}


@dataclass(frozen=True)
class Operator:
    operator_id: str
    name: str
    role: str  # admin / teamlead / contractor
    unit: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)

    def can_see(self, unit: str) -> bool:
        """矿级管理员看全矿；其他角色只看本单位。"""
        return self.is_admin or self.unit == unit


OPERATORS: dict[str, Operator] = {
    "admin": Operator("admin", "值班管理员", "admin", "矿调度中心"),
    "leader1": Operator("leader1", "综采一队班组长", "teamlead", "综采一队"),
    "leader2": Operator("leader2", "综采二队班组长", "teamlead", "综采二队"),
    "contractor1": Operator("contractor1", "外委维修队负责人", "contractor", "外委维修队"),
}


def find_operator(operator_id: str | None) -> Operator | None:
    if not operator_id:
        return None
    return OPERATORS.get(operator_id.strip())
