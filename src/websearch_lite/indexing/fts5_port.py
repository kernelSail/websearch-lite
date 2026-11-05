"""P0 FTS5 后端适配成 SearchPort（对照基线，保持默认可用）。"""
from __future__ import annotations

from ..storage.sqlite_store import Store


class Fts5SearchPort:
    name = "fts5"

    def __init__(self, store: Store) -> None:
        self.store = store

    def search(self, query: str, *, filters: dict | None = None, limit: int = 20) -> list[dict]:
        domain_id = (filters or {}).get("domain_id")
        return self.store.search(query, domain_id=domain_id, limit=limit)

    def upsert(self, doc_id: str, document: dict) -> None:
        # P0 的 store.ingest 已经同步维护 FTS5 投影，这里不重复写
        pass

    def delete(self, doc_id: str) -> None:
        with __import__("contextlib").closing(self.store._connect()) as db:
            db.execute("DELETE FROM documents_index WHERE doc_id=?", (doc_id,))
            db.commit()

    def stats(self) -> dict:
        return {"engine": self.name, **self.store.stats()}

    def rebuild(self, documents: list[dict]) -> None:
        with __import__("contextlib").closing(self.store._connect()) as db:
            db.execute("DELETE FROM documents_index")
            db.execute('INSERT INTO documents_fts(documents_fts) VALUES(?)', ("rebuild",))
            db.commit()
