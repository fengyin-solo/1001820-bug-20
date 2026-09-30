"""清淤疏浚业务规则：状态流转、字段校验、取消清理、批次去重与断线重试都收在这里。"""
from __future__ import annotations

import threading
from datetime import date
from typing import Any

from app.store import store

MODULE = "dredge"
REQUIRED_FIELDS = ["清淤单号", "清淤管段", "淤积厚度"]
# 安排作业时由现场录入的字段；取消重复开单时这些值必须一并清掉，不能残留取消前的口径。
EXECUTION_FIELDS = ["淤积厚度", "清淤长度", "清出泥量", "作业班组", "完成日期", "验收结论"]
NUMERIC_FIELDS = ["淤积厚度", "清淤长度", "清出泥量"]
STATUS_PENDING = "待安排"
STATUS_RUNNING = "清淤中"
STATUS_DONE = "已完成"
STATUS_CANCELED = "已取消"
STATUS_ORDER = [STATUS_PENDING, STATUS_RUNNING, STATUS_DONE, STATUS_CANCELED]
FINAL_STATUSES = {STATUS_DONE, STATUS_CANCELED}
ACCEPT_RESULTS = ["合格", "不合格"]

# 动作 -> 可执行的前置状态。只允许按队列推进；已完成/已取消是终态，重复取消不会把作业退回待安排。
ACTION_RULES: dict[str, dict[str, Any]] = {
    "安排清淤": {"target": STATUS_RUNNING, "from": {STATUS_PENDING}},
    "确认完成": {"target": STATUS_DONE, "from": {STATUS_RUNNING}},
    "取消清淤": {"target": STATUS_CANCELED, "from": {STATUS_PENDING, STATUS_RUNNING}},
}

# 断线重试登记表：client_token 唯一标识一次点击，重复提交直接回放首次结果，不做第二次状态流转。
_idem_lock = threading.Lock()
_idem_records: dict[str, dict[str, Any]] = {}


def _to_number(value: Any) -> float:
    """把录入值转成数字参与统计；样例占位文字、空值一律按 0 处理。"""
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    """列表与详情共用同一出口：清淤状态取真实流转状态，保证任何入口看到的口径一致。"""
    item = dict(row)
    item["清淤状态"] = row.get("status", STATUS_PENDING)
    return item


