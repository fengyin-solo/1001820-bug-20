"""清淤疏浚业务规则：状态流转、字段校验、调度台账与筛选口径都收在这里。

关键约定：
- 状态只能沿 待安排 -> 清淤中 -> 已完成 前进；待安排可取消；已完成/已取消为终态。
- 取消只允许发生在「待安排」，重复取消、取消已完成都会被拦下并说明原因，
  已完成作业绝不会因重复操作退回待安排。
- 取消确认后清掉作业/计量字段，列表、详情、概览待处理量同一份数据同时生效。
- 确认完成时按「批次号」把验收结论写入调度台账；同一批次只落一行、只算一次，
  断线重试与重复提交不会重复记账。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.store import store

MODULE = "dredge"
LEDGER_SCOPE = "dredge"
REQUIRED_FIELDS = ["清淤单号", "清淤管段", "淤积厚度"]
STATUS_ORDER = ["待安排", "清淤中", "已完成", "已取消"]
# 每个状态允许执行的动作；不在表里就是终态或非法流转。
ALLOWED_ACTIONS: dict[str, dict[str, str]] = {
    "待安排": {"安排清淤": "清淤中", "取消清淤": "已取消"},
    "清淤中": {"确认完成": "已完成"},
}
ACCEPT_RESULTS = ["验收合格", "验收不合格"]
# 取消时要一并清空的作业过程与计量字段，避免残留取消前的值。
CANCEL_CLEAR_FIELDS = ["清淤长度", "清出泥量", "作业班组", "完成日期", "验收结论", "淤积厚度"]
_NUMBER_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)")


def _to_number(value: Any) -> float:
    """从「12.5t」「260m」这类带单位文本里取数值，取不到按 0 处理。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER_RE.search(str(value))
    return float(match.group(1)) if match else 0.0


