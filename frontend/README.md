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
- `/inventory` 物品 / 商店：物品分类为星星 / 边框 / 称号 / 其他，商店按商品类别展示
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
  - 首页与 `/rival` 共用 `variant="full"` 的 `RivalDuelCard`：显示双方本周 XP、今日 XP
    比分、对撞条、差距、本周剩余/日注锁注两个时间，以及周注/日注两个独立注面。
    未下注且未截止时分别显示「下注周注 / 下注日注」，已下注时显示该注面的目标、赔率、
    总本金和总返，截止后只显示截止状态。两个入口分别用 `onlyKind="weekly"` /
    `onlyKind="daily"` 直接打开对应 dialog，不再先展示另一个 tab；复用同一套
    `RivalDuelCard` / `RivalCandidatePicker` 组件。
- 小组/好友榜：
  - 小组：`GET /v1/league/standings`
  - 好友：`GET /v1/me/friends/standings`，保留本人和已关注的人，按 XP 排序；
    本人带“我的位置”标记。没有关注时只显示本人，接口返回空列表时显示空状态，
    不伪造行。
  - 组注：`GET /v1/me/bets` 的 `bets.groups`（或 `groups` / `bet_options.group.markets`）
    按服务端返回的可用盘口渲染 `top3` / `promote` / `no_demote` 三个独立卡片；Bronze
    不出现“押不降段”，Diamond 不出现“押升段”。只在「小组」tab 显示；没有小组或没有
    可用盘口时不显示，不伪造。每张卡独立下注，请求体发送
    `{kind: "group", market, paid_stake, request_id}`。
- 动态与他人资料：
  - `GET /v1/league/feed?limit=20`：只读 feed，渲染作者、正文、时间、reactions 和 tags；
    不提供自由发帖。
  - 点击动态、榜单或宿敌对比卡的头像读取 `GET /v1/users/{user_id}`，打开全屏公开资料页；
    页面展示大头像、段位、`@handle`（没有 handle 时不显示这一行）、关注按钮、本周 XP / 战力 /
    关注 / 粉丝、最近 7 天每日 XP 双折线（他 / 你）和概览四格；装备/称号只在后端返回
    真实数据时显示。不显示他人钻石、下注或私有数据。
  - `recent_xp` 由后端返回 7 天日期、中文星期标签、双方每日 XP 与 7 天总和；前端不补造
    数据，没有记录时按 0 绘制。
  - 「关注 / 已关注」调用 `POST/DELETE /v1/me/follows/{user_id}`；成功后刷新 feed、
    资料页和好友榜，失败显示真实错误。
- 历史：
  - `GET /v1/me/history?limit=100`，前端按 全部 / 打卡 / 下注 / 宿敌 / 星星 / 周结算
    单选筛选；卡片显示相对时间 + Asia/Shanghai 绝对时间；空态明确写“还没有历史记录”。
  - 页面复用 `PullToRefresh`，并覆盖加载、错误和重试状态。
- 物品 / 商店：
  - 商店：`GET /v1/shop` 按商品类别分组展示星星 / 余烬 / 仓库上限 / 其他商品，
    购买统一走 `POST /v1/shop/purchase`
  - 物品：星星列表来自 `status.stars`（含 `GET /v1/me/stars/{star_id}/svg`），
    边框/称号/其他来自 `GET /v1/me/collection`
  - 装备/换装/卸下：`PATCH /v1/me/loadout`，边框传 `frame_id`、称号传 `title_id`、
    其他物品按 `slot` 传 `backdrop_id` / `badge_accent_id`；已装备物品传对应字段 `null`
    卸下。成功后刷新首页快照和 collection，并显示 toast。
- 我的：复用首页快照；物品栏入口、历史入口、设置面板（音量、外观、账号）。
- 不发明后端字段，不在前端生成假星星、假钻石或假概率。加载、空态、错误态都有明确 UI；
  失败只显示真实错误文案，并提供重试。

## 页面行为

- **首页**：删除了小组排行榜和小组号展示；今日进度不再显示“第 N 档 X 分钟”。更新标记
  按 `status.last_activity_at` 计算，超过 1 小时不显示“刚刚更新”。顶部没有刷新按钮，
  页面容器支持 touch 下拉刷新（调用真实 refetch）。未选宿敌时显示内联候选；选好后首页
  显示完整宿敌卡：双方本周/今日 XP、对撞条、差距、本周剩余/日注锁注两个时间，以及
  周注/日注两个独立注面，两个下注按钮分别打开对应 dialog。
- **任务拍照**：手动任务选图后先在浏览器里把可解码图片压到 ≤1MB（`lib/image.ts`），
  压缩期间按钮显示“处理中…”，随后上传并显示“上传中…”。HEIC 等浏览器解不了的文件
  原样上传，由服务端转换并兜底压到 ≤1MB。
- **任务宝箱**：完成后的“开宝箱”只打开 `ChestOpenDialog`，弹层内点“开启”才调用
  `POST /v1/me/tasks/{id}/chest`。请求期间按钮禁用、宝箱抖动；成功后箱盖打开、
  光晕扩散、奖励卡显示服务端返回的真实奖励（钻石 / 经验宝 / 星星），失败显示
  `describeApiError` 并保留弹层重试。`prefers-reduced-motion` 下跳过抖动和光晕，
  直接淡入结果；不播放音效。
