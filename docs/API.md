# Ghost League API

这是 Ghost League 自托管部署的人读 API 契约。PWA 的“设置 → 集成文档”提供同样的
移动端说明和可复制示例。

- API 根地址：`https://your-host.example`
- PWA 同源入口：`https://your-host.example`（生产环境由反向代理提供 TLS）
- 时区：`Asia/Shanghai`
- 游戏状态：`data/league/league.db`；账号/社交：`data/api/`；source 缓存：`data/cache/`
- 不提供全员列表；每个 token 只能看到自己的资料、小组和状态。
- 生产环境默认关闭 `/docs`、`/redoc`、`/openapi.json`。只有在可信内网显式设置
  `GHOST_LEAGUE_ENABLE_DOCS=1` 时才开放；用户文档不依赖自动生成页面。

## 路由总览

除特别标注外，`/v1/...` 接口都需要普通账号 Bearer token；Channel 接口使用独立
Channel token。`/badge/...`、`/embed/...`、`/health` 和 `/avatars/...` 公开。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查，无鉴权 |
| GET | `/badge/{user_id}.svg` | 公开状态卡（段位/称号/边框） |
| GET | `/embed/{user_id}` | 公开 iframe 卡片 |
| GET/PATCH | `/v1/me/profile` | 读取/修改自己的资料 |
| POST | `/v1/me/token/rotate` | 轮换自己的 token |
| POST | `/v1/me/avatar` | 上传头像 |
| GET | `/avatars/{user_id}` | 读取头像，无鉴权 |
| GET | `/v1/me/status` | 助理轮询状态快照 |
| POST | `/v1/me/increments` | 写入真人活动增量 |
| POST | `/v1/channels/{channel_id}/roster` | Channel 全量周名单 |
| POST | `/v1/channels/{channel_id}/increments` | Channel 小时增量 |
| GET | `/v1/me/league` | 自己的小组与本周数据 |
| GET | `/v1/league/standings` | 自己所在小组的榜单 |
| GET | `/v1/league/history` | 自己已结算的联赛历史 |
| GET | `/v1/league/feed` | 组内动态 |
| POST | `/v1/league/feed/{event_id}/reactions` | 给动态加表情 |
| GET | `/v1/me/embers` | 余烬余额与最近流水 |
| GET | `/v1/me/collection` | 已解锁称号/物品 |
| PATCH | `/v1/me/loadout` | 更新已装备展示项 |
| POST | `/v1/me/repair` | 补签 |
| GET | `/v1/me/checkins` | 按周读取打卡 |
| GET | `/v1/users/{user_id}` | 公开用户卡片 |
| POST/DELETE | `/v1/me/follows/{user_id}` | 关注/取消关注 |
| GET | `/v1/me/follows` | 我关注的人 |
| GET | `/v1/me/followers` | 关注我的人 |
| GET | `/v1/me/friends/standings` | 我与关注对象的周榜 |
| GET | `/v1/discover/people` | 发现本地账号 |
| POST/GET | `/v1/me/webhooks` | 创建/列出 webhook |
| PATCH/DELETE | `/v1/me/webhooks/{webhook_id}` | 修改/删除 webhook |
| POST | `/v1/me/webhooks/{webhook_id}/test` | 立即测试投递 |

## 认证

用户 `/v1/...` 接口使用 Bearer account token：

```http
Authorization: Bearer <account-token>
```

Channel ingest 接口使用**独立的 Channel token**，不能复用账号 token；见
“Channel ingest”。缺失或错误 token 返回 `401`。`GET /health` 和
`GET /avatars/{user_id}` 不需要 token。
token 只以 SHA-256 哈希保存在 `data/api/accounts.db`，不会出现在 API 响应或日志中。

账号管理：

```bash
# 创建账号：明文 token 只打印这一次；可选 --activity 指定活动标签
python -m ghost_league.accounts add --user-id friend-1 --name Friend --activity 骑行

# 只显示 user_id / name / created_at，不显示 token
python -m ghost_league.accounts list

# 换 token：新 token 只打印一次，旧 token 立即失效
python -m ghost_league.accounts rotate --user-id friend-1
```

