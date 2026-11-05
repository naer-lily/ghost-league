# Ghost League 部署模板

Ghost League 的定时任务已经收进 API 进程。FastAPI lifespan 启动
`ghost_league.game.scheduler.GhostScheduler`，先做一次 catch-up，之后每 20 秒检查
到期任务；任务运行记录保存在游戏库的 `job_runs` 表，用 `(name, period_key)` 唯一键
和租约保证多个进程不会重复执行同一周期。

因此：

- 不再安装任何 `ghost-league-*.timer`。
- Ghost 侧只有 API/PWA 两个常驻服务。
- Waka 的 XP 传输和缓存刷新是 `ai_channel` 的独立 systemd timer：
  `ai-channel-waka.timer` 每小时 `:01` 触发 oneshot `ai-channel-waka.service`，
  `ai-channel-fetch.timer` 每周一 `00:02` 刷新缓存；两者都不是 Ghost 任务。
- `ai-channel-waka.service` 是 oneshot，不是常驻进程；`ai-channel.service` 是独立的
  idle 通用 `sim-` 常驻循环，不承载 Waka。见 `ai_channel/README.md`。
- Ghost 不依赖外部 cron、systemd timer 或 ifrule；Waka timer 属于 `ai_channel` 部署。
- 仓库只保留 API/PWA 部署模板：`deploy/ghost-league-api.service`、
  `deploy/ghost-league-web.service`；`ai_channel` 的通用常驻模板在
  `ai_channel/deploy/ai-channel.service`。

## 调度任务

所有时间都是 `Asia/Shanghai` 本地时间。

| 任务 | 时间 | 说明 |
| --- | --- | --- |
| `power` | 每小时第 5 分钟 | 从 `weekly_scores` 重算展示战力，不写周历史 |
| `diamond-decay` | 每小时第 10 分钟 | 钻石软上限衰减；重复执行不会多扣 |
| `weekly-settle` | 周一 00:05 | 结算上一个本地周；本周内未完成可补跑 |
| `rival-auto` | 周二 00:00 | 为没有宿敌的真人自动匹配；本周内可补跑 |
| `daily-bets` | 每天 10:30 | 结算当天日注；09:00 锁注，之后拒绝新日注 |

Waka/source 任务已移出 Ghost 调度器：`waka-tick`、`waka-roster`、`source-fetch`
不再注册，`runtime_jobs.py` 也不 import Channel/provider。历史 `job_runs` 行保留。
Waka 缓存/投影与 `ch-` 账号的 XP 传输由独立 `ai_channel` 负责
（见 `ai_channel/README.md`），不是 Ghost 后台任务。

## Waka 传输 timer

Waka cutover 已于 2026-11-05 ~15:41 CST 在 live 执行，切流前备份在
`/data/backups/ghost-league/pre-waka-cutover-20261105T154101`。生产链路是
`ai_channel` 的两个 timer 加一个 idle 通用服务：

- `ai-channel-waka.timer`：`OnCalendar=*-*-* *:01:00`，每小时 `:01` 触发 oneshot
  `ai-channel-waka.service`，运行 `ai_channel tick --source waka`，读取
  `data/cache/cn-978.json`，把 `player_ref` 映射到已有 `ch-` 普通账号并调用
  `/v1/me/increments`。
- `ai-channel-fetch.timer`：`OnCalendar=Mon *-*-* 00:02:00`，每周一 `00:02` 触发
  oneshot `ai-channel-fetch.service`，运行 `scripts/source_fetch.py` 刷新同一缓存；
  只写缓存，不写游戏库。
- `ai-channel-waka.service` 是 `Type=oneshot`，不是常驻进程。
- `ai-channel.service` 是 `Type=simple` 的 `serve --prefix sim-` 通用常驻循环，
  active 但当前 0 个 `sim-` 账号（日志 `accounts=0`，不发起 HTTP 请求）；它不是
  Waka tick，也不加载 `ch-` token。

两个 timer 都设置 `Persistent=true`。Ghost 调度器只保留通用游戏任务，不注册
Waka/source 任务；历史 `job_runs` 和已有 Waka `channel_events` 行保留。新 XP 写
`activity_events`，每日 resolver 仍取两者较大值，所以前端 XP 不变。

启动 catch-up 的行为：

- 周一 00:06 启动：补跑 `weekly-settle`、`power`、`diamond-decay`（各自按最近到期周期）。
- 周二 01:00 启动：补跑 `rival-auto`，以及当周仍未完成的其它周期。
- 每天 10:31 启动：补跑当天 `daily-bets`。
- 09:30 启动：不会提前结算当天日注；09:00 后下注接口已经拒绝。
- 周三启动：未完成的 `weekly-settle` 仍会补跑。

每个任务本身都可重复调用：重复发钱、重复写结算、重复 tick 都由业务层的幂等键和
`job_runs` 唯一键挡住。租约默认 30 秒，运行中的任务每 10 秒续租；进程崩溃后心跳停止，
租约过期即可由后续 tick 重新认领。已成功的周期永久跳过。任务异常只记录日志，不会让
API 退出。

## 环境变量

