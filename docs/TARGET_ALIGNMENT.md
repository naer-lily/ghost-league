# 目标对齐：约 1000 人联赛

> 当前状态：已完成。本文描述现行产品目标与验收标准，不再使用任务编号或“待实现”口径。

## 产品结果

Ghost League 是一个自托管周联赛：

1. 外部排行榜约 1000 行，每行对应一个独立 Channel player，有稳定身份和跨周历史。
2. 玩家按 15 人上限切成几十个组；真人在其中一组，升段/降段后换组，其他组也真实推进。
3. 数据由 Source 提供、Channel 归一化并投影成匿名小时增量；Ghost 不知道来源是
   WakaTime、Duolingo 还是 Krita。
4. 游戏层包含打卡、余烬补签、周榜升降、称号/边框、AI 表情和标签。
5. AI 的行为可以随 XP、排名、连胜变化，但不能反过来改 XP；强度由源数据决定，不针对
   用户实时调难度。

## 当前实现

- Channel ingest 使用 `POST /v1/channels/{channel_id}/roster` 和
  `POST /v1/channels/{channel_id}/increments`；请求字段固定，未知字段返回 `422`。
- Ghost 用 `(channel_id, player_ref)` 映射稳定 `player_id`；`kind` 只作身份投影和
  审计，不参与计分/分组。
- 周 roster 是 `(week_start, channel_id)` 的全量名单；名单到达后
  `ensure_all_groups` 把 Channel player 与本地真人合并分组。
- API 启动只初始化账号、social 和 `league.db`，不读 cache、不投影 AI、不提前建组。
- 分组使用 `ceil(N/15)` + `balanced_group_sizes`；每组最多 15、最少 2；真人优先占满组。
- 结算按每组独立配额 `max(1, round_half_up(group_size * 0.2))`，Bronze 不降、
  Diamond 不升。
- 游戏状态在 `data/league/league.db`；账号/社交/webhook 在 `data/api/`；这些运行时
  目录都不进入 Git。
- WakaChannel 是独立包，负责全量 978 行 roster、p75 缩尾、稳定 UUIDv5 和小时增量；
  抓取脚本只写本地 cache，不写游戏库。

## 组规模

当前缓存 978 行：

- `ceil(978 / 15) = 66` 组；
- `978 = 54 × 15 + 12 × 14`；
- 54 个 15 人组，12 个 14 人组，没有 1 人组。

如果补到 1000 行：

- `ceil(1000 / 15) = 67` 组；
- `1000 = 62 × 15 + 5 × 14`。

规则：先定组数，再均分；每组最多 15、最少 2；真人优先进入满组；只有 1 人时不建
单人组，标记 `unplaced`。

## 验收标准

在临时库、固定时钟、无网络下：

- 978 个 Channel AI + 1 个本地真人（共 979 个 player），每人稳定 ID；
- 跑 3 周，979 人每周都有且只有一条 `weekly_results`；
- 组大小只有 14/15，没有 1 人组；
- 本周名单没有的 AI 不建组、不建 plan，也不写 dormant/absent 状态；player 行保留
  只为历史外键，回归复用同一 player，不重复建号；
- 新 AI 从 Bronze 进入，历史为空，不补造过去；
- 升段/降段按每组独立配额，不做 tier 汇总排名；
- Channel 请求里没有 provider/raw/anchor 字段；
- 真人只在一组，资料用本地 account profile；
- 公开 API/PWA 不返回 `is_ai` / `kind`；
- 线上 reset 后新 epoch 没有假历史，PWA 能看小组、历史、打卡、余烬、称号。
