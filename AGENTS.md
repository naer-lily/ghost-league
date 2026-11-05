# AGENTS.md

Ghost League 仓库的 agent 工作说明。架构边界以 `docs/CHANNEL_BOUNDARY.md` 为准，游戏循环设计见 `docs/GAME_LOOP_DESIGN.md`。

## 架构边界

```text
Source (WakaTime / Duolingo / Krita / ...)
        ↓ 由 Channel 拉取、归一化、按小时投影
Channel (waka-channel / duolingo-channel / krita-channel)
        ↓ roster + 每小时 increment
Ghost (通用联赛引擎)
```

- **Ghost 不 import Channel，不调用 Source，不出现 provider 名称。**
- Ghost 只接收匿名 `player_ref`、展示资料和 `{event_id, seconds, occurred_at}`。
  Ghost 没有 player identity class：每名玩家都是普通参赛者，不按 human / ai 分支。
- Channel 可以有状态和生命周期：拉周快照、cursor、重试、心跳、补推。
- Channel 可以是模块，也可以独立部署；这是部署选择，不改变边界。
- `channel_id` 是认证/路由用的不透明标识；Ghost 不按它分支。
- Channel roster 一律创建/刷新普通 player；`players` 没有 `kind` / `controller`
  列，`channel_players` 没有 `kind` 列。`source_kind` / `source_key_hash` 只是
  Channel provenance，不是身份。
- `SOURCE_WAKA` 是 Waka 的 provenance 常量（值仍为
  `wakatime_public_leaderboard`）；不存在 `SOURCE_AI`。Waka 是 Channel，其排行榜
  玩家是普通参赛者。
- Ghost 的 Channel ingest：`POST /v1/channels/{channel_id}/roster` 与
  `POST /v1/channels/{channel_id}/increments`；契约在
  `ghost_league/channels/contract.py`。
- Channel 使用独立 token（`GHOST_LEAGUE_CHANNEL_TOKEN` / `create_app(channel_token=...)`），
  不能复用普通账号 token。
- 请求字段固定为 roster 的 `player_ref` / `profile` 和 increment 的
  `player_ref` / `event_id` / `seconds` / `occurred_at`；未知字段（含旧 `kind`）422。
- `group_members.is_human` 仅为兼容旧 UI 保留，所有普通成员都写 1；不得用它恢复
  新的身份分类或分支。
- **Channel account simulation（v1）**：模拟客户端是普通账号，由独立 `ai_channel/` 通过
  `POST /v1/provisioning/accounts` 创建，之后只调用 `/v1/me/*` 与 `/v1/shop*`；
  账号第一次读取走既有 `ensure_human_player`，写普通 player 行。Ghost 不写 AI
  标记，也不为模拟器新增私有接口或数据库旁路。身份和策略只留在 `ai_channel/`
  自己的状态里；provisioning 不再提供 `adopt_existing_player`。

## Widget Studio（图片模版编辑器）

- 编辑器挂在现有 PWA 的 `/widget-studio/`，复用 FastAPI/PWA/TLS/Bearer；不新增服务、端口、venv。
- API 前缀 `/v1/widget-studio`；路由在 `ghost_league/widget_studio/routes.py`，由
  `create_app` 在静态挂载前注册；读写模版 JSON 的接口要求现有 Bearer。
- 模版数据只落 `data/widgets/<id>/`（`template.json`、`flame.png`、`backgrounds/*.png`），
  目录文件是权威；生产图每次请求重新读取，保存后立即生效，不需要重启。
- 模版只接受 schema version 4：没有顶层 `styles`；每张底图自带 `styles.label` 与
  `styles.counter`，切换底图即切换整套样式。`layout.counter` 只有火焰锚点 `{x,y}`，
  `layout.texts` 是各自独立的文字位置。火焰+数字是一个组件，`counter.scale`（0.5–2.0）
  锁定两者比例，`counter.gap`（0–160）是可见火焰右缘到数字左缘的距离，数字相对火焰
  垂直居中。没有全局 `layers`；v3 / v2 / 带 `layers` 的 JSON 明确报错，迁移用
  `scripts/migrate_widget_template_v4.py`（幂等）。
- 显式保存是硬规则：前端拖动、输入、改条件都不 PUT；只有 `Ctrl/Cmd+S` 或“保存”按钮
  PUT 完整 snapshot。上传接口只写文件并返回 `src`，不改 `template.json`。
- 编辑器按当前底图编辑组件与文字：组 X/Y、整体缩放、火焰与数字间隔；文字字号、字重、
  字间距、描边宽度、文字颜色、描边颜色。多个文字变体共用该底图的 `styles.label`，
  位置各自独立。不做旋转；未完成灰度只作用于火焰和数字，文字不变灰。
- Ghost 的 `web/assets/tiers/card/*.png`、`web/assets/frames/*.png` 只通过
  `ghost:assets/...` 的 `src` 形式引用，不复制，不搬动。
