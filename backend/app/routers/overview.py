"""运营概览接口：按当前身份的可见范围出数，支持快照留存与回放。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.access_control import record_denied
from app.security import current_identity
from app.services.overview import (
    ForbiddenUnitError,
    SnapshotForbiddenError,
    UnknownUnitError,
    build_overview,
    get_snapshot,
    list_snapshots,
    save_snapshot,
)

router = APIRouter(prefix="/api/overview", tags=["运营概览"])


@router.get("")
def overview(unit_id: str | None = Query(default=None, description="指定查看的单位，仅矿级可跨单位")) -> dict:
    """运营概览：只汇总当前身份可见范围内的模块；跨单位数据只报有无。"""
    identity = current_identity.get()
    try:
        return build_overview(identity, unit_id)
    except UnknownUnitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ForbiddenUnitError as exc:
        record_denied(
            identity,
            action="越权访问",
            module="overview",
            target=f"unit:{unit_id}",
            detail=str(exc),
        )
        raise HTTPException(status_code=403, detail="无权查看其他单位的概览，本次尝试已记入操作日志") from exc


@router.post("/snapshots")
def create_snapshot(unit_id: str | None = Query(default=None, description="指定快照单位，仅矿级可跨单位")) -> dict:
    """把当前概览按现行口径落库为快照；落库后不再改写。"""
    identity = current_identity.get()
    try:
        snapshot = save_snapshot(identity, unit_id)
    except UnknownUnitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ForbiddenUnitError as exc:
        record_denied(
            identity,
            action="越权访问",
            module="overview",
            target=f"snapshot:unit:{unit_id}",
            detail=str(exc),
        )
        raise HTTPException(status_code=403, detail="无权为其他单位保存快照，本次尝试已记入操作日志") from exc
    return {"ok": True, "snapshot": snapshot}


@router.get("/snapshots")
def snapshots() -> dict:
    """快照列表：矿级看全部，其他角色只看本单位名下；按落库内容原样返回。"""
    identity = current_identity.get()
    items = list_snapshots(identity)
    return {"items": items, "total": len(items)}


@router.get("/snapshots/{snapshot_id}")
def snapshot_detail(snapshot_id: int) -> dict:
    """单条快照：保留落库时的可见范围与口径，不按新口径重算。"""
    identity = current_identity.get()
    try:
        snapshot = get_snapshot(identity, snapshot_id)
    except SnapshotForbiddenError as exc:
        record_denied(
            identity,
            action="越权访问",
            module="overview",
            target=f"snapshot:{snapshot_id}",
            detail=str(exc),
        )
        raise HTTPException(status_code=403, detail="无权查看其他单位的快照，本次尝试已记入操作日志") from exc
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"快照 {snapshot_id} 不存在")
    return snapshot
