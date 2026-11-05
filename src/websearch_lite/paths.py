"""项目根定位：按 config.json 向上查找，避免按 __file__ 深度硬编码。"""
from pathlib import Path


def find_project_root(start: str | Path | None = None) -> Path:
    current = Path(start or __file__).resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / "config.json").exists() and (candidate / "migrations").exists():
            return candidate
    raise RuntimeError("cannot locate project root (config.json + migrations/)")
