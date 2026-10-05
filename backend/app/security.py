"""身份解析与越权守卫：所有 /api 请求先过这一层，再进业务路由。

职责：
1. 从 X-Operator-Id 解析操作者，写入请求级上下文（contextvar），供数据层判断可见范围；
2. 未识别身份一律 401 并记入操作日志；
3. 跨单位读取单条、跨单位执行动作、非管理员查看操作日志，一律 403 并记入操作日志。

用纯 ASGI 中间件而不是 BaseHTTPMiddleware：后者会把下游放到独立 task 里跑，
contextvar 传不进路由处理函数，可见范围过滤会失效。
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.users import Operator, find_operator

OPERATOR_HEADER = "x-operator-id"

_current_operator: ContextVar[Operator | None] = ContextVar("current_operator", default=None)


class PermissionDenied(Exception):
    """业务层抛出的越权异常，由 main.py 统一转成 403 并记操作日志。"""

    def __init__(self, message: str, *, category: str = "越权修改", module: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.category = category
        self.module = module


def current_operator() -> Operator | None:
    return _current_operator.get()


def require_operator() -> Operator:
    operator = _current_operator.get()
    if operator is None:
        raise PermissionDenied("未识别操作者身份，请求被拒绝", category="越权访问")
    return operator


class OperatorGuardMiddleware:
    """纯 ASGI 中间件：身份解析 + 可见范围守卫 + 越权记录。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET")
        if not path.startswith("/api") or path == "/api/health":
            await self.app(scope, receive, send)
            return

        # 延迟导入，避免与 store 的模块级依赖成环。
        from app.store import store

        headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
        operator = find_operator(headers.get(OPERATOR_HEADER))
        if operator is None:
            store.log_audit(
                operator_id=headers.get(OPERATOR_HEADER) or "未携带",
                category="越权访问",
                module=None,
                detail=f"未识别身份访问 {method} {path}，已拒绝",
                result="已拒绝",
            )
            await JSONResponse(
                status_code=401,
                content={"detail": "未识别操作者身份，请求被拒绝并记录"},
            )(scope, receive, send)
            return

        token = _current_operator.set(operator)
        try:
            rejection = self._guard(store, operator, method, path)
            if rejection is not None:
                status, category, module, detail = rejection
                store.log_audit(
                    operator_id=operator.operator_id,
                    category=category,
                    module=module,
                    detail=detail,
                    result="已拒绝",
                )
                await JSONResponse(status_code=status, content={"detail": detail})(scope, receive, send)
                return
            await self.app(scope, receive, send)
        finally:
            _current_operator.reset(token)

    def _guard(
        self, store: Any, operator: Operator, method: str, path: str
    ) -> tuple[int, str, str | None, str] | None:
        """返回 None 表示放行；否则返回 (状态码, 日志类别, 模块, 说明)。"""
        segments = [seg for seg in path.split("/") if seg]
        # /api/audit-logs 仅矿级管理员可查。
        if segments[:2] == ["api", "audit-logs"] and not operator.is_admin:
            return 403, "越权访问", None, f"{operator.name}（{operator.unit}）无权查看操作日志，已拒绝"
        # /api/{module}/{entry_id} 与 /api/{module}/{entry_id}/actions 的跨单位拦截。
        if len(segments) >= 3 and segments[0] == "api" and segments[1] in store.module_names():
            module = segments[1]
            try:
                entry_id = int(segments[2])
            except ValueError:
                return None
            row = store.find(module, entry_id)
            if row is None or operator.can_see(str(row.get("unit", ""))):
                return None
            if method == "GET":
                return 403, "越权访问", module, (
                    f"{operator.name}（{operator.unit}）试图读取外单位记录 "
                    f"{module}#{entry_id}（归属 {row.get('unit')}），已拒绝"
                )
            return 403, "越权修改", module, (
                f"{operator.name}（{operator.unit}）试图改动外单位记录 "
                f"{module}#{entry_id}（归属 {row.get('unit')}），已拒绝"
            )
        return None
