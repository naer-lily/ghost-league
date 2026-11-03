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
| GET | `/v1/me/rival` | 本周宿敌、选择窗口、下注与上次结果 |
| GET | `/v1/me/rival/candidates` | 可选择的宿敌候选（跨组） |
| POST | `/v1/me/rival/select` | 手动选择/改选本周宿敌 |
| GET | `/v1/me/bets` | 本周周注、三个组注盘口与当天日注 |
| POST | `/v1/me/bets` | 下注周注、任一组注盘口或日注 |
| GET | `/v1/me/stars/{star_id}/svg` | 自己一颗星的独属 SVG |
| POST | `/v1/me/increments` | 写入真人活动增量 |
| POST | `/v1/channels/{channel_id}/roster` | Channel 全量周名单 |
| POST | `/v1/channels/{channel_id}/increments` | Channel 小时增量 |
| GET | `/v1/me/league` | 自己的小组与本周数据 |
| GET | `/v1/league/standings` | 自己所在小组的榜单 |
| GET | `/v1/league/history` | 自己已结算的联赛历史 |
| GET | `/v1/league/feed` | 组内动态 |
| POST | `/v1/league/feed/{event_id}/reactions` | 给动态加表情 |
| GET | `/v1/me/embers` | 余烬余额与最近流水 |
| GET | `/v1/shop` | 钻石商店有效商品 |
| POST | `/v1/shop/purchase` | 用钻石购买商品 |
| GET | `/v1/me/collection` | 已解锁称号/物品 |
| PATCH | `/v1/me/loadout` | 更新已装备展示项 |
| POST | `/v1/me/repair` | 补签 |
| GET | `/v1/me/checkins` | 按周读取打卡 |
| GET | `/v1/me/history` | 自己的统一个人历史时间线 |
| GET | `/v1/users/{user_id}` | 登录态公开卡片 + 与我的本周对比 |
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
分组时返回 `group=null`、`group_size=0`、`promotion_quota=0`、`demotion_quota=0`、
`me=null`、`standings=[]`，不自己造数据。
`GET /v1/league/standings` 返回同一结构。

每组前 30% 晋级、后 30% 降级，均向下取整并至少 1 人：
`max(1, (group_size * 3) // 10)`。因此 15 人组前 4/后 4、14 人组前 4/后 4、
13 人组前 3/后 3、2 人组前 1/后 1。Bronze 不降级，Diamond 不晋级，少于 2 人
不移动。前端直接使用 `promotion_quota`、`demotion_quota` 和每行的
`promoted`/`demoted`，不要自己按百分比推算。

```json
{
  "week_start": "2026-10-26",
  "group": {"id": 12, "no": 1, "tier": "Bronze", "week_start": "2026-10-26", "size": 15},
  "group_id": 12,
  "group_size": 15,
  "promotion_quota": 4,
  "demotion_quota": 4,
  "me": {"rank": 1, "xp": 1234, "power": 421},
  "standings": [
    {
      "rank": 1,
      "user_id": "owner",
      "display_name": "Owner",
      "avatar_url": "/avatars/owner",
      "is_me": true,
      "xp": 1234,
      "power": 421,
      "checkin": "verified",
      "streak": 3,
      "promoted": true,
      "demoted": false,
      "title": "点火",
      "frame": "余烬",
      "backdrop": null
    }
  ]
}
```

榜单每行返回展示用 `title`、`frame`、`backdrop`、`power` 和当前名次对应的
`promoted`/`demoted` 标记；`me` 对象也带 `power`。`power` 为 `null` 表示该玩家
还没有任何可用周，不伪造 1000。榜单不返回内部 `kind`、`is_ai`、target、source key、
channel_id 或原始秒数。成员按 XP 降序排名。战力只是派生展示字段，不改变排名、
分组、升降级或结算。

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

## 个人历史

### `GET /v1/me/history?limit=100`

只返回当前登录账号自己的历史，不返回他人、钱包、下注账本或任何私有流水。`limit`
范围为 1–200，默认 100；六类记录合并后按 `at` 降序，`at` 相同时按 `id` 升序稳定
排序。`type` 只有 `checkin`、`bet`、`group_bet`、`rival`、`star`、`week`。

```json
{
  "user_id": "owner",
  "generated_at": "2026-11-02T22:30:00+08:00",
  "limit": 100,
  "items": [
    {
      "id": "checkin:2026-11-02",
      "type": "checkin",
      "at": "2026-11-02T22:31:00+08:00",
      "title": "打卡",
      "body": "画画 · 画了一张速写",
      "data": {"date": "2026-11-02", "domain": "画画", "content": "画了一张速写"}
    }
  ]
}
```

`id` 在每类内稳定：`checkin:{date}`、`bet:{id}`、`group_bet:{id}`、
`rival:{week_start}`、`star:{star_id}`、`week:{week_start}`。`at` 统一为
Asia/Shanghai 的 ISO-8601。旧打卡没有 `domain` / `content` 时 `body` 为“打卡记录”，
不会报错或伪造内容。下注 `data` 保留 `period_key`；组注 `data` 另含 `market`、
`market_label` 和该盘口的 `target_rank`，同一周三笔会显示为三条 `group_bet`；
宿敌、星星和周结算的 `data` 只包含本人可读的展示字段。

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

给助理或外部轮询方的稳定快照。只返回当前 token 的用户，不提供全员状态。

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
  "power": 421,
  "power_percentile": 0.2107,
  "power_week": "2026-10-26",
  "power_updated_at": "2026-11-02T15:05:00+08:00",
  "power_provisional": false,
  "today_seconds": 137,
  "today_xp": 22,
  "last_activity_at": "2026-10-26T16:30:00+08:00",
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
  "diamonds": 2700,
  "diamond_cap": 1000,
  "diamond_cap_level": 0,
  "diamond_excess": 1700,
  "diamond_boost": {
    "expires_at": null,
    "remaining_seconds": 0,
    "multiplier": 1
  },
  "inventory": {"star": 1, "seasonal_star": 1, "ember": 1},
  "stars": [
    {
      "id": "8f14e45fceea167a5a36dedd4bea2543",
      "name": "霜蓝",
      "kind": "normal",
      "season_key": null,
      "star_type": "white_dwarf",
      "type_label": "白矮星",
      "rarity": "uncommon",
      "rarity_label": "星辉",
      "palette": ["#e8f2ff", "#ffffff", "#6b7c99"],
      "visual_seed": 123456789,
      "companion_count": 0,
      "catalog_code": "GL-2026-AB12CD34",
      "acquired_at": "2026-11-02T15:30:00+08:00",
      "svg_url": "/v1/me/stars/8f14e45fceea167a5a36dedd4bea2543/svg"
    }
  ],
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
- `last_activity_at` 是本周最后一条 `activity_events.occurred_at`，没有活动时为 `null`。
  前端用它计算“刚刚更新/N 分钟前更新”，超过 1 小时不再显示“刚刚更新”；`updated_at`
  仍是响应生成时间，两者语义不同。