只有在账号库完全为空时，首次启动才会从 `GHOST_LEAGUE_TOKEN_FILE` 指向的本地
文件读取一次性迁移 token 并创建配置的 owner；该 token 不会打印。不设置时使用
`data/api/token`。账号库已有其他账号但 owner 不存在时，API 启动会报错，不会创建
`current-user`。所有者 ID 通过 `GHOST_LEAGUE_OWNER_ID` 配置，默认 `owner`；
生产部署应显式设置自己的所有者 ID：

```bash
export GHOST_LEAGUE_OWNER_ID=owner-user
export GHOST_LEAGUE_LEGACY_OWNER_ID=legacy-user
python -m ghost_league.accounts rename --from "$GHOST_LEAGUE_LEGACY_OWNER_ID" --to "$GHOST_LEAGUE_OWNER_ID" --dry-run
python -m ghost_league.accounts rename --from "$GHOST_LEAGUE_LEGACY_OWNER_ID" --to "$GHOST_LEAGUE_OWNER_ID"
```

`rename` 会迁移 accounts、membership、events、webhooks 和头像文件；失败会回滚。

## 健康检查

### `GET /health`

无需认证。不列账号、不返回 token。

```json
{
  "status": "ok",
  "current_week": "2026-10-26",
  "timezone": "Asia/Shanghai"
}
```

## 令牌

### `POST /v1/me/token/rotate`

Bearer 鉴权。为当前账号生成新令牌并立即让旧令牌失效。响应中的明文 token 只返回
这一次，客户端应马上保存在本地安全存储中，并同步更新其他活动客户端。

```json
{
  "user_id": "owner-user",
  "token": "<new-token>"
}
```

服务端日志只记录账号 ID，不记录完整令牌。

## 资料

### `GET /v1/me/profile`

返回当前 token 对应账号的资料、段位和小组。

```json
{
  "user_id": "owner",
  "display_name": "Owner",
  "avatar_url": "/avatars/owner",
  "activity_label": "骑行",
  "icon_theme": "classic",
  "tier": "Bronze",
  "group_id": 12,
  "group_no": 1,
  "joined_week": "2026-10-26",
  "week_start": "2026-10-26",
  "equipped_title": "点火",
  "frame": "余烬",
  "backdrop": null,
  "badge_accent": null,
  "updated_at": "2026-10-26T18:42:15+08:00"
}
```

### `PATCH /v1/me/profile`

只能改自己的资料。`display_name`、`activity_label` 与 `icon_theme` 至少传一个，
可单独或同时更新。显示名去掉首尾空白后长度 1–32；活动标签去掉首尾空白后长度
1–16，不能含控制字符。`icon_theme` 当前支持 `classic` 与 `material`。空白、超长
或非法值返回 `422`。

请求：

```json
{"display_name": "Owner", "activity_label": "骑行", "icon_theme": "material"}
```

响应与 `GET /v1/me/profile` 相同。旧账号迁移默认活动为 `画画`；新账号默认
`练习`。缺失或非法的历史 `icon_theme` 按 `classic` 返回。

## 头像

### `POST /v1/me/avatar`

`multipart/form-data`，字段名 `file`。允许 PNG / JPEG / WebP，文件最大 2MB。
服务端用 Pillow 读取实际图片内容（不信任 `Content-Type`），居中裁剪并转为
256×256 WebP，保存为 `data/api/avatars/<user_id>.webp`。同一用户上传会安全覆盖
旧头像。

```bash
curl -X POST "https://your-host.example/v1/me/avatar" \
  -H "Authorization: Bearer $GHOST_LEAGUE_TOKEN" \
  -F "file=@avatar.png"
```

响应：

```json
{"avatar_url": "/avatars/owner-user"}
```

错误：

- `401`：无 token 或 token 错误
- `413`：文件超过 2MB
- `415`：不是可识别的 PNG / JPEG / WebP

### `GET /avatars/{user_id}`

无需认证，返回 WebP 头像。找不到返回 `404`。只允许安全的 user_id 字符，不能用于
目录遍历；不提供目录列表。响应带 `Cache-Control: public, max-age=86400`。

## 活动增量

### `POST /v1/me/increments`

Bearer 鉴权。`event_id` 在单个账号内幂等；同一账号重复发送不会重复加时间。
`seconds` 必须是正整数，不设 180 秒上限。`occurred_at` 可省略，省略时使用服务器
当前时间；不能是未来时间。按 `Asia/Shanghai` 自然周分组。

