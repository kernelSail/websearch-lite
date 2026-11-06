"""P5 存储迁移、备份与恢复（V1.1 §15）。"""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..common import now_iso
from ..paths import find_project_root

ROOT = find_project_root()


def ensure_version_table(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
      version TEXT PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)""")
    db.commit()


def migrate(store) -> dict:
    """按 migrations/*.sql 顺序应用，已应用版本跳过。"""
    applied = []
    with __import__("contextlib").closing(store._connect()) as db:
        ensure_version_table(db)
        existing = {r[0] for r in db.execute("SELECT version FROM schema_migrations")}
        for path in sorted((ROOT / "migrations").glob("*.sql")):
            version = path.stem
            if version in existing:
                continue
            sql = path.read_text(encoding="utf-8")
            db.executescript(sql)
            checksum = hashlib.sha256(sql.encode()).hexdigest()[:16]
            db.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (version, now_iso(), checksum))
            db.commit()
            applied.append(version)
        return {"applied": applied, "total": len(list((ROOT / "migrations").glob('*.sql'))),
                "current": max(existing | set(applied)) if (existing or applied) else None}


def backup(store, *, backup_dir: str | None = None) -> dict:
    """SQLite 在线备份 + 域配置/Schema + 迁移记录 + 评估集。"""
    from contextlib import closing

    cfg = json_load_config()
    target = Path(backup_dir or cfg.get("p5", {}).get("backup_dir", str(ROOT / "backups")))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = target / stamp
    dest.mkdir(parents=True, exist_ok=True)
    db_path = Path(store.path)
    # 注意：sqlite3 的 context manager 只 commit/rollback，不关闭连接，必须显式 closing
    with closing(sqlite3.connect(str(db_path))) as src, \
            closing(sqlite3.connect(str(dest / "registry.db"))) as dst:
        src.backup(dst)
    for sub in ("domains", "migrations", "eval"):
        src_dir = ROOT / sub
        if src_dir.exists():
            shutil.copytree(src_dir, dest / sub, dirs_exist_ok=True)
    (dest / "config.json").write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    manifest = {"created_at": now_iso(), "database": str(db_path),
                "files": [str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()]}
    (dest / "manifest.json").write_text(__import__("json").dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"backup_dir": str(dest), "files": len(manifest["files"]), "manifest": manifest}


def json_load_config() -> dict:
    import json
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def verify_backup(backup_dir: str | Path) -> dict:
    """备份有效性演练：数据库可打开、表完整、配置/Schema 存在。"""
    from contextlib import closing

    dest = Path(backup_dir)
    db_path = dest / "registry.db"
    if not db_path.exists():
        return {"valid": False, "reason": "missing registry.db"}
    with closing(sqlite3.connect(str(db_path))) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"documents", "document_versions", "facts", "fact_versions", "documents_index"}
        missing = sorted(required - tables)
        docs = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    files_ok = (dest / "config.json").exists() and (dest / "migrations").exists()
    return {"valid": not missing and files_ok, "missing_tables": missing,
            "documents": docs, "config_and_migrations": files_ok}


def restore(store, backup_dir: str | Path, *, dry_run: bool = True) -> dict:
    """恢复演练：默认 dry_run 只校验；dry_run=False 时把备份库覆盖为当前库。"""
    check = verify_backup(backup_dir)
    if not check["valid"]:
        return {"restored": False, "check": check}
    if dry_run:
        return {"restored": False, "dry_run": True, "check": check}
    cfg = json_load_config()
    target = Path(cfg["database"])
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(backup_dir) / "registry.db", target)
    return {"restored": True, "target": str(target), "check": check}

def check_storage_paths(store) -> dict:
    """移动盘路径识别：域 storage_path 不可用时明确报告，不静默返回空。"""
    cfg = json_load_config()
    paths = []
    with __import__("contextlib").closing(store._connect()) as db:
        for row in db.execute("SELECT domain_id,storage_path,enabled FROM domains"):
            path = Path(row[1]) if row[1] else None
            paths.append({
                "domain_id": row[0], "path": row[1] or "",
                "exists": bool(path and path.exists()),
                "enabled": bool(row[2]),
            })
    return {
        "temp_root": cfg.get("temp_root", ""),
        "temp_exists": Path(cfg.get("temp_root", "")).exists(),
        "database": cfg.get("database", ""),
        "database_exists": Path(cfg.get("database", "")).exists(),
        "domains": paths,
        "offline_domains": [p["domain_id"] for p in paths if p["enabled"] and not p["exists"]],
    }
