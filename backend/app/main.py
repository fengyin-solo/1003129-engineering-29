"""矿山安全监测管理平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import summary
from app.config import settings
from app.routers import ROUTERS
from app.security import OperatorGuardMiddleware, PermissionDenied, current_operator
from app.store import store

app = FastAPI(title="矿山安全监测管理平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 身份解析与越权守卫放在最外层业务中间件：先过守卫，再进业务路由。
app.add_middleware(OperatorGuardMiddleware)

for module in ROUTERS:
    app.include_router(module.router)


@app.exception_handler(PermissionDenied)
def permission_denied_handler(request: Request, exc: PermissionDenied) -> JSONResponse:
    """业务层抛出的越权：统一 403，并记入操作日志。"""
    operator = current_operator()
    store.log_audit(
        operator_id=operator.operator_id if operator else "未识别",
        category=exc.category,
        module=exc.module,
        detail=exc.message,
        result="已拒绝",
    )
    return JSONResponse(status_code=403, content={"detail": exc.message})


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：按操作者角色与单位归属过滤，本单位给条数、跨单位只给有无。"""
    return store.overview()


class SnapshotPayload(BaseModel):
    label: str = Field(default="", max_length=50)


@app.post("/api/overview/snapshots", status_code=201)
def save_overview_snapshot(payload: SnapshotPayload) -> dict[str, object]:
    """把当前概览按当前口径与当前可见范围落库；已落库的快照不回头改写。"""
    return store.save_snapshot(label=payload.label)


@app.get("/api/overview/snapshots")
def list_overview_snapshots() -> dict[str, object]:
    """快照列表：按落库时的可见范围保留，普通角色只看自己单位名下的快照。"""
    return {"items": store.list_snapshots()}


class CaliberPayload(BaseModel):
    version: str


@app.post("/api/overview/caliber")
def switch_caliber(payload: CaliberPayload) -> dict[str, object]:
    """调整汇总口径：之后的概览与快照按新口径重算，旧快照保持原样。"""
    operator = current_operator()
    if operator is None or not operator.is_admin:
        raise PermissionDenied("只有矿级管理员可以调整汇总口径", category="越权修改", module="overview")
    caliber = summary.set_current_caliber(payload.version)
    if caliber is None:
        return {"ok": False, "message": f"口径版本「{payload.version}」不存在", "caliber": None}
    store.log_audit(
        operator_id=operator.operator_id,
        category="口径调整",
        module=None,
        detail=f"汇总口径切换为 {caliber.version}（{caliber.label}），后续按新口径重算",
        result="已生效",
    )
    return {"ok": True, "message": f"汇总口径已切换为 {caliber.version}", "caliber": {"version": caliber.version, "label": caliber.label}}


@app.get("/api/audit-logs")
def audit_logs() -> dict[str, object]:
    """操作日志：越权访问、越权修改、快照与口径调整都记在这里，仅矿级管理员可查。"""
    return {"items": store.list_audit_logs()}