- `gems` 继续是原来的展示值，由该玩家 `weekly_scores` 的累计 `SUM(xp) // 10` 派生，
  每累计 10 XP 得 1 个宝石；不按本周 XP 重置，也没有独立 ledger 表。`gems` 不是钻石，
  不会因为商店消费而变化。
- `diamonds` 是独立钻石钱包余额。新真人钱包初始 1000，`diamond_cap` 初始 1000、
  `diamond_cap_level` 初始 0。旧库中已有钱包保留余额并补 1000 上限；没有钱包记录的
  真人补 1000/1000。AI 没有钱包。当前只有本地管理命令/未来奖励接入会充值，正式的
  宿敌、活动奖励后续再接。
- 钻石是**软上限**：余额可以超过上限，超出部分 `diamond_excess = max(0, diamonds - cap)`
  不删、不拒绝入账，按完整小时 1% 复利损耗；只有完整小时计费，重复读取同一小时不会
  重复扣。服务器离线后按 `last_decay_at` 在下次钱包读写或 `diamond-decay` job 补算。
- `diamond_boost` 是当前生效的经验宝状态：`expires_at` 是到期时间，`remaining_seconds`
  是服务端时钟下的剩余秒数，`multiplier` 是生效倍率。未生效/已过期时 `expires_at=null`、
  `remaining_seconds=0`、`multiplier=1`。倍率只作用于正常游戏钻石入账，初始钱包和管理
  发钻不乘。
- `inventory` 至少包含 `star`、`seasonal_star` 与 `ember`。`inventory.star` 读取通用物品栏
  `inventory_items`，是普通星数量；`inventory.seasonal_star` 是季节星数量；
  `inventory.ember` 直接读取现有 `ember_balance.balance`，不复制到 `inventory_items`。
  没有记录的物品返回 0，不会省略字段。
- `stars` 是自己的抽卡星列表；每颗星一条记录，含 `id`、`name`、`kind`
  （`normal` / `seasonal`）、`season_key`（普通星为 `null`）、`star_type`、
  `type_label`、`rarity`、`rarity_label`、`palette`、`visual_seed`、
  `companion_count`、`catalog_code`、`acquired_at` 和 `svg_url`。名字只给本人看；
  只按 `acquired_at` 升序返回本人数据。
- 钻石、上限、经验宝、物品栏和星星只在自己的 `/v1/me/status` 返回；`status_for_user`
  （badge/widget 快照）、榜单、公开资料、`/v1/users/{id}` 和任何他人视角都不包含
  `diamonds`、`diamond_cap`、`diamond_cap_level`、`diamond_excess`、`diamond_boost`、
  `inventory`、`stars`。
- `power` 是 0–2000 的派生展示战力。计算窗口为最近 4 个自然周（含当前未结束周），
  权重从新到旧为 `0.4 / 0.3 / 0.2 / 0.1`，只按该玩家实际有 `weekly_scores` 行的周
  重新归一化；每周百分位 `p = (less_count + equal_count / 2) / total_count`，
  `P = sum(weight * p) / sum(weight)`，`power = round(1000 + 1000 * (2P - 1))`
  并裁剪到 0–2000。`power_percentile` 保存加权后的 `P`，`power_week` 是计算窗口的
  当前周。
- 只有完全没有可用周时 `power` 才为 `null`，此时 `power_provisional=true`；有 1 周
  及以上就已经正式定级，`power_provisional=false`，不会显示“定级中”。
- 战力由 API 进程内的调度器每小时第 5 分钟刷新 `players` 当前值；该任务不写周历史、
  不结算。周结算在 `weekly_results` 落库后写 `player_power_history` 最终值。
  `status_for_user` 返回同一组战力字段。
- 轮询方可以比较 `updated_at`、`xp`、`rank` 和 `next_settlement_at`；重复 `event_id`
  不会推进 `updated_at`。
- 没有 `version` 字段；当前也不实现推送。

轮询示例（不包含真实 token）：

```bash
curl -sS "https://your-host.example/v1/me/status" \
  -H "Authorization: Bearer $GHOST_LEAGUE_TOKEN"
```

## 钻石与商店

钻石是独立于 `gems` 的货币，只属于真人。新真人钱包初始 1000 钻石、1000 软上限；
旧库已有钱包保留余额并补 1000 上限、0 级、`last_decay_at` 置为迁移时间；缺失的真人
钱包补 1000/1000。AI 没有钱包、不能购买，也不会出现在他人视角。

钻石是**软上限**，不是硬截断：

- 余额可以超过 `diamond_cap`；超出部分按完整小时 `1%` 复利损耗：
  `new_balance = cap + floor(excess * 0.99 ** hours)`，损耗后不低于上限。
- 余额不高于上限时不损耗；同一小时重复读取/job 不会重复扣。
- 每次实际损耗写一条负数 `diamond_ledger`，`reason='decay'`；服务器离线后按
  `last_decay_at` 在钱包读写时惰性补算，或由
  `python3 -m ghost_league.game.jobs diamond-decay --at <iso>` 统一补算。
- 充值/奖励不因超过上限被拒绝；下注等未来消耗也不受上限阻塞。

本地管理命令仍可用于测试或未来奖励接入：

```bash
python3 -m ghost_league.game.jobs grant-diamonds --player <id> --amount 3000 --reason test
```

