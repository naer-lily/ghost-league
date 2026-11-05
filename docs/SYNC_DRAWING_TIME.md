# 把绘画时间同步到 Ghost League

**适用对象**：绘画软件、计时器或桌面小工具的开发者/配置者。\
**目标**：每三分钟把当前这段绘画时间增量送到 Ghost League，让本周累计、排名、每日打卡和连胜自动更新。\
**API 版本**：2026-10-26 当前部署。

---

## 1. 先明确三件事

1. **发送的是增量，不是累计。**\
   每次只发“刚刚这段画了多久”，例如 137 秒。不要每次把今天的总秒数重发一遍。

2. **服务不限制 180 秒。**\
   你的软件习惯三分钟发一次没问题；某次延迟到 5 分钟、一次发 300 秒也可以。服务只要求 `seconds` 是正整数。

3. **同一条事件必须带同一个 `event_id`。**\
   网络失败、超时、重试都复用原 `event_id`；服务端会幂等去重，不会重复加时间。

---

## 2. 接口地址与认证

绘画客户端走 WireGuard 内网的 HTTP API：

```text
http://<ghost-host>:8095
```

PWA（网页/手机）走同一个后端的 HTTPS 入口：

```text
https://<ghost-host>:8445
```

把 `<ghost-host>` 换成管理员提供的内网主机名或 IP。\
本文的绘画同步示例使用 `8095`。\
所有 `/v1/...` 请求都要带：

```http
Authorization: Bearer <你的个人 token>
Content-Type: application/json
```

token 由管理员通过安全渠道提供；不要把它写进仓库、截图或聊天记录。

只把 token 放在你自己的绘图软件配置或系统环境变量里；不要写进代码仓库、截图或聊天记录。怀疑泄漏时，让管理员执行 `python -m ghost_league.accounts rotate --user-id <你的 user_id>`，旧 token 会立即失效。

---

## 3. 核心接口：上报绘画增量

### `POST /v1/me/drawing-increments`

请求体：

```json
{
  "event_id": "draw-20261026-183600-a1b2c3",
  "seconds": 137,
  "occurred_at": "2026-10-26T18:36:00+08:00"
}
```

字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `event_id` | 是 | 本次增量的唯一 id；重试必须复用同一个 |
| `seconds` | 是 | 本次增量秒数，正整数；不设 180 秒上限 |
| `occurred_at` | 否 | 这段绘画实际发生的时间；省略则用服务器当前时间；不能是未来时间 |

成功响应：

```json
{
  "accepted": true,
  "duplicate": false,
  "week_start": "2026-10-26",
  "week_total_seconds": 1234,
  "event_id": "draw-20261026-183600-a1b2c3"
}
```

重试同一条事件：

```json
{
  "accepted": true,
  "duplicate": true,
  "week_start": "2026-10-26",
  "week_total_seconds": 1234,
  "event_id": "draw-20261026-183600-a1b2c3"
}
```

`duplicate: true` 表示服务端已经收过这条，周累计没有再次增加。

### 时间与周边界

- 所有统计按 `Asia/Shanghai`。
- 每周从周一 00:00 开始，到周日 23:59:59 结束。
- 如果你在周一 00:05 才把周日 23:58 的事件补发上来，带上真实的 `occurred_at` 就会记到上一周；不带则按服务器收到时间记到新周。
- 不要发送未来时间。

---

## 4. 客户端计时逻辑

推荐状态机：

```text
绘画软件处于前台 且 用户正在操作
        ↓
开始计时
        ↓
每 3 分钟结算一次
        ↓
seconds = 这段实际绘画秒数
        ↓
生成 event_id（如果这段还没有 id）
        ↓
POST /v1/me/drawing-increments
        ↓
成功：清零本段，继续下一段
失败：保留本段和 event_id，退避重试
```

规则：

1. **暂停、切走、长时间无操作时不累计。**\
   不要把挂机时间算进去；也不要为了凑时间伪造活动。

2. **重启后未发送的段要补发。**\
   本地队列里保存 `event_id + seconds + occurred_at`，重启后继续发送。

3. **不要用“当前总时长”覆盖。**\
   这个接口是追加式；服务端不做“设置为 X 秒”的操作。

4. **事件 id 在本地生成后固定。**\
   推荐 `draw-<uuid>` 或 `draw-<日期>-<序号>-<随机串>`；不要每次重试换新 id。

5. **网络失败不要丢数据。**\
   指数退避重试；超过一定次数可以先落本地队列，下一次启动继续。

---

## 5. 最小可运行示例

### curl

```bash
export GHOST_LEAGUE_TOKEN="${GHOST_LEAGUE_TOKEN:?set your token}"
export GHOST_LEAGUE_API_URL="${GHOST_LEAGUE_API_URL:?set your API URL, e.g. http://<ghost-host>:8095}"

curl -sS -X POST "$GHOST_LEAGUE_API_URL/v1/me/drawing-increments" \
  -H "Authorization: Bearer $GHOST_LEAGUE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "draw-demo-001",
    "seconds": 137,
    "occurred_at": "2026-10-26T18:36:00+08:00"
  }'
```

