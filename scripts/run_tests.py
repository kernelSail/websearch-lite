"""无 pytest 时的等价自测运行器（bundled Python 零第三方依赖）。"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT_BOOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_BOOT / "src"))


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT_BOOT / "tests" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run():
    suites = [load("test_p0"), load("test_p1"), load("test_p2"), load("test_p3"), load("test_p4")]
    passed = 0
    failed = []
    for suite in suites:
        print(f"--- {suite.__name__} ---")
        for name in sorted(n for n in dir(suite) if n.startswith("test_")):
            fn = getattr(suite, name)
            try:
                if name in ("test_register_and_ingest_idempotent", "test_search_fallback_and_domain_filter",
                            "test_consistency_and_crawl_tasks"):
                    with tempfile.TemporaryDirectory() as tmp:
                        store = suite.Store(Path(tmp) / "test.db", ROOT_BOOT / "migrations")
                        fn(store)
                else:
                    fn()
                passed += 1
                print(f"PASS {name}")
            except Exception as e:
                failed.append((name, e))
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{passed} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