class DredgeService:
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
        return [_serialize(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return _serialize(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        rows = store.rows(MODULE)
        code = str(values.get("清淤单号")).strip()
        # 同一清淤单号视为重复开单：登记时就拦住，避免又排进待安排队列。
        if any(str(row.get("清淤单号", "")).strip() == code for row in rows):
            return None, f"清淤单号 {code} 已存在，请勿重复开单"
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        if str(values.get("批次号") or "").strip():
            entry["批次号"] = str(values.get("批次号")).strip()
        entry["status"] = STATUS_PENDING
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return _serialize(entry), "清淤单已登记"

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
        client_token: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        if client_token:
            with _idem_lock:
                replay = _idem_records.get(client_token)
            if replay is not None:
                # 断线后重试：回放首次结论（含首次拒绝原因），不重复扣状态、不重复计数。
                return replay["entry"], replay["message"]

        entry = store.find(MODULE, entry_id)
        if entry is None:
            return self._record(client_token, None, f"清淤单 {entry_id} 不存在或已归档")
        rule = ACTION_RULES.get(action)
        if rule is None:
            return self._record(client_token, None, f"动作「{action}」不属于清淤疏浚可执行范围")

        current = str(entry.get("status", STATUS_PENDING))
        if current not in rule["from"]:
            if current == rule["target"]:
                return self._record(
                    client_token, _serialize(entry),
                    f"清淤单已是「{current}」状态，无需重复{action}",
                )
            return self._record(
                client_token, None,
                f"清淤单当前为「{current}」，不允许{action}；仅{'、'.join(sorted(rule['from']))}状态可执行",
            )

        if action == "取消清淤":
            # 取消确认：状态出队的同时清掉作业字段，详情/列表/统计都不再看到取消前的残留值。
            for field in EXECUTION_FIELDS:
                entry[field] = None
        elif action == "安排清淤":
            crew = str(values.get("作业班组") or "").strip()
            if not crew:
                return self._record(client_token, None, "安排清淤前必须指定作业班组")
            entry["作业班组"] = crew
        elif action == "确认完成":
            volume = str(values.get("清出泥量") or "").strip()
            if not volume or _to_number(volume) <= 0:
                return self._record(client_token, None, "确认完成前必须录入大于 0 的清出泥量")
            conclusion = str(values.get("验收结论") or "合格").strip()
            if conclusion not in ACCEPT_RESULTS:
                return self._record(
                    client_token, None, f"验收结论仅支持：{'、'.join(ACCEPT_RESULTS)}"
                )
            if str(values.get("清淤长度") or "").strip():
                entry["清淤长度"] = values["清淤长度"]
            entry["清出泥量"] = volume
            entry["完成日期"] = str(values.get("完成日期") or date.today())
            entry["验收结论"] = conclusion

        entry["status"] = rule["target"]
        entry["pending"] = entry["status"] not in FINAL_STATUSES
        entry["abnormal"] = False
        message = f"清淤单已{action}"
        if action == "确认完成" and entry.get("验收结论"):
            message += f"，验收结论：{entry['验收结论']}"
        return self._record(client_token, _serialize(entry), message)

    def _record(
        self, client_token: str | None, entry: dict[str, Any] | None, message: str
    ) -> tuple[dict[str, Any] | None, str]:
        if client_token:
            with _idem_lock:
                _idem_records[client_token] = {"entry": entry, "message": message}
        return entry, message

    def stats(self) -> dict[str, float]:
        """概览统计：待安排看队列长度；清淤长度/泥量只统计本月已完成、且按批次去重后的数据。"""
        rows = store.rows(MODULE)
        pending = sum(1 for row in rows if row.get("status") == STATUS_PENDING)
        month_prefix = date.today().strftime("%Y-%m")
        ledger = self.ledger_rows()
        month_rows = [row for row in ledger if str(row.get("完成日期") or "").startswith(month_prefix)]
        return {
            "pending": pending,
            "month_length": sum(_to_number(row.get("清淤长度")) for row in month_rows),
            "mud_volume": sum(_to_number(row.get("清出泥量")) for row in month_rows),
        }

    def ledger_rows(self) -> list[dict[str, Any]]:
        """调度台账：同一批次清淤疏浚只算一次。

        按批次号归并已完成的作业单，批次内取代表单（验收不合格优先暴露），
        长度/泥量等数值按批次计一次，不随重复开单累加。
        """
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in store.rows(MODULE):
            if row.get("status") != STATUS_DONE:
                continue
            batch = str(row.get("批次号") or row.get("清淤单号") or row.get("id"))
            groups.setdefault(batch, []).append(row)

        ledger: list[dict[str, Any]] = []
        for batch, members in groups.items():
            unqualified = [row for row in members if row.get("验收结论") == "不合格"]
            representative = unqualified[0] if unqualified else members[0]
            # 同一批次只算一次：数值不按单据条数累加，取批次实际产出（成员一致时天然不翻倍）。
            length = max((_to_number(row.get("清淤长度")) for row in members), default=0.0)
            volume = max((_to_number(row.get("清出泥量")) for row in members), default=0.0)
            thickness = max((_to_number(row.get("淤积厚度")) for row in members), default=0.0)
            conclusion = "不合格" if unqualified else str(representative.get("验收结论") or "合格")
            ledger.append({
                "批次号": batch,
                "清淤管段": representative.get("清淤管段"),
                "淤积厚度": thickness,
                "清淤长度": length,
                "清出泥量": volume,
                "作业班组": representative.get("作业班组"),
                "完成日期": representative.get("完成日期"),
                "验收结论": conclusion,
                "归并单数": len(members),
            })
        ledger.sort(key=lambda item: str(item.get("完成日期") or ""), reverse=True)
        return ledger
