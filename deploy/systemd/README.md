# Ghost League 部署模板

Ghost League 的定时任务已经收进 API 进程。FastAPI lifespan 启动
`ghost_league.game.scheduler.GhostScheduler`，先做一次 catch-up，之后每 20 秒检查
到期任务；任务运行记录保存在游戏库的 `job_runs` 表，用 `(name, period_key)` 唯一键
和租约保证多个进程不会重复执行同一周期。

因此：

- 不再安装任何 `ghost-league-*.timer`。
- 不再需要单独的 worker service；只有 API/PWA 两个常驻服务。
- 不依赖外部 cron、systemd timer 或 ifrule。
- 仓库只保留 API/PWA 部署模板：`deploy/ghost-league-api.service`、
  `deploy/ghost-league-web.service`。

## 调度任务

所有时间都是 `Asia/Shanghai` 本地时间。

| 任务 | 时间 | 说明 |
| --- | --- | --- |
| `waka-tick` | 每小时第 1 分钟 | 只发送已完成的整点；cursor + 全局 `event_id` 双重幂等 |
| `power` | 每小时第 5 分钟 | 从 `weekly_scores` 重算展示战力，不写周历史 |
| `diamond-decay` | 每小时第 10 分钟 | 钻石软上限衰减；重复执行不会多扣 |
| `source-fetch` | 周一 00:02 | 刷新公开榜缓存；只在周一当天补跑，过期不补 |
| `waka-roster` | 周一 00:03 | 发送本周全量 roster；只在周一当天补跑，过期不补 |
| `weekly-settle` | 周一 00:05 | 结算上一个本地周；本周内未完成可补跑 |
| `rival-auto` | 周二 00:00 | 为没有宿敌的真人自动匹配；本周内可补跑 |
| `daily-bets` | 每天 10:30 | 结算当天日注；09:00 锁注，之后拒绝新日注 |

启动 catch-up 的行为：

- 周一 00:06 启动：补跑 `waka-tick`、`source-fetch`、`waka-roster`、
  `weekly-settle`、`power`、`diamond-decay`（各自按最近到期周期）。
- 周二 01:00 启动：补跑 `rival-auto`，以及当周仍未完成的其它周期。
- 每天 10:31 启动：补跑当天 `daily-bets`。
- 09:30 启动：不会提前结算当天日注；09:00 后下注接口已经拒绝。
- 周三启动：不补跑周一的 `source-fetch` / `waka-roster`；未完成的
  `weekly-settle` 仍会补跑。

每个任务本身都可重复调用：重复发钱、重复写结算、重复 tick 都由业务层的幂等键和
`job_runs` 唯一键挡住。租约默认 30 秒，运行中的任务每 10 秒续租；进程崩溃后心跳停止，
租约过期即可由后续 tick 重新认领。已成功的周期永久跳过。任务异常只记录日志，不会让
API 退出。

## 环境变量

定时任务在 API/PWA 进程内运行，因此凡是可能执行 Channel 任务的进程都需要：

```bash
GHOST_LEAGUE_CHANNEL_TOKEN=<channel-token>
GHOST_LEAGUE_BASE_URL=http://127.0.0.1:8095
```

生产模板从 0600 的 EnvironmentFile 读取：

- API：`/etc/ghost-league/api.env`
- PWA：`/etc/ghost-league/web.env`

多进程同时运行调度器是安全的；租约保证同一周期只有一个进程真正执行。如果只想让
其中一个进程承担定时任务，可以不把 Channel token 放进另一个进程的 EnvironmentFile，
任务失败后会在后续 tick 由有权限的进程补上。

游戏数据库默认位于 `/srv/ghost-league/data/league/league.db`。`source-fetch` 只刷新
`data/cache/cn-978.json`，从不把榜单行写进 `league.db`。

## 安装 API/PWA 服务

```bash
sudo install -d -m 0700 /etc/ghost-league
sudo install -m 0600 /dev/null /etc/ghost-league/api.env
sudo install -m 0600 /dev/null /etc/ghost-league/web.env
# 编辑两个文件，至少写入：
#   GHOST_LEAGUE_CHANNEL_TOKEN=<channel-token>
#   GHOST_LEAGUE_BASE_URL=https://your-host.example

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

查看运行记录（只读）：

```bash
sqlite3 /srv/ghost-league/data/league/league.db \
  "SELECT name, period_key, status, attempts, started_at, finished_at
   FROM job_runs ORDER BY started_at DESC LIMIT 20;"
```

## 手工运行

任务仍保留 CLI，可用于本地排查；生产环境不需要手工配置定时器：

```bash
cd /srv/ghost-league
python3 scripts/source_fetch.py --out data/cache/cn-978.json --country CN
python3 scripts/source_fetch.py --out data/cache/cn-978.json --country CN --dry-run
python3 -m waka_channel.cli sync-roster
python3 -m waka_channel.cli tick
python3 -m waka_channel.cli tick --week-start 2026-10-26 --at 2026-10-28T16:00:00+08:00
python3 -m ghost_league.game.jobs settle
python3 -m ghost_league.game.jobs rival-auto
python3 -m ghost_league.game.jobs daily-bets
```

`source_fetch.py` 输出包含 `row_count`、`pages`、`source_week_start`、`fetched_at` 和
`elapsed_ms` 的 JSON 摘要；`--dry-run` 抓取但不写缓存。Channel 命令是幂等的：
roster 替换本周名单，tick 只发送 cursor 之后已完成的小时。