该命令是管理/测试发钻，不受经验宝倍率影响。

当前商品：

| id | kind | 名称 | 价格 | 发货 | 限制 |
| --- | --- | --- | --- | --- | --- |
| `star` | `star` | 普通星抽卡 | 300 钻石/抽 | 随机一颗星写 `player_stars`，并递增 `inventory_items.star` | 每次只能买 1 颗；名字可省略；可重复买 |
| `seasonal_star` | `seasonal_star` | 季节星抽卡 | 500 钻石/抽 | 随机一颗当季星写 `player_stars`，并递增 `inventory_items.seasonal_star` | 每个玩家每个自然月最多 1 颗；名字可省略 |
| `ember` | `ember` | 余烬 | 800 钻石/个 | 进入现有 `ember_balance`，不写 `inventory_items` | 每次只能买 1 个；72 小时冷却 |
| `diamond_cap_1` … `diamond_cap_5` | `cap` | 仓库上限升级 | 500 / 800 / 1200 / 1800 / 2600 | 扣钻石，上限 +500，等级 +1 | 只能按当前等级买下一级；5 级后不再出现 |
| `diamond_boost_25` | `boost` | 经验宝 · 配置分钟数 | `diamond_boost_25_price` | 扣钻石，写入/顺延 `diamond_boosts` | 每次只能买 1 个；`diamond_boost_25_active=0` 时不可购买 |
| `diamond_boost_60` | `boost` | 经验宝 · 配置分钟数 | `diamond_boost_60_price` | 扣钻石，写入/顺延 `diamond_boosts` | 每次只能买 1 个；`diamond_boost_60_active=0` 时不可购买 |

经验宝是长期平衡参数，读取 `game_config`，不写死在代码里：

| key | 种子值 | 含义 |
| --- | --- | --- |
| `diamond_boost_multiplier` | `2` | 生效期间正常钻石入账倍率 |
| `diamond_boost_25_price` | `25` | 25 档价格 |
| `diamond_boost_25_minutes` | `25` | 25 档分钟数 |
| `diamond_boost_60_price` | `60` | 60 档价格 |
| `diamond_boost_60_minutes` | `60` | 60 档分钟数 |
| `diamond_boost_25_active` | `1` | 25 档是否上架 |
| `diamond_boost_60_active` | `1` | 60 档是否上架 |

种子只在缺失时插入，不覆盖运营改过的值。配置缺省或非法时，该商品不出现、购买返回
`409 boost_config_invalid`，不会按 0 价格或 0 倍率成交。调整示例：

```bash
sqlite3 data/league/league.db \
  "UPDATE game_config SET value='30', updated_at=datetime('now') WHERE key='diamond_boost_25_price';"
```

购买成功会扣对应价格；已有未到期经验宝时从原到期时间顺延分钟数，否则从现在开始。
`diamond_boosts` 每个玩家一行，记录当前 `multiplier`、`expires_at`、`updated_at`。
生效期间宿敌奖励、下注派彩等正常钻石入账按配置倍率入账；初始 1000 钱包和管理/测试
`grant-diamonds` 不乘。经验宝只改钻石入账，不改 XP、打卡、战力或 WakaTime 数据。

上限阶梯：

| 等级 | 价格 | 上限变化 |
| --- | --- | --- |
| 1 | 500 | 1000 → 1500 |
| 2 | 800 | 1500 → 2000 |
| 3 | 1200 | 2000 → 2500 |
| 4 | 1800 | 2500 → 3000 |
| 5 | 2600 | 3000 → 3500 |

星星抽卡规则：

- 每次购买先按概率抽 `rarity`，再从该稀有度的类型池均匀抽 `star_type`；概率使用
  `secrets` 系统随机源，权重常量 `RARITY_WEIGHTS` 之和精确为 1.0。
- 保底暂未实现；普通星可重复抽，季节星每个自然月仍只允许一颗。
- 普通星 300 钻石/抽，季节星 500 钻石/抽；本次不改价。
- `name` 可选：省略或传 `null` 时服务器从中文双字词池生成默认名；显式传空字符串仍是
  非法名字。名字去掉首尾空白后长度 1–40，拒绝换行和控制字符，只给本人看。
- 名字不要求全服唯一；每颗星有独立 `id`、`catalog_code`、`visual_seed` 和
  `acquired_at`，永久保留，不回售。
- 每颗星记录最终 `palette` 三色和 63 位正整数 `visual_seed`；之后渲染 SVG 只读记录，
  不重新抽颜色或细节，所以同一颗星每次得到逐字节相同的图。
- 季节星 `season_key` 使用服务器当前自然月，例如 `2026-11`；客户端提供的任何月份都
  不参与判断。跨月后可以再买下一颗；同月第二颗返回 `409 seasonal_star_owned`。
- 普通星 `season_key` 为 `null`，`UNIQUE(player_id, season_key)` 不会阻止重复购买；
  季节星由该唯一约束兜底。

| rarity | 中文 | 概率 | 类型池 |
| --- | --- | --- | --- |
| `common` | 微光 | 50% | `red_dwarf` 红矮星、`orange_dwarf` 橙矮星、`yellow_dwarf` 黄矮星 |
| `uncommon` | 星辉 | 30% | `white_dwarf` 白矮星、`blue_white_star` 蓝白星、`variable_star` 变星 |
| `rare` | 耀星 | 15% | `red_giant` 红巨星、`blue_giant` 蓝巨星、`binary_star` 双星 |
| `epic` | 奇点 | 4.5% | `triple_star` 三合星、`neutron_star` 中子星、`pulsar` 脉冲星 |
| `legendary` | 神话 | 0.5% | `black_hole_relic` 黑洞遗迹 |

`binary_star` 固定 1 颗伴星，`triple_star` 固定 2 颗，其余类型为 0。
`black_hole_relic` 是黑洞遗迹，不是普通恒星。

### `GET /v1/shop`

