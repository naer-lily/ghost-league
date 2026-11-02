# 星图前端 · React + TypeScript

`frontend/` 是当前维护的 React 18 + TypeScript + Vite 前端，包含首页、小组榜、
星图、历史占位页和个人页。构建产物输出到仓库根目录的 `web-next/`；旧 `web/` 不修改，
保留作生产回滚。生产切流只切换 `ghost_league/pwa.py` 的静态根，不新增端口。

## 技术栈

- React 18 + TypeScript + Vite 5
- React Router 6
- TanStack Query 5（服务端状态、30 秒轮询、401 不重试）
- Zustand 4（纯客户端 UI 状态）
- Radix UI primitives（Tooltip、Dialog 无障碍底座）
- Motion / framer-motion（页面切换、数字滚动、节点反馈）
- lucide-react（线性图标；顶栏钻石用 `Diamond`，星图入口用 `Sparkles`）
- `@fontsource/nunito` 自托管 600/700/800/900 字重；`--font` 第一项为 `Nunito`，中文回退
  `Noto Sans CJK SC` / `PingFang SC` / `Microsoft YaHei`，不依赖 Google Fonts CDN
- CSS 自定义属性 + CSS Modules；token、字体栈、3D 按钮和图标优先的深色界面语言移植自
  `prototype/src/styles.css`
- Vitest + Testing Library + Playwright

没有 Tailwind、MUI、Chakra、Element Plus，也没有引入后台 UI 套件。

## 目录

```text
frontend/
  public/
    manifest.webmanifest   # PWA manifest（构建时复制到 web-next/）
    sw.js                  # PWA shell service worker
    icons/                 # 从 web/icons/ 复制的 192/512/apple-touch 图标
  src/
    api/          # fetch/blob 封装、Bearer 注入、API 类型、TanStack Query hook
    components/   # AppShell、PlayerHeader、榜单、StarArt、StarDialog、RivalBetDialog、通用状态组件
    lib/          # API → 页面视图映射、星图/宿敌格式与错误文案、段位资源、音效
    pages/        # 首页 / 小组 / 宿敌 / 星图 / 个人页 / 登录 / 历史占位
    store/        # Zustand UI 状态；复用旧 token
    styles/       # token + 全局基础样式
    test/         # Vitest setup 与 fixtures
  e2e/            # Playwright 真数据截图和对比检查
```

## 启动、测试与构建

```bash
cd frontend
npm ci

# 开发服务器固定 127.0.0.1:4174
# GHOST_LEAGUE_API_PROXY 只用于本地 /v1、/avatars 代理，不写进部署
# 也可以在 frontend/.env.local 里设置（已 gitignore）；默认 http://127.0.0.1:8095
GHOST_LEAGUE_API_PROXY=http://127.0.0.1:8095 npm run dev

npm run typecheck     # 严格模式 tsc --noEmit
npm test -- --run     # Vitest + Testing Library
npm run build         # tsc --noEmit && vite build，产物写入 ../web-next/
npm run test:e2e      # Playwright（需要真实 token 与 running API）

宿敌页关键测试：`src/pages/RivalPage.test.tsx`、`src/lib/rival.test.ts`。
```

构建后 `web-next/` 必须包含 `index.html`、`assets/`、`manifest.webmanifest`、`sw.js`、
`icons/`。`web-next/` 仍在 `.gitignore` 中，不提交。

## 路由与导航

- `/` 首页
- `/league` 完整小组榜
- `/rival` 宿敌选择与对抗、下注 dialog
- `/shop` 星图
- `/history` 历史占位页（保留）
- `/me` 我的
- `/embers` 旧地址重定向到 `/shop`

底部/侧边导航固定 6 个入口：首页、小组、宿敌、星图、历史、我的。导航是纯图标 +
`aria-label` + Radix Tooltip。顶栏左侧是品牌，右侧是钻石余额（`Diamond` 图标 +
`status.diamonds`，`aria-label="钻石 N"`，链接到 `/shop`）、刷新、声音、设置和头像；
390px 下这些操作不被钻石数字挤出。`gems` 字段仍保留兼容，但不再作为主要货币显示。

## 真实数据

- 复用旧页面同一个 `localStorage["gl.token.v1"]`，以 `Authorization: Bearer <token>`
  访问 API。登录页只校验并保存这个既有 token。
