# Ghost League

Ghost League 是一个自托管的每周活动联赛：外部活动经 Channel 归一化成匿名小时增量，
Ghost 负责计分、分组、打卡、余烬补签、周结算和 PWA 展示。游戏状态在 SQLite，不依赖
任何前端静态模拟数据。

- **Source**：WakaTime、Duolingo、Krita 等外部活动来源，不属于本仓库。
- **Channel**：每个来源的适配层，负责拉取、归一化、按小时投影、维护 cursor 和重试。
- **Ghost**：通用联赛引擎，只接收匿名 `player_ref`、展示 profile 和增量。

```text
Source (WakaTime / Duolingo / Krita / ...)
        │  Channel 拉取、归一化、按小时投影
        ▼
Channel (waka-channel / duolingo-channel / krita-channel / ...)
        │  roster + {event_id, seconds, occurred_at}
        ▼
Ghost (SQLite + FastAPI + PWA)
```

Ghost 不 import Channel，不调用 Source，也不在业务逻辑里判断 provider。Ghost 没有
player identity class：所有 Channel player 都按普通参赛者创建/刷新；Waka 是 Channel，
Ghost 只保存 `source_kind` / `source_key_hash` 作为 provenance。公开 API 和 PWA 不返回
`is_ai` / player `kind`。

Waka 的 XP 传输走 account-backed 路径：

```text
Waka cache / projection  ->  ai_channel (Channel)
ai_channel uses the existing ordinary account tokens
  -> POST /v1/me/increments (same public API as any player)
Ghost: fixed rules, no provider imports, no Waka scheduler jobs
```

前端看到的 event id、秒数和每日 XP 口径不变；只有传输从 Channel ingest 换成普通
账号 API。历史 `channel_events` 保留，详见
[`docs/CHANNEL_BOUNDARY.md`](docs/CHANNEL_BOUNDARY.md)。

## 快速开始

要求 Python 3.11+。

```bash
git clone <your-repo-url> ghost-league
cd ghost-league
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'

# 1. 初始化账号。明文 token 只打印一次，请保存到本地安全位置。
export GHOST_LEAGUE_OWNER_ID=owner
python -m ghost_league.accounts add --user-id owner --name Owner

# 2. 启动 API（默认只监听 127.0.0.1:8095）
export GHOST_LEAGUE_TOKEN="<上一步打印的 token>"
./scripts/run_api.sh
```

本地开发时也可以让 PWA 与 API 同进程启动：

```bash
python3 -m uvicorn ghost_league.pwa:app --host 127.0.0.1 --port 8096
```

生产环境的 PWA 入口建议由 HTTPS 反向代理提供；`scripts/run_pwa.sh` 会读取
`GHOST_LEAGUE_TLS_CERT` / `GHOST_LEAGUE_TLS_KEY`（默认 `deploy/tls/`，已 gitignore）。

### Waka 数据与 ai_channel

Waka 是 source/projection 库，只由 `ai_channel` 的 Waka 模式使用。`waka_channel/`
只读本地榜单快照 `data/cache/cn-978.json`，复用 `ghost_league/schedule.py` 的纯投影
函数，产出与原来相同的 `event_id` / `seconds`。XP 传输由独立 `ai_channel/` 完成：
它把每个 `player_ref` 映射到 `ch-` + sha256(`ghost-channel-player-v1\0waka\0` +
`player_ref`) 的已有普通账号，再用 `ai_accounts.db` 里的 token 调用
`POST /v1/me/increments`。Ghost 不注册 Waka/source 调度任务，也不 import Channel
或 provider 客户端。

Waka cutover 已于 2026-11-05 ~15:41 CST 在 live 执行，切流前备份在
`/data/backups/ghost-league/pre-waka-cutover-20261105T154101`。生产传输是 systemd
timer，不是 Ghost 后台任务：

- `ai-channel-waka.timer` 每小时 `:01` 触发 oneshot `ai-channel-waka.service`，运行
  `ai_channel tick --source waka`，读取缓存并逐个调用 `/v1/me/increments`。