Ghost 调度器只跑通用游戏任务，不再需要为后台任务配置 Channel/provider 凭据。
API/PWA 仍用 `GHOST_LEAGUE_CHANNEL_TOKEN` 验证外部 Channel ingest 请求（如果还有
Channel 使用该接口）；它不用于 Waka 的 account-backed XP 路径。

生产模板从 0600 的 EnvironmentFile 读取：

- API：`/etc/ghost-league/api.env`
- PWA：`/etc/ghost-league/web.env`

多进程同时运行调度器是安全的；租约保证同一周期只有一个进程真正执行。

游戏数据库默认位于 `/srv/ghost-league/data/league/league.db`。Waka 缓存
`data/cache/cn-978.json` 由 `ai-channel-fetch.timer` 每周一 `00:02` 通过
`scripts/source_fetch.py` 刷新，也可手动显式刷新；它只写缓存，不会把榜单行写进
`league.db`。

## 安装 API/PWA 服务

```bash
sudo install -d -m 0700 /etc/ghost-league
sudo install -m 0600 /dev/null /etc/ghost-league/api.env
sudo install -m 0600 /dev/null /etc/ghost-league/web.env
# 编辑两个文件，至少写入：
#   GHOST_LEAGUE_TOKEN=<owner-token>              # 按现有 API 部署模板要求
#   GHOST_LEAGUE_CHANNEL_TOKEN=<channel-token>    # 仅在还有外部 Channel ingest 时需要
#   GHOST_LEAGUE_PROVISIONING_TOKEN=<token>       # 如需 provisioning API

sudo install -m 0644 deploy/ghost-league-api.service \
  /etc/systemd/system/ghost-league-api.service
sudo install -m 0644 deploy/ghost-league-web.service \
  /etc/systemd/system/ghost-league-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now ghost-league-api.service ghost-league-web.service
```

如果主机上安装过旧的任务 timer，先删除它们再启动服务：

```bash
sudo systemctl disable --now \
  ghost-league-source-fetch.timer \
  ghost-league-waka-roster.timer \
  ghost-league-settle.timer \
  ghost-league-rival-auto.timer \
  ghost-league-daily-bets.timer \
  ghost-league-waka-tick.timer \
  ghost-league-power.timer
sudo rm -f /etc/systemd/system/ghost-league-source-fetch.timer \
  /etc/systemd/system/ghost-league-waka-roster.timer \
  /etc/systemd/system/ghost-league-settle.timer \
  /etc/systemd/system/ghost-league-rival-auto.timer \
  /etc/systemd/system/ghost-league-daily-bets.timer \
  /etc/systemd/system/ghost-league-waka-tick.timer \
  /etc/systemd/system/ghost-league-power.timer
sudo systemctl daemon-reload
```

## 检查

```bash
systemctl status ghost-league-api.service ghost-league-web.service
# 调度器启动/catch-up/任务失败日志都在 API/PWA journal 里
journalctl -u ghost-league-api.service -u ghost-league-web.service -f
```

Waka 传输不在 Ghost 服务里，检查 `ai_channel` 的 timer 和 oneshot：

```bash
systemctl status ai-channel.service ai-channel-waka.timer ai-channel-fetch.timer
systemctl list-timers ai-channel-waka.timer ai-channel-fetch.timer
journalctl -u ai-channel-waka.service -u ai-channel-fetch.service -n 50 --no-pager
```

查看运行记录（只读）：

```bash
sqlite3 /srv/ghost-league/data/league/league.db \
  "SELECT name, period_key, status, attempts, started_at, finished_at
   FROM job_runs ORDER BY started_at DESC LIMIT 20;"
```

## 手工运行

游戏任务仍保留 CLI，可用于本地排查；生产环境不需要手工配置定时器：

```bash
cd /srv/ghost-league
python3 -m ghost_league.game.jobs settle
python3 -m ghost_league.game.jobs rival-auto
python3 -m ghost_league.game.jobs daily-bets
```

Waka 缓存和 XP 由 `ai_channel` 的 timer 自动执行；以下命令只用于手动排查或补跑：

```bash
cd /opt/ghost-league
export PYTHONPATH=/opt/ghost-league:/opt/ghost-league/ai_channel
# 可选：只刷新缓存，不写游戏库
python3 scripts/source_fetch.py --out data/cache/cn-978.json --country CN
python3 scripts/source_fetch.py --out data/cache/cn-978.json --country CN --dry-run
# 用已有普通账号 token 推送已完成小时；重复执行由 cursor + event_id 幂等
python3 -m ai_channel tick --config ai_channel/config.json --source waka \
  --cache data/cache/cn-978.json --state data/cache/waka-channel-state.json
```

`source_fetch.py` 输出包含 `row_count`、`pages`、`source_week_start`、`fetched_at` 和
`elapsed_ms` 的 JSON 摘要；`--dry-run` 抓取但不写缓存。旧的
`python3 -m waka_channel.cli sync-roster` / `tick` 只保留作历史 Channel ingest 的
手动排查，不再由 Ghost 调度，也不是当前 Waka XP 的生产路径。