- 首页快照读取：
  - `GET /v1/me/profile`
  - `GET /v1/me/status`
  - `GET /v1/league/standings`
- `/v1/me/status` 已使用字段：`diamonds`、`diamond_cap`、`diamond_cap_level`、
  `diamond_excess`、`inventory`（`star` / `seasonal_star` / `ember`）、`stars`、`power`、
  `power_percentile`、`power_updated_at`、`power_provisional`，以及原有 XP、排名、
  连胜、余烬和段位字段。
- 宿敌读取：
  - `GET /v1/me/rival`：本周宿敌、选择窗口、状态行、下注与预计达成线
  - `GET /v1/me/rival/candidates`：跨组候选；前端默认筛“略高于我”，没有时退回全部
  - `POST /v1/me/rival/select`，请求体 `{ rival_id, request_id }`；成功后直接进入对抗态
  - `GET /v1/me/bets`、`POST /v1/me/bets`：周注 / 日注 / 组注；成功返回 `{bet, state}`
  - mutation 成功后 invalidate `rival` / `bets` / `rival candidates`，状态行用真实返回刷新
- 星图读取：
  - `GET /v1/shop`
  - `POST /v1/shop/purchase`，请求体 `{ item_id, quantity: 1, request_id }`；本次前端不填
    `name`，由服务器生成
  - `GET /v1/me/stars/{star_id}/svg`，需要 Bearer；`StarArt` 用 `apiFetchBlob` 取 blob，
    生成 object URL 给 `<img>`，卸载时 `URL.revokeObjectURL`
- 不发明后端字段，不在前端生成假星星、假钻石或假概率。加载、空态、错误态都有明确 UI；
  抽取失败只显示后端错误文案，不显示假结果。

## 页面行为

- 首页保留扁平布局：单行 `PlayerHeader`、六档今日进度条、一张轻量宿敌入口、小组榜前
  5 行。榜单每行在名字下显示 `战力 N`（`null` 显示 `—`），不出现内部身份标签。
- `/league` 渲染完整小组榜，每行同样显示战力。
- `/rival` 三态：周一可选时显示候选（头像、名字、组号、战力、本周/今日 XP、选择按钮）；
  已有宿敌时显示双方 XP、单条左右对撞条、领先/落后、剩余时间与三行下注状态；锁定但
  没有宿敌时只显示空状态和重试，不伪造对局。下注按钮打开 `RivalBetDialog`，三个 tab
  分别接周注 / 日注 / 组注，已下注的 tab 不可重复提交，09:00 后日注显示“今天的注已截止”。
  不显示固定本周目标、免责声明或内部身份标签。
- `/me` 保留三列统计（本周 XP、排名、余烬）、紧凑 XP 环和“我的榜单位置”行；在三列统计
  下增加一行紧凑资源信息：钻石、星图星数、战力，整行链接到 `/shop`。
- `/shop` 从上到下：`PlayerHeader`、星图层头（余额、仓库上限、超出量）、抽取区、星库、
  补给。
  - 抽取条目来自 `GET /v1/shop` 的 `kind === "star"` / `"seasonal_star"`，显示名称、
    描述、价格、已拥有数量、可用状态、冷却、`rates` 和 `types`。概率条完全由 API 的
    `rates` 渲染；类型只显示数量（如“13 种星体”），不展示内部英文枚举。
  - 普通星按钮“抽取一颗”，钻石不足时禁用并显示还差多少。季节星显示 `season_key`
    （如“2026-11 限定”）；不可用且本月已拥有时显示“本月已获得”，否则“暂不可用”。
  - 点击抽取生成 `crypto.randomUUID()`（不支持时时间戳 + 随机串），只发一次
    `POST /v1/shop/purchase`，进行中按钮禁用。成功用返回的真实 `star` 打开结果对话框；
    结果不自动关闭，用户点“收下”。失败在抽取区显示后端错误。
  - 星库来自 `status.stars`，按 API 顺序显示全部。移动端 2 列、≥720px 3 列、
    ≥1100px 4 列。空态是虚线星形 + “还没有星，去抽一颗”，不显示假卡片或“0 颗”。
  - 卡片和结果/详情对话框均用真实 Bearer SVG。对话框复用
    `@radix-ui/react-dialog`，有 `aria-labelledby` / `aria-describedby`、44px 关闭按钮、
    Escape 关闭、遮罩滚动锁定；结果态 `data-testid="star-reveal"`，详情态
    `data-testid="star-detail"`。
  - 补给区显示余烬（价格、真实余额、冷却）和仓库升级（当前等级、下一级价格、当前上限）。
    冷却中按钮禁用并显示剩余时间；等级不匹配或钻石不足也禁用。没有真实货币充值入口。