请求：

```json
{
  "event_id": "activity-20261026-1836-001",
  "seconds": 137,
  "occurred_at": "2026-10-26T18:36:00+08:00"
}
```

响应：

```json
{
  "accepted": true,
  "duplicate": false,
  "event_id": "activity-20261026-1836-001",
  "week_start": "2026-10-26",
  "seconds": 137,
  "week_seconds": 1234,
  "week_xp": 205,
  "today_seconds": 137,
  "today_xp": 22,
  "checkin": null
}
```

同一 `event_id` 重发时 `duplicate` 为 `true`，周累计不重复增加。不同账号可以使用
相同的 `event_id`，互不影响。事件写入 `data/league/league.db` 的
`activity_events`，按 `(player_id, event_id)` 幂等；这是人类账号路径。

## Channel ingest

Channel 适配层只向 Ghost 发送匿名 `player_ref`、`kind`、展示 profile 和已经投影好的
小时增量。Ghost 不知道 provider，不读取 source 快照、anchor 或 raw 周总量。
`channel_id` 是路由/认证用的不透明标识，Ghost 不按它切换业务逻辑。

认证使用独立的 Channel token（部署配置 `GHOST_LEAGUE_CHANNEL_TOKEN`），不能用普通
账号 token：

```http
Authorization: Bearer <channel-token>
```

### `POST /v1/channels/{channel_id}/roster`

按 `(channel_id, player_ref)` 幂等创建/更新 player。请求体只允许 `players`；每个
player 只允许 `player_ref`、`kind`、`profile`，未知字段返回 `422`。也可以直接发送
player 数组。

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

- `kind` 只落库/用于身份投影，不参与计分或分组；
- 同一 `player_ref` 在不同 `channel_id` 下是不同 player；
- profile 只存展示快照，更新 profile 不换 `player_id`、不改历史分数；
- AI 的 `display_name` / `avatar_url` 从 Channel profile 读取；真人仍优先本地账号资料；
- 外部 `avatar_url` 不写入 `players` 表，也不作为游戏输入；
- 内部 `player_id` 稳定，响应会返回 `player_ref`、`player_id`、`kind`、`profile`。

### `POST /v1/channels/{channel_id}/increments`

请求体只允许以下四个字段，未知字段（包括 `provider`、`raw_seconds`）返回 `422`：

```json
{
  "player_ref": "opaque-ref",
  "event_id": "channel:week:hour",
  "seconds": 137,
  "occurred_at": "2026-10-28T12:00:00+08:00"
}
```

- `event_id` 在 Ghost 内全局幂等，重复发送不重复写事件/计分；
- 分数、今日 XP、check-in、streak 的推进与人类事件一致；
- 未在 roster 中声明的 `(channel_id, player_ref)` 返回 `404`，不自动创建 player；
- 同一 `event_id` 被其他 player/channel 使用时返回 `409`；
- 响应字段：`accepted`、`duplicate`、`channel_id`、`player_ref`、`player_id`、
  `event_id`、`week_start`、`seconds`、`week_seconds`、`week_xp`、`today_seconds`、
  `today_xp`、`checkin`。

Channel 路径使用 `channel_players` / `channel_events`，不读取旧 source 计划，也不调用
旧投影。旧 source 兼容代码不在 API/ingest 主路径，也不应被新增代码 import。

API 启动只初始化账号、social 和 `league.db`，确保本地真人存在并建当前周记录；它不读
`data/cache`、不创建 AI、不建组。本周名单到达后，roster 接口写入名单并调用一次
`ensure_all_groups`，把 Channel player 与已存在的本地真人一起分组；真人晚于 roster
到达时，下一次读取会把它补进已有组，不复制 AI、不改已有身份。

没有 Channel roster 时是空/等待状态，不是错误：`GET /v1/me/status` 返回
`group=null`、`group_size=0`、`rank=null`；`GET /v1/league/standings` 返回空
`standings`；`GET /v1/league/history` 返回空 `results`。roster 到达后这些接口恢复
正常的小组数据。

## 本周联赛

### `GET /v1/me/league`

返回当前 token 所在的小组、组人数、自己的名次和完整小组榜单。没有 roster 或尚未
分组时返回 `group=null`、`group_size=0`、`me=null`、`standings=[]`，不自己造数据。
`GET /v1/league/standings` 返回同一结构。

