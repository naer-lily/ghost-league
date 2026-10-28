# Ghost League

Ghost League 是一个自托管的每周活动联赛：外部活动经 Channel 归一化成匿名小时增量，
Ghost 负责计分、分组、打卡、余烬补签、周结算和 PWA 展示。游戏状态在 SQLite，不依赖
任何前端静态模拟数据。

- **Source**：WakaTime、Duolingo、Krita 等外部活动来源，不属于本仓库。
- **Channel**：每个来源的适配层，负责拉取、归一化、按小时投影、维护 cursor 和重试。
- **Ghost**：通用联赛引擎，只接收匿名 `player_ref`、`kind`、展示 profile 和增量。

```text
Source (WakaTime / Duolingo / Krita / ...)
        │  Channel 拉取、归一化、按小时投影
        ▼
Channel (waka-channel / duolingo-channel / krita-channel / ...)
        │  roster + {event_id, seconds, occurred_at}
        ▼
Ghost (SQLite + FastAPI + PWA)
```

Ghost 不 import Channel，不调用 Source，也不在业务逻辑里判断 provider。`kind` 只用于
身份投影和审计，不参与计分、分组或难度；公开 API 和 PWA 不返回 `is_ai` / `kind`。

## 快速开始

要求 Python 3.11+。

```bash
git clone <your-repo-url> ghost-league
cd ghost-league
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'

# 1. 初始化账号。明文 token 只打印一次，请保存到本地安全位置。
export GHOST_LEAGUE_OWNER_ID=owner
python -m ghost_league.accounts add --user-id owner --name Owner

# 2. 启动 API（默认只监听 127.0.0.1:8095）
export GHOST_LEAGUE_TOKEN="<上一步打印的 token>"
./scripts/run_api.sh
```

本地开发时也可以让 PWA 与 API 同进程启动：

```bash
python3 -m uvicorn ghost_league.pwa:app --host 127.0.0.1 --port 8096
```

生产环境的 PWA 入口建议由 HTTPS 反向代理提供；`scripts/run_pwa.sh` 会读取
`GHOST_LEAGUE_TLS_CERT` / `GHOST_LEAGUE_TLS_KEY`（默认 `deploy/tls/`，已 gitignore）。

### 接入 WakaChannel

WakaChannel 是独立于 Ghost 的接入包。它读取本地榜单缓存，生成稳定匿名 `player_ref`，
再通过 Channel ingest 推送 roster 和已完成小时的增量。token 只放在环境变量里：

```bash
export GHOST_LEAGUE_BASE_URL=http://127.0.0.1:8095
export GHOST_LEAGUE_CHANNEL_TOKEN="<channel-token>"

# 可选：刷新公开榜缓存（只写 data/cache/，不写游戏库）
python3 scripts/source_fetch.py --out data/cache/cn-978.json --country CN

# 发送本周全量名单
python3 -m waka_channel.cli sync-roster --cache data/cache/cn-978.json

# 只推送已经结束的整点；重复 tick 不会重发
python3 -m waka_channel.cli tick
```

Channel token 在 API 进程里由 `GHOST_LEAGUE_CHANNEL_TOKEN` 配置，不能使用普通账号
token。systemd 模板把 token 放在 `/etc/ghost-league/waka.env`（0600）；安装和定时器
说明见 [`deploy/systemd/README.md`](deploy/systemd/README.md)。

### 定时器

仓库只提供模板，不自动安装：

- `ghost-league-source-fetch`：周一 00:02 刷新公开榜缓存。
- `ghost-league-waka-roster`：周一 00:03 发送本周 roster。
- `ghost-league-settle`：周一 00:05 结算上一周。
- `ghost-league-waka-tick`：每小时第 1 分钟推送已完成小时。

结算只处理上一个本地周，不预建下一周；提前或重复运行会安全跳过。

## 关键规则

- **分组**：每组最多 15 人。先按 `ceil(N/15)` 定组数，再均分；不足 15 人时允许
  14/15 人混合小组，但不会创建 1 人组（至少 2 人）。真人优先进入满组。
- **升降级**：每个组独立结算，不按整个 tier 汇总。每组配额为
  `max(1, round_half_up(group_size * 0.2))`，组内前 N 升、后 N 降。
- **段位**：Bronze 不降段，Diamond 不升段；段位顺序为 Bronze → Silver → Gold →
  Sapphire → Ruby → Emerald → Amethyst → Pearl → Obsidian → Diamond。
