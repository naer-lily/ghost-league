# 炉火联赛前端 · React + TypeScript

`frontend/` 是当前维护的 React 18 + TypeScript + Vite 前端，包含首页（宿敌 + 赌注）、
小组/好友/动态榜、物品栏、历史时间线和个人页。构建产物输出到仓库根目录的 `web-next/`；
旧 `web/` 不修改，保留作生产回滚。生产切流只切换 `ghost_league/pwa.py` 的静态根，
不新增端口。

## 技术栈

- React 18 + TypeScript + Vite 5
- React Router 6
- TanStack Query 5（服务端状态、30 秒轮询、401 不重试）
- Zustand 4（纯客户端 UI 状态）
- Radix UI primitives（Tooltip、Dialog 无障碍底座）
- Motion / framer-motion（页面切换、数字滚动、节点反馈）
- lucide-react（线性图标；导航和物品栏使用 `Package`，钻石使用 `Diamond`）
- `@fontsource/nunito` 自托管 600/700/800/900 字重
- CSS 自定义属性 + CSS Modules
- Vitest + Testing Library + Playwright

## 目录

```text
frontend/
  public/             # PWA manifest、sw.js、icons
  src/
    api/              # fetch/blob 封装、Bearer 注入、API 类型、TanStack Query hook
    components/       # AppShell、PlayerHeader、宿敌卡/候选、物品栏、榜单、TierProgress 等
    lib/              # API → 页面视图映射、宿敌/物品栏格式、段位、音效
    pages/            # 首页 / 小组 / 宿敌深链 / 物品栏 / 我的 / 登录 / 历史
    store/            # Zustand UI 状态；复用旧 token
    styles/           # token + 全局基础样式
    test/             # Vitest setup 与 fixtures
  e2e/                # Playwright 真数据双端走查和截图
```

## 启动、测试与构建

```bash
cd frontend
npm ci

# 开发服务器固定 127.0.0.1:4174
# GHOST_LEAGUE_API_PROXY 只用于本地 /v1、/avatars 代理，不写进部署
GHOST_LEAGUE_API_PROXY=http://127.0.0.1:8095 npm run dev

npm run typecheck     # 严格模式 tsc --noEmit
npm test -- --run     # Vitest + Testing Library
npm run build         # tsc --noEmit && vite build，产物写入 ../web-next/
npm run test:e2e      # Playwright（需要真实 token 与 running API）
```

## 路由与导航

- `/` 首页：段位身份行、今日进度、宿敌 + 赌注主入口
- `/league` 小组 / 好友榜切换
- `/rival` 宿敌选择与对抗的深链页（导航不再单列）
- `/inventory` 物品栏：星星 / 边框 / 称号 / 其他
- `/shop`、`/embers` 旧地址重定向到 `/inventory`
- `/history` 历史时间线：打卡 / 下注 / 宿敌 / 星星 / 周结算，按时间倒序并可筛选
- `/me` 我的

底部/侧边导航固定 5 个入口：首页、小组、物品栏、历史、我的。导航是纯图标 +
`aria-label` + Radix Tooltip。顶栏只剩品牌、钻石余额（链接到 `/inventory`）和头像；
设置、音量、刷新按钮都不在顶栏。

## 真实数据

- 复用旧页面同一个 `localStorage["gl.token.v1"]`，以 `Authorization: Bearer <token>`
  访问 API。登录页只校验并保存这个既有 token。
- 首页快照：
  - `GET /v1/me/profile`
  - `GET /v1/me/status`（含 `last_activity_at`，用于“刚刚更新”）
  - `GET /v1/league/standings`
