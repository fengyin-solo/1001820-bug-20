"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_LEDGER_ROWS, SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 调度台账按业务子域分表（如清淤疏浚 -> dredge），每行以业务键去重
        self._ledgers: dict[str, dict[Any, dict[str, Any]]] = {
            name: {row["key"]: dict(row) for row in rows}
            for name, rows in SEED_LEDGER_ROWS.items()
        }

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def ledger(self, scope: str) -> dict[Any, dict[str, Any]]:
        """取某个业务子域的调度台账（以业务键为索引，天然防重）。"""
        return self._ledgers.setdefault(scope, {})

    def ledger_rows(self, scope: str) -> list[dict[str, Any]]:
        """台账按业务键排序展开，供列表/导出使用。"""
        table = self.ledger(scope)
        return [table[key] for key in sorted(table, key=lambda item: str(item))]

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