- `ai-channel-fetch.timer` 每周一 `00:02` 刷新 `data/cache/cn-978.json`。
- `ai-channel-waka.service` 是由 timer 触发的 oneshot unit，不是常驻进程。
- `ai-channel.service` 仍是 `serve --prefix sim-` 的 idle 通用常驻循环，不承载 Waka。

手动/排查时仍可执行：

```bash
export PYTHONPATH=/opt/ghost-league:/opt/ghost-league/ai_channel

# 可选：刷新公开榜缓存（只写 data/cache/，不写游戏库）
python3 scripts/source_fetch.py --out data/cache/cn-978.json --country CN

# 只推送已经结束的整点；event_id 沿用 Waka 投影，cursor 幂等
python3 -m ai_channel tick --config ai_channel/config.json --source waka \
  --cache data/cache/cn-978.json \
  --state data/cache/waka-channel-state.json
```

`ai_channel serve --source waka` 仍可手动运行，但不是 live 传输。缺 token 的
`player_ref` 只记录并跳过，不创建玩家或账号。传输不走 `/v1/channels/...`；历史
`channel_events` 行保留，新事件写入 `activity_events`，前端和每日 XP resolver 仍取
两者较大值，所以现有前端 XP 不变。

### 进程内调度器

Ghost 自带调度器，随 FastAPI lifespan 启动/停止，不依赖外部 timer、cron 或
ifrule，也不需要额外的 worker 服务。启动时先做一次 catch-up，之后每 20 秒检查到期
任务；`job_runs` 表用 `(name, period_key)` 唯一键和租约保证多进程下同一周期只执行
一次，失败/崩溃的周期会在后续 tick 重试，成功的周期幂等跳过。

Ghost 调度器只注册通用游戏任务：

- `power`：每小时第 5 分钟刷新当前战力。
- `diamond-decay`：每小时第 10 分钟执行钻石软上限衰减。
- `weekly settle`：周一 00:05 结算上一周；本周内未完成可补跑。
- `rival-auto`：周二 00:00 为没有宿敌的真人自动匹配；本周内可补跑。
- `daily-bets`：每天 10:30 结算日注；09:00 锁注，之后不能再下。

Waka 缓存刷新和 XP 传输由 `ai-channel-fetch.timer` / `ai-channel-waka.timer`
负责，不在 Ghost 调度器里；Waka roster 也不再由 Ghost 调度。历史 `job_runs` 中的
旧任务行保留作审计，不删除。

结算只处理上一个本地周，不预建下一周；提前或重复运行会安全跳过。

## 关键规则

- **分组**：每组最多 15 人。先按 `ceil(N/15)` 定组数，再均分；不足 15 人时允许
  14/15 人混合小组，但不会创建 1 人组（至少 2 人）。本地真人优先进入满组；
  Channel player 在同一 tier 内按周哈希换位，跨周不会固定同一批对手。
- **升降级**：每个组独立结算，不按整个 tier 汇总。每组配额为
  `max(1, round_half_up(group_size * 0.2))`，组内前 N 升、后 N 降。
- **段位**：Bronze 不降段，Diamond 不升段；段位顺序为 Bronze → Silver → Gold →
  Sapphire → Ruby → Emerald → Amethyst → Pearl → Obsidian → Diamond。
- **打卡**：`Asia/Shanghai` 自然日累计 600 秒 = 100 XP 即打卡成功。
- **余烬补签**：已完成自然日 D 结束后 7 天内可补（D-1 到 D-7）；每次消耗 1 枚余烬，
  只恢复打卡/连胜与历史标记，不增加周 XP、不改变名次或升降级。
- **XP**：`XP = floor(seconds / 6)`；周榜按 XP 排名。
- **所有参赛者同规则**：计分、打卡、分组、升降级、称号和边框完全一致；Ghost 不保存
  player identity class，公开响应和前端不暴露 `kind` / `is_ai`。
