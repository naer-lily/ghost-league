# 前端下一版 · React + TypeScript

这是本仓库前端的第三个新栈迭代：三页（首页、排行榜、个人页）从“多个圆角卡片拼成的
统计面板”重排为无卡片、图标优先的游戏界面。旧 `web/` 原样保留，仍是当前生产入口；
`frontend/` 包含真实首页、完整小组榜和个人页，构建产物输出到仓库根目录的
`web-next/`，由现有静态服务单独提供，不覆盖 `web/`，也不新增生产端口。

## 技术栈

- React 18 + TypeScript + Vite 5
- React Router 6
- TanStack Query 5（服务端状态、30 秒轮询、错误与重试）
- Zustand 4（纯客户端 UI 状态）
- Radix UI primitives（Tooltip、Dialog 无障碍底座）
- Motion / framer-motion（页面切换、数字滚动、节点反馈）
- lucide-react（线性图标）
- CSS 自定义属性 + CSS Modules；token、字体栈、3D 按钮和图标优先的深色界面语言移植自
  `prototype/src/styles.css`，三页主内容不再使用内容卡片
- Vitest + Testing Library + Playwright

没有 Tailwind、MUI、Chakra、Element Plus，也没有引入后台 UI 套件。

## 目录

```text
frontend/
  src/
    api/          # fetch 封装、Bearer 注入、API 类型、TanStack Query hook
    components/   # 应用外壳、纯图标导航、三合一 PlayerHeader、榜单、TierIcon、StreakBadge、进度环
    lib/          # API → 页面视图映射、段位资源路径、数字/时间格式、错误文案、音效
    pages/        # 真实首页 / 小组榜 / 个人页、登录、余烬与历史占位
    store/        # Zustand UI 状态；复用旧 token
    styles/       # token + 全局基础样式
    test/         # Vitest setup 与 fixtures
  e2e/            # Playwright 真数据截图和对比检查
```

## 启动与构建

```bash
cd frontend
npm ci

# 开发服务器固定 127.0.0.1:4174
# GHOST_LEAGUE_API_PROXY 只用于本地 /v1、/avatars 代理，不写进部署
# 也可以在 frontend/.env.local 里设置（已 gitignore）；默认 http://127.0.0.1:8095
GHOST_LEAGUE_API_PROXY=http://127.0.0.1:8095 npm run dev
# 打开 http://127.0.0.1:4174/
```

构建到 `web-next/`：

```bash
npm run build
# = tsc --noEmit && vite build
```

其他命令：

```bash
npm run typecheck     # 严格模式 tsc --noEmit
npm run test          # Vitest + Testing Library
npm run test:e2e      # Playwright（需要真实 token 与旧页面地址）
```

生产接入不在本迭代范围内：`web-next/` 交给现有静态服务单独提供；静态服务需要把
非文件路径回退到 `web-next/index.html`（SPA fallback，Vite 开发服务器已内置），
`/v1` 与 `/avatars` 在生产同源访问，开发时只通过 Vite 代理。旧 `web/index.html`、
`web/app.js`、`web/style.css`、`web/sw.js` 未修改。

## 登录态与真实数据

- 复用旧页面同一个 `localStorage["gl.token.v1"]`，以 `Authorization: Bearer <token>`
  访问 API。没有新建账号体系；登录页只校验并保存这个既有 token。
- 首页只读以下现有接口：
  - `GET /v1/me/profile`
  - `GET /v1/me/status`
  - `GET /v1/league/standings`
- 首页展示真实：单行 `PlayerHeader`（头像 64px、名字、段位图标 + 段位/组号、连胜）、
  180px 的今日 100 XP 主视觉圆环、小组榜前 5 行；名次 `10/15` 是榜单标题右侧的小标签，
  本周 XP 是同一标题行的无框数字。首页不再有“排名”卡、`PageAside`、“节奏/赛程/计分”
  三张卡。
- `/league` 用同一份快照渲染完整小组榜（全部行，不只前三），`PlayerHeader` 下方只有
  一条组信息 + 结算倒计时；左侧名次是裸数字，前 3 名金/银/铜色，行内右侧只有 XP 数字，
  单位在榜单标题说明一次；当前用户行用青色左侧竖条 + 轻底色，不是圆角卡片。
- `/me` 使用同一个 `PlayerHeader`，下方是一行三列无框统计（本周 XP、排名、余烬）、
  68px 的紧凑今日 XP 状态环和“我的榜单位置”一行；没有第二个头像/段位/连胜块。
- 三页主内容无内容卡片：没有圆角背景、边框或阴影把一组信息包起来；层级靠字号、
  颜色、留白和全宽细分隔线。头像、段位图标、图标按钮、底部导航选中态、圆环内部和
  小标签仍可保留自己的圆角/底色。
- 段位图标复用旧 `web/assets/tiers/` 的 10 个资源：`TierIcon` 按
  `profile.icon_theme` 选择 `classic` / `material`，未知主题回退 `classic`，加载失败
  回退另一套主题；路径通过 `import.meta.env.BASE_URL` 拼接。
- `StreakBadge` 只显示火焰 + 整数：今天已打卡时火焰为暖橙色，未打卡时火焰和数字都是
  纯灰度；没有可见的“连胜 / 连续 / 已打卡”文字，`aria-label` 只服务读屏。三页的
  玩家头部和榜单行都复用它。