- **打卡**：`Asia/Shanghai` 自然日累计 600 秒 = 100 XP 即打卡成功。
- **余烬补签**：已完成自然日 D 结束后 7 天内可补（D-1 到 D-7）；每次消耗 1 枚余烬，
  只恢复打卡/连胜与历史标记，不增加周 XP、不改变名次或升降级。
- **XP**：`XP = floor(seconds / 6)`；周榜按 XP 排名。
- **AI 与真人同规则**：计分、打卡、分组、升降级、称号和边框完全一致；公开响应和
  前端不暴露 AI 身份。

## API 与 PWA

- [`docs/API.md`](docs/API.md)：认证、账号、资料、头像、增量、Channel ingest、联赛、
  feed、收藏、打卡、补签、社交和错误码。
- [`docs/CHANNEL_BOUNDARY.md`](docs/CHANNEL_BOUNDARY.md)：Source → Channel → Ghost
  契约、身份规则和分组规则。
- [`docs/WEBHOOKS.md`](docs/WEBHOOKS.md)：webhook 事件、签名、重试和 CLI。
- PWA：`web/` 是移动优先的静态应用，`ghost_league/pwa.py` 先注册 API 路由，再挂载
  静态根；`/v1/...`、`/avatars/...` 始终走 API。
- 状态卡片：`GET /badge/{user_id}.svg` 返回公开 SVG，包含段位、称号和已装备边框；
  `GET /embed/{user_id}` 返回 60 秒自动刷新的 iframe。

示例 host 统一使用 `https://your-host.example`：

```md
![联赛状态](https://your-host.example/badge/owner.svg)
```

```html
<img src="https://your-host.example/badge/owner.svg" alt="联赛状态">
<iframe src="https://your-host.example/embed/owner" width="880" height="260" style="border:0;max-width:100%" title="联赛状态"></iframe>
```

## 数据与隐私

仓库只包含代码、文档和通用示例，**不提交**：

- `data/` 下的 live 数据、账号库、SQLite、头像、webhook、cache；
- `data.backup-*`、`data/archive/`、`artifacts/`、`*.bundle`；
- 本地 TLS 证书/私钥、token、真实账号资料或个人部署路径。

`.gitignore` 已排除这些路径；`.git/info/exclude` 可再放本地专用文件。发布前用
CI 或本地的隐私扫描规则检查 tracked 文件，确保没有真实主机、内网 IP、个人 ID、
token 或部署路径；扫描规则本身不要写进被扫描的文档。

生产部署用 `GHOST_LEAGUE_OWNER_ID` 覆盖默认 owner `owner`，并通过环境变量或未跟踪的
`EnvironmentFile` 提供 token；不要把真实 host、内网 IP、个人 ID 或凭据写进仓库。

## 项目结构

```text
ghost_league/
  api.py              # FastAPI 路由与 GameService
  accounts.py         # 本地账号、token 哈希、资料/头像 CLI
  badge.py            # SVG 状态卡与 embed 页面
  pwa.py              # 挂载 web/ PWA
  webhooks.py         # webhook 订阅、签名与投递
  schedule.py         # 周/小时投影纯函数（Channel 复用）
  themes.py           # 图标主题
  channels/           # Channel ingest 契约
  game/               # 规则、分组、打卡、结算、SQLite store
  source/             # 旧的归一化工具，仅供 Channel/fetch 兼容
  fetch.py            # 公开榜抓取（只写 cache）
waka_channel/         # 独立 WakaTime Channel 包
web/                  # PWA 静态资源
scripts/              # API/PWA 启动与抓取脚本
deploy/               # systemd/服务模板
docs/                 # API、Channel、Webhook 文档
tests/                # pytest 测试
```

`docs/GAME_LOOP_DESIGN.md` 是早期设计稿，仅作历史参考；当前契约以 `docs/API.md` 和
`docs/CHANNEL_BOUNDARY.md` 为准。

## 测试与检查

```bash
PYTHONPATH=. pytest -q
ruff check ghost_league tests
python3 -m compileall -q ghost_league
node --check web/app.js && node --check web/sw.js
```

测试不依赖网络，使用临时 SQLite 和 fake Channel。API/PWA 测试覆盖鉴权、账号隔离、
Channel roster/increments、分组、打卡、补签、称号/边框、feed、webhook 和静态资源。

## License

MIT。见 [`LICENSE`](LICENSE)。