Bearer 鉴权。返回当前可买商品数组。普通商品按 `sort` 排序；仓库升级只返回当前等级
的下一级（5 级后无升级项）；经验宝不写 `shop_items`，每次由 `game_config` 生成两个
固定 SKU。字段包含 `kind`；季节星额外带 `season_key`；上限升级额外带
`required_cap_level`；经验宝额外带 `active`、`minutes`、`multiplier`，其中 `active`
表示该档是否上架。`available` 综合考虑冷却、季节窗口、上限等级和经验宝上架状态；
余额是否足够仍在购买时单独校验。

```json
[
  {
    "id": "star",
    "name": "星星",
    "description": "300 钻石抽一颗随机星；名字可省略，由服务器生成，仅自己可见。",
    "price_diamonds": 300,
    "currency": "diamonds",
    "kind": "star",
    "gacha": true,
    "rates": {"common": 0.5, "uncommon": 0.3, "rare": 0.15, "epic": 0.045, "legendary": 0.005},
    "types": ["red_dwarf", "orange_dwarf", "yellow_dwarf", "white_dwarf", "blue_white_star", "variable_star", "red_giant", "blue_giant", "binary_star", "triple_star", "neutron_star", "pulsar", "black_hole_relic"],
    "owned_quantity": 1,
    "cooldown_seconds": 0,
    "cooldown_until": null,
    "available": true
  },
  {
    "id": "seasonal_star",
    "name": "季节星",
    "description": "500 钻石抽一颗当季随机星；每个自然月最多一颗，名字可省略。",
    "price_diamonds": 500,
    "currency": "diamonds",
    "kind": "seasonal_star",
    "gacha": true,
    "rates": {"common": 0.5, "uncommon": 0.3, "rare": 0.15, "epic": 0.045, "legendary": 0.005},
    "types": ["red_dwarf", "orange_dwarf", "yellow_dwarf", "white_dwarf", "blue_white_star", "variable_star", "red_giant", "blue_giant", "binary_star", "triple_star", "neutron_star", "pulsar", "black_hole_relic"],
    "season_key": "2026-11",
    "owned_quantity": 1,
    "cooldown_seconds": 0,
    "cooldown_until": null,
    "available": false
  },
  {
    "id": "ember",
    "name": "余烬",
    "description": "立即获得 1 枚余烬；每 72 小时最多购买一次。",
    "price_diamonds": 800,
    "currency": "diamonds",
    "kind": "ember",
    "owned_quantity": 1,
    "cooldown_seconds": 259200,
    "cooldown_until": "2026-11-05T12:00:00+08:00",
    "available": false
  },
  {
    "id": "diamond_cap_1",
    "name": "仓库上限 1 级",
    "description": "仓库上限 +500；购买后进入 1 级。",
    "price_diamonds": 500,
    "currency": "diamonds",
    "kind": "cap",
    "required_cap_level": 0,
    "owned_quantity": 0,
    "cooldown_seconds": 0,
    "cooldown_until": null,
    "available": true
  },
  {
    "id": "diamond_boost_25",
    "name": "经验宝 · 25 分钟",
    "description": "",
    "price_diamonds": 25,
    "currency": "diamonds",
    "kind": "boost",
    "active": true,
    "minutes": 25,
    "multiplier": 2,
    "owned_quantity": 0,
    "cooldown_seconds": 0,
    "cooldown_until": null,
    "available": true
  },
  {
    "id": "diamond_boost_60",
    "name": "经验宝 · 60 分钟",
    "description": "",
    "price_diamonds": 60,
    "currency": "diamonds",
    "kind": "boost",
    "active": true,
    "minutes": 60,
    "multiplier": 2,
    "owned_quantity": 0,
    "cooldown_seconds": 0,
    "cooldown_until": null,
    "available": true
  }
]
```

### `POST /v1/shop/purchase`

Bearer 鉴权。`request_id` 必填，用于幂等；同一个 `request_id` 重复提交只扣一次款并
返回同一购买结果（`replayed=true`），不会重新抽卡、重复扣钻石或重复顺延经验宝。
`quantity` 缺省为 1；普通星/季节星/余烬/上限升级/经验宝都只能一次买 1 个。普通星和
季节星的 `name` 可省略；省略时由服务器生成默认名，显式空字符串仍返回
`422 invalid_star_name`。

```json
{
  "item_id": "star",
  "quantity": 1,
  "name": "给妈妈的星",
  "request_id": "shop-20261102-001"
}
```

```json
{
  "ok": true,
  "item_id": "star",
  "quantity": 1,
  "diamonds": 700,
  "diamond_cap": 1000,
  "diamond_cap_level": 0,
  "diamond_excess": 0,
  "inventory": {"star": 1, "seasonal_star": 0, "ember": 0},
  "cooldown_until": null,
  "replayed": false,
  "star": {
    "id": "8f14e45fceea167a5a36dedd4bea2543",
    "name": "霜蓝",
    "kind": "normal",
    "season_key": null,
    "star_type": "white_dwarf",
    "type_label": "白矮星",
    "rarity": "uncommon",
    "rarity_label": "星辉",
    "palette": ["#e8f2ff", "#ffffff", "#6b7c99"],
    "visual_seed": 123456789,
    "companion_count": 0,
    "catalog_code": "GL-2026-AB12CD34",
    "acquired_at": "2026-11-02T15:30:00+08:00",
    "svg_url": "/v1/me/stars/8f14e45fceea167a5a36dedd4bea2543/svg"
  }
}
```

上限升级示例：

```json
{"item_id": "diamond_cap_1", "quantity": 1, "request_id": "cap-1"}
```

购买后会扣钻石、`diamond_cap += 500`、`diamond_cap_level += 1`，并重新计算
`diamond_excess`。购买本身是消费，不受旧上限阻塞；余额不足仍然拒绝。

经验宝示例：

```json
{"item_id": "diamond_boost_25", "quantity": 1, "request_id": "boost-1"}
```

成功响应额外带当前状态：

```json
{
  "ok": true,
  "item_id": "diamond_boost_25",
  "quantity": 1,
  "diamonds": 975,
  "diamond_cap": 1000,
  "diamond_cap_level": 0,
  "diamond_excess": 0,
  "inventory": {"star": 0, "seasonal_star": 0, "ember": 0},
  "cooldown_until": null,
  "replayed": false,
  "diamond_boost": {
    "expires_at": "2026-11-02T12:25:00+08:00",
    "remaining_seconds": 1500,
    "multiplier": 2
  }
}
```