- 首页宿敌：
  - `GET /v1/me/rival`、`GET /v1/me/rival/candidates`
  - `POST /v1/me/rival/select`
  - `GET /v1/me/bets`、`POST /v1/me/bets`（周注/日注 dialog 与 `/rival` 共用）
  - 周注/日注请求体只发送 `kind`、`target_margin`、`paid_stake`、`request_id`；
    `stake`（`free_stake + paid_stake`）和赔率都由服务端返回，前端只读
    `bet_options` 的 `target_options` 档位与赔率。
  - 首页显示双方本周 XP/今日增量、对撞条、差距和**周注/日注**状态与下注入口；
    未选宿敌时直接给内联选择入口。`/rival` 保留为深链，复用同一套
    `RivalDuelCard` / `RivalCandidatePicker` 组件。
- 小组/好友榜：
  - 小组：`GET /v1/league/standings`
  - 好友：`GET /v1/me/friends/standings`，前端过滤掉自己，只显示已关注的人；
    没有关注时显示空状态，不伪造行。
  - 组注：`GET /v1/me/bets` 的 `bet_options.group` 与本周 `bets.group`；只在
    「小组」tab 显示 `GroupBetCard`，文案是“押我本人在本组本周排名前三”。没有小组或
    `bet_options.group` 为 `null` 时不显示，不伪造。组注 dialog 只输入自付钻石，
    请求体发送 `{kind: "group", paid_stake, request_id}`。
- 动态与他人资料：
  - `GET /v1/league/feed?limit=20`：只读 feed，渲染作者、正文、时间、reactions 和 tags；
    不提供自由发帖。
  - 点击作者头像/名字/卡片读取 `GET /v1/users/{user_id}`，底部显示公开资料卡；不显示
    他人钻石、下注或私有数据。
  - 「关注 / 已关注」调用 `POST/DELETE /v1/me/follows/{user_id}`；成功后刷新 feed、
    资料卡和好友榜，失败显示真实错误。
- 历史：
  - `GET /v1/me/history?limit=100`，前端按 全部 / 打卡 / 下注 / 宿敌 / 星星 / 周结算
    单选筛选；卡片显示相对时间 + Asia/Shanghai 绝对时间；空态明确写“还没有历史记录”。
  - 页面复用 `PullToRefresh`，并覆盖加载、错误和重试状态。
- 物品栏：
  - 星星：`GET /v1/shop`、`POST /v1/shop/purchase`、
    `GET /v1/me/stars/{star_id}/svg`
  - 边框/称号/其他：`GET /v1/me/collection`
  - 补给：`GET /v1/shop` + 同一个购买接口
- 我的：复用首页快照；物品栏入口、历史入口、设置面板（音量、外观、账号）。
- 不发明后端字段，不在前端生成假星星、假钻石或假概率。加载、空态、错误态都有明确 UI；
  失败只显示真实错误文案，并提供重试。

## 页面行为

- **首页**：删除了小组排行榜和小组号展示；今日进度不再显示“第 N 档 X 分钟”。更新标记
  按 `status.last_activity_at` 计算，超过 1 小时不显示“刚刚更新”。顶部没有刷新按钮，
  页面容器支持 touch 下拉刷新（调用真实 refetch）。未选宿敌时显示内联候选；选好后首页
  直接显示双方对撞条、本周 XP/今日增量、差距和**周注/日注**状态。
- **周注/日注 dialog**：目标差值只从服务端 `bet_options[tab].target_options` 渲染，
  显示 `+margin XP` 与该档赔率；自付钻石用数字输入 + `0–500` 滑杆，总本金为
  `free_stake + paid_stake`，总返为 `round(stake × 服务端赔率)`。自付 0 合法，默认只
  使用免费 20；周注截止周一 `23:59:59`，日注 `21:00` 锁注、`22:30` 结算。
- **小组/好友榜**：顶部只有结算倒计时，不显示小组人数。`小组 / 好友 / 动态` 分段切换。
  好友榜按关注关系读真实数据，排除自己，按 XP 排名，没有关注时给空状态。小组榜下方的
  `GroupBetCard` 显示个人前三组注（目标名次、赔率、免费 20、押注 0–500 和已下注状态），
  好友/动态 tab 不显示组注。