- **周注/日注 dialog**：目标差值只从服务端 `bet_options[tab].target_options` 渲染，
  显示 `+margin XP` 与该档赔率；自付钻石用数字输入 + `0–500` 滑杆，总本金为
  `free_stake + paid_stake`，总返为 `round(stake × 服务端赔率)`。自付 0 合法，默认只
  使用免费 20；周注截止周一 `23:59:59`，日注 `21:00` 锁注、`22:30` 结算。
- **小组/好友榜**：顶部只有结算倒计时，不显示小组人数。`小组 / 好友 / 动态` 分段切换。
  好友榜按关注关系读真实数据，包含本人并标“我的位置”，按 XP 排名并显示后端返回的
  战力；没有关注时仍显示本人，接口返回空列表时才给空状态。小组榜使用后端
  `promotion_quota` / `demotion_quota` 和每行 `promoted` / `demoted`，只给前 N 行标“晋升”、
  后 N 行标“下降”，按实际组人数计算；好友榜、动态和资料卡不显示这些标识。小组榜下方
  `GroupBetCard` 并排显示服务端允许的“押前三 / 押升段 / 押不降段”，各自赔率、已下注状态和
  下注按钮，互不合并；好友/动态 tab 不显示组注。
- **动态与他人资料**：动态只来自真实服务端事件；点击动态、榜单或宿敌对比卡的头像打开
  全屏 `UserProfileSheet`，顶部是返回箭头和名字，中间是大头像、段位小徽章与 handle，
  下方是亮蓝色关注按钮、统计行、最近 7 天每日 XP 双折线和概览四格；装备/称号只在
  后端返回真实数据时显示。有 `handle` 时显示 `@handle`，没有时不显示 handle 行，
  不显示随机 `ch-...` 标识，也不用身份词兜底。
  关注或取消关注后立即刷新 feed、资料页和好友榜；没有动态或关注时给真实空态。
- **历史**：`历史` tab 打开真实时间线；筛选 chips 单选，`group_bet` 归入「下注」；
  计数随筛选更新；时间同时显示相对时间和绝对日期；无记录时不伪造示例。
- **物品 / 商店**：页面标题叫“物品”，商店是独立区域。物品分类为星星 / 边框 / 称号 /
  其他；星星只是其中一类，保留抽卡、概率、稀有度和独属 SVG。商店按星星 / 余烬 /
  仓库上限 / 其他商品分组渲染 `shop.data`，不把抽星星当成整个商店。边框、称号和其他
  有装备槽的物品显示“装备”；`collection.equipped` 为真时显示“已装备”和“卸下”。
  没有对应槽位的物品只展示、不显示装备按钮；同槽位换装直接覆盖字段。每类都有加载、
  错误和空状态。
- **我的**：顶部显示钻石和连胜；横向 10 段段位进度条高亮当前阶段，已完成的段位正常显示，
  紧邻的下一段位作为预览保留，再往后的未到达段位用迷雾/问号遮住名称；到达最高段位时不再
  有迷雾。本周 XP、今日 XP、本周排名、当前/最长连胜；物品栏、历史、设置入口。设置和音量
  从顶栏移到这里，音量在现有 `SettingsDialog` 内；页面支持下拉刷新。
- **宿敌深链 `/rival`**：三态（选候选 / 已有宿敌 / 锁定空态）；完整卡显示今日 XP 比分和
  周注/日注两个注面，每个注面各自打开对应注种的 dialog（`onlyKind`），不再需要先切换 tab。
  组注不出现在宿敌卡或宿敌 dialog，只在 `/league` 的小组 tab。

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

前端单测覆盖：首页有/无宿敌、首页完整宿敌卡（今日 XP、周注/日注注面与两个 dialog）、
宿敌页今日 XP 比分与周注/日注独立注面、真实更新时间、下拉刷新、周注/日注目标档位、
自付 0/500 与总返、
15 人小组前 4/后 4 晋升/下降标识、组注三盘口
独立显示与 `market` payload、小组/好友切换和空态、动态 tab、作者/榜单/对比卡头像资料、
全屏资料页与最近 7 天双折线（有数据 / 全 0 / 关注自己）、关注后好友榜更新、
历史盘口简称与六类筛选、物品四类、商店商品分类、边框/称号/
背景/徽章装备与卸下、同槽位换装、无槽位物品不显示装备按钮、我的段位迷雾、钻石/连胜、
设置入口、导航和顶栏收敛。
`e2e/home.spec.ts` 用真实 token 在 390×844 与 1440×1000 走一遍首页、周注/日注 dialog、无宿敌、
下拉刷新、小组组注与好友榜、无组注空态、物品分类与商店商品分类、我的与设置，并把截图写到
`artifacts/ghost-ui-group1/`。历史与动态/关注走查截图在 `artifacts/ghost-history-feed/`；
`e2e/inventory.spec.ts` 单独走物品/商店分类并把截图写到 `artifacts/ghost-inventory-shop/`。

## 部署边界

- 只在本仓库本地构建、测试、提交；不 push、不部署、不重启线上服务、不写 live DB。
- 不修改 `web/`、systemd unit 和旧 PWA 测试的预期。
- `web-next/` 是构建产物，仍由 `.gitignore` 忽略。