扣款、抽卡结果、星记录、物品栏、冷却、流水和 request 记录在同一个 SQLite 事务内完成。
任何一步失败都会回滚，普通星失败不会留下半颗星或半条流水。同一个 `request_id`
重放时直接返回已保存的 `star`，不会再抽一次。

错误状态：

- 未知商品：`404`。
- 数量非法、一次买多颗、普通星/季节星名字非法：`422`，`detail.code` 为
  `invalid_quantity` / `quantity_must_be_one` / `invalid_star_name`。
- 余额不足：`409`，响应顶层和 `detail` 都带当前 `balance`/`diamonds`，`detail.code`
  为 `insufficient_diamonds`。
- 同月第二颗季节星：`409`，`detail.code='seasonal_star_owned'`，带 `season_key`。
- 上限升级不是当前下一级或已经满级：`409`，`detail.code='cap_unavailable'`。
- 经验宝已下架：`409`，`detail.code='boost_inactive'`。
- 经验宝配置缺省或非法：`409`，`detail.code='boost_config_invalid'`，商品不会出现。
- `ember` 冷却未到：`409`，响应顶层和 `detail` 都带 `cooldown_until`，
  `detail.code` 为 `cooldown`。
- 同一 `request_id` 用于不同商品/数量：`409`。

`ember` 购买成功会同时写负数 `diamond_ledger` 和正数 `ember_ledger`，更新
`ember_balance`，并写 `shop_purchase_cooldowns`；它不会写 `inventory_items`。

### `GET /v1/me/stars/{star_id}/svg`

Bearer 鉴权。只允许读取自己的星；别人的星、不存在的 id 都返回 `404`，不泄露星星
是否存在。成功时返回 `image/svg+xml`（UTF-8），正文是完整 `<svg>...</svg>`，
`viewBox="0 0 512 512"`，透明背景。

- SVG 只由该星的 `star_type`、`rarity`、`palette`、`visual_seed`、
  `companion_count` 和 `catalog_code` 决定；不读用户名字，不请求外部资源，不包含
  字体、脚本或远程 URL。
- 同一颗星重复请求逐字节一致；不同 `visual_seed` 生成不同图形。
- 普通单星是核心 + 光晕 + 4/6/8 条射线；双星/三合星带 1/2 颗伴星和轨道弧线；
  中子星/脉冲星是细核心 + 双向光束；黑洞遗迹是深色核心 + 吸积环。

## 宿敌与下注

宿敌是每周一次的跨组配对，只属于真人；它不参与小组排名，也不会改变 `weekly_scores`
或升降段。周注和日注都要求本周已有宿敌；组注要求本周已有小组，但不需要宿敌。

每笔下注都由两部分组成：**押我比宿敌高多少 XP**（`target_margin`）和
**押多少钻石**（`paid_stake`，0–500 的整数）。每笔仍带 `free_stake = 20` 免费本金，
存储时 `stake = 20 + paid_stake`。下注只从 `diamond_balance` 扣除 `paid_stake`：

- 押 `0`：总本金 `20`，自付 `0`。
- 押 `80`：总本金 `100`，自付 `80`。
- 押 `500`：总本金 `520`，自付 `500`。

赢：按 **总本金 × 锁注赔率** 派彩；输：只失去 `paid_stake`；平/void：只退
`paid_stake`。所有派彩都走同一本钻石账；宿敌奖励、下注派彩属于正常游戏入账，生效中
的经验宝会按配置倍率入账，管理/测试发钻不会。

### 时间口径（Asia/Shanghai）

- 选宿敌：周一 `00:05` 开放，周一 `23:59:59` 锁定；窗口内可以改选。
- 自动选：周二 `00:00` 起，为没有宿敌的真人匹配；之后不能改选。没有合适候选时
  `rival` 为 `null`，不伪造对手。
- 周注：周一 `23:59:59` 前可下；下一个周一 `00:05` 的 `settle_week()` 结算。
- 组注：与周注同一窗口；下一个周一 `00:05` 随 `settle_week()` 结算，每真人每周
  一次，可与周注/日注同时存在。
- 日注：当天 `21:00` 前可下（`now < 21:00`），`21:00` 锁注，`22:30` 结算。
- 日注按当天 `22:30` 时的打卡 XP 差判定，不使用之后（含 23:59）的最终日 XP。

### 目标差值与赔率

服务端返回 `target_options`，前端直接展示。周注仍接受区间内任意整数；日注只接受
本次 `projection.daily_target_margins` 中的档位。越界或不在档位返回 `invalid_target`
（`422`）。

- 周注上界：`max(100, round_to_50(rival_week_estimate * 2))`，并保留旧的动态锚点：

```text
power_delta = my_power - rival_power
power_factor = clamp(0.5, 1.5, 1 + power_delta / 4000)
anchor = clamp(0, upper_bound, round_to_step(upper_bound * 0.5 * power_factor))
```

- 日注不再有“周估算摊平”或区间锚点。双方各取一条日均 XP 正态分布，再对差值
  `D = 我的 XP - 他的 XP` 取样：

```text
历史样本：只读今天之前的 checkins，窗口 28 天
         按玩家聚合 AVG(xp)，至少 3 个记录日才算一个样本
战力分段：宽度 250；本段样本不足 20 时加入相邻段；
         仍不足 20 时使用全部样本；都没有时使用中性先验 (0, 150)
分布参数：μ 为段内样本均值，σ 为样本标准差（n-1）
μD = μ我 - μ他
σD = sqrt(σ我² + σ他²)
```

  第一档固定为 `1 XP`：险胜档，即 `D > 0` 的最小差值。其余档位只落在整
  15 分钟（150 XP）边界上：`150 / 300 / 450 / 600 / …`，不会出现 `151`、`301`
  这类尾数。分位点先取 `q = 0.50, 0.60, 0.70, 0.80, 0.90`；只保留
  `raw = μD + z_q * σD > 0` 的值，按 150 XP 向上取整，去重升序。最高档仍由这些
  分位点的最大正 ceiling 决定：默认从 150 开始按 150 递增补齐到该 ceiling；若
  ceiling 高于 `600`（第 4 个 15 分钟档），则保留 `150 / 300 / 450 / 600` 和该
  ceiling，避免超过 6 档；档位不足 3 个时补到 `150 / 300`。最多 6 个，最少 3 个
  （含 `1 XP` 险胜档）。日注不返回 `0` 档，所有档位都是“我比他多”的正差值。
  同一份历史、同一天内，档位和赔率固定；
  今天的 checkins 不参与计算。

