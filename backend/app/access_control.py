"""越权拦截中间件：在业务代码之前统一挡住跨单位访问与改动，并写入操作日志。

拦截规则（只处理 /api/ 下已注册的业务模块路径）：
- 列表、导出：放行，由 store.visible_rows 按可见范围过滤，不算越权；
- 明细读取、动作执行：目标行不属于当前身份可见范围时一律 403 拒绝并记录；
- 登记新行：归属单位默认落当前身份所在单位；显式指定其他单位时，
  非矿级角色一律 403 拒绝并记录（矿级管理员可为任意单位落单）。

运营概览、操作日志等自有接口不在这里拦截，由各自路由判定。
"""
from __future__ import annotations

import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.security import (
    UNITS,
    Identity,
    IdentityError,
    current_create_unit,
    current_identity,
    resolve_identity,
    row_visible,
)
from app.store import store

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def record_denied(identity: Identity, *, action: str, module: str, target: str, detail: str) -> None:
    """越权尝试统一记入操作日志。"""
    store.log_audit(
        identity=identity,
        action=action,
        module=module,
        target=target,
        result="已拒绝",
        detail=detail,
    )


class AccessControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if not path.startswith("/api/") or path == "/api/health":
            return await call_next(request)
        try:
            identity = resolve_identity(request.headers)
        except IdentityError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        token = current_identity.set(identity)
        create_token = None
        try:
            denied, create_unit = await self._guard(request, identity)
            if denied is not None:
                return denied
            if create_unit is not None:
                create_token = current_create_unit.set(create_unit)
            return await call_next(request)
        finally:
            if create_token is not None:
                current_create_unit.reset(create_token)
            current_identity.reset(token)

    async def _guard(self, request: Request, identity: Identity) -> tuple[Response | None, str | None]:
        """返回 (拒绝响应, 登记目标单位)；放行时为 (None, ...)。"""
        parts = request.url.path.strip("/").split("/")
        if len(parts) < 2:
            return None, None
        module = parts[1]
        if module not in store.module_names():
            return None, None  # overview / audit 等由各自路由判定
        rest = parts[2:]
        method = request.method.upper()

        if not rest:
            if method == "POST":
                return await self._guard_create(request, identity, module)
            return None, None  # 列表按可见范围过滤即可

        first = rest[0]
        if first == "export" or not first.isdigit():
            return None, None  # 导出走列表同一口径；非法路径交给业务层报错

        entry = store.find(module, int(first))
        if entry is None:
            return None, None  # 不存在交给业务层返回 404
        if row_visible(identity, entry):
            return None, None

        if method in MUTATING_METHODS:
            detail = (
                f"尝试改动其他单位（{entry.get('unit_id')}）的数据，"
                "跨单位改动一律拒绝"
            )
            action = "跨单位改动"
            message = "跨单位改动一律拒绝，本次尝试已记入操作日志"
        else:
            detail = f"尝试读取其他单位（{entry.get('unit_id')}）的明细"
            action = "越权访问"
            message = "无权访问其他单位的数据，本次尝试已记入操作日志"
        record_denied(identity, action=action, module=module, target=f"{module}#{first}", detail=detail)
        return JSONResponse(status_code=403, content={"detail": message}), None

    async def _guard_create(
        self, request: Request, identity: Identity, module: str
    ) -> tuple[Response | None, str | None]:
        """登记请求：核定归属单位；跨单位落单一律拒绝并记录。"""
        body = await request.body()
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return None, None  # 非法报文交给业务层返回 422
        values = payload.get("values") if isinstance(payload, dict) else None
        raw_unit = values.get("unit_id") if isinstance(values, dict) else None
        target_unit = str(raw_unit).strip() if raw_unit else identity.unit_id
        if target_unit not in UNITS:
            return JSONResponse(
                status_code=400,
                content={"detail": f"归属单位「{target_unit}」不存在，可选：{'、'.join(UNITS)}"},
            ), None
        if not identity.is_admin and target_unit != identity.unit_id:
            record_denied(
                identity,
                action="跨单位改动",
                module=module,
                target=f"{module}#新建",
                detail=f"尝试把新记录登记到其他单位（{target_unit}）名下，跨单位改动一律拒绝",
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "跨单位登记一律拒绝，本次尝试已记入操作日志"},
            ), None
        return None, target_unit
