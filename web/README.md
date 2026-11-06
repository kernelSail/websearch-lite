# WebSearch Lite 控制台（前端）

深色玻璃拟态风格的本地可视化前端，配合 `websearch_lite.server` 提供的 HTTP API 使用。

## 技术栈

| 项 | 选择 |
|---|---|
| 框架 | React 18 + TypeScript |
| 构建 | Vite 6 |
| 样式 | 手写 CSS（无 UI 框架、无 Tailwind），设计变量集中在 `src/styles.css` |
| 路由 | hash 路由（`#/facts` 等），无需服务端配合 |
| 数据 | 仅 `fetch` 本地 `/api/*`，无外部依赖与埋点 |

## 目录

```
web/
  index.html
  vite.config.ts          # dev 端口 5173，/api 代理到 8765
  src/
    main.tsx
    App.tsx               # 侧栏 + hash 路由 + 30s 概览轮询
    api.ts                # API 客户端与时间/ID 格式化
    types.ts              # 后端契约类型
    styles.css            # 设计系统（颜色/玻璃/动效/响应式）
    components/
      Tags.tsx            # 域、验证状态、谓词标签
      Toast.tsx           # 轻提示
      ConfirmDialog.tsx   # 写操作二次确认
      DocumentDrawer.tsx  # 文档详情抽屉（版本 + 证据）
    pages/
      SearchPage.tsx      # 检索、筛选、结果卡片、快捷查询、最近入库
      FactsPage.tsx       # 事实表格、状态/域筛选、谓词分布
      ConflictsPage.tsx   # 冲突快照对比 + 人工裁决
      ReviewsPage.tsx     # 人工复核队列
      SystemPage.tsx      # 存储/一致性/来源健康 + 触发采集与验证
```

## 页面

| 页面 | 内容 |
|---|---|
| 检索 | 主入口。跨域检索、域/状态筛选、结果卡片（标题原文、摘要、验证状态、谓词、score）、点击打开详情抽屉、URL 可分享（`?q=`） |
| 事实 | 49 条事实版本的表格视图，按域/状态过滤，显示证据数与实际使用的分类器 |
| 冲突 | 并排展示当前值与竞争值，选择胜出版本后二次确认，写入裁决记录 |
| 复核 | 低置信实体、冲突、任务重试耗尽等产生的待办队列 |
| 系统 | 文档/事实/实体计数、验证状态分布、来源健康、最近运行、最近入库；「触发采集」「触发验证」带二次确认 |

## 设计

- 深色基底 + 三处径向光晕（青 / 紫 / 绿），顶部 1px 渐变光带
- 玻璃拟态：`backdrop-filter: blur(20px) saturate(130%)` + 半透明渐变 + 内侧高光
- 强调色青蓝 → 紫渐变；语义色：绿=已验证、黄=单源、红=冲突、灰=过期
- 动效：卡片 hover 微抬升、抽屉滑入、确认框缩放、骨架屏 shimmer
- 响应式：≤1100px 侧栏转为横向导航
- 快捷键 `/` 聚焦搜索框，`Esc` 关闭抽屉/弹层

## 启动

```bash
# 1) 后端 API（项目根目录）
$env:PYTHONPATH="src"
python -m websearch_lite.server          # http://127.0.0.1:8765

# 2) 前端开发模式（另一个终端）
cd web
pnpm install
pnpm dev                                  # http://127.0.0.1:5173
```

生产模式无需 dev server：`pnpm build` 后由 `websearch_lite.server` 直接托管 `web/dist`，访问 `http://127.0.0.1:8765/` 即可。

## API 契约

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/overview` | 统计、域、来源健康、一致性、最近运行/入库 |
| GET | `/api/search?q=&domain=&limit=&status=` | 检索 + 引用完整性 |
| GET | `/api/documents?domain=&q=&limit=&offset=` | 文档分页列表 |
| GET | `/api/documents/<doc_id>` | 文档详情 + 版本 + 证据 |
| GET | `/api/facts?domain=&status=&limit=` | 事实列表 |
| GET | `/api/conflicts` | 冲突快照 |
| GET | `/api/reviews?limit=` | 待复核任务 |
| POST | `/api/conflicts/resolve` | `{conflict_id, winner, reason}` |
| POST | `/api/actions/crawl` | `{domain?, max_pages?}` |
| POST | `/api/actions/verify` | `{domain?}` |

写操作在服务端用全局锁串行执行，避免并发抓取/验证互相干扰。

## 注意

- `web/node_modules`、`web/dist`、`.shots` 不进版本库。
- 前端只读为主；三个写操作均需二次确认。
- 服务端默认只绑定 `127.0.0.1`，不对外暴露。