class DredgeService:
    def __init__(self) -> None:
        # 动作结果按请求编号缓存，断线后带同一编号重试直接返回首次结果。
        self._action_results: dict[str, tuple[dict[str, Any] | None, str]] = {}

    # ---------- 查询 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("清淤单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def stats(self) -> dict[str, float]:
        """页面统计：待安排看作业单；长度与泥量取调度台账，保证同一批只算一次。"""
        rows = store.rows(MODULE)
        pending = sum(1 for row in rows if row.get("status") == "待安排")
        month_prefix = date.today().strftime("%Y-%m")
        month_length = 0.0
        total_mud = 0.0
        for ledger_row in store.ledger_rows(LEDGER_SCOPE):
            total_mud += _to_number(ledger_row.get("清出泥量"))
            if str(ledger_row.get("完成日期", "")).startswith(month_prefix):
                month_length += _to_number(ledger_row.get("清淤长度"))
        return {
            "待安排清淤": pending,
            "本月清淤长度": round(month_length, 2),
            "清出泥量": round(total_mud, 2),
        }

    def ledger_entries(self) -> list[dict[str, Any]]:
        """调度台账：验收结论反映到这里，同一批次只有一行。"""
        return store.ledger_rows(LEDGER_SCOPE)

    # ---------- 登记 ----------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 批次号缺省取清淤单号，保证后续台账一定有去重键。
        entry["批次号"] = str(values.get("批次号") or values.get("清淤单号") or "").strip()
        for field in CANCEL_CLEAR_FIELDS:
            if field != "淤积厚度":
                entry[field] = ""
        entry["status"] = STATUS_ORDER[0]
        entry["清淤状态"] = entry["status"]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    # ---------- 动作 ----------
    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        request_id = str(values.get("request_id") or "").strip()
        if request_id and request_id in self._action_results:
            # 断线重连后带同一请求编号重试：沿用首次结果，不重复执行。
            return self._action_results[request_id]

        result = self._run_action(entry_id, action, values)
        if request_id and result[0] is not None:
            self._action_results[request_id] = result
        return result

    def _run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"清淤单 {entry_id} 不存在或已归档"
        if not action:
            return None, "未指定要执行的动作（安排清淤、确认完成、取消清淤）"

        current = str(entry.get("status"))
        allowed = ALLOWED_ACTIONS.get(current, {})
        if action not in allowed:
            reason = self._reject_reason(current, action)
            return None, reason
        target = allowed[action]

        if action == "取消清淤":
            self._apply_cancel(entry)
        elif action == "安排清淤":
            entry["status"] = target
        elif action == "确认完成":
            message = self._apply_complete(entry, values)
            if message:
                return None, message
        self._sync_flags(entry)
        done_message = {
            "安排清淤": "清淤单已安排，状态更新为清淤中",
            "确认完成": "清淤单已完成，验收结论已同步到调度台账",
            "取消清淤": "清淤单已取消，已退出待安排队列并清空作业字段",
        }[action]
        return entry, done_message

    @staticmethod
    def _reject_reason(current: str, action: str) -> str:
        if current == "已取消":
            if action == "取消清淤":
                return "清淤单已取消，请勿重复取消"
            return f"清淤单已取消，不能再执行「{action}」"
        if current == "已完成":
            if action == "取消清淤":
                return "清淤单已完成并通过验收，不能取消或退回待安排"
            return f"清淤单已完成，不能重复执行「{action}」"
        if current == "清淤中" and action == "取消清淤":
            return "清淤单已在作业中，不能取消；如需中止请先完工验收"
        if current == "待安排" and action == "确认完成":
            return "清淤单尚未安排作业，不能直接确认完成"
        return f"「{current}」状态不允许执行「{action}」"

    @staticmethod
    def _apply_cancel(entry: dict[str, Any]) -> None:
        entry["status"] = "已取消"
        for field in CANCEL_CLEAR_FIELDS:
            entry[field] = ""

    def _apply_complete(self, entry: dict[str, Any], values: dict[str, Any]) -> str:
        accept = str(values.get("验收结论") or "验收合格").strip()
        if accept not in ACCEPT_RESULTS:
            return f"验收结论只能是：{'、'.join(ACCEPT_RESULTS)}"
        entry["status"] = "已完成"
        entry["验收结论"] = accept
        entry["完成日期"] = str(values.get("完成日期") or date.today().isoformat())
        for field in ("清淤长度", "清出泥量", "作业班组"):
            submitted = values.get(field)
            if submitted is not None and str(submitted).strip():
                entry[field] = submitted
        self._write_ledger(entry)
        return ""

    @staticmethod
    def _sync_flags(entry: dict[str, Any]) -> None:
        status = str(entry.get("status"))
        entry["清淤状态"] = status
        entry["pending"] = status in ("待安排", "清淤中")
        entry["abnormal"] = entry.get("验收结论") == "验收不合格"

    def _write_ledger(self, entry: dict[str, Any]) -> None:
        """确认完成把验收结论同步到调度台账；同批次只保留一行，计量只算一次。"""
        table = store.ledger(LEDGER_SCOPE)
        batch_no = str(entry.get("批次号") or entry.get("清淤单号") or "").strip()
        order_no = str(entry.get("清淤单号") or "").strip()
        row = table.get(batch_no)
        if row is None:
            table[batch_no] = {
                "key": batch_no,
                "批次号": batch_no,
                "清淤管段": entry.get("清淤管段", ""),
                "代表单号": order_no,
                "清淤长度": entry.get("清淤长度", ""),
                "清出泥量": entry.get("清出泥量", ""),
                "完成日期": entry.get("完成日期", ""),
                "验收结论": entry.get("验收结论", ""),
                "关联单数": 1,
                "关联单号": order_no,
            }
            return
        # 同批次重复完工/断线重试：计量沿用首张已完工单，验收结论以最新一次为准。
        related = [item for item in str(row.get("关联单号", "")).split(",") if item]
        if order_no and order_no not in related:
            related.append(order_no)
        row["关联单号"] = ",".join(related)
        row["关联单数"] = len(related)
        row["验收结论"] = entry.get("验收结论", row.get("验收结论"))
        for field in ("清淤长度", "清出泥量", "完成日期", "清淤管段"):
            if not row.get(field) and entry.get(field):
                row[field] = entry[field]