- 每个选项同时返回锁注赔率，供 UI 预览：

```json
{"margin": 150, "odds": 2.37}
```

  赔率在锁注时计算一次并写入 `bets.odds`，之后不随 XP 或历史变化。周注赔率仍用
  周估计和战力差：

```text
reference = max(500, rival_week_estimate)
power_ratio = clamp(0.5, 2.0, 1 + (rival_power - my_power) / 4000)
effective_reference = reference * power_ratio
ratio = target_margin / effective_reference
odds = clamp(1.2, 15.0, 1.2 + 0.8 * ratio ** 1.4)
```

  日注赔率按档位和 `σD` 的正态生存概率计算：

```text
z = (target_margin - μD) / σD
p = 1 - Φ(z)
odds = clamp(1.2, 15.0, 1 / p)
odds = round(odds, 2)
```

  因此日注档位越高赔率严格不降；`target_margin = μD` 时约为 `2.0`。

### `GET /v1/me/rival`

返回当前周的实时状态：

```json
{
  "server_now": "2026-11-02T12:00:00+08:00",
  "week_start": "2026-11-02",
  "selection": {
    "open": true,
    "locks_at": "2026-11-02T23:59:59+08:00",
    "auto_select_at": "2026-11-03T00:00:00+08:00",
    "mode": null
  },
  "me": {
    "user_id": "owner",
    "display_name": "You",
    "avatar_url": null,
    "group_no": 1,
    "tier": "Bronze",
    "power": 679,
    "week_xp": 150,
    "today_xp": 150
  },
  "rival": null,
  "result": null,
  "bets": {
    "weekly": null,
    "daily": null,
    "group": null,
    "groups": [
      {
        "market": "top3",
        "label": "押前三",
        "available": true,
        "can_place": true,
        "reason": null,
        "target_rank": 3,
        "promotion_quota": 4,
        "demotion_quota": 4,
        "odds": 5.13,
        "status": "open",
        "bet": null
      },
      {
        "market": "promote",
        "label": "押升段",
        "available": true,
        "can_place": true,
        "reason": null,
        "target_rank": 4,
        "promotion_quota": 4,
        "demotion_quota": 4,
        "odds": 4.19,
        "status": "open",
        "bet": null
      }
    ]
  },
  "bet_options": {
    "weekly": null,
    "daily": null,
    "group": {
      "target_rank": 3,
      "target_margin": 0,
      "min_paid_stake": 0,
      "max_paid_stake": 500,
      "free_stake": 20,
      "odds": 5.13,
      "markets": []
    }
  },
  "projection": null,
  "bet_windows": {
    "weekly_locks_at": "2026-11-02T23:59:59+08:00",
    "daily_locks_at": "2026-11-02T21:00:00+08:00",
    "daily_settles_at": "2026-11-02T22:30:00+08:00"
  }
}
```

- `selection.open` 只在周一 `00:05–23:59:59` 且没有已锁定 assignment 时为 `true`。
- `selection.mode` 为 `manual` / `auto` / `null`。
- `me` / `rival` 只含公开字段；不返回 `kind`、`is_ai`、钱包或钻石余额。
- `result` 是最近一次已结算宿敌结果（`outcome`、`my_xp`、`rival_xp`、
  `reward_diamonds`、`settled_at`），没有则为 `null`。
- `bet_options` 与 `bets` 并列，存放前端可直接渲染的下注参数。`weekly` / `daily`
  在没有宿敌时为 `null`；`group` 在没有小组时为 `null`。周注/日注对象包含
  `target_options`（每项 `margin` + 锁注赔率 `odds`；日注还带 `expected_xp`）、
  `min_target_margin`、`max_target_margin`、`min_paid_stake`、`max_paid_stake`、
  `free_stake` 和
  `reference`；日注的 `min_target_margin` 就是第一档 `1`（险胜），`reference` 是
  `μD` 的整数近似（赔率不再使用它）。日注的 `expected_xp` 是
  `round_to_10(daily_mu_rival + margin)`，即“预计宿敌日均 + 目标差值”，不是
  我的当前 XP 或实时估算；周注不返回该字段。组注对象保留旧的 `target_rank: 3`、
  `target_margin: 0` 和
  `odds`（前三盘口），并新增 `markets`；`markets` 与 `bets.groups` 是同结构、
  同顺序的可用盘口（Silver 等中间段位为三项；Bronze 不含 `no_demote`，Diamond
  不含 `promote`；示例中省略重复内容）。赔率全部由服务端计算，前端只显示。
- `projection` 只用于下注界面展示，不参与结算；没有宿敌时为 `null`。有宿敌时：

```json
{
  "rival_week_estimate": 3400,
  "weekly_target_max": 6800,
  "daily_mu_me": 620.5,
  "daily_sd_me": 180.2,
  "daily_mu_rival": 510.0,
  "daily_sd_rival": 150.0,
  "daily_mu_diff": 110.5,
  "daily_sigma_diff": 234.5,
  "daily_target_margins": [1, 150, 300, 450]
}
```

周估计：用宿敌 `power / 2000` 作百分位，取最近一个 `weeks.status='settled'` 周的
`weekly_scores.xp` 分位值，四舍五入到百位；没有已结算周时退化到宿敌本周 XP。
`weekly_target_max` 是周注上界。

日估计：`daily_mu_*` / `daily_sd_*` 是按上面“目标差值与赔率”的战力分段历史分布
算出的双方均值与样本标准差；`daily_mu_diff` / `daily_sigma_diff` 是差值的 μD/σD；
`daily_target_margins` 是当天实际可下的正档位，固定以 `1` 开头，其余为 150 的倍数。
每个档位的 `expected_xp` 由
`daily_mu_rival + margin` 四舍五入到 10 得到，表示达到该档位预计需要的总 XP。
只读今天之前的 checkins，且不读
当天实时 XP，因此同一天 `09:00` 与 `21:00` 的 `projection`、`target_options`（含
`expected_xp`）和赔率完全一致（前提是同一份历史）。

