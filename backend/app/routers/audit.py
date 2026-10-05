"""操作日志接口：越权访问、跨单位改动的记录，仅矿级管理员可查。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.access_control import record_denied
from app.security import current_identity
from app.store import store

router = APIRouter(prefix="/api/audit", tags=["操作日志"])


@router.get("/logs")
def list_logs(page: int = 1, size: int = 50) -> dict:
    """操作日志列表：最新的在前；非矿级角色查询本身也算越权，照样记录。"""
    identity = current_identity.get()
    if not identity.is_admin:
        record_denied(
            identity,
            action="越权访问",
            module="audit",
            target="audit/logs",
            detail="非矿级角色尝试查看操作日志",
        )
        raise HTTPException(status_code=403, detail="操作日志仅矿级管理员可查，本次尝试已记入操作日志")
    logs = store.audit_logs()
    start = max(page - 1, 0) * size
    return {"items": logs[start:start + size], "total": len(logs), "page": page, "size": size}