- 生产图：`GET /v1/widgets/{user_id}/{template_id}.png`；不要求 Bearer，也不接受数据
  query。数据由服务端按 `user_id` 从 `GameService.status_for_user` 读取；`when`/priority/
  fallback 选底图，文字在该底图 `layout.texts` 中随机选一条。URL 固定，换数据/底图/
  文字/条件不变，换外层模版只改 `template_id`。1x 用 `{template_id}-1x.png`。
  响应头 `X-Widget-Background` / `X-Widget-Text`；未知 user/template/坏 JSON 一律 404。
- 编辑器顶部“我的小组件”显示当前登录 `user_id` + 当前 `template_id` 的固定 URL；当前
  用户来自 `/v1/me/profile`，不在前端伪造。
- 条件与 schema 校验在 `widget_studio/schema.py`；Pillow 生产渲染在 `renderer.py`；
  前端主画布必须即时，`pointermove` 不发请求。
- 详细契约见 `docs/WIDGET_STUDIO.md`。

## 身份与 ID

- 当前 ingest 只做匿名玩家的普通身份：`(channel_id, player_ref)` 映射稳定 `player_id`；Channel 路径不写 AI 标记，本地 account 命中/合并和全量 roster 是后续任务。
- 后续真人：Channel 用本地账号 ID 作为 `player_ref`；Ghost 查账号表，命中即真人，资料用本地 account profile，忽略 Channel 的 profile。
- Channel player：Channel 用稳定 ID，例如 `UUIDv5(channel_id + source_id)`；同一来源行永远同一 ID，不要每次随机。
- Ghost 内部 `player_id` 与 `player_ref` 分离，保存 `(channel_id, player_ref) -> player_id`；
  同一 `player_ref` 在不同 Channel 不混用。
- 玩家进过系统就不硬删；某周不在 roster 就是没参赛，不建组、不写 dormant/absent 状态；历史保留，回归复用同一 ID。
- **展示硬规则**：产品 UI、文案、截图里不得出现 AI / 机器人 / 人机 / Channel / provider 等
  身份词；Channel player 与本地真人都是普通参赛者，不单独标身份。缺少 handle 时不显示
  handle 行，不用身份词兜底；内部 legacy 字段不参与展示。

## 分组

- 旧 `ghost_league/league.py::LeagueEngine._balanced_groups` 已经实现 `ceil(N/15)` + `divmod` 均分，新 game 层应复用它/移植它，不要另写一套均衡算法。
- 旧逻辑的缺口只有：`N=1` 会造单人组、incomplete group 仍按前 3 全升、人类没有优先占满组；在这些点上补规则，不要重写均衡本身。
- 每组最多 15 人；先定组数 `ceil(N/15)`，再均分，不要先装满再丢尾组。
- 每组至少 2 人；只有 1 人时不建单人组，标记 unplaced。
- 本地账号玩家先占组；该 tier 有 15 人以上时，用户必须进满 15 人组。
- 不足 15 人时才允许小组，且尽量均分。
- 升段/降段按 tier 汇总配额，不机械按每个组前 3/后 3；尾组按比例，避免 3 人组全员升降。

## 当前数据/迁移状态

- 旧 `data/league/state.json`、`data/api/membership.json`、旧 `events.db` 只作历史留档，不再作为联赛真相源。
- 新游戏状态在 `data/league/league.db`（GameStore）。
- **Player identity 列移除**：schema 14 起 `players` 没有 `kind` / `controller`，
  `channel_players` 没有 `kind`。游戏状态仍是 `data/league/league.db`；live 迁移已于
  2026-11-05 14:53 CST 执行，迁移时 1076 名普通玩家、1074 条 Channel 映射、1954 条
  group member、XP、小组与 source key 均保留，`group_members.is_human` 统一回填为 1，
  `PRAGMA integrity_check=ok`，API/Web 重启后健康。迁移后 Waka 全量 roster sync 成功：
  972 行、0 新建、972 已有，Waka 排行榜未受影响。
- **live 迁移已执行（无需重跑）**：迁移前备份在
  `/data/backups/ghost-league/pre-player-kind-20261105T145317`（含 `league.db`、
  `accounts.db`、`SHA256SUMS`）；`GameStore.initialize()` 在重建前另写了数据库旁备份
  `data/league/league.db.backup-player-identity-20261105T145319553868`。脚本仍保留给
  新实例或演练：
  `PYTHONPATH=. python3 scripts/migrate_player_identity.py --db data/league/league.db`
  （已迁移库上幂等，不新增备份）。回滚时停服务、恢复上述备份（连同需要的
  `-wal` / `-shm` 状态）后回退到 schema 13 代码。详见 `docs/CHANNEL_BOUNDARY.md`
  与 `docs/CHANNEL_ACCOUNTS.md`。
