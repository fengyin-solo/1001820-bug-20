"""清淤疏浚接口：维护清淤单，覆盖安排清淤、确认完成、取消清淤等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.dredge import DredgeService

router = APIRouter(prefix="/api/dredge", tags=["清淤疏浚"])

service = DredgeService()

LIST_FIELDS = [
    "清淤单号", "批次号", "清淤管段", "淤积厚度", "清淤长度", "清出泥量",
    "作业班组", "完成日期", "验收结论", "清淤状态",
]
STATUSES = ["待安排", "清淤中", "已完成", "已取消"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按清淤单号检索"),
    status: str | None = Query(default=None, description="待安排、清淤中、已完成、已取消"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按清淤单号与状态过滤清淤疏浚列表；没有数据时返回空页，不报错。"""
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"状态只能是：{'、'.join(STATUSES)}")
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def get_stats() -> dict[str, float]:
    """清淤页指标：待安排单数、本月清淤长度、累计清出泥量（台账口径，同批只算一次）。"""
    return service.stats()


@router.get("/ledger")
def get_ledger() -> dict[str, Any]:
    """清淤疏浚调度台账：验收结论按批次反映到这里，同批次仅一行。"""
    items = service.ledger_entries()
    return {"module": "dredge", "total": len(items), "items": items}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出清淤疏浚清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "dredge", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条清淤单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"清淤单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条清淤单，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="清淤单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条清淤单执行安排清淤、确认完成、取消清淤；不允许的动作会被拦下并说明原因。

    报文：{"values": {"action": "取消清淤", "request_id": "可选，断线重试带上同一编号"}}
    """
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
