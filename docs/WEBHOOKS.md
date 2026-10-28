# Ghost League Webhooks v1

Webhook 订阅保存在本地 SQLite（默认 `data/api/webhooks.db`，权限 `600`）。HTTP API
与 CLI 直接读写同一数据库；启用 API 时后台 worker 会投递 outbox，服务重启后会继续
处理未完成投递。每个订阅有 `transport` 字段：`generic`（默认，签名 JSON webhook）
或 `event_injector`（本地文本事件）。

## 边界与 URL 规则

正常 API / CLI（无 `--force`）：

- 只接受 `https://`。
- hostname 必须是带点的域名。
- 拒绝 IPv4 / IPv6 字面量、`localhost`。
- **不做 DNS 解析、私网/CIDR 检查、allowlist、DNS rebinding 防护。**

需要投递到本地或内网地址时，只能在部署机器上用 root CLI 加 `--force`：

```bash
python -m ghost_league.webhooks set \
  --user-id owner-user \
  --url http://127.0.0.1:19000/hook \
  --events checkin.completed \
  --force
```

`--force` 允许 HTTP 和内网 IP，但仍要求 URL 使用 `http`/`https` 且包含 host。
它不会解析 DNS，也不提供 SSRF 白名单机制。生产部署应把真实目标地址放在本地配置
或环境变量中，不要提交到仓库。

## 事件

所有事件的包络：

```json
{
  "id": "checkin:owner-user:2026-10-26",
  "type": "checkin.completed",
  "version": 1,
  "occurred_at": "2026-10-26T18:42:15+08:00",
  "data": {
    "date": "2026-10-26",
    "today_seconds": 600,
    "current_streak": 1,
    "week_start": "2026-10-26",
    "activity_label": "骑行"
  }
}
```

`data` 里的字段仍是秒，和 API/数据库一致。事件类型和触发条件：

- `checkin.completed`：该用户当天首次达到 600 秒时产生一次；同一自然日不重复。
- `streak.milestone`：打卡完成后，当天连续打卡天数正好是 `3 / 7 / 14 / 30 /
  60 / 100` 之一。同一用户同一天同一里程碑只产生一次；事件 `data` 含
  `milestone`、`date` 和 `current_streak`。
- `streak.broken`：用户再次打卡时，上一次打卡日期早于“昨天”。事件 `data`
  含 `previous_last_checkin_date`、`gap_days` 和 `date`；`gap_days` 是两次
  打卡日期之间的自然日差。
- `rank.top3`：一次真实增量后，组内排名从 `> 3` 进入 `<= 3`。事件 `data` 含
  `previous_rank`、`rank`、`group_size` 和 `week_start`。
- `rank.bottom3`：一次真实增量后，组内排名从 `<= group_size - 3` 进入
  `> group_size - 3`。字段同 `rank.top3`。
- `webhook.test`：`POST /v1/me/webhooks/{id}/test` 立即生成并投递。

排行榜事件只在未重复的真实增量后比较记录前后的排名；`duplicate` 增量不会产生
任何新事件，也不会重复已有事件。所有事件的 `event_id` 都由用户、日期/周、类型
和关键值组成，不含随机 UUID，因此 outbox 重试和重复写入保持幂等。

活动增量写入成功后，只把对应 delivery 写入 outbox；实际 HTTP 由后台 worker
发送，不在增量请求线程里同步发网络请求。事件生成本身失败会被隔离，不影响增量
写入或 `checkin.completed` 的独立投递。

## API

所有 `/v1/me/webhooks` 接口需要 Bearer token，只能操作自己的订阅。secret 只在
创建响应中出现一次，之后 GET/PATCH 响应不会包含 secret。

### `POST /v1/me/webhooks`

```json
{
  "url": "https://hooks.example.com/ghost",
  "events": ["checkin.completed"],
  "transport": "generic"
}
```

响应：

```json
{
  "id": 1,
  "user_id": "owner-user",
  "url": "https://hooks.example.com/ghost",
  "events": ["checkin.completed"],
  "transport": "generic",
  "active": true,
  "created_at": "2026-10-26T18:36:00+08:00",
  "updated_at": "2026-10-26T18:36:00+08:00",
  "last_status": null,
  "last_attempt_at": null,
  "last_success_at": null,
  "failure_count": 0,
  "latest_delivery": null,
  "secret": "whsec_...一次性返回..."
}
```

### `GET /v1/me/webhooks`

返回自定义订阅数组，不包含 `secret`。每项包含最近投递摘要：

```json
[
  {
    "id": 1,
    "user_id": "owner-user",
    "url": "https://hooks.example.com/ghost",
    "events": ["checkin.completed"],
    "transport": "generic",
    "active": true,
    "last_status": "delivered",
    "last_attempt_at": "2026-10-26T18:42:16+08:00",
    "last_success_at": "2026-10-26T18:42:16+08:00",
    "failure_count": 0,
    "latest_delivery": {
      "id": 3,
      "event_id": "checkin:owner-user:2026-10-26",
      "event_type": "checkin.completed",
      "status": "delivered",
      "attempts": 1,
      "last_error": null,
      "created_at": "2026-10-26T18:42:15+08:00",
      "delivered_at": "2026-10-26T18:42:16+08:00"
    }
  }
]
```

### `PATCH /v1/me/webhooks/{id}`

可传 `url`、`events`、`active`、`transport` 中的任意字段。`transport` 只能是
`generic`（默认）或 `event_injector`。改 `url` 时同样走正常域名校验。

### `DELETE /v1/me/webhooks/{id}`

成功返回 `204`，并级联删除该 webhook 的 deliveries。