- **动态与他人资料**：动态只来自真实服务端事件；点击卡片打开 `UserProfileSheet`，
  显示段位、本周 XP、组内排名、连胜、关注/粉丝数。关注或取消关注后立即刷新 feed、
  资料卡和好友榜；没有动态或关注时给真实空态。
- **历史**：`历史` tab 打开真实时间线；筛选 chips 单选，`group_bet` 归入「下注」；
  计数随筛选更新；时间同时显示相对时间和绝对日期；无记录时不伪造示例。
- **物品栏**：页面标题和导航都叫“物品栏”。分类为星星 / 边框 / 称号 / 其他；
  星星分类下保留抽卡、概率、稀有度和独属 SVG，其他分类来自 `collection` 和真实库存。
  每类都有加载、错误和空状态。
- **我的**：顶部显示钻石和连胜；横向 10 段段位进度条高亮当前阶段；本周 XP、今日 XP、
  本周排名、当前/最长连胜；物品栏、历史、设置入口。设置和音量从顶栏移到这里，
  音量在现有 `SettingsDialog` 内；页面支持下拉刷新。
- **宿敌深链 `/rival`**：三态（选候选 / 已有宿敌 / 锁定空态）与周注/日注 dialog；
  组注不再出现在宿敌卡或宿敌 dialog，只在 `/league` 的小组 tab。

## PWA shell

- `frontend/public/manifest.webmanifest`：名称“炉火联赛”、短名“联赛”、`start_url` /
  `scope` 为 `/`、`display: standalone`、`background_color` / `theme_color` 为 `#131F24`。
- `frontend/public/sw.js`：版本 `gl-next-v1-2026-11-02`；安装时缓存 `/`、
  `/manifest.webmanifest`、192/512 图标，不预缓存 API；导航 network-first 并回退缓存
  `/index.html`，静态资源 cache-first，`/v1/` 与 `/avatars/` 一律 network-only。
- `src/main.tsx` 在 `load` 后注册 `/sw.js` 并调用 `registration.update()`。

## 生产挂载与切流

`ghost_league/pwa.py` 保留 `WEB_ROOT = web/`，使用 `ACTIVE_WEB_ROOT` 读取
`GHOST_LEAGUE_WEB_ROOT`；未设置时仍服务旧 `web/`。生产切流由 systemd 设置该环境变量，
不在本前端任务内执行：

```bash
Environment=GHOST_LEAGUE_WEB_ROOT=/opt/ghost-league/web-next
```

回滚只需移除该环境变量或指回 `web/`。

## 测试

```bash
cd /opt/ghost-league/frontend
npm run typecheck
npm test -- --run
npm run build

cd /opt/ghost-league
PYTHONPATH=. pytest -q tests/test_api.py
PYTHONPATH=. pytest -q tests/test_pwa.py tests/test_pwa_design.py tests/test_pwa_next.py
```

前端单测覆盖：首页有/无宿敌、周注/日注状态、真实更新时间、下拉刷新、周注/日注目标档位、
自付 0/500 与总返、组注卡片（仅小组 tab）、组注 `paid_stake` payload、小组/好友切换和空态、
动态 tab、作者资料、关注后好友榜更新、历史六类筛选/计数/空态/错误重试、相对与绝对时间、
物品栏四类、空态与购买、我的横向段位、钻石/连胜、设置入口、导航和顶栏收敛。
`e2e/home.spec.ts` 用真实 token 在 390×844 与 1440×1000 走一遍首页、周/日注 dialog、无宿敌、
下拉刷新、小组组注与好友榜、无组注空态、物品栏分类、我的与设置，并把截图写到
`artifacts/ghost-ui-group1/`。历史与动态/关注走查截图在 `artifacts/ghost-history-feed/`。

## 部署边界

- 只在本仓库本地构建、测试、提交；不 push、不部署、不重启线上服务、不写 live DB。
- 不修改 `web/`、systemd unit 和旧 PWA 测试的预期。
- `web-next/` 是构建产物，仍由 `.gitignore` 忽略。