```json
{
  "week_start": "2026-10-26",
  "group": {"id": 12, "no": 1, "tier": "Bronze", "week_start": "2026-10-26", "size": 15},
  "group_id": 12,
  "group_size": 15,
  "me": {"rank": 1, "xp": 1234},
  "standings": [
    {
      "rank": 1,
      "user_id": "owner",
      "display_name": "Owner",
      "avatar_url": "/avatars/owner",
      "is_me": true,
      "xp": 1234,
      "checkin": "verified",
      "streak": 3,
      "title": "点火",
      "frame": "余烬",
      "backdrop": null
    }
  ]
}
```

榜单每行只返回展示用 `title`、`frame`、`backdrop`；不返回内部 `kind`、`is_ai`、
target、source key、channel_id 或原始秒数。成员按 XP 降序排名。

### `GET /v1/league/history`

返回当前账号已结束的联赛历史。加入前没有记录，不补造；未结算周不出现。

```json
{
  "user_id": "owner",
  "week_start": "2026-10-26",
  "results": [
    {
      "week_start": "2026-10-19",
      "group_id": 12,
      "tier": "Bronze",
      "rank": 3,
      "xp": 4200,
      "promoted": true,
      "demoted": false,
      "repaired_days": 0,
      "clean_checkins": 5,
      "settled_at": "2026-10-26T00:05:00+08:00"
    }
  ],
  "generated_at": "2026-10-28T15:00:00+08:00"
}
```

## 组内动态

动态只来自真实的 `checkins` / `weekly_results`，不开放自由发帖、评论或图片上传。
默认返回我所在小组成员、我关注的人和自己的最近事件；没有小组时只返回自己。
不暴露 `source_ref`、`channel_id`、秒数或任何内部目标。

### `GET /v1/league/feed?limit=20`

`limit` 为 1–50，默认 20。响应：

```json
{
  "week_start": "2026-10-26",
  "generated_at": "2026-10-28T15:00:00+08:00",
  "items": [
    {
      "id": 1,
      "kind": "checkin",
      "day": "2026-10-28",
      "body": "今天点着了 1,340 XP",
      "author": {
        "id": "owner-user",
        "name": "Owner",
        "title": "点火",
        "frame": "余烬"
      },
      "reactions": [{"emoji": "盯", "count": 1, "mine": false}],
      "tags": [{"tag": "稳", "count": 1}],
      "created_at": "2026-10-28T15:00:00+08:00"
    }
  ]
}
```

`kind` 为 `checkin`（今日打卡）、`promoted`（本周晋级）或 `champion`（本周第一）。
AI 回应由确定性规则生成：同一事件最多 3 个同组 AI，每个 AI 最多 1 个表情和
1 个标签。表情池为“盯 / 卷 / 递茶 / 记下了 / 肃然起敬 / 同行”；标签池为
“稳 / 狠 / 慢热 / 夜航 / 爆发 / 苦行 / 手稳 / 敢冲”，标签必须能由事件本身解释。

### `POST /v1/league/feed/{event_id}/reactions`

只能回应自己可见的事件。请求体：

```json
{"emoji": "同行"}
```

重复提交同一 `(event_id, viewer, emoji)` 幂等；未知表情返回 `422`，不可见或不存在
的事件返回 `404`。响应是更新后的同一条 feed item。

## 收藏与装备

### `GET /v1/me/collection`

只返回当前账号已经解锁的称号与物品，以及当前装备状态。称号和物品只影响展示，
不改变 XP、排名、分组或结算。

```json
{
  "player_id": "owner-user",
  "titles": [
    {
      "id": "title_ignition",
      "name": "点火",
      "description": "首次完成 100 XP 打卡",
      "awarded_at": "2026-10-26T18:36:00+08:00",
      "season_id": null,
      "equipped": true
    }
  ],
  "items": [
    {
      "id": "frame_ember",
      "name": "余烬",
      "slot": "frame",
      "description": "首次完成 100 XP 打卡",
      "awarded_at": "2026-10-26T18:36:00+08:00",
      "season_id": null,
      "equipped": true
    }
  ],
  "equipped": {
    "title_id": "title_ignition",
    "frame_id": "frame_ember",
    "backdrop_id": null,
    "badge_accent_id": null,
    "updated_at": "2026-10-26T18:40:00+08:00"
  }
}
```

