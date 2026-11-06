"""诊断：当前索引覆盖的域、站点与文档数。"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from websearch_lite.app.crawl import load_config


def main() -> int:
    config = load_config()
    db = sqlite3.connect(config["database"])
    db.row_factory = sqlite3.Row
    print("域 / 文档数：")
    for row in db.execute(
        """SELECT d.domain_id, d.label, COUNT(i.doc_id) AS n
           FROM domains d LEFT JOIN documents_index i ON i.domain_id=d.domain_id
           GROUP BY d.domain_id"""
    ):
        print(f"  {row['label'] or row['domain_id']}: {row['n']} 篇")

    hosts = Counter()
    for row in db.execute("SELECT canonical_url FROM documents_index"):
        url = row["canonical_url"] or ""
        hosts[urlparse(url).netloc or "(空)"] += 1
    print("\n来源站点：")
    for host, count in hosts.most_common():
        print(f"  {host}: {count} 篇")

    total = db.execute("SELECT COUNT(*) FROM documents_index").fetchone()[0]
    print(f"\n索引文档总数：{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
