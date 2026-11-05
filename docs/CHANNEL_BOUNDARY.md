# Source → Channel → Ghost 边界

## 三个逻辑主体

1. **Source**：外部数据提供方，例如 WakaTime、Duolingo、Krita。它不是本仓库的一部分。
2. **Channel**：每个来源一个适配层，负责拉取、归一化、按小时投影、维护身份映射和 cursor。
3. **Ghost**：通用联赛引擎，只接收匿名 player 和已经投影好的小时增量。

```text
WakaTime   --pull-->  waka-channel   --push-->  Ghost
Duolingo   --pull-->  duolingo-channel --push--> Ghost
Krita      --events--> krita-channel  --push--> Ghost
```

Channel 可以是模块，也可以独立部署；这是部署选择，不改变边界。

Waka 的当前实现是 account-backed 变体：`waka_channel` 只负责 cache 和小时投影，
`ai_channel --source waka` 用已有普通账号 token 调用 `/v1/me/increments`。Ghost 仍只
看到普通账号和固定规则，不注册 Waka/source 任务，也不 import `waka_channel`。

## 为什么叫 Channel

Adapter 听起来像无状态翻译器，但 Channel 有自己的生命周期：每周拉快照、维护 source
身份映射、按小时投影、维护 cursor、重试、心跳、暂停/恢复和补推。它主动向 Ghost 推送，
因此 `Channel` 比 `Adapter` 更准确。

每个 Channel 有自己的：

- source 凭证和 cache；
- 稳定的匿名 `player_ref` 映射；
- 周快照与归一化；
- 小时增量投影；
- push cursor / 幂等 `event_id`；
- 心跳与离线恢复。

## Ghost 的输入契约

Ghost 只认识 `channel_id`、`player_ref`、展示 profile 和事件。Ghost 没有 player
identity class，也不接收、存储或分支 human / ai 身份；`channel_id` 是路由/认证用的
不透明标识，Ghost 不按它分支，也不从中推断 provider。Channel 可以知道自己的来源，
但只能以 `source_kind` / `source_key_hash` 的形式留下 provenance。

契约类型在 `ghost_league/channels/contract.py`：

- `RosterPlayer(player_ref, profile=None)`；
- `IncrementEvent(player_ref, event_id, seconds, occurred_at)`。

### Channel 认证

Channel 接口使用**独立的 Channel token**，不能使用普通账号 token：

```http
Authorization: Bearer <channel-token>
```

部署通过 `GHOST_LEAGUE_CHANNEL_TOKEN` 配置；测试可用固定 test token 调用
`create_app(channel_token=...)`。缺失、错误或把账号 token 用在 Channel 接口上均返回
`401`。`channel_id` 只做路由和身份命名空间。

### Roster

```http
POST /v1/channels/{channel_id}/roster
```

```json
{
  "players": [
    {
      "player_ref": "opaque-ref",
      "profile": {"display_name": "Display Name", "avatar_url": "/snapshot.webp"}
    }
  ]
}
```

也可以直接发送 player 数组。顶层和 player 对象都只允许上述字段，未知字段
（例如 `provider`、`raw_seconds`）返回 `422`。

- roster 是**本周名单**，以 `(week_start, channel_id)` 为键全量替换；
- 按 `(channel_id, player_ref)` 幂等创建/更新；重复 roster 不创建新 player；
- 新建和刷新映射一律是普通 player；Ghost 不接受 `kind` 字段，旧字段作为未知字段
  返回 `422`，且不会产生部分写入；
- 已有 `channel_players` 映射的玩家保持普通身份，刷新只更新展示名、profile、
  `last_seen_week` 和活跃状态；
- 同一 `player_ref` 在不同 `channel_id` 下是两个不同的 Ghost player；
- Ghost 内部 `player_id` 由 `(channel_id, player_ref)` 稳定派生，不随 profile 改变；
- 本周不在 roster 的 player 只是不参赛；不删身份、不写 dormant/absent 状态；
- 名单到达后调用一次 `ensure_all_groups`，与本地账号玩家一起按 tier 分组；
- 响应包含 `channel_id`、`week_start`、`count`、`created`、`existing` 和 `players`
  （`updated` 为兼容字段）。

`profile` 只作展示快照存储，不进入 `activity_events`、分数或打卡；更新 profile
不改 `player_id`，也不改历史分数。`players` 没有 `kind` / `controller` 列，
`channel_players` 没有 `kind` 列；`source_kind` / `source_key_hash` 只是 Channel
provenance，不是身份分类。

### Increments

```http
POST /v1/channels/{channel_id}/increments
```

```json
{
  "player_ref": "opaque-ref",
  "event_id": "channel:week:hour",
  "seconds": 137,
  "occurred_at": "2026-10-28T12:00:00+08:00"
}
```