- **Player identity 列移除**：schema 14 起 `players` 没有 `kind` / `controller`，
  `channel_players` 没有 `kind`；`group_members.is_human` 仅为旧 UI 保留并统一写 1。
  live 迁移已于 2026-11-05 14:53 CST 执行，迁移时 1076 名玩家、1074 条 Channel
  映射、1954 条 group member、XP、profile、source key 和小组关系均保留，
  `integrity_check=ok`，API/Web 重启后健康。迁移后 Waka 全量 roster sync 成功：
  972 行、0 新建、972 已有，Waka 排行榜未受影响。
- **live 迁移已执行（无需重跑）**：迁移前备份在
  `/data/backups/ghost-league/pre-player-kind-20261105T145317`；数据库旁另有
  `data/league/league.db.backup-player-identity-20261105T145319553868`。脚本仍可用于
  新实例或演练：
  `PYTHONPATH=. python3 scripts/migrate_player_identity.py --db data/league/league.db`；
  已迁移库上幂等，不新增备份。回滚时停服务、恢复备份（连同需要的 `-wal` / `-shm`
  状态）并回退代码。
- **live provisioning 与 Waka cutover**：live provisioning 路由已配置 token 并启用
  （token 只在服务 env 与 `ai_channel/config.json`，均 0600、untracked，不打印、
  不提交），本地 token DB 保留 1074 个 Waka `ch-` 普通账号。Waka cutover 已于
  2026-11-05 ~15:41 CST 执行，切流前备份在
  `/data/backups/ghost-league/pre-waka-cutover-20261105T154101`。生产传输由
  `ai-channel-waka.timer` 每小时 `:01` 触发 oneshot `ai-channel-waka.service`；
  `ai-channel-fetch.timer` 每周一 `00:02` 刷新缓存。`ai-channel.service` 仍是
  `serve --prefix sim-` 的 idle 通用常驻循环（当前 0 个 `sim-` 账号，日志
  accounts=0，不发起 HTTP 请求），不是 Waka tick，也不加载 `ch-` token。
  `ai-channel-waka.service` 是 oneshot，不是常驻进程。
- **Waka 作业退出 Ghost 调度器**：`waka-tick`、`waka-roster`、`source-fetch` 不再注册；
  历史 `job_runs` 行保留。Waka XP 切到 `ai_channel` 后写入 `activity_events`，
  历史 `channel_events` 行保留，前端不变，每日 XP resolver 仍取两者较大值。
- 完整行为策略（bets/tasks/rival/chests）仍待后续。

## API 与 PWA

- [`docs/API.md`](docs/API.md)：认证、账号、资料、头像、增量、Channel ingest、联赛、
  feed、收藏、打卡、补签、社交和错误码。
- [`docs/CHANNEL_BOUNDARY.md`](docs/CHANNEL_BOUNDARY.md)：Source → Channel → Ghost
  契约、身份规则和分组规则。
- [`docs/GAME_ECONOMY.md`](docs/GAME_ECONOMY.md)：XP、钻石、星星的经济分工，游戏化边界，以及平衡调整口径。
- [`docs/DAILY_TASKS.md`](docs/DAILY_TASKS.md)：每日手动、补断联、周末与周连续任务，以及宝箱和 API 契约。
- [`docs/WEBHOOKS.md`](docs/WEBHOOKS.md)：webhook 事件、签名、重试和 CLI。
- [`docs/CHANNEL_ACCOUNTS.md`](docs/CHANNEL_ACCOUNTS.md)：Channel 账号模拟、provisioning API、
  `ai_channel` 的 Waka 传输、普通玩家模型与 player identity 迁移。
- PWA：`web/` 是旧的移动优先静态应用，`ghost_league/pwa.py` 先注册 API 路由，再挂载
  静态根；`/v1/...`、`/avatars/...` 始终走 API。当前生产通过
  `GHOST_LEAGUE_WEB_ROOT=/opt/ghost-league/web-next` 挂载新构建，SPA 深链回退到
  `index.html`；未设置时回退旧 `web/`，旧目录保留回滚。