未解锁项不返回，因此也没有获取概率。`season_id` 为 `null` 表示永久有效。

### `PATCH /v1/me/loadout`

只接受自己已解锁的 id；字段可单独或同时更新。未知 id、未解锁 id、或把物品 id
放进错误槽位都返回 `422`。显式传 `null` 可以卸下该槽位。

```json
{
  "title_id": "title_ignition",
  "frame_id": "frame_ember",
  "backdrop_id": null,
  "badge_accent_id": null
}
```

响应是当前 loadout：

```json
{
  "player_id": "owner-user",
  "title_id": "title_ignition",
  "title": "点火",
  "frame_id": "frame_ember",
  "frame": "余烬",
  "backdrop_id": null,
  "backdrop": null,
  "badge_accent_id": null,
  "badge_accent": null,
  "updated_at": "2026-10-26T18:40:00+08:00"
}
```

`GET /v1/users/{id}` 增加 `equipped_title`、`frame`、`backdrop`、`badge_accent`。
公开响应不返回内部 `kind` 或 `is_ai`。AI 的 loadout 由稳定 taste 从它已解锁的项中选择，不读取实时 XP。

## 余烬与打卡

打卡按 `Asia/Shanghai` 自然日计算：当天累计 `seconds >= 600` 即打卡成功，折算
100 XP。当前连胜、最长连胜和最近打卡日期在 `GET /v1/me/status` 中返回；没有独立的
`/v1/me/streak` 路由。

### `GET /v1/me/embers`

返回当前余烬余额、本周可获得上限和最近 20 条流水：

```json
{
  "week_start": "2026-10-26",
  "balance": 1,
  "cap": 3,
  "earned_this_week": 1,
  "week_xp": 1200,
  "ledger": [
    {
      "id": 3,
      "week_start": "2026-10-26",
      "delta": -1,
      "balance_after": 1,
      "reason": "repair",
      "ref": "repair-20261026-1",
      "created_at": "2026-10-28T09:00:00+08:00"
    }
  ],
  "updated_at": "2026-10-28T09:00:00+08:00"
}
```

### `POST /v1/me/repair`

补签一个错过的已完成自然日。窗口按 `Asia/Shanghai` 计算：D 日结束后 **7 天**内有效
（最晚到 D+8 00:00），即 D-1 到 D-7 可补；D-8 及更早返回 `outside_window`，今天和
未来返回 `today_or_future`。该日必须有 1–599 秒（1–99 XP）记录、尚未打卡、账户有至少
1 枚余烬，并使用幂等键。

```json
{"date": "2026-10-26", "idempotency_key": "repair-20261026-1"}
```

```json
{
  "repaired": true,
  "duplicate": false,
  "player_id": "owner",
  "date": "2026-10-26",
  "seconds": 300,
  "xp": 50,
  "embers_spent": 1,
  "balance": 1,
  "current_streak": 2,
  "clean_current": 1,
  "history_marker": "repaired"
}
```

补签只恢复打卡/连胜与历史标记，不增加周 XP、不改变名次或升降级。重复使用同一幂等键
返回 `duplicate=true`；把同一幂等键用于另一个日期返回 `409`。余额不足、窗口外、0 XP
或已打卡分别返回稳定的 422 `detail.code`。

### `GET /v1/me/checkins`

按周返回 7 天打卡状态。`week_start` 缺省为当前周；可选 `week_start` 查询过去周。
每天包含 `date`、`checked_in`、`source`（`verified` / `repaired` / `null`）、`seconds`
与 `xp`。该接口用于 PWA 列出最近七天可补日期，不会自动补签。

```json
{
  "week_start": "2026-10-26",
  "required_xp": 100,
  "days": [
    {
      "date": "2026-10-26",
      "checked_in": true,
      "source": "verified",
      "seconds": 640,
      "xp": 106
    }
  ],
  "generated_at": "2026-10-28T15:00:00+08:00"
}
```

## 助理轮询状态

### `GET /v1/me/status`

给助理或 cron 的稳定快照。只返回当前 token 的用户，不提供全员状态。