### `GET /v1/me/rival/candidates`

```json
{
  "week_start": "2026-11-02",
  "selection_open": true,
  "candidates": [
    {
      "user_id": "ch-...",
      "display_name": "AI-1234ABCD",
      "avatar_url": null,
      "group_no": 3,
      "tier": "Bronze",
      "power": 980,
      "week_xp": 760,
      "today_xp": 120
    }
  ]
}
```

候选必须 active、不是自己、与自己在不同小组、本周有 `weekly_scores` 行。默认按与
自己的战力差从小到大排序；界面可再过滤“略高于我”。每个候选只出现一次，响应不含
`kind`、`is_ai`、钱包或钻石。

### `POST /v1/me/rival/select`

```json
{"rival_id": "ch-...", "request_id": "select-20261102"}
```

- 仅周一窗口内可调用；窗口关闭或已锁定返回 `409`。
- 候选不存在（含同组、已无本周分数）返回 `404`；选择自己返回 `422`。
- 成功返回与 `GET /v1/me/rival` 相同的结构；窗口内重复调用可改选。

### `GET /v1/me/bets`

```json
{
  "server_now": "2026-11-02T12:00:00+08:00",
  "week_start": "2026-11-02",
  "day": "2026-11-02",
  "weekly": null,
  "daily": null,
  "group": null,
  "groups": [
    {
      "market": "top3",
      "label": "押前三",
      "available": true,
      "can_place": true,
      "reason": null,
      "target_rank": 3,
      "promotion_quota": 4,
      "demotion_quota": 4,
      "odds": 5.13,
      "status": "open",
      "bet": null
    },
    {
      "market": "promote",
      "label": "押升段",
      "available": true,
      "can_place": true,
      "reason": null,
      "target_rank": 4,
      "promotion_quota": 4,
      "demotion_quota": 4,
      "odds": 4.19,
      "status": "open",
      "bet": null
    }
  ],
  "bets": {"weekly": null, "daily": null, "group": null, "groups": []},
  "bet_options": {
    "weekly": null,
    "daily": null,
    "group": {
      "target_rank": 3,
      "target_margin": 0,
      "min_paid_stake": 0,
      "max_paid_stake": 500,
      "free_stake": 20,
      "odds": 5.13,
      "markets": []
    }
  },
  "bet_windows": {
    "weekly_locks_at": "2026-11-02T23:59:59+08:00",
    "daily_locks_at": "2026-11-02T21:00:00+08:00",
    "daily_settles_at": "2026-11-02T22:30:00+08:00"
  }
}
```

`weekly` / `daily` / `group` 是 `bets` 同名字段的顶层别名，二者内容一致。
`groups` 是组注的权威列表，按固定的 `top3`、`promote`、`no_demote` 顺序返回
当前段位可用的盘口：Bronze 不返回 `no_demote`，Diamond 不返回 `promote`，所以
示例（Bronze）只有两项。`bets.groups` 与它内容相同（示例为简洁写空）。
`bet_options` 与 `GET /v1/me/rival` 中的结构相同；
`bet_options.group.markets` 也与 `groups` 同结构。已下注时
`bets`/`groups[].bet` 仍返回下注本身，`groups[].odds` 返回锁注赔率；
`bet_options` 继续提供赔率/押注上下限，前端不需要自己算赔率。

每个盘口对象都带 `market`、`label`、`available`、`can_place`（未下注且可下）、
`reason`（`already_placed` / `no_group` / `null`）、
`target_rank`、`promotion_quota`、`demotion_quota`、服务端赔率 `odds`、
`status`（未下注为 `open`）和 `bet`（`null` 或下注 payload）。

每笔下注都包含 `id`、`player_id`、`kind`、`period_key`、`stake`、`free_stake`、
`paid_stake`、`target_margin`、`odds`、`status`、`payout`；周注/日注另含
`rival_id` 和 `result_diff`，组注另含 `market`、`group_id`、`target_rank`、
`group_size`、`promotion_quota`、`demotion_quota` 和结算后的 `group_rank`。

### `POST /v1/me/bets`

所有下注的请求体只接受 `paid_stake`（0–500 整数），旧的 `stake` 字段不再作为输入。
`stake = 20 + paid_stake`，`free_stake = 20`，`paid_stake` 原样保存；下注只扣
`paid_stake`。周注必须带周注区间内的 `target_margin`；日注必须带本次 projection
`daily_target_margins` 中的一个档位；两者都不接受 `market`。组注不带
`target_margin`，`market` 缺省为 `top3`。

周注：

```json
{"kind": "weekly", "target_margin": 120, "paid_stake": 80, "request_id": "weekly-20261102"}
```

- 目标范围见上文“目标差值与赔率”；`target_margin` 是“我本周最终 XP 比宿敌高多少”。
- 锁注时计算并固定 `odds`。结算：`my_week_xp - rival_week_xp >= target_margin` 为赢，
  按 `stake * odds` 派彩；实际打平（差值为 0）且未达成目标为 `void`，只退
  `paid_stake`；其余为输，失去 `paid_stake`。
- 周一 `23:59:59` 前可下；下一个周一 `00:05` 随 `settle_week()` 结算。

日注：

```json
{"kind": "daily", "target_margin": 1, "paid_stake": 80, "request_id": "daily-20261102"}
```

- `target_margin` 是“我当天 `22:30` 的打卡 XP 比宿敌高多少”，只能选当天
  `projection.daily_target_margins` 中的正档位；第一档 `1` 是险胜档，也是前端默认
  选中的档位；其余档位都是 150 的倍数。赔率随档位和 `σD` 固定不变。
- 判定与周注一致；结算使用当天 `22:30` 的打卡 XP，不使用之后的最终日 XP。
- 当天 `21:00` 前可下，`21:00` 锁注，`22:30` 结算。

组注：

```json
{"kind": "group", "market": "promote", "paid_stake": 100, "request_id": "group-promote-20261102"}
```