- live 服务已配置 provisioning token，`POST /v1/provisioning/accounts` 已启用并按
  Bearer 鉴权；token 只在服务 env 与 `ai_channel/config.json`（均 0600、Git-ignored），
  不打印、不提交。`ai_channel/` 可用该路由，仓库根的本地 token DB 保留 1074 个
  Waka `ch-` 普通账号。`ai_channel serve` 常驻入口已存在；systemd unit
  `ai-channel.service` 已于 2026-11-05 15:07 CST 安装并启用，当前 active，运行
  `serve --prefix sim-`。`sim-` 前缀目前匹配 0 个账号，服务因此处于 idle（日志
  accounts=0，不发起 HTTP 请求）；它只处理 `sim-` 前缀，不会加载或使用 Waka
  `ch-` token。完整行为策略（bets/tasks/rival/chests）仍是未来工作。Channel roster
  刷新不会改变 provenance。
- 新 Channel ingest 已落在 `channel_players` / `channel_events`，按 `(channel_id, player_ref)`
  映射身份，按全局 `event_id` 幂等；不读取 `sources` / `opponent_week_plan`，不调用
  `projection.tick`。旧 source 分组也暂时排除 `source_kind=channel_ingest` 的 player。
- 旧 `sources`、`opponent_week_plan`、`projection.tick`、`seed_roster` /
  `sync_week_roster` 的 source 流程属于 Channel 逻辑，仍保留作历史兼容，待后续迁出；
  不要把 WakaTime 周总量重新塞进 Ghost。
- 待删清单以 `docs/CHANNEL_BOUNDARY.md` 的“旧代码迁移”为准；新增代码不得让
  game/ingest 路径 import `ghost_league/source/`、`fetch.py` 或任何 provider。
- 排行榜快照在 `data/cache/cn-978.json`；source fetch 只写缓存，不写游戏库。
- **每日 XP 只经 store resolver 读取**：单日走 `daily_activity_on_day()` /
  `_daily_activity_on_day_with()`，窗口走 `daily_xp_between()`。check-in 存在时权威
  （`xp=0` 也是），否则取当天 `max(activity_events, channel_events)`，不得在
  API/页面/榜单里另写 check-in 或 Channel fallback。任务进度与系统任务条件同样
  统一走这套 daily resolver，禁止在任务模块另写 fallback。

## 开发命令

```bash
cd /opt/ghost-league
PYTHONPATH=. pytest -q
ruff check ghost_league scripts tests
python3 -m compileall -q ghost_league scripts
```

涉及当前生产 PWA 时再加：

```bash
PYTHONPATH=. pytest -q tests/test_pwa.py tests/test_pwa_design.py
```

下一版前端（`frontend/`）单独跑：

```bash
cd frontend
npm ci
npm run build          # tsc --noEmit && vite build，产物在 web-next/
npm run typecheck
npm test
# 真实数据截图/旧新对比需要 token 与旧页面地址，见 frontend/README.md
```

`web-next/` 是独立构建产物；不要覆盖 `web/`。生产默认仍挂载旧 `web/`；切流时由 systemd
设置 `GHOST_LEAGUE_WEB_ROOT=/opt/ghost-league/web-next`，`ghost_league/pwa.py` 的
`ACTIVE_WEB_ROOT` 读取该变量并提供 SPA fallback。旧 `web/index.html`、`web/app.js`、
`web/style.css`、`web/sw.js` 保持可回滚，不在前端任务里改。

## 定时任务

- 所有周期任务由 API 进程内 `ghost_league/game/scheduler.py` 触发，FastAPI lifespan
  启动/停止；不使用 systemd timer、cron、ifrule，也不新增 worker service。
- 任务注册与 Channel/Source 运行时装配在 `ghost_league/runtime_jobs.py`；`game/` 和
  ingest 路径仍不得 import Channel/Source。
- 运行记录在 `league.db` 的 `job_runs`：`(name, period_key)` 唯一，带租约；多进程
  同一周期只执行一次，失败/崩溃后下一 tick 可重试，成功周期永久跳过。
- 时间口径：日注 09:00 锁注、10:30 结算；周注/组注仍是周一 23:59:59 锁、周一
  00:05 结算。

## 安全与部署

- 不修改 `data/` live 数据，除非任务明确要求 reset/部署。
- 不执行 live reset、部署、push，除非用户明确要求。
- 迁移/重置前必须备份；使用临时 DB 测试。
- 不把 token、个人路径、内网 IP、真实姓名写进代码或 git 历史。
- 不在 Ghost 中保留 Source 的 display name/avatar 作为游戏状态；profile 只能是展示快照。

## 交付习惯

- 改完跑真实测试，报告命令和输出，不只说“应该能过”。
- 不伪造兼容层；旧接口可以直接废弃，前端另单改。
- 大规模重构先过临时库和 fake channel，不拿线上当测试环境。
- **文档跟代码同单更新**：改架构、接口、状态机、部署方式时，同一任务更新对应 `docs/`、`README`、`AGENTS.md`，不要把旧路径、旧字段、旧架构留在文档里等下一单补。验收时检查 `git diff --stat` 和文档 grep。