- 请求体只允许 `player_ref`、`event_id`、`seconds`、`occurred_at`；未知字段返回 `422`；
- `event_id` 在 Ghost 内**全局幂等**；重复发送不重复写活动、不重复计分；
- 更新周分数、今日 XP、check-in 和 streak 的路径与真人增量事件一致；
- 找不到 `(channel_id, player_ref)` roster 时返回 `404`，**不自动猜 player**；
- 同一 `event_id` 被另一个 player/channel 使用时返回 `409`；
- Ghost 不知道 provider、周总量、anchor 或排行榜页面；
- 所有 Channel 参赛者走同一条 ingest 路径；来源身份只留在 Channel 自己的状态里。

响应字段：`accepted`、`duplicate`、`channel_id`、`player_ref`、`player_id`、
`event_id`、`week_start`、`seconds`、`week_seconds`、`week_xp`、`today_seconds`、
`today_xp`、`checkin`。

## 展示 profile

Channel 可以声明自己是否提供展示资料：

- `waka-channel` 有公开显示名/头像，roster 里可以带 `profile`；
- `krita-channel` 背后是真人账户，资料由 Ghost 的本地 account/profile 提供；
- 其他 Channel 以后按需要声明。

Ghost 只把 profile 当**展示层快照**：不参与计分、分组、难度或行为。缺 profile 时用
`(channel_id, player_ref)` 派生的稳定匿名显示名；有 profile 时由 Ghost 存储并展示。
本地真人 account profile 优先于 Channel 提供的匿名回退资料。`channel_id` 仍是不透明
路由标识，Ghost 不按它切换业务逻辑。

## 身份与 ID

- Channel 为每个来源行派生稳定 `player_ref`，例如 `UUIDv5(channel_id + source_id)`；
  同一来源行永远同一 ID，不每次随机。
- Ghost 内部 `player_id` 与 `player_ref` 分离，保存
  `(channel_id, player_ref) -> player_id` 映射；同一 `player_id` 不会重复创建。
- `player_ref` 只在它的 Channel 命名空间里唯一；Ghost 不需要知道它来自哪个 provider。
- 本地 account 与 Channel player 的命中/合并使用本地账号 ID；Channel profile 不得
  覆盖本地 account profile。
- 某周不在 roster 只表示没参赛；历史保留，回归复用同一 `player_id`。

## 分组与结算

- Ghost 把本周 roster 中的 player 与本地真人合并去重，按 tier 归类；
- 每组最多 15 人，先定组数 `ceil(N/15)`，再用 `balanced_group_sizes` 均分；
- Channel player 在同一 tier 内按周哈希排序后填组，同周重复读取不变，跨周会换组，
  避免每周都是同一批对手；
- 本地真人优先进入满组；不足 15 人时才允许 14/15 人混合小组；只有 1 人时标记 unplaced；
- 只有 Channel player 的 tier 也建组，不因没有本地真人而跳过；
- 周结算在每个组内独立进行，配额为 `max(1, round_half_up(group_size * 0.2))`；
- Bronze 不降段，Diamond 不升段；
- 下一周 `ensure_all_groups` 按结算后的 tier 重建分组，升段者进入目标 tier、降段者
  进入低一档。

## 每周生命周期

1. Channel 拉取 source 的全量快照；
2. Channel 发送本周 roster manifest：新 player、回归 player；未出现的只是本周不参赛；
3. Channel 按小时把增量 push 给 Ghost；
4. Ghost 只按事件记分、打卡、分组、结算；
5. Channel 有 cursor；Ghost 宕机或 Channel 重启后可以从 cursor 补推，依赖 `event_id`
   幂等；
6. Channel 心跳丢失时，Ghost 保留玩家和历史，不把 Channel 当真相源。

周一及每天的 Ghost 任务由 API 进程内调度器触发（`ghost_league/runtime_jobs.py`
装配）：`weekly-settle` 00:05、`rival-auto`、`daily-bets`、`power`、
`diamond-decay`。Waka 的缓存刷新和小时 XP 传输由 `ai_channel` 的 systemd timer
（`ai-channel-fetch.timer` / `ai-channel-waka.timer`）驱动，不在 Ghost 调度器注册；
历史 `job_runs` 中的旧任务行保留作审计。调度器只是运行时组合根，`game/` 与 ingest
路径仍不 import Channel/Source。

## Waka 缓存/投影与 ai_channel