- 接口失败显示无卡片错误态和“重试”，不显示假数字；无小组时显示明确空态。首屏统计来自
  同一次 `Promise.all` 快照，避免三块数据来自不同时间点。
- 设置里的声音是本地真实音效开关；外观会调用现有 `PATCH /v1/me/profile` 的
  `icon_theme` 能力。本迭代没有实现打卡、补签、关注、分享等联赛写操作。

## 响应式与可访问性

- `< 960px`：顶部栏 + 底部 5 个纯图标 Tab。
- `≥ 960px`：左侧 88px 纯图标 rail；主内容仍是居中的游戏列（首页/个人页 640px、
  排行榜 760px），不铺成后台仪表盘。
- 底部和侧边导航不显示可见文字，只保留图标、`aria-label` 和 Radix Tooltip；选中项有
  对应颜色的底块。
- 保留 skip link、`:focus-visible`、44px 最小触达、`prefers-reduced-motion`。
- 路由：`/` 首页；`/league` 完整小组榜；`/me` 个人页；`/embers`、`/history` 仍是
  可导航占位页，不展示占位数字。

## 测试与本地证据

单元 / 组件测试覆盖：

- API 映射：段位、今日 XP、本周 XP、名次、连胜、前 3、自己的行、结算倒计时。
- Bearer 注入、错误解析、网络失败、token 读写。
- `TierIcon` 10 个段位的 classic / material `src`、未知主题/段位回退、`onError` 换主题。
- `StreakBadge` 已打卡 / 未打卡的灰度与彩色状态、可见文本不含“天/连胜/连续/已打卡”。
- `PlayerHeader` 四个部分同属一个 `display:flex; flex-wrap:nowrap` 行，头像 64px、
  段位图标 20px，且没有卡片外壳。
- 首页真实数据、5 行榜单、无 `RankCard` / `PageAside`、空态、错误态、点击重试后恢复。
- `/league` 完整行数等于 API、前三名 data-medal 与金银铜配色、行内无 XP 后缀、
  当前用户行 `data-me`、行内无语言/状态拼接文本。
- `/me` 单行头部、三列统计、紧凑 XP 环、“我的榜单位置”行、无重复段位块。
- 三页主内容无 `class*="card"`；底部导航可见文本为空，仅保留 `aria-label` / Tooltip。

运行真实数据截图与旧/新对比：

```bash
cd frontend
GHOST_LEAGUE_TOKEN_FILE=/path/to/token \
GHOST_LEAGUE_API_PROXY=http://127.0.0.1:8095 \
npm run test:e2e
```

也可以把 token 放进 `GHOST_LEAGUE_TOKEN`。默认使用 `/usr/bin/google-chrome`；其他环境
用 `CHROME_PATH=/path/to/chrome` 指定。Playwright 会：

- 在 390×844 与 1440×900 打开真实数据的首页、完整小组榜和个人页并截图；
- 校验段位 PNG 真的加载（不是通用图标）、底部/侧边导航无可见文字；
- 校验 `PlayerHeader` 四个部分在同一 flex 行且垂直居中，头像 64px；
- 校验首页只有 5 行、无排名卡/`PageAside`，排行榜 15 行、前三名金银铜、行内无 XP 后缀、
  当前用户行有青色左条和整行底色；
- 校验三页主内容没有 `class*="card"`，`[data-flat]` 区块没有圆角/阴影/底色；
- 校验每行名字下是火焰 + 整数、未打卡行两处颜色 R=G=B、已打卡行火焰带颜色；
- 校验横向 overflow、console/page error、可见交互元素 ≥44px、头像无空白圆；
- 写入 `report.json`，并在抓取前后比对 API 签名，证明展示没有写 live 数据。

截图与报告（本地证据，`artifacts/` 已在 `.gitignore` 中，含真实榜单信息，不提交）：

```text
artifacts/frontend-iteration-3/390/home.png
artifacts/frontend-iteration-3/390/league.png
artifacts/frontend-iteration-3/390/me.png
artifacts/frontend-iteration-3/1440/home.png
artifacts/frontend-iteration-3/1440/league.png
artifacts/frontend-iteration-3/1440/me.png
artifacts/frontend-iteration-3/report.json
```

最近一次本地验证（2026-10-31）：

```bash
npm ci                                  # 229 packages
npm run build                           # tsc --noEmit + vite build 通过
npm run test                            # 10 个测试文件，32 个测试通过
GHOST_LEAGUE_TOKEN_FILE=/path/to/token \
  npx playwright test e2e/home.spec.ts  # 1 passed
```

Playwright 两个视口均无横向 overflow、无 console/page error、无小于 44px 的可见触达
元素；完整榜单 15 行（8 行已打卡、7 行未打卡），当前用户第 10 名，首页 5 行，前三名
颜色分别为金/银/铜，当前用户行有青色左条。`artifacts/` 不提交；旧 `web/`、
`ghost_league/` 后端和 live 数据均未修改。

## 后续小步

1. 余烬、历史页读取现有接口。
2. 在写操作单独评审后再接打卡、补签、关注、分享。
3. 生产入口切换单独安排，届时仅改变静态服务挂载点，不改 API。
