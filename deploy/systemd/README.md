# WakaChannel 与周任务 systemd 模板

这些文件是模板；安装或启用是部署步骤，应用不会在 import 时自动安装。WakaChannel
单元从 `/etc/ghost-league/waka.env`（0600）读取 Channel token，不把 token 或主机
信息写进 unit 文件。

游戏数据库默认位于 `/srv/ghost-league/data/league/league.db`。source-fetch 只刷新
`data/cache/cn-978.json`，从不把榜单行写进 `league.db`。

## 定时任务

- `ghost-league-source-fetch.timer`：`Mon 00:02`，`Persistent=true`；分页抓取公开
  周榜并原子替换匿名 `id`/`rank`/`seconds` 缓存。
- `ghost-league-waka-roster.timer`：`Mon 00:03`，`Persistent=true`；执行
  `python3 -m waka_channel.cli sync-roster`，发送本周全量名单。
- `ghost-league-settle.timer`：`Mon 00:05`，`Persistent=true`；执行
  `python3 -m ghost_league.game.jobs settle`，只结算上一个本地周，不预建下一周。
- `ghost-league-waka-tick.timer`：每小时第 1 分钟，`Persistent=true`；执行
  `python3 -m waka_channel.cli tick`，只发送已完成小时，重复或漏跑由 cursor 处理。

source-fetch 在 roster 前运行，保证新周从完整快照开始。Ghost 的小时增量只来自
WakaChannel，不再有旧的 AI 投影 tick。

## 手工安装

```bash
sudo install -d -m 0700 /etc/ghost-league
sudo install -m 0600 /dev/null /etc/ghost-league/waka.env
# 编辑 /etc/ghost-league/waka.env：
#   GHOST_LEAGUE_CHANNEL_TOKEN=<channel-token>
#   GHOST_LEAGUE_BASE_URL=https://your-host.example
# API 进程必须收到同一个 GHOST_LEAGUE_CHANNEL_TOKEN。

sudo install -m 0644 deploy/systemd/ghost-league-source-fetch.service \
  /etc/systemd/system/ghost-league-source-fetch.service
sudo install -m 0644 deploy/systemd/ghost-league-source-fetch.timer \
  /etc/systemd/system/ghost-league-source-fetch.timer
sudo install -m 0644 deploy/systemd/ghost-league-waka-roster.service \
  /etc/systemd/system/ghost-league-waka-roster.service
sudo install -m 0644 deploy/systemd/ghost-league-waka-roster.timer \
  /etc/systemd/system/ghost-league-waka-roster.timer
sudo install -m 0644 deploy/systemd/ghost-league-settle.service \
  /etc/systemd/system/ghost-league-settle.service
sudo install -m 0644 deploy/systemd/ghost-league-settle.timer \
  /etc/systemd/system/ghost-league-settle.timer
sudo install -m 0644 deploy/systemd/ghost-league-waka-tick.service \
  /etc/systemd/system/ghost-league-waka-tick.service
sudo install -m 0644 deploy/systemd/ghost-league-waka-tick.timer \
  /etc/systemd/system/ghost-league-waka-tick.timer

sudo systemctl daemon-reload
sudo systemctl enable --now \
  ghost-league-source-fetch.timer \
  ghost-league-waka-roster.timer \
  ghost-league-settle.timer \
  ghost-league-waka-tick.timer
```

## 检查

```bash
systemctl list-timers --all 'ghost-league*' --no-pager
systemctl status \
  ghost-league-source-fetch.timer \
  ghost-league-waka-roster.timer \
  ghost-league-settle.timer \
  ghost-league-waka-tick.timer
journalctl -u ghost-league-source-fetch.service \
  -u ghost-league-waka-roster.service \
  -u ghost-league-settle.service \
  -u ghost-league-waka-tick.service
```

手工运行：

```bash
cd /srv/ghost-league
python3 scripts/source_fetch.py --out data/cache/cn-978.json --country CN
python3 scripts/source_fetch.py --out data/cache/cn-978.json --country CN --dry-run
python3 -m waka_channel.cli sync-roster
python3 -m waka_channel.cli tick
python3 -m waka_channel.cli tick --week-start 2026-10-26 --at 2026-10-28T16:00:00+08:00
python3 -m ghost_league.game.jobs settle
```

`source_fetch.py` 输出包含 `row_count`、`pages`、`source_week_start`、`fetched_at` 和
`elapsed_ms` 的 JSON 摘要；`--dry-run` 抓取但不写缓存。Channel 命令是幂等的：
roster 替换本周名单，tick 只发送 cursor 之后已完成的小时。

## Unit 文本

### `ghost-league-source-fetch.service`

```ini
[Unit]
Description=Ghost League weekly full leaderboard fetch
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/srv/ghost-league
ExecStart=/usr/bin/python3 scripts/source_fetch.py --out data/cache/cn-978.json --country CN
NoNewPrivileges=true
PrivateTmp=true
UMask=0077
```

### `ghost-league-source-fetch.timer`

```ini
[Unit]
Description=Ghost League weekly full leaderboard fetch timer

[Timer]
OnCalendar=Mon 00:02
Persistent=true
Unit=ghost-league-source-fetch.service

[Install]
WantedBy=timers.target
```

### `ghost-league-waka-roster.service`

```ini
[Unit]
Description=Ghost League WakaChannel weekly roster sync
After=network-online.target ghost-league-source-fetch.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/srv/ghost-league
EnvironmentFile=/etc/ghost-league/waka.env
ExecStart=/usr/bin/python3 -m waka_channel.cli sync-roster
NoNewPrivileges=true
PrivateTmp=true
UMask=0077
```

### `ghost-league-waka-roster.timer`

```ini
[Unit]
Description=Ghost League WakaChannel weekly roster timer

[Timer]
OnCalendar=Mon 00:03
Persistent=true
Unit=ghost-league-waka-roster.service

[Install]
WantedBy=timers.target
```

### `ghost-league-settle.service`

```ini
[Unit]
Description=Ghost League weekly settlement
After=local-fs.target

[Service]
Type=oneshot
WorkingDirectory=/srv/ghost-league
ExecStart=/usr/bin/python3 -m ghost_league.game.jobs settle
NoNewPrivileges=true
PrivateTmp=true
UMask=0077
```

### `ghost-league-settle.timer`

```ini
[Unit]
Description=Ghost League weekly settlement timer

[Timer]
OnCalendar=Mon 00:05
Persistent=true
Unit=ghost-league-settle.service

[Install]
WantedBy=timers.target
```

### `ghost-league-waka-tick.service`

```ini
[Unit]
Description=Ghost League WakaChannel hourly tick
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/srv/ghost-league
EnvironmentFile=/etc/ghost-league/waka.env
ExecStart=/usr/bin/python3 -m waka_channel.cli tick
NoNewPrivileges=true
PrivateTmp=true
UMask=0077
```

### `ghost-league-waka-tick.timer`

```ini
[Unit]
Description=Ghost League WakaChannel hourly tick timer

[Timer]
OnCalendar=*-*-* *:01:00
Persistent=true
Unit=ghost-league-waka-tick.service

[Install]
WantedBy=timers.target
```