```json
{
  "user_id": "owner",
  "display_name": "Owner",
  "avatar_url": "/avatars/owner",
  "activity_label": "骑行",
  "icon_theme": "material",
  "tier": "Bronze",
  "group": {"id": 12, "no": 1, "tier": "Bronze", "week_start": "2026-10-26", "size": 15},
  "group_id": 12,
  "group_size": 15,
  "week_start": "2026-10-26",
  "seconds": 1234,
  "xp": 205,
  "rank": 8,
  "today_seconds": 137,
  "today_xp": 22,
  "required_xp": 100,
  "checkin": null,
  "streak": {
    "current": 3,
    "longest": 7,
    "clean_current": 3,
    "last_checked_date": "2026-10-25"
  },
  "embers": {"balance": 1, "cap": 3, "earned_this_week": 1},
  "gems": 20,
  "equipped_title": "点火",
  "equipped_title_id": "title_ignition",
  "frame": "余烬",
  "frame_id": "frame_ember",
  "backdrop": null,
  "badge_accent": null,
  "next_settlement_at": "2026-11-02T00:00:00+08:00",
  "updated_at": "2026-10-26T18:42:15+08:00"
}
```

- 该接口只读当前 token 的账号，不提供全员状态。
- `gems` 由该玩家 `weekly_scores` 的累计 `SUM(xp) // 10` 派生，每累计 10 XP 得 1 个
  宝石；不按本周 XP 重置，也没有独立 ledger 表。`status_for_user`（badge/widget 快照）
  返回同一派生值。
- 轮询方可以比较 `updated_at`、`xp`、`rank` 和 `next_settlement_at`；重复 `event_id`
  不会推进 `updated_at`。
- 没有 `version` 字段；当前也不实现推送。

轮询示例（不包含真实 token）：

```bash
curl -sS "https://your-host.example/v1/me/status" \
  -H "Authorization: Bearer $GHOST_LEAGUE_TOKEN"
```

## 公开用户与社交

### `GET /v1/users/{user_id}`

返回本地账号或 Channel player 的公开卡片。公开响应**不包含** `kind`、`is_ai`、
`origin`、`synthetic` 或原始秒数。字段包括 `user_id`、`display_name`、
`avatar_url`、`activity_label`、`tier`、`group_id`、`week_start`、`xp`、`rank`、
`group_size`、`checkin`、`streak`、`equipped_title`、`frame`、`backdrop`、
`badge_accent`、`is_following`、`followers_count` 和 `following_count`。
未知 user_id 返回 `404`。

### 关注与发现

- `POST /v1/me/follows/{user_id}`：幂等关注；不能关注自己（`422`），未知用户 `404`。
- `DELETE /v1/me/follows/{user_id}`：幂等取消，成功返回 `204`。
- `GET /v1/me/follows`、`GET /v1/me/followers`：返回用户卡片数组。
- `GET /v1/me/friends/standings`：返回 `{week_start, members}`，成员按 XP 降序。
- `GET /v1/discover/people`：只列出本地账号，不含 Channel player；排除自己。

### 公开卡片

- `GET /badge/{user_id}.svg`：无鉴权 SVG，展示段位、组别、XP、排名、打卡、称号和
  已装备边框；未知用户 `404`，响应 `Cache-Control: no-store`。
- `GET /embed/{user_id}`：无鉴权 iframe 页面，内嵌同一张卡片并每 60 秒刷新；未知用户
  `404`。

## 错误码

| 状态码 | 含义 |
| --- | --- |
| `200` | 成功 |
| `204` | 删除/取消关注成功，无响应体 |
| `401` | Bearer token 缺失或错误 |
| `404` | 资源/用户/webhook/feed 事件不存在，或 Channel roster 未声明该 player |
| `409` | 幂等键或 `event_id` 被另一个目标占用 |
| `413` | 头像超过 2MB |
| `415` | 头像不是 PNG / JPEG / WebP |
| `422` | 请求体校验失败、未来时间、资料名不合法、业务规则拒绝 |

## 边界

- 没有全员列表、没有跨组查询、没有账号管理 HTTP 接口；管理走 CLI。
- `/v1/league/standings` 只暴露自己的小组。
- 不暴露未来周或内部投影参数。
- `GET /health` 与 `GET /avatars/{user_id}` 无鉴权；生产环境只应通过 HTTPS 反向代理暴露。