三个独立盘口，同一真人同一周最多三笔，一笔一个盘口，可分别下注：

| `market` | 赢的条件 |
| --- | --- |
| `top3` | 本人组内最终排名 ≤ 3 |
| `promote` | 本人组内最终排名 ≤ `max(1, (group_size * 3) // 10)`，且当前段位不是 Diamond |
| `no_demote` | 本人组内最终排名 ≤ `group_size - max(1, (group_size * 3) // 10)`，且当前段位不是 Bronze |

- 要求本周已有小组；与周注/日注可同时存在，每个盘口独立扣款、独立赔率、独立结算。
- 赔率由服务端按组大小、当前组内排名/XP 缓冲和盘口门槛确定性计算，不使用随机数；
  难度/赔率固定为 `top3 > promote > no_demote`，前端只显示 `odds`。
- Bronze 不下发 `no_demote`，Diamond 不下发 `promote`；强行提交返回 `422`
  `market_unavailable`，不写库、不扣款。
- 组内排名按本周 `weekly_scores.xp` 降序，同分按 `player_id` 升序；组总 XP 不参与判定。
- 结算：三个盘口分别按最终组内排名判胜负，未命中 `lost`，赢按各自
  `stake * odds` 派彩；缺小组、段位或个人本周分数为 `void`，只退该笔
  `paid_stake`。结算写回实际 `group_rank`，重复结算不重复打款。
- 数据库唯一键是 `(player_id, week_start, market)`；旧数据迁移为 `top3`。
  `request_id` 幂等键包含 `market`：同一盘口重复 `request_id` 返回原下注，
  同一盘口换 `request_id` 返回 `409`，不同盘口可复用同一个 `request_id`。

- 周注每周、日注每天只能一笔；组注每个盘口每周一笔。重复 `request_id` 返回原下注，
  不重复扣款。
- 成功返回 `{"bet": {...}, "state": {...}}`，`state` 与 `GET /v1/me/rival` 同结构。

宿敌周结算：比较本周最终 `weekly_scores.xp`；真人赢 `+120` 钻石，平 `+40`，输 `0`。
宿敌、周注、组注都随下一次 `settle_week()` 执行，幂等，重复结算不会重复发钱；
组注在下一个周一 `00:05` 的结算窗口写入 `group_rank`。

### 下注错误

- `409`：选择/下注窗口关闭、本周/当天/同一组注盘口已下注、没有宿敌、钻石不足。
- `404`：候选不存在。
- `422`：`paid_stake`、`target_margin`、`market` 或请求体不合法；目标超出区间；
  组注时本周还没有分组；`market` 不属于 `top3`/`promote`/`no_demote`；
  Bronze 提交 `no_demote` 或 Diamond 提交 `promote`（`market_unavailable`）。
- `401`：缺少或错误的 Bearer token。

钻石软上限不拒绝下注；扣款后余额可以高于上限，超出部分继续按每小时 1% 复利衰减。


## 登录态用户详情与社交

### `GET /v1/users/{user_id}`

需要普通账号 Bearer token。返回本地账号或 Channel player 的公开卡片，并附带
“我与目标”的本周对比。公开响应**不包含** `kind`、`is_ai`、`origin`、`synthetic`、
钻石、钱包、下注、私有库存或原始秒数。顶层字段包括 `user_id`、`handle`、
`display_name`、`avatar_url`、`activity_label`、`tier`、`group_id`、`week_start`、
`xp`、`power`、`rank`、`group_size`、`checkin`、`streak`、`equipped_title`、`frame`、
`backdrop`、`badge_accent`、`is_following`、`followers_count`、`following_count` 和
`comparison`。未知 user_id 返回 `404`；无 token 返回 `401`。

`handle` 只对本地人类账号返回其 `user_id`；Channel/AI 玩家返回 `null`，前端不得把
随机 `ch-...` 标识当作 handle 展示。`power` 是公开的当前战力，没有可用周数据时为
`null`。

`comparison` 在查看自己时为 `null`（前端不渲染“我和我对比”），查看他人时稳定返回：

```json
{
  "viewer_id": "owner",
  "target_id": "friend-1",
  "viewer_xp": 100,
  "target_xp": 300,
  "viewer_rank": 7,
  "target_rank": 2,
  "viewer_group_size": 15,
  "target_group_size": 15,
  "xp_diff": -200,
  "leader": "them"
}
```

`xp_diff = viewer_xp - target_xp`，正数表示我领先；`leader` 只有 `me` / `them` /
`tie`。任一方本周没有小组数据时，对应 `*_rank` 为 `null`、`*_group_size` 为 `0`，
对比仍按本周 XP 返回，不伪造名次。

### 关注与发现

- `POST /v1/me/follows/{user_id}`：幂等关注；不能关注自己（`422`），未知用户 `404`。
- `DELETE /v1/me/follows/{user_id}`：幂等取消，成功返回 `204`。
- `GET /v1/me/follows`、`GET /v1/me/followers`：返回用户卡片数组。
- `GET /v1/me/friends/standings`：返回 `{week_start, members}`，成员按 XP 降序；
  每个成员带公开的 `power` 与 `handle`（人类账号为 `user_id`，AI/Channel 为 `null`）。
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
| `404` | 资源/用户/webhook/feed 事件不存在、Channel roster 未声明该 player、宿敌候选不存在 |
| `409` | 幂等键或 `event_id` 被另一个目标占用；宿敌/下注窗口关闭、已下注、无宿敌、钻石不足 |
| `413` | 头像超过 2MB |
| `415` | 头像不是 PNG / JPEG / WebP |
| `422` | 请求体校验失败、未来时间、资料名不合法、宿敌/下注参数或业务规则拒绝 |

## 边界

- 没有全员列表、没有通用跨组查询、没有账号管理 HTTP 接口；管理走 CLI。宿敌候选是
  唯一按跨组规则返回的受限列表，且只含公开字段。
- `/v1/league/standings` 只暴露自己的小组。
- 不暴露未来周或内部投影参数。
- `GET /health` 与 `GET /avatars/{user_id}` 无鉴权；生产环境只应通过 HTTPS 反向代理暴露。
