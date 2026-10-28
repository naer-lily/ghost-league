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

Ghost 只认识 `channel_id`、`player_ref`、`kind`、展示 profile 和事件。
`channel_id` 是路由/认证用的不透明标识，Ghost 不按它分支，也不从中推断 provider。

契约类型在 `ghost_league/channels/contract.py`：

- `RosterPlayer(player_ref, kind, profile=None)`；
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
      "kind": "ai",
      "profile": {"display_name": "Display Name", "avatar_url": "/snapshot.webp"}
    }
  ]
}
```

也可以直接发送 player 数组。顶层和 player 对象都只允许上述字段，未知字段
（例如 `provider`、`raw_seconds`）返回 `422`。

- roster 是**本周名单**，以 `(week_start, channel_id)` 为键全量替换；
- 按 `(channel_id, player_ref)` 幂等创建/更新；重复 roster 不创建新 player；
- 同一 `player_ref` 在不同 `channel_id` 下是两个不同的 Ghost player；
- Ghost 内部 `player_id` 由 `(channel_id, player_ref)` 稳定派生，不随 profile 改变；
- 本周不在 roster 的 player 只是不参赛；不删身份、不写 dormant/absent 状态；
- 名单到达后调用一次 `ensure_all_groups`，与本地真人一起按 tier 分组；
- 响应包含 `channel_id`、`week_start`、`count`、`created`、`existing` 和 `players`
  （`updated` 为兼容字段）。

`kind` 只落库并用于身份投影/审计，不参与计分、难度或行为分支。`profile` 只作展示
快照存储，不进入 `activity_events`、分数或打卡；更新 profile 不改 `player_id`，也不改
历史分数。

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
- 人类和 AI 都走同一条 ingest 路径。

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
- 真人优先进入满组；不足 15 人时才允许 14/15 人混合小组；只有 1 人时标记 unplaced；
- AI-only tier 也建组，不因没有真人而跳过；
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

Ghost 周一 00:05 结算上一周；Channel 周一 00:02 拉新快照。两者独立，不互相调用。

## WakaChannel 独立包

WakaTime 接入在独立包 `waka_channel/`，不进入 Ghost 的 `game/` 或 `channels/`。Ghost
只通过上面的 roster/increments 契约接收匿名结果。包内职责：

- `identity.py`：对每条 source row id 生成固定命名空间的 UUIDv5 `player_ref`；
- `roster.py`：只读 `data/cache/cn-978.json`，保留全量行（含 0 秒行），复用 p75 缩尾；
  manifest 只含 `player_ref` / `kind` / `profile`；
- `projection.py`：复用 `ghost_league/schedule.py` 的纯函数，把每行 effective target
  投到 168 小时；`event_id` 固定为 `waka:{player_ref}:{week_start}:{hour_iso}`，只发出
  已经结束的整点；
- `client.py`：POST 到 `/v1/channels/waka/roster` 与 `/v1/channels/waka/increments`，
  token 从 `GHOST_LEAGUE_CHANNEL_TOKEN`（兼容 `WAKA_CHANNEL_TOKEN`）读取；
- `state.py` / `cli.py`：本地按周记录每个 ref 的已处理小时，重复 tick 不重发；cursor
  默认写在 `data/cache/waka-channel-state.json`，可用 `WAKA_CHANNEL_STATE` 覆盖。

```bash
cd ghost-league
export GHOST_LEAGUE_BASE_URL=http://127.0.0.1:8095
export GHOST_LEAGUE_CHANNEL_TOKEN=<channel-token>
python3 scripts/source_fetch.py --out data/cache/cn-978.json --country CN
python3 -m waka_channel.cli sync-roster --cache data/cache/cn-978.json
python3 -m waka_channel.cli tick
```

`sync-roster` 每次发送当前全量名单：新行加入，消失行本周不出现，回归行复用同一
`player_ref`。`tick` 默认处理 `--at` 所在周，也可用 `--week-start` 显式补推上一周。

## 历史归属

- **Ghost**：`activity_events`、`weekly_scores`、`weekly_results`、`checkins`、
  `streaks`、`group_members`；每个 player 自己的历史。
- **Channel**：source 快照、身份映射、投影计划、cursor；不复制 Ghost 历史。
- AI 消失：Ghost 仍保留历史；回归时 Channel 复用同一个 `player_ref`，不新建。
- AI 某周 0 活跃：只要仍在 manifest 中，Ghost 仍正常建组；没有事件/打卡，排名自然
  垫底，不额外标记或踢出组。

## 兼容边界

API 和 ingest 主路径已经是 Channel-only：`GameService.initialize()` 只建账号、social
和 GameStore，不读 `data/cache`、不投影 AI、不建组；roster 到达后才建组。旧 source
计划/投影代码只作历史兼容，不在 API/ingest 路径，也不应被新增代码 import。