### `POST /v1/me/webhooks/{id}/test`

立即创建一个 `webhook.test` delivery 并同步尝试一次，返回：

```json
{
  "delivery_id": 4,
  "status": "delivered",
  "attempts": 1,
  "last_error": null
}
```

### 错误码

| 状态码 | 含义 |
| --- | --- |
| `401` | token 缺失或错误 |
| `404` | webhook 不存在或不属于当前用户 |
| `422` | URL / events / transport / 字段不合法 |

secret 不会出现在错误响应里。

## 投递签名

每次投递的原始 body 是紧凑 JSON，只序列化一次。请求头包含 Ghost League 签名和
兼容接收端使用的 V2 签名：

```text
X-Ghost-Event-Id: checkin:owner-user:2026-10-26
X-Ghost-Timestamp: 1793011335
X-Ghost-Signature: v1=<hex>
X-Webhook-Timestamp: 1793011335
X-Webhook-Signature-V2: <hex>
```

签名算法：

```text
X-Ghost-Signature: v1=HMAC-SHA256(secret, timestamp + "." + raw_body)
X-Webhook-Signature-V2: HMAC-SHA256(secret, timestamp + "." + raw_body)
```

V2 头只放 hex，不带 `v1=` 前缀；同一次投递复用同一个整数 Unix 秒时间戳。
每次重试会生成新的时间戳并重新签名。

Python 校验示例：

```python
import hashlib
import hmac

def verify_v1(secret: str, timestamp: str, raw_body: bytes, header: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(header, f"v1={expected}")

def verify_v2(secret: str, timestamp: str, raw_body: bytes, header: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(header, expected)
```

2xx 视为成功。不要只校验签名后读取解析后的 JSON；必须使用收到的原始 body
字节计算 HMAC。

## event-injector 传输

`transport` 默认是 `generic`。设为 `event_injector` 后，投递目标改为本地事件
接收器：

- 地址示例：`http://127.0.0.1:19000/inject`（本地 HTTP/IP 目标需 CLI `--force`）。
- 请求头带 `X-Event-Token: <webhook.secret>`，不发送 `X-Ghost-*`，也不发送
  `X-Webhook-Signature-V2` / `X-Webhook-Timestamp`。
- 请求体只有两个字段：`{"content": "...", "role": "user"}`，其中 `content`
  只说明“系统有一个变化”，不携带完整明细；接收方应自行查询当前状态。

```text
【Ghost League】检测到系统事件：打卡完成（checkin.completed）。
事件时间：2026-10-26T18:42:15+08:00。
这里只有变化提示，不是完整数据。请查询当前状态，判断这个变化是否值得告诉用户。
```

事件文本不预先计算今日/本周时长、排名或连胜，也不把完整 JSON 包络塞进
`content`。接收方按需查询 API，避免事件端和状态端各算一套。

```bash
python -m ghost_league.webhooks set \
  --user-id owner-user \
  --url http://127.0.0.1:19000/inject \
  --events checkin.completed \
  --transport event_injector \
  --force
```

创建后 CLI 打印的 secret 必须与本地接收器服务端 token 一致；token 只放在本地
数据库或服务端 secret 配置里，不要写进仓库、文档或命令行历史。成功仍按 2xx
判定，失败进入与 generic 相同的 outbox 重试和 `last_status` / `failure_count`
记录。

普通 HTTP API 仍只接受 `https://` + 域名，因此本地 HTTP 目标要用上面的 CLI
`--force` 创建。

## 重试语义

- 首次投递失败后最多重试 3 次，间隔依次为 `1m / 5m / 30m`。
- 每次重试都会生成新的整数时间戳并重新计算两种签名。
- 因此最多 4 次 HTTP 尝试（首次 + 3 次重试）。
- 所有尝试失败后 delivery 状态变为 `failed`，不再自动重试。
- `last_status` 可能是 `retrying`、`delivered`、`failed`。
- 单机 SQLite outbox；进程重启后 pending delivery 会继续被处理。
- 网络错误、超时、非 2xx 都会记录为失败，错误文本会截断，不保存 secret。

## CLI

```bash
# 创建；secret 只在这里打印一次
python -m ghost_league.webhooks set \
  --user-id owner-user \
  --url https://hooks.example.com/ghost \
  --events checkin.completed

# 创建本地文本事件传输（本地 HTTP 目标必须用 --force）
python -m ghost_league.webhooks set \
  --user-id owner-user \
  --url http://127.0.0.1:19000/inject \
  --events checkin.completed \
  --transport event_injector \
  --force

# 只显示 id / url / events / transport / active / 最近状态，不显示 secret
python -m ghost_league.webhooks list --user-id owner-user

# 轮换 secret；新 secret 只打印一次
python -m ghost_league.webhooks rotate-secret \
  --user-id owner-user \
  --webhook-id 1
```

默认数据库是 `data/api/webhooks.db`，也可用环境变量
`GHOST_LEAGUE_WEBHOOKS_DB` 或全局 CLI 参数 `--db` 指定临时/测试库。

## 数据表

`webhooks`：`id, user_id, url, secret, events, transport, active, created_at,
updated_at, last_status, last_attempt_at, last_success_at, failure_count`。
`transport` 的旧库迁移默认值是 `generic`。

`webhook_deliveries`：`id, webhook_id, event_id, event_type, payload, status,
attempts, last_error, created_at, delivered_at`，另有内部 `next_attempt_at`
用于退避调度；`(webhook_id, event_id)` 唯一，避免同一事件重复入 outbox。

secret 只存在 `600` 权限的本地 SQLite 中，不写入日志或 GET 响应。