- 设置里的声音是本地真实音效开关；外观调用 `PATCH /v1/me/profile` 的 `icon_theme`。
  本迭代没有实现打卡、补签、关注、分享等联赛写操作。

## PWA shell

- `frontend/public/manifest.webmanifest`：名称“炉火联赛”、短名“联赛”、`start_url` /
  `scope` 为 `/`、`display: standalone`、`background_color` / `theme_color` 为 `#131F24`，
  192/512 PNG 图标来自 `web/icons/`（已复制到 `frontend/public/icons/`）。
- `frontend/public/sw.js`：版本 `gl-next-v1-2026-11-02`；安装时缓存 `/`、
  `/manifest.webmanifest`、192/512 图标，不预缓存 API；导航 network-first 并回退缓存
  `/index.html`，静态资源 cache-first，`/v1/` 与 `/avatars/` 一律 network-only；
  `skipWaiting` + `clients.claim`；`activate` 清理旧 cache；不缓存 API/token 响应。
- `frontend/index.html` 增加 manifest、apple-touch-icon、apple-mobile-web-app 相关 meta；
  `src/main.tsx` 在 `load` 后注册 `/sw.js` 并调用 `registration.update()`。

## 生产挂载与切流

`ghost_league/pwa.py` 保留 `WEB_ROOT = web/`，新增 `ACTIVE_WEB_ROOT`：

```text
GHOST_LEAGUE_WEB_ROOT 未设置 -> ACTIVE_WEB_ROOT = WEB_ROOT（旧 web/）
GHOST_LEAGUE_WEB_ROOT 已设置 -> ACTIVE_WEB_ROOT = 该目录
```

`mount_web` 在 API 路由之后注册 SPA fallback：真实文件、目录 `index.html` 正常返回；
`/v1`、`/avatars`、`/assets`、`/icons` 缺失时保持 404；其余无扩展名的缺失路径返回
`index.html`（HTTP 200）。`/manifest.webmanifest` 与 `/sw.js` 保留原有响应头。

生产切流（不在本前端任务内执行）：

```bash
# systemd unit 里设置，不改代码
Environment=GHOST_LEAGUE_WEB_ROOT=/opt/ghost-league/web-next
# 然后重启 web/API 服务
```

回滚只需移除该环境变量或指回 `web/`；旧 `web/` 与旧 PWA 测试保持不动。

## 测试

```bash
cd /opt/ghost-league/frontend
npm run typecheck
npm test -- --run
npm run build

cd /opt/ghost-league
ruff check ghost_league scripts tests
python3 -m compileall -q ghost_league scripts
PYTHONPATH=. pytest -q tests/test_pwa.py tests/test_pwa_design.py tests/test_pwa_next.py
PYTHONPATH=. pytest -q --ignore=tests/test_source_normalize.py --ignore=tests/test_waka_channel.py
```

前端测试覆盖：API 映射、Bearer/blob、`StarArt` 的 blob 渲染与卸载 revoke、
`ShopPage` 的加载、两个抽取条目与真实概率、钻石不足、购买成功结果、购买失败、
空星库、季节星已拥有、星库详情与 Escape、补给区；`AppShell` 的钻石替代宝石、
`/shop` 导航和旧的 `/embers` 不出现在主导航；`MePage` 的钻石/星数/战力和原有三列统计。
`fixtures.ts` 补齐钻石、仓库、库存、星星、战力字段，避免测试靠 `undefined` 通过。

## 部署边界

- 只在本仓库本地构建、测试、提交；不 push、不部署、不重启线上服务、不写 live DB。
- 不修改 `web/`、systemd unit 和旧 PWA 测试的预期。
- `web-next/` 是构建产物，仍由 `.gitignore` 忽略，不强制加入 Git。