Waka 仍是 Channel，但 XP 路径不再走 Channel ingest：`waka_channel/` 是
source/projection 库，只由 `ai_channel/` 的 Waka 传输层使用。Ghost 只看到普通账号和
`/v1/me/increments`，不注册 Waka/source 调度任务，也不 import `waka_channel` 或
provider 客户端。生产传输自 2026-11-05 ~15:41 CST 起由 `ai-channel-waka.timer`
每小时 :01 触发 oneshot `ai-channel-waka.service`，缓存由
`ai-channel-fetch.timer` 每周一 00:02 刷新；`ai-channel.service` 只是 idle 的通用
`sim-` 常驻循环，不承载 Waka。

`waka_channel/` 职责：

- `identity.py`：对每条 source row id 生成固定命名空间的 UUIDv5 `player_ref`；
- `roster.py`：只读 `data/cache/cn-978.json`，保留全量行（含 0 秒行），复用 p75 缩尾；
  manifest 只含 `player_ref` / `profile`；
- `projection.py`：复用 `ghost_league/schedule.py` 的纯函数，把每行 effective target
  投到 168 小时；`event_id` 固定为 `waka:{player_ref}:{week_start}:{hour_iso}`，只发出
  已经结束的整点；
- `state.py`：本地按周记录每个 ref 的已处理小时，重复 tick 不重发；cursor 默认写在
  `data/cache/waka-channel-state.json`，可用 `WAKA_CHANNEL_STATE` 覆盖；
- `client.py` / `cli.py`：旧 Channel ingest 客户端和手动命令保留作历史数据/诊断，
  Ghost 不再调度它们，也不是当前 Waka XP 的生产路径。

`ai_channel/` Waka 模式：

- 读取现有 cache 和 `waka_channel.projection`，不写 Ghost 数据库；
- 把 `player_ref` 映射为 `ch-` + sha256(`ghost-channel-player-v1\0waka\0` +
  `player_ref`)，与 Ghost 现有 Channel player id 完全一致；
- 从 `ai_accounts.db` 读取该普通账号的 token；缺 token 只报告并跳过，不创建玩家；
- 每个正增量调用 `POST /v1/me/increments`，沿用 Waka 的 `event_id` / `seconds` /
  `occurred_at`，不走 `/v1/channels/...`；
- 复用 Waka cursor；只推进整批成功的玩家，重复 tick 不再发送同一小时；
- `tick --source waka` / `serve --source waka` 支持 `--cache` / `--state`；
  通用 `sim-` 账号模式不变；
- live 传输由 `ai-channel-waka.timer` 每小时 :01 触发 oneshot
  `ai-channel-waka.service` 执行 `tick --source waka`；`serve --source waka`
  不是当前生产入口。

```bash
cd /opt/ghost-league
export PYTHONPATH=/opt/ghost-league:/opt/ghost-league/ai_channel
# 可选：刷新公开榜缓存（只写 cache，不写游戏库）
python3 scripts/source_fetch.py --out data/cache/cn-978.json --country CN
python3 -m ai_channel tick --config ai_channel/config.json --source waka \
  --cache data/cache/cn-978.json \
  --state data/cache/waka-channel-state.json
```

切换只改变传输：`event_id`、秒数和小时边界沿用现有投影。cutover 已于
2026-11-05 ~15:41 CST 在 live 执行，切流前备份在
`/data/backups/ghost-league/pre-waka-cutover-20261105T154101`。历史 `channel_events`
行保留；新事件写入 `activity_events`，每日 XP resolver 仍取两者较大值，所以当前前端
数据不变。`ai-channel.service` 仍是 idle 的通用 `sim-` 常驻循环，不是 Waka tick。

## Channel account simulation (v1)

新的模拟客户端不走 Channel ingest，而是像普通客户端一样使用账号和公开 API：

- Ghost 提供独立 provisioning token（`GHOST_LEAGUE_PROVISIONING_TOKEN` /
  `create_app(provisioning_token=...)`）和 `POST /v1/provisioning/accounts`；
  该 token 不能与 owner / bootstrap / Channel token 混用。
- `ai_channel/` 是独立的账号模拟器：通用模式通过 provisioning API 创建普通账号、
  在本地保存 token，然后调用 `/v1/me/increments`、`/v1/me/status` 和
  `/v1/shop/purchase`；Waka 模式直接复用已有的 1074 个 Waka `ch-` 普通账号 token，
  读取 `waka_channel.projection` 后同样调用 `/v1/me/increments`。两种模式都不写
  Ghost 数据库，不调用私有接口。
- 账号第一次调用 `/v1/me/*` 时走既有 `ensure_human_player` 路径，写普通 player 行；
  Ghost 没有 player identity 列，也不写 AI 标记。provisioning 不提供
  `adopt_existing_player`。
- Waka 仍是 Channel，其排行榜玩家是普通参赛者；Ghost 没有来源身份分类。Waka 的
  provenance 常量是 `SOURCE_WAKA`（值仍为 `wakatime_public_leaderboard`），
  不存在 `SOURCE_AI`。Ghost 已不注册 `waka-tick` / `waka-roster` / `source-fetch`，
  历史 `job_runs` 行保留。