- 星图前端：`frontend/` 是 React/TypeScript 新栈，构建到 `web-next/`，不覆盖 `web/`；
  包含首页、小组榜、宿敌、星图、历史占位、个人页和 PWA shell。启动、测试、切流和截图见
  [`frontend/README.md`](frontend/README.md)。
- [`docs/AVATAR_FRAME_SPEC.md`](docs/AVATAR_FRAME_SPEC.md)：头像框的 `1.36D` 画布、
  `1.00D` 开孔和 `1.08×` 辉光规范，PWA 与 SVG 状态卡共用同一组数字。
- 状态卡片：`GET /badge/{user_id}.svg` 返回公开 SVG，包含段位、称号和已装备边框；
  `GET /embed/{user_id}` 返回 60 秒自动刷新的 iframe。

示例 host 统一使用 `https://your-host.example`：

```md
![联赛状态](https://your-host.example/badge/owner.svg)
```

```html
<img src="https://your-host.example/badge/owner.svg" alt="联赛状态">
<iframe src="https://your-host.example/embed/owner" width="880" height="260" style="border:0;max-width:100%" title="联赛状态"></iframe>
```

## Widget Studio

`web/widget-studio/` 是挂在现有 PWA 上的图片模版编辑器，地址为
`https://your-host.example/widget-studio/`。它复用 Ghost 现有 Bearer 认证和 TLS 入口，
不新增服务或端口。编辑器从 `localStorage["gl.token.v1"]` 读取 token；没有 token 时只显示
“先登录 Ghost”和输入框。

- 模版数据：`data/widgets/<id>/template.json`、`flame.png`、`backgrounds/*.png`；目录文件
  是唯一真相源，保存后生产图立即生效，不需要重启。
- 模版是 version 4：样式按底图存（`backgrounds[].styles`），没有全局 `styles`。火焰+数字
  是一个组件，支持整体缩放与间隔；文字支持字号、字重、字间距、描边与颜色。多个文字变体
  共用当前底图的 `styles.label`，位置各自独立；切换底图切换整套样式。
- Ghost 现有 `web/assets/tiers/card/*.png` 和 `web/assets/frames/*.png` 通过
  `ghost:assets/...` 原地引用，不复制。
- API：`/v1/widget-studio`（模版列表/详情与写接口要求现有 Bearer；图片、缩略图和资源库只读公开）。
- 生产图固定路径：`GET /v1/widgets/<user_id>/<template_id>.png`，不需要 Bearer，也不带数据
  query；数据由服务端按 `user_id` 从 Ghost 当前状态读取。用户/模版不存在、路径或 JSON
  非法返回 404。1x 用单独路径 `<template_id>-1x.png`（368×219）。响应头返回
  `X-Widget-Background` / `X-Widget-Text` / `X-Widget-Completed`，并在该底图的文字变体
  中随机选一条。今日未完成时火焰转灰度、数字用纯灰 `#9a9a9a`，文字保持白色。
- 编辑器顶部“我的小组件”显示当前登录 `user_id` + 当前 `template_id` 的固定 URL，可复制；
  换外层模版改变 URL 中的 `template_id`，换底图/文字/条件 URL 不变。生产预览直接请求
  固定 URL，提示显示已保存版本。预览“今日已完成 是/否”只切换画布的火焰/数字颜色。
- 显式保存：拖动、输入文字、改条件、改 x/y 都不写文件；只有 `Ctrl/Cmd+S` 或“保存”按钮
  PUT 完整 snapshot。上传底图/火焰只写文件并返回 `src`，编辑器标“未保存”，保存后才改 JSON。
- 主画布即时绘制，`pointermove` 不发请求；右侧只调文字内容与位置，不提供样式输入。
- 详细 schema、条件规则、v2→v3 迁移、API 表、生产 URL 和测试命令见
  [`docs/WIDGET_STUDIO.md`](docs/WIDGET_STUDIO.md)。

## Thermal printing

