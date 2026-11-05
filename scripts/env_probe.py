import sqlite3, urllib.request, urllib.robotparser, sys

print("python", sys.version.split()[0])
print("sqlite", sqlite3.sqlite_version)
db = sqlite3.connect(":memory:")
db.execute('CREATE VIRTUAL TABLE t USING fts5(x, tokenize="trigram")')
db.execute('INSERT INTO t VALUES (?)', ("企业信息查询平台",))
print("fts5 trigram hit:", db.execute("SELECT count(*) FROM t WHERE t MATCH ?", ('"信息"',)).fetchone()[0])

sites = [
    "https://www.ccgp.gov.cn/",
    "https://www.ccgp.gov.cn/robots.txt",
    "http://www.ccgp.gov.cn/cggg/dfgg/gkzb/",
    "https://www.cninfo.com.cn/",
    "https://www.cninfo.com.cn/robots.txt",
    "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
]
for url in sites:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "websearch-lite/0.1 (personal; contact local)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read(400)
            print("OK", r.status, r.geturl(), "len", len(body), "type", r.headers.get("content-type"))
    except Exception as e:
        print("FAIL", url, type(e).__name__, str(e)[:120])