- live 服务已配置 provisioning token，`/v1/provisioning/accounts` 已启用并鉴权；
  token 只在服务 env 与 `ai_channel/config.json`（均 0600、Git-ignored），不打印、
  不提交。`ai_channel/` 可用该路由，仓库根的本地 token DB 保留 1074 个 Waka
  `ch-` 普通账号。
- Waka cutover 已于 2026-11-05 ~15:41 CST 在 live 执行，切流前备份在
  `/data/backups/ghost-league/pre-waka-cutover-20261105T154101`。
  `ai-channel-waka.timer` 每小时 :01 触发 oneshot `ai-channel-waka.service` 运行
  `tick --source waka`；`ai-channel-fetch.timer` 每周一 00:02 刷新缓存。
  `ai-channel-waka.service` 不是常驻进程。`ai-channel.service` 仍是
  `serve --prefix sim-` 的 idle 通用常驻循环（当前 0 个 `sim-` 账号，日志
  accounts=0，不发起 HTTP 请求），不是 Waka tick，也不加载 `ch-` token。
- 完整行为策略（bets/tasks/rival/chests）仍是未来工作。见
  [`CHANNEL_ACCOUNTS.md`](CHANNEL_ACCOUNTS.md)。

## Player identity live migration

schema 14 删除 `players.kind` / `players.controller` 和 `channel_players.kind`。
该迁移已于 2026-11-05 14:53 CST 在 live 执行：迁移前备份在
`/data/backups/ghost-league/pre-player-kind-20261105T145317`，数据库旁自动备份为
`data/league/league.db.backup-player-identity-20261105T145319553868`；迁移时
1076 名玩家、1074 条 Channel 映射、1954 条 group member 全部保留，
`PRAGMA integrity_check=ok`，API/Web 重启后健康。迁移后的 Waka 全量 roster sync
成功：972 行、0 新建、972 已有，Waka 排行榜未受影响。以下机制与命令保留作复核、
新实例和回滚参考；live 库无需重跑。

迁移是幂等的，由 `GameStore.initialize()` 在打开旧库时执行：

1. 检测三列中任意一条仍存在；
2. 用 SQLite backup API 在数据库旁写
   `league.db.backup-player-identity-<timestamp>`；
3. 在同一个事务内重建 `players` 和 `channel_players`，只复制共享列；
4. 保留 player id、`source_kind` / `source_key_hash`、`channel_players.profile_json`
   映射、XP、`weekly_scores`、小组关系和钱包；不删除任何玩家行；
5. 把 `group_members.is_human` 统一设为 1（旧 UI 兼容值，不再代表身份分类）。

执行（live 已按此完成；新实例或演练仍先停 API/Web）：

```bash
cd /opt/ghost-league
PYTHONPATH=. python3 scripts/migrate_player_identity.py --db data/league/league.db
```

脚本打印 `integrity_check`、`players`、`channel_players`、`group_members` 计数和
备份路径。已迁移库上重复运行不会再次迁移，也不会新增备份。回滚：停服务，恢复上述
迁移前备份（`/data/backups/ghost-league/pre-player-kind-20261105T145317`）或最近的
`league.db.backup-player-identity-*`（连同需要的 `-wal` / `-shm` 状态），再回退到
schema 13 代码；不要在服务运行时覆盖数据库文件。

## 历史归属

- **Ghost**：`activity_events`、`weekly_scores`、`weekly_results`、`checkins`、
  `streaks`、`group_members`；每个 player 自己的历史。
- **Channel**：source 快照、身份映射、投影计划、cursor；不复制 Ghost 历史。
- 玩家消失：Ghost 仍保留历史；回归时 Channel 复用同一个 `player_ref`，不新建。
- 玩家某周 0 活跃：只要仍在 manifest 中，Ghost 仍正常建组；没有事件/打卡，排名自然
  垫底，不额外标记或踢出组。

## 兼容边界

API 和 ingest 主路径已经是 Channel-only：`GameService.initialize()` 只建账号、social
和 GameStore，不读 `data/cache`、不投影旧 source、不建组；roster 到达后才建组。旧 source
计划/投影代码只作历史兼容，不在 API/ingest 路径，也不应被新增代码 import。
`ghost_league/runtime_jobs.py` 只注册通用游戏任务，不 import Channel/Source/provider，
也不注册 Waka/source 任务；历史 `job_runs` 行保留作审计。

Waka 的传输切换不删除历史：现有 `channel_events` 行继续保留，切流前由旧 tick 写入的
数据仍会被每日 XP resolver 读取；切流后新事件写 `activity_events`，前端数据口径不变。