`print-service/` 是独立的 FastAPI + SQLite 打印队列（租约、重试、去重、补打、
打印机心跳），只接收已经渲染好的 ESC/POS 字节；`print-daemon/` 是仅用标准库的
PC 端守护进程，轮询服务、认领任务并通过 TCP 9100 直接打印。服务端不连接打印机，
打印机不需要暴露到公网。

- 服务端入口：`print_service.app:create_app`；生产使用独立 token 和独立数据库。
- 客户端：`python -m print_daemon --config config.json`，支持 `--once` 和
  `--print-test`，Windows 可用 Task Scheduler 或 NSSM。
- 完整架构、鉴权边界、状态机、API 和部署说明见
  [`docs/PRINT_QUEUE.md`](docs/PRINT_QUEUE.md)。

## 数据与隐私

仓库只包含代码、文档和通用示例，**不提交**：

- `data/` 下的 live 数据、账号库、SQLite、头像、webhook、cache；
- `data.backup-*`、`data/archive/`、`artifacts/`、`*.bundle`；
- 本地 TLS 证书/私钥、token、真实账号资料或个人部署路径。

`.gitignore` 已排除这些路径；`.git/info/exclude` 可再放本地专用文件。发布前用
CI 或本地的隐私扫描规则检查 tracked 文件，确保没有真实主机、内网 IP、个人 ID、
token 或部署路径；扫描规则本身不要写进被扫描的文档。

生产部署用 `GHOST_LEAGUE_OWNER_ID` 覆盖默认 owner `owner`，并通过环境变量或未跟踪的
`EnvironmentFile` 提供 token；不要把真实 host、内网 IP、个人 ID 或凭据写进仓库。

## 项目结构

```text
ghost_league/
  api.py              # FastAPI 路由与 GameService
  accounts.py         # 本地账号、token 哈希、资料/头像 CLI
  badge.py            # SVG 状态卡与 embed 页面
  pwa.py              # 挂载 web/ PWA
  widget_studio/      # Widget 模版 schema、文件 store、Pillow 渲染、API 路由
  webhooks.py         # webhook 订阅、签名与投递
  schedule.py         # 周/小时投影纯函数（Channel 复用）
  themes.py           # 图标主题
  channels/           # Channel ingest 契约
  game/               # 规则、分组、打卡、结算、SQLite store、进程内调度器
  source/             # 旧的归一化工具，仅供 Channel/fetch 兼容
  fetch.py            # 公开榜抓取（只写 cache）
  runtime_jobs.py     # 进程内调度器任务注册（仅通用游戏任务）
waka_channel/         # Waka 缓存/归一化/小时投影库（由 ai_channel Waka 模式使用）
print-service/        # 独立 FastAPI + SQLite 打印队列（ESC/POS 原始字节）
print-daemon/         # PC 端纯标准库打印守护进程
web/                  # 旧 PWA 静态资源（生产默认入口，保留回滚；含 web/widget-studio/）
frontend/             # 星图前端 React/TypeScript 源码
web-next/             # frontend 构建产物（gitignore；切流时由 pwa.py 挂载）
data/widgets/         # Widget Studio 运行时模版目录（gitignore，仅 .gitkeep 入库）
scripts/              # API/PWA 启动与抓取脚本
deploy/               # 部署模板（API/PWA service）
docs/                 # API、Channel、Webhook 文档
tests/                # pytest 测试
```

`docs/GAME_LOOP_DESIGN.md` 是早期设计稿，仅作历史参考；当前契约以 `docs/API.md` 和
`docs/CHANNEL_BOUNDARY.md` 为准。

## 测试与检查

```bash
PYTHONPATH=. pytest -q
ruff check ghost_league tests
python3 -m compileall -q ghost_league
node --check web/app.js && node --check web/sw.js
```

测试不依赖网络，使用临时 SQLite 和 fake Channel。API/PWA 测试覆盖鉴权、账号隔离、
Channel roster/increments、分组、打卡、补签、称号/边框、feed、webhook 和静态资源。

## License

MIT。见 [`LICENSE`](LICENSE)。
