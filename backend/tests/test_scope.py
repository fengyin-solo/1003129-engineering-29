"""可见范围与汇总口径的回归测试。

覆盖需求点：
1. 概览按角色与单位归属过滤，本单位给条数、跨单位只给有无；
2. 越权访问 / 跨单位改动一律拒绝并记入操作日志；
3. 概览与模块列表同口径，同一个数两边一致；
4. 口径调整后按新口径重算，已落库旧快照不回头改写。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import summary
from app.main import app
from app.store import store

ADMIN = {"X-Operator-Id": "admin"}
LEADER1 = {"X-Operator-Id": "leader1"}  # 综采一队
LEADER2 = {"X-Operator-Id": "leader2"}  # 综采二队
CONTRACTOR = {"X-Operator-Id": "contractor1"}  # 外委维修队


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
    # 每个用例结束后恢复默认口径，避免相互影响。
    summary.set_current_caliber("v2")


def test_health_is_open(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_anonymous_is_rejected_and_logged(client):
    before = len(store._audit_logs)
    resp = client.get("/api/overview")
    assert resp.status_code == 401
    resp = client.get("/api/gas")
    assert resp.status_code == 401
    new_logs = store._audit_logs[before:]
    assert len(new_logs) == 2
    assert all(log["category"] == "越权访问" and log["result"] == "已拒绝" for log in new_logs)


def test_overview_scoped_by_unit(client):
    resp = client.get("/api/overview", headers=LEADER1)
    assert resp.status_code == 200
    data = resp.json()
    assert data["operator"]["unit"] == "综采一队"
    # 综采一队名下：7 个主办模块（各 2 条）+ 6 个外委模块的轮转记录（各 1 条）。
    assert len(data["modules"]) == 13
    gas = next(m for m in data["modules"] if m["name"] == "gas")
    assert gas == {"name": "gas", "created": 2, "pending": 2, "abnormal": 1}
    # 卡片只汇总本单位名下的模块。
    cards = {c["label"]: c["value"] for c in data["cards"]}
    assert cards["业务模块"] == 13
    assert cards["今日新增"] == 20
    # 综采二队主办的 7 个模块只显示有无，不显示条数。
    assert len(data["crossUnits"]) == 7
    assert all(set(item) == {"name", "hasData"} for item in data["crossUnits"])
    assert all(item["hasData"] for item in data["crossUnits"])


def test_overview_cross_unit_presence_only(client):
    # 外委维修队名下没有 gas 记录（gas 主办单位是综采一队），gas 出现在跨单位区，只有有无。
    resp = client.get("/api/overview", headers=CONTRACTOR)
    data = resp.json()
    own_names = {m["name"] for m in data["modules"]}
    cross = {c["name"]: c["hasData"] for c in data["crossUnits"]}
    assert "gas" not in own_names
    assert cross["gas"] is True
    assert all(set(item) == {"name", "hasData"} for item in data["crossUnits"])


def test_admin_sees_whole_mine(client):
    resp = client.get("/api/overview", headers=ADMIN)
    data = resp.json()
    assert data["crossUnits"] == []
    gas = next(m for m in data["modules"] if m["name"] == "gas")
    assert gas["created"] == 3
    cards = {c["label"]: c["value"] for c in data["cards"]}
    assert cards["今日新增"] == 60


def test_overview_matches_list_total(client):
    """同一个数在概览和列表里必须一致：created == 列表无过滤 total。"""
    for headers in (ADMIN, LEADER1, CONTRACTOR):
        overview = client.get("/api/overview", headers=headers).json()
        for module in overview["modules"]:
            listing = client.get(f"/api/{module['name']}", headers=headers).json()
            assert module["created"] == listing["total"], (headers, module["name"])


def test_list_is_scoped_by_unit(client):
    resp = client.get("/api/gas", headers=LEADER1)
    data = resp.json()
    assert data["total"] == 2
    assert all(item["unit"] == "综采一队" for item in data["items"])
    # 管理员看全矿。
    assert client.get("/api/gas", headers=ADMIN).json()["total"] == 3


def test_cross_unit_read_rejected_and_logged(client):
    before = len(store._audit_logs)
    # gas#1 归属综采一队，综采二队班组长读取属于越权。
    resp = client.get("/api/gas/1", headers=LEADER2)
    assert resp.status_code == 403
    new_logs = store._audit_logs[before:]
    assert len(new_logs) == 1
    assert new_logs[0]["category"] == "越权访问"
    assert new_logs[0]["module"] == "gas"
    assert new_logs[0]["result"] == "已拒绝"
    # 本单位记录正常可读。
    assert client.get("/api/gas/1", headers=LEADER1).status_code == 200


def test_cross_unit_action_rejected_and_logged(client):
    before = len(store._audit_logs)
    resp = client.post(
        "/api/gas/1/actions", headers=LEADER2,
        json={"values": {"action": "处置确认"}},
    )
    assert resp.status_code == 403
    new_logs = store._audit_logs[before:]
    assert len(new_logs) == 1
    assert new_logs[0]["category"] == "越权修改"
    # 记录未被改动。
    assert store.find("gas", 1)["status"] == "正常"


def test_cross_unit_create_rejected_and_logged(client):
    before = len(store._audit_logs)
    resp = client.post(
        "/api/gas", headers=LEADER1,
        json={"values": {"测点编号": "GAS-9001", "所在区域": "一采区", "瓦斯浓度": "0.4", "unit": "综采二队"}},
    )
    assert resp.status_code == 403
    new_logs = store._audit_logs[before:]
    assert len(new_logs) == 1
    assert new_logs[0]["category"] == "越权修改"
    assert store.find("gas", 9001) is None


def test_own_unit_create_lands_in_own_unit(client):
    resp = client.post(
        "/api/gas", headers=LEADER2,
        json={"values": {"测点编号": "GAS-9002", "所在区域": "二采区", "瓦斯浓度": "0.3"}},
    )
    assert resp.status_code == 200
    entry = resp.json()["entry"]
    assert entry["unit"] == "综采二队"
    # 综采一队看不到这条新记录。
    assert client.get(f"/api/gas/{entry['id']}", headers=LEADER1).status_code == 403
    # 清理现场，避免影响其他用例。
    store.rows("gas").remove(store.find("gas", entry["id"]))


def test_audit_logs_admin_only(client):
    before = len(store._audit_logs)
    resp = client.get("/api/audit-logs", headers=LEADER1)
    assert resp.status_code == 403
    assert store._audit_logs[before:][0]["category"] == "越权访问"
    resp = client.get("/api/audit-logs", headers=ADMIN)
    assert resp.status_code == 200
    assert len(resp.json()["items"]) >= 1


def test_snapshot_keeps_old_caliber_and_scope(client):
    # 班组长按当前口径（v2）落一份快照。
    resp = client.post("/api/overview/snapshots", headers=LEADER1, json={"label": "班前会"})
    assert resp.status_code == 201
    snap = resp.json()
    assert snap["caliber"]["version"] == "v2"
    assert snap["scope"]["unit"] == "综采一队"
    gas_pending_v2 = next(m for m in snap["payload"]["modules"] if m["name"] == "gas")["pending"]

    # 管理员调整口径为 v1，之后的概览按新口径重算。
    resp = client.post("/api/overview/caliber", headers=ADMIN, json={"version": "v1"})
    assert resp.json()["ok"] is True
    overview = client.get("/api/overview", headers=LEADER1).json()
    assert overview["caliber"]["version"] == "v1"

    # 旧快照不回头改写：口径、数值、可见范围都保持落库时的样子。
    snaps = client.get("/api/overview/snapshots", headers=LEADER1).json()["items"]
    old = next(s for s in snaps if s["id"] == snap["id"])
    assert old["caliber"]["version"] == "v2"
    gas_old = next(m for m in old["payload"]["modules"] if m["name"] == "gas")
    assert gas_old["pending"] == gas_pending_v2

    # 新快照按新口径落库。
    resp = client.post("/api/overview/snapshots", headers=LEADER1, json={"label": "调整后"})
    assert resp.json()["caliber"]["version"] == "v1"


def test_snapshot_visibility_follows_scope(client):
    client.post("/api/overview/snapshots", headers=LEADER1, json={"label": "一队快照"})
    client.post("/api/overview/snapshots", headers=LEADER2, json={"label": "二队快照"})
    mine1 = client.get("/api/overview/snapshots", headers=LEADER1).json()["items"]
    assert mine1 and all(s["scope"]["unit"] == "综采一队" for s in mine1)
    mine2 = client.get("/api/overview/snapshots", headers=LEADER2).json()["items"]
    assert mine2 and all(s["scope"]["unit"] == "综采二队" for s in mine2)
    everything = client.get("/api/overview/snapshots", headers=ADMIN).json()["items"]
    assert len(everything) == len(store._snapshots)


def test_caliber_switch_requires_admin(client):
    before = len(store._audit_logs)
    resp = client.post("/api/overview/caliber", headers=CONTRACTOR, json={"version": "v1"})
    assert resp.status_code == 403
    assert store._audit_logs[before:][0]["category"] == "越权修改"
    # 未知版本不切换。
    resp = client.post("/api/overview/caliber", headers=ADMIN, json={"version": "v9"})
    assert resp.json()["ok"] is False
    assert summary.current_caliber().version == "v2"


def test_caliber_changes_numbers_consistently(client):
    """口径调整后按新口径重算，且概览与列表仍同数。

    综采二队名下只有 gas#3（超限报警、pending 标记为 False）：
    - v1 标记口径看标记 → 待处理 0；
    - v2 状态口径看是否办结 → 待处理 1。
    """
    for version, expected_pending in (("v1", 0), ("v2", 1)):
        client.post("/api/overview/caliber", headers=ADMIN, json={"version": version})
        overview = client.get("/api/overview", headers=LEADER2).json()
        assert overview["caliber"]["version"] == version
        gas = next(m for m in overview["modules"] if m["name"] == "gas")
        assert gas["pending"] == expected_pending
        listing = client.get("/api/gas", headers=LEADER2).json()
        assert gas["created"] == listing["total"] == 1
