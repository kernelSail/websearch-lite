# WebSearch Lite 联网搜索（P9）

时间：2026-11-06

## 背景

之前系统只有「按配置站点定向采集 + 本地索引」（2 个域、26 篇文档），
输入任意关键词只能搜到库里已有的内容。这不是 bug，但缺了「联网搜索」这条能力。

现在补上：**本地库 与 联网搜索 双模式**。

## 实现

| 模块 | 说明 |
|---|---|
| `app/websearch.py` | 元搜索客户端：Bing HTML 端点优先、搜狗备用；`HTMLParser` 解析结果；Bing 跳转链 `bing.com/ck/a?u=a1<base64>` 自动还原真实 URL；gzip 解压与多编码兜底 |
| `app/ingest.py` | 把任意 URL 抓取入库：robots → 抓取 → 正文抽取 → 去重 → 入库，归入 `adhoc` 域（网页收录），与定向采集域区分；同 URL 重复收录不产生新版本 |
| `server.py` | 新增 `GET /api/websearch?q=&limit=`（联网搜索）与 `POST /api/actions/ingest`（收录），写操作串行 |
| 前端 | 检索页顶部加「本地库 / 联网搜索」模式切换；联网结果卡片带来源引擎、URL、「收录到本地库」按钮；收录后回到本地库即可搜到 |

## 设计取舍

- **不绕过反爬**：用正常 UA、单次低频请求，Bing/搜狗公开 HTML 端点；不并发轰炸、不做验证码绕过。
- **结果不入库**：联网搜索只读展示，用户显式点「收录」才落库，避免库被噪音灌满。
- **收录后完整走本地链路**：正文抽取、去重、FTS/Tantivy 索引，与站点采集等价；归入 `adhoc` 域方便区分来源。
- **引擎降级链**：Bing 失败→搜狗，全部失败返回空并带回错误原因，不抛异常给前端。

## 验证

```
GET /api/websearch?q=大模型最新进展  → engine=bing, 8 条结果
POST /api/actions/ingest {url}      → ok, chars=12080, new_version=true
GET /api/search?q=大模型排行榜       → 1 条，domain=adhoc（收录后可搜到）
GET /api/websearch?q=DeepSeek 最新模型 → engine=bing, 3 条
```

单元测试 6 项（`tests/test_websearch.py`）：Bing 解析、URL 还原、搜狗解析、引擎降级、全失败返回空、收录后本地可搜且重复收录不建新版本。
全部测试 **69 passed**。

## 限制

- Bing/搜狗 HTML 结构变化会使解析失效；解析器与网络解耦，改 fixture 即可回归。
- 未接入正式搜索 API（Brave/Google），因此没有 SLA、可能被限流；个人低频使用足够。
- 收录页面不做结构化事实抽取（adhoc 域无封闭 Schema），只做文档级检索。
- 联网结果不参与本地的事实验证与冲突裁决，二者是独立数据源。
- DuckDuckGo、searx.be 在当前网络环境不可达（超时），故未作为后端。