### Python

```python
import os
import time
import uuid
import requests
from datetime import datetime, timezone, timedelta

API = os.environ["GHOST_LEAGUE_API_URL"]  # 例如 http://<ghost-host>:8095
TOKEN = os.environ["GHOST_LEAGUE_TOKEN"]  # 不要把 token 写死在源码里
TZ = timezone(timedelta(hours=8))

def send_increment(seconds: int, occurred_at: datetime | None = None,
                   event_id: str | None = None) -> dict:
    """发送一段绘画增量；失败时用同一个 event_id 重试。"""
    event_id = event_id or f"draw-{uuid.uuid4().hex}"
    payload = {"event_id": event_id, "seconds": int(seconds)}
    if occurred_at is not None:
        payload["occurred_at"] = occurred_at.astimezone(TZ).isoformat()

    last_error = None
    for attempt in range(5):
        try:
            r = requests.post(
                f"{API}/v1/me/drawing-increments",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10,
            )
            if r.status_code == 200:
                return r.json()
            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(2 ** attempt)
    raise RuntimeError(f"发送失败: {last_error}; event_id={event_id}")

# 每三分钟调用一次；这里只演示一次 137 秒
print(send_increment(137, datetime.now(TZ)))
```

### 离线队列伪代码

```text
pending = load_pending()          # [{event_id, seconds, occurred_at}]
for item in pending:
    try:
        send(item)                # 复用 item.event_id
        remove(item)
    except:
        save_pending(pending)
        break
```

---

## 6. 查询今天的打卡和连胜

### `GET /v1/me/streak`

先按第 5 节导出 `GHOST_LEAGUE_TOKEN` 和 `GHOST_LEAGUE_API_URL`：

```bash
curl -sS "$GHOST_LEAGUE_API_URL/v1/me/streak" \
  -H "Authorization: Bearer $GHOST_LEAGUE_TOKEN"
```

响应：

```json
{
  "today_seconds": 137,
  "required_seconds": 600,
  "checked_in_today": false,
  "current_streak": 3,
  "longest_streak": 7,
  "last_checkin_date": "2026-10-25",
  "next_checkin_at": "2026-10-27T00:00:00+08:00"
}
```

规则：

- 当天累计达到 **600 秒**，算当天打卡成功。
- 今天还没打满，但昨天打满了，当前连胜暂时保留；今天结束仍不满才断。
- 没有补签、冻结或道具。

### `GET /v1/me/status`

给定时任务/助理轮询用：

```json
{
  "user_id": "current-user",
  "display_name": "You",
  "tier": "Bronze",
  "group_id": "Bronze-W53-G01",
  "week_total_seconds": 1234,
  "today_seconds": 137,
  "required_seconds": 600,
  "checked_in_today": false,
  "current_streak": 3,
  "longest_streak": 7,
  "rank": 8,
  "group_size": 15,
  "last_event_at": "2026-10-26T18:36:00+08:00",
  "last_event_id": "draw-...",
  "updated_at": "2026-10-26T18:42:15+08:00",
  "version": 42
}
```

轮询时比较 `version` 或 `updated_at`，只在变化时处理；不要每秒请求。

---

## 7. 常见错误

| HTTP | 原因 | 处理 |
| --- | --- | --- |
| 401 | token 缺失/错误 | 检查 Authorization，不要继续重试到死 |
| 422 | `seconds` 不是正整数、event_id 为空、occurred_at 在未来 | 修正请求；不要换 event_id 掩盖 |
| 404 | 路径错误 | 检查 `/v1/me/drawing-increments` |
| 5xx / 超时 | 服务临时故障 | 用同一个 event_id 指数退避重试 |
| 200 + duplicate=true | 这条已经收过 | 当作成功，不要再加时间 |

---

## 8. 验收清单

1. 发 137 秒 → 返回 200，`week_total_seconds` 增加 137。
2. 同一条 `event_id` 再发 → `duplicate=true`，累计不增加。
3. 发 600 秒 → `GET /v1/me/streak` 的 `checked_in_today=true`，`current_streak` 增加。
4. 断网后再发 → 队列保留同一条 event_id，恢复后只加一次。
5. 看 PWA 或 `GET /v1/league/standings`，自己的秒数/名次更新；幽灵按整点更新。
6. 周日夜/周一凌晨跨周 → 用 `occurred_at` 验证归周正确。

---

## 9. 安全边界

- API 只绑定 WireGuard 内网，不要转发到公网。
- token 只存本地配置/环境变量；不要写进前端 JS、Git 或日志。
- 一个账号一个 token；不要和朋友共用 token。
- 绘画软件只调用 `POST /v1/me/drawing-increments` 和 `GET /v1/me/streak/status` 即可；不需要管理接口。
- 测试会增加真实周累计；如果要空跑，使用测试账号或接受少量测试秒数。
