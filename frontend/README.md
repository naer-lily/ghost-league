# 前端下一版 · React + TypeScript

这是本仓库前端的第一个新栈迭代。旧 `web/` 原样保留，仍是当前生产入口；
`frontend/` 只建立新地基和真实首页，构建产物输出到仓库根目录的 `web-next/`，由现有
静态服务单独提供，不覆盖 `web/`，也不新增生产端口。

## 技术栈

- React 18 + TypeScript + Vite 5
- React Router 6
- TanStack Query 5（服务端状态、30 秒轮询、错误与重试）
- Zustand 4（纯客户端 UI 状态）
- Radix UI primitives（Tooltip、Dialog 无障碍底座）
- Motion / framer-motion（页面切换、数字滚动、节点反馈）
- lucide-react（线性图标）
- CSS 自定义属性 + CSS Modules；token、字体栈、3D 按钮和卡片语言移植自
  `prototype/src/styles.css`
- Vitest + Testing Library + Playwright

没有 Tailwind、MUI、Chakra、Element Plus，也没有引入后台 UI 套件。

## 目录

```text
frontend/
  src/
    api/          # fetch 封装、Bearer 注入、API 类型、TanStack Query hook
    components/   # 应用外壳、导航、榜单、设置、Toast、头像、进度环
    lib/          # API → 页面视图映射、数字/时间格式、错误文案、音效
    pages/        # 真实首页、登录、其余路由占位
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
- 首页展示真实：段位、今日 XP / 目标、本周名次、本周累计、连胜、小组前 3、自己的行、
  组内人数、结算倒计时、余烬余额。
- 接口失败显示错误态和“重试”，不显示假数字；无小组时显示明确空态。首屏统计来自同一
  次 `Promise.all` 快照，避免三块数据来自不同时间点。
- 设置里的声音是本地真实音效开关；外观会调用现有 `PATCH /v1/me/profile` 的
  `icon_theme` 能力。本迭代没有实现打卡、补签、关注、分享等联赛写操作。

## 响应式与可访问性

- `< 960px`：顶部栏 + 底部 5 Tab。
- `≥ 960px`：左侧 88px rail。
- `≥ 1200px`：rail + 560px 主列 + 300px 右侧窄栏。
- 保留 skip link、`:focus-visible`、44px 最小触达、`prefers-reduced-motion`。
- Radix Tooltip / Dialog 提供键盘与焦点管理；所有图标按钮有 `aria-label`。
- 路由：`/` 首页；`/league`、`/embers`、`/history`、`/me` 是可导航占位页，不展示
  占位数字。

## 测试与本地证据

单元 / 组件测试覆盖：

- API 映射：段位、今日 XP、本周 XP、名次、连胜、前 3、自己的行、结算倒计时。
- Bearer 注入、错误解析、网络失败、token 读写。
- 首页真实数据、空态、错误态、点击重试后恢复。
- 不显示假数据的空态断言。

运行真实数据截图与旧/新对比：

```bash
cd frontend
GHOST_LEAGUE_TOKEN_FILE=/path/to/token \
E2E_OLD_BASE_URL=https://your-host.example:8445 \
GHOST_LEAGUE_API_PROXY=http://127.0.0.1:8095 \
npm run test:e2e
```

也可以把 token 放进 `GHOST_LEAGUE_TOKEN`。默认使用 `/usr/bin/google-chrome`；其他环境
用 `CHROME_PATH=/path/to/chrome` 指定。Playwright 会：

- 在 390×844 与 1440×900 打开新首页并截图；
- 用同一 token 打开旧 `web/`，断言段位、今日 XP、本周 XP、名次、连胜、前三名与新页一致；
- 检查横向 overflow、console/page error、可见交互元素 ≥44px、产品禁用词；
- 生成旧/新同屏对比图与 `report.json`。

截图与报告（本地证据，`artifacts/` 已在 `.gitignore` 中，含真实榜单信息，不提交）：

```text
artifacts/frontend-iteration-1/390/home.png
artifacts/frontend-iteration-1/1440/home.png
artifacts/frontend-iteration-1/390/old-web.png
artifacts/frontend-iteration-1/1440/old-web.png
artifacts/frontend-iteration-1/compare/390.png
artifacts/frontend-iteration-1/compare/1440.png
artifacts/frontend-iteration-1/report.json
```

最近一次本地验证：

- `npm run build` 通过，产物在 `web-next/`。
- `npm run typecheck` 通过。
- `npm run test`：3 个测试文件，18 个测试全部通过。
- Playwright：390/1440 均无横向 overflow、无 console error、无 page error、无 <44px
  可见触达元素；旧/新两侧数字在同一抓取窗口内一致。
- `git diff -- web/` 为空；旧 PWA 文件一行未改。

## 后续小步

1. 小组榜完整页、成员资料与升降级区。
2. 余烬、历史、个人页读取现有接口。
3. 在写操作单独评审后再接打卡、补签、关注、分享。
4. 生产入口切换单独安排，届时仅改变静态服务挂载点，不改 API。
