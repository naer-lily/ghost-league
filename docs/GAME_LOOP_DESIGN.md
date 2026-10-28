> **历史设计稿，已被取代。** 当前实现与契约以 [`API.md`](API.md) 和
> [`CHANNEL_BOUNDARY.md`](CHANNEL_BOUNDARY.md) 为准。本文保留 2026-10-28 的设计
> 推演和开放问题，其中提到的旧模块、旧 source 流程、任务编号和“待实现”状态均不再
> 代表当前仓库；不要把它当现状或部署说明。
>
> 当前产品是 Channel-fed 的 SQLite 联赛，`public/` 静态 demo、旧 CLI 和旧
> `projection.tick` 已删除。分组、身份和 ingest 规则请直接看 `docs/CHANNEL_BOUNDARY.md`。

# 游戏循环重设计：从预生成周榜到 AI 对手联赛

> 状态：设计稿，2026-10-28。本文只描述目标与迁移方案，不实现、不修改线上数据。
>
> 工作名：**Momentum League（势能联赛）**。仓库 slug `ghost-league` 暂不改；产品界面与内部领域词不再使用 “ghost / 幽灵 / synthetic / 模拟 / 伪实时 / 真人”。工作名只是建议，最终名称见第 9 节开放问题。
>
> 参考框架：MDA（Mechanics–Dynamics–Aesthetics）、core loop、progression。本机没有找到适用的只读文档型游戏设计 skill，因此未安装可执行插件，直接使用这三个框架。本设计把“外部可见的竞争、真实代价、他者对比、即时反馈”作为第一优先级，把收集/称号作为第二层。

---

## 0. 结论先行

**推荐循环：每日打卡 + AI 对手动态 + 周榜升降级。**

- 每天回来的理由：**今天还差多少 XP 才能打卡、AI 对手今天做了什么、我现在第几名、昨天能不能补签。**
- 每周在意的理由：**本周 tier 内的晋级/降级名额、周一早上看到上周名次、称号和新小组。**
- 不做赛季通行证、不做可购买货币、不做 52 周预生成。所有 AI 对手只在当前周、当前小组内生成；过去只保留真实结算过的周。
- 修复资源叫 **余烬（Ember）**，只用于补签，不能买外观、不能交易、不能换数值。
- AI 的原始锚点只用 WakaTime 的**公开周总量**；对手是 AI 角色，不是那个 WakaTime 用户，UI 始终标明“AI 对手”。

一句话版本：

> **每天为 100 XP 和排名回来，每周为 tier 内的晋级/降级名额留下。**

---

## 1. 现状地图

### 1.1 当前真实状态（只读核对）

本地数据核对结果（不读取 token、不输出姓名）：

| 对象 | 当前值 | 含义 |
| --- | --- | --- |
| `data/league/state.json` | `settled_weeks=52`、`user_count=979`、10 段 | 已经模拟并结算了 52 周 |
| `data/league/weeks.json` | 52 周 × 978 条 standings | 过去 52 周的“历史”是预生成结果 |
| `data/api/membership.json` | 2 个账号，均在 `Bronze-W53-G01` | 第 53 周 Bronze 小组，2 个真人 + 13 个 ghost |
| `ghost_league/api.py` | `GHOST_COUNT=14`、`GROUP_SIZE=15` | 单真人时上限 14 个 ghost；当前 2 真人 → 13 个 ghost |
| `ghost_league/league.py` | `TIERS` 10 段、`GROUP_SIZE=15`、旧前 3 升后 3 降 | 旧代码留档；新 game 层按每组比例配额 |
| `ghost_league/api.py` | `CHECKIN_SECONDS=600` | 600 秒 = 100 XP，自动打卡 |

当前代码里，“历史”有三层来源，必须区分：

1. **真实结算周**：未来应由我们自己的库保存，只追加，不补造。
2. **预生成 52 周**：`ghost_league/beta.py` 生成；`league_cli.py bootstrap` 写入 `data/league/state.json` 和 `weeks.json`。
3. **前端 8 周演示历史**：`ghost_league/history.py` 的 `synthetic_total_for()` 和 `generate.py` 的 `weekly_history()` 生成，标记 `synthetic=True`。

三者现在混在一起，导致“历史”不可信，也让 reset 无法干净地只保留真实周。

### 1.2 文件级保留 / 必须改 / 可删除

| 路径 | 现状 | 决定 | 目标 |
| --- | --- | --- | --- |
| `ghost_league/league.py` | 10 段、15 人、旧 3 升 3 降；`join()` 要求 `settled_weeks >= 52`（约 344–345 行）；`settle()` 从全 Bronze 重放所有周（206–322 行）；`join()` 直接写 `state.json`（381–385 行） | **旧代码留档，新 game 层重写生命周期** | 段位和组大小保留；升降级改由 `game/rules.py` 的每组比例配额计算；`join()` 改为任意时间加入当前周；`settle()` 改为增量结算单周；不再写 JSON |
| `ghost_league/beta.py` | 52 周模拟、`weekly_seconds()`、`bootstrap()` 写 `state.json`/`weeks.json` | **删除** | 不再有“先跑 52 周再让人加入” |
| `ghost_league/history.py` | `synthetic_total_for()`、`weekly_history()` 合成过去周 | **删除** | 历史只来自 `weekly_results`；没有真实结算就没有历史 |
| `ghost_league/generate.py` | 静态 demo 的 8 周历史、168 小时投影 | **删除或移入 archive** | 产品路径不再生成演示历史 |
| `ghost_league/validate.py` | 校验 `synthetic` 标记、8 周历史 | **删除或重写** | 新校验针对真实结算不变量 |
| `ghost_league/leaderboard.py` | 只读的“已结算周”内存视图 | **可删除/降级为测试工具** | 不再作为生产数据入口 |
| `ghost_league/report.py` | 52 周封闭内测报告 | **删除/归档** | 不进入产品 |
| `ghost_league/league_cli.py` | `bootstrap` / `report` / `join` | **替换命令** | `reset`、`settle-week`、`seed-anchors`、`audit` |
| `ghost_league/schedule.py` | BLAKE2b 确定性 168 小时分配、`projected_seconds` | **保留数学，改语义** | 作为 AI 日节奏/日内展示的纯函数；不再声称是真人逐小时数据 |
| `ghost_league/wakatime.py` | 公开资料缓存（bio/city/社交链接） | **保留缓存，限制使用** | 只作为人工核验；AI 行为只用匿名化公开周总量，bio/city 不进入游戏或前端 |
| `ghost_league/fetch.py` | 抓公开榜，保留公开 `name` / `avatar_url` | **保留抓取，展示资料只走 Channel profile** | 缓存留 `id`/`rank`/`seconds`/`name`/`avatar_url`；Ghost 只存 Channel profile 快照，不存 raw 周总量 |
| `ghost_league/api.py` | 2219 行单体；加载 52 周 state；`ghost_seconds`/`ghost_names`/`ghost_tiers`/`ghost_avatar_urls`；按整点投影 ghost（751–766 行） | **拆分为路由 + 游戏服务，重写游戏部分** | 新 API 只读自己的 `league.db`；AI 状态持久化；XP 对外 |
| `ghost_league/accounts.py` | 账号、token 哈希、资料、头像 | **保留** | 身份/鉴权不变 |
| `ghost_league/badge.py` | SVG 状态卡，显示 tier/rank/XP/打卡 | **保留渲染，换数据源** | 显示称号/余烬；不显示秒/分钟；AI 不出现在个人 badge |
| `ghost_league/webhooks.py` | 签名、重试、`STREAK_MILESTONES` | **保留** | 增加 `checkin.repaired`；不改签名协议 |
| `ghost_league/social.py` | 关注关系 | **冻结，不扩展** | 本轮不做多用户社交；保留表但不出现在新循环 |
| `ghost_league/pwa.py` | 挂载 `web/` | **保留** | 只换前端资源与 API |
| `ghost_league/__init__.py` | 导出 synthetic/history | **改导出** | 只导出新规则/纯函数 |
| `data/league/state.json` | 52 周、979 用户 | **备份后归档，不读取** | 新库无此文件 |
| `data/league/weeks.json` | 52 周 × 978 | **备份后归档，不读取** | 新库无此文件 |
| `data/api/membership.json` | 2 人 + 13 ghost 的 W53 组 | **备份后删除** | 由 `groups`/`group_members` 表替代 |
| `data/api/events.db` | 真实增量事件 | **备份后归档旧库，新建空库** | 新 epoch 从零开始；旧数据可回滚 |
| `data/api/accounts.db` | 账号/token 哈希/资料 | **保留** | 不因 reset 丢账号 |
| `data/cache/cn-978.json` | 公开榜缓存，可能含展示名 | **只保留匿名锚点字段** | 重建 `anchor_pool`；不保留姓名 |
| `data/cache/wakatime-profiles.json` | 公开资料缓存，含 bio/city | **不进入 AI 模型；可保留作人工核验** | 不向其他用户暴露 |
| `public/` | 旧静态 demo | **归档/下线** | 产品入口只保留 `web/` PWA |
| `web/app.js`、`web/index.html`、`web/style.css`、`web/sw.js` | 当前 PWA，已有 XP/无 ghost 文案 | **改 UI/缓存版本** | AI 标识、每日动态、补签、称号、收藏 |
| `tests/test_league.py`、`tests/test_core.py` | 52 周/8 周合成历史断言 | **重写** | 新测试针对真实周、AI、补签、reset |
| `tests/test_api.py` | 52 周 state 启动 API | **改 fixture** | 新库 fixture；旧测试保留迁移覆盖 |
| `tests/test_pwa.py` | 已断言 UI 不含“幽灵/synthetic/模拟/伪实时” | **保留这类断言，扩展** | 增加“AI 对手必须可见”“不出现分钟” |
| `README.md`、`docs/API.md` | 旧 demo/52 周说明 | **重写产品段** | README 可保留技术沿革；API 以 XP 为准 |
| `reports/closed-beta-52w.md` | 52 周报告 | **归档** | 不作为产品证据 |

### 1.3 预生成历史、幽灵命名、full-state reset 的具体落点

**预生成历史**

- `ghost_league/beta.py:99-126`：`build_api()` 为 1..N 周生成 standings。
- `ghost_league/beta.py:147-178`：`bootstrap()` 写 `data/league/state.json` 与 `weeks.json`。
- `ghost_league/league.py:206-322`：`settle()` 从全 Bronze 重放选定周，历史由重放产生。
- `ghost_league/history.py:18-52`：`synthetic_total_for()` 为过去周造总量。
- `ghost_league/generate.py:119-142`：`weekly_history()` 把过去周写入前端 JSON。
- `ghost_league/api.py:1024-1046`：`history_for()` 从 52 周 state 取用户历史。
- `ghost_league/league.py:344-345`：`join()` 要求 52 周已结算，等于强迫先铺历史。

**幽灵命名**

- `ghost_league/api.py:50-51`：`GHOST_COUNT=14`、`GROUP_SIZE=GHOST_COUNT+1`。
- `ghost_league/api.py:355-358`：`ghost_seconds`、`ghost_names`、`ghost_tiers`、`ghost_avatar_urls`。
- `ghost_league/api.py:267-284`：`_load_ghost_avatars()`。
- `ghost_league/api.py:423-620`：`ghost_ids`、`_available_ghosts()`、`_place_user()`、`_validate_memberships()`。
- `ghost_league/api.py:751-766`：用 `projected_seconds()` 把 ghost 当“整点快照”。
- `ghost_league/api.py:1049-1106`：`_membership_record_for()`、`_member_identity()` 仍把 ghost 当 member。
- `ghost_league/__init__.py`、`README.md`、`docs/`、`deploy/` 中的产品名与环境变量前缀。

**full-state reset 落点**

- `ghost_league/api.py:369-407`：`initialize()` 加载 `state.json`、ghost 缓存、membership，并自动给 owner 建组。
- `ghost_league/api.py:409-421`：`_current_league_week()` 基于 `settled_weeks + 1`。
- `ghost_league/api.py:423-446`：`_load_memberships()` 迁移/读取 `membership.json`。
- `ghost_league/api.py:622-698`：`_init_db()` 只负责 `drawing_events`；没有游戏表。
- `ghost_league/league.py:325-386`：`join()` 直接改 `state.json`，没有事务、没有 epoch。
- `data/league/state.json`、`data/league/weeks.json`、`data/api/membership.json`、`data/api/events.db` 是 reset 的实际数据落点。

### 1.4 保留的资产

- 10 段位名称和图标、15 人组：`ghost_league/league.py:16-32`、`web/assets/tiers/`。旧前 3/后 3 只留在旧 `league.py`，新 game 层已改每组比例配额。
- 600 秒阈值和纯函数分配：`ghost_league/schedule.py`、`ghost_league/api.py:54`。
- 账号、token 哈希、头像、PWA 安装、badge/embed、webhook 签名：现有实现质量足够，不需要重写。
- Asia/Shanghai 周/日边界：`ghost_league/schedule.py:25-29`、`ghost_league/api.py:248-264`。

---

## 2. 推荐的游戏循环

### 2.1 一句话

> **每天为 100 XP 打卡、AI 对手的今日动作和名次回来；每周为 tier 内的晋级/降级名额和一条可展示的周战绩留下。**

**MDA 对照**

| 层 | 本设计 |
| --- | --- |
| Mechanics | 增量换 XP、100 XP 打卡、15 人组、每组比例配额升降、余烬补签、AI 日行动、周结算 |
| Dynamics | 每天追赶 AI、周末冲榜、资源取舍、补签/干净连胜、晋级后的更强对手 |
| Aesthetics | 紧张（名次）、竞争（他者对比）、掌控（自己的节奏）、收集（称号/物品）、归属（固定小组） |

### 2.2 日循环

| 时点（Asia/Shanghai） | 玩家动作 | AI 动作 | 反馈 |
| --- | --- | --- | --- |
| 00:00–00:05 | 新一天开始；看到昨日结算 | 日切：结算昨日、生成今日计划（只生成今天） | 昨日回顾：“你 320 XP，1 个 AI 超过你” |
| 09:00 / 14:00 / 21:00 | 同步增量、看今日 XP | 按当日节奏执行 2–4 段行动 | 小程序/页面显示 AI 今日行动与排名变化 |
| 任意时刻达到 100 XP | 自动打卡，火焰 +1 | 达到 100 XP 时同样自动打卡 | 即时 XP 增量、打卡动画、连胜 |
| 任意时刻 | 用余烬补签 T-1 到 T-7 | AI 按同一规则、同一余额决定是否补签 | “补签成功，连胜恢复；本周历史标记 repaired” |
| 任意时刻 | 查看小组动态、换称号/边框 | AI 装备自己已获得的称号 | 名次/称号即时可见 |
| 23:59 前 | 最后冲一次 | 最后一段行动 | 今日 XP、排名、次日目标 |

**日循环的设计意图**

- 即时反馈来自真实增量，不是“点一下领奖励”。
- AI 的今日动作是可见的，不是只给一个分数。
- 补签是唯一的追溯入口，且有资源上限，不能无限补。
- 不设置“必须登录才保留 XP”的惩罚；不登录只是不产生新 XP。

### 2.3 周循环

| 时点 | 事件 |
| --- | --- |
| 周一 00:00 | 上周分数锁定；不再接受会改变上周名次的事件 |
| 周一 00:05 | 结算：每个组内成员按 seconds 降序、`player_id` 升序排名；`quota = max(1, round_half_up(group_size * 0.2))`，组内前 `quota` 晋级、后 `quota` 降级；Bronze 不降、Diamond 不升；每组独立结算并写入 `weekly_results` |
| 周一 00:10 | 新一周分组；每个真人最多与 14 个 AI 同组；生成当前周 AI 计划 |
| 周一全天 | 周回顾卡：上周名次、升降级、获得称号、下周对手 |
| 周日 24:00 前 | 最后冲榜；周冠军/前三/保级是本周的主要外部压力 |

**周循环的设计意图**

- 周榜不是“伪实时投影”，而是本周真实增量 + 本周 AI 行为的共同结果。
- 升降级是外部可见的代价；不靠扣资源/惩罚连胜来制造压力。
- 周结算后不回放、不重算、不补造；只追加真实结果。

### 2.4 赛季循环：现在不做

- 当前只有 2 个真实账号、第 1 天 beta，做 8 周赛季只会增加重置/奖励/内容负担。
- 先用 **epoch** 管理 reset（见 7.5），不做赛季重置。
- 触发做赛季的条件（建议）：真人 ≥ 100、Bronze 以上有 ≥ 3 个稳定小组、连续 8 周留存可观测。届时只做“赛季徽章 + 软重置”，不做通行证/付费轨。
- 数据表预留 `season_id NULL`，v1 所有奖励永久。

### 2.5 结算与反馈的边界

- **周分数锁**：周一 00:00。`occurred_at` 属于上一周、但在锁后到达的事件只进审计流水，不改变已锁周名次。
- **日锁**：每日 00:05。日锁后到达的昨日事件不追溯打卡；补签是唯一追溯手段。
- **补签窗**：错过日 D 结束后 7 天内（D+8 00:00 前），即 D-1 到 D-7 可补，且 D 有 1–599 秒真实记录。周日补签发生在周一结算后，只恢复连胜/历史标记，不改上周名次。
- **AI 结算**：与真人同一日锁/周锁；AI 不接受“补算未来周”。

---

## 3. 两个备选循环

### 备选 A：每日 1v1 对决

**形态**：每天随机/匹配 1 个 AI，今日 XP 高者获胜；赢一场得星，集星升段；每天 00:00 重置。

**适合**：需要极强即时反馈、用户每天只愿意投入 100–300 XP 的轻量产品。

**为什么不选**：

- 每日二值胜负会把“今天状态不好”放大成失败，容易产生逃避。
- 1v1 必须针对用户调 AI，天然走向“刚好压你”的 rubber-banding；这与“不能永远刚好压用户”冲突。
- 没有 15 人组的他者对比，也没有周榜的“保级/晋级”叙事。
- 段位变成每日重置的星数，长期积累感弱。

### 备选 B：8 周赛季通行证

**形态**：8 周一个赛季，做章节任务、经验轨道、外观奖励、软重置；赛季末按段位发限定称号。

**适合**：内容团队能持续产出、用户对收集有强需求、产品已有稳定日活。

**为什么不选**：

- 内容生产是持续成本；当前只有 1 个 beta 用户和 2 个账号，无法支撑。
- 通行证天然引入“付费/免费轨”和虚拟经济联想，与“不要自制金币/虚拟经济做核心驱动”冲突。
- 它不能替代核心循环：如果每日/每周不好玩，通行证只是把问题延后 8 周。
- 用户明确说“不做大而全的赛季系统”。

**结论**：先做“周联赛 + 日打卡 + AI 行为”，把收集/称号作为**额外解锁**，等核心循环验证后再考虑赛季外观层。

---

## 4. 修复资源经济：余烬（Ember）

### 4.1 定位

- 名称：**余烬（Ember）**。
- 它不是货币：不能购买外观、不能交易、不能换 XP、不能换名次、不能送人。
- 唯一用途：补签一个**已经错过、但当天确有活动记录**的打卡日。
- 不做“断连胜扣资源”“资源过期”“付费补充”。资源只增不减（除了补签消耗）。

### 4.2 获取公式（按 XP）

所有对外数字用 XP；后端存 seconds。

```text
xp(seconds)      = seconds // 6                 # 向下取整，唯一换算
week_xp          = week_seconds // 6
earned_this_week = min(2, week_xp // 2000)      # 每周最多可赚 2 枚
potential        = earned_this_week - granted_this_week
added            = min(potential, 3 - balance)   # 持有上限 3
balance         += added
granted_this_week += added
```

- 每 **2,000 XP** 获得 1 枚余烬（2,000 XP = 12,000 秒）。
- 每周最多获得 **2 枚**。
- 持有上限 **3 枚**；跨周保留。
- 因此一周最多补 3 天（受余额和 7 天窗口约束），但本周最多**新赚** 2 枚。
- 每日结算时统一入账，入账幂等；同一天不会重复发。
- 若余额已满 3，新增的 `potential` 不强行塞入；余额降到 3 以下后，下一次日结算可以补入本周尚未入账的部分。
- 获得不消耗 XP，不影响排名。

### 4.3 消耗与时间窗

- 补签 1 天消耗 **1 枚**。
- 只能补 **最近 7 个已完成自然日**：T-1 到 T-7；今天不能补。
- 补签窗口：D 日结束后 **7 天**（D+8 00:00 前）；D-7 仍可补，D-8 及更早拒绝。
- 补签条件：
  - 该日 `1 <= day_seconds < 600`，即当天有至少 1 XP 的真实活动但没到 100 XP；
  - 该日尚未打卡、尚未补签；
  - 账户余额 ≥ 1；
  - 该日不是未来、不是今天、不超过窗口。
- **0 XP 的日子不能补签**。理由：补签是“把差一点的火接上”，不是凭空造一天；否则资源会变成“买连胜”。如果用户坚持要覆盖 0 XP（例如忘记同步），应另做“请假”机制，不与本资源混用。
- 补签不加 XP、不改周名次、不改晋级/降级；只恢复打卡状态和连胜。
- 周结算后发生的补签（主要是周日）只更新连胜/历史标记，`weekly_results` 的 XP/rank 不变。

### 4.4 连胜与历史标记

| 字段 | 含义 |
| --- | --- |
| `checkins.source` | `verified`（自然达标）或 `repaired`（补签） |
| `checkins.repaired_at` | 补签时间；自然打卡为 NULL |
| `streaks.current` | 计入补签的当前连胜 |
| `streaks.clean_current` | 不计补签的“干净连胜” |
| `weekly_results.repaired_days` | 本周补签天数 |
| `weekly_results.post_settlement_repairs` | 周锁后补签天数（只影响连胜展示） |
| `weekly_results.clean_checkins` | 自然达标天数 |

- 当前连胜把补签日算作连续。
- “干净周 / 完美周”类高 prestige 里程碑要求 `clean_checkins = 7`，补签不算；普通 7 日连胜称号可以算补签。
- 历史卡显示“补签 ×1”，不是惩罚，只是诚实标记。
- 不因补签降低段位、XP 或已有称号。

### 4.5 防刷

- 服务端时间判定，不信客户端日期。
- `(player_id, date)` 唯一；补签请求带 `idempotency_key`，重复请求返回同一结果。
- 余额扣减和 `checkins` 写入同一 SQLite 事务；不允许负余额。
- 每个自然日最多补 1 次；一周最多消耗 3 枚（持有上限），不是无限补。
- 0 XP、未来日期、今天、超窗、已打卡、已补签全部拒绝。
- 不退款、不撤销；补签是最终状态。
- AI 使用完全相同公式、上限、窗口、条件；没有隐藏补贴。

### 4.6 具体算例

假设某用户本周（周一到周日）真实记录：

| 日 | seconds | XP | 状态 |
| --- | ---: | ---: | --- |
| 周一 | 12,000 | 2,000 | 已打卡 |
| 周二 | 13,200 | 2,200 | 已打卡 |
| 周三 | 300 | 50 | 未打卡 |
| 周四 | 360 | 60 | 未打卡 |
| 周五 | 12,600 | 2,100 | 已打卡 |
| 周六 | 12,000 | 2,000 | 已打卡 |
| 周日 | 10,800 | 1,800 | 已打卡 |
| **合计** | **61,260** | **10,210** | 5 天自然达标 |

- 周二结束时 `week_xp=4,200`，`earned_this_week = min(2, 4,200//2,000) = 2`，余额 2。
- 周三/周四错过；周五/周六/周日自然达标。
- 若周三、周四都在窗口内，各花 1 枚：余额 2 → 0。
- 结果：`current_streak=7`，`clean_current=5`，`repaired_days=2`，`clean_checkins=5`。
- 若用户直到下周四才凑到 4,000 XP，上周三的 7 天窗口已在下周四 00:00 关闭，则只能补上周四到本周三中的有效日期；这是“早行动”的真实代价，不是系统惩罚。
- 若余额已有 3 枚，本周再获得 2 枚也仍是 3，不能囤到 5；窗口内最多补 3 天，但本周新赚仍只有 2 枚。

> 注意：周 XP 是 `floor(61,260/6)=10,210`；日 XP 是逐日 floor。逐日相加可能与周 XP 相差最多 6 XP。**名次和结算永远用 seconds；展示用各自范围的 floor。** 不要在 UI 里把日 XP 相加当周 XP。

### 4.7 AI 如何使用同一资源

- AI 的 `week_xp` 来自它本周已结算的模拟 seconds，同样 `min(2, week_xp//2000)`、上限 3。
- AI 在日结算时检查昨日：
  - 若昨日 `1 <= seconds < 600`、余额 ≥ 1、且 `hash(seed, date, "repair") % 100 < threshold`，则花 1 枚补签。
  - `threshold = 45`（当前连胜 ≥3）否则 `20`；即 AI 也会经常不补，避免“AI 永远完美”。
- AI 补签同样标记 `source=repaired`，同样进入连胜/称号判定，同样显示在动态里。
- AI 不获得任何人类没有的资源；其模拟 XP 只用于同一公式。

---

## 5. AI 对手模型

### 5.1 定位与披露

- 对手内部仍是 AI 参赛者，但不是 WakaTime 用户，不是“幽灵”，不是“真人”；公开 UI 不显示 AI 标签，统一展示昵称、称号和边框。
- 详情页说明：“对手行为是游戏模拟；其强度锚定公开周总量，不代表任何人的真实逐小时活动。”
- 不读取 bio、city、社交账号；公开 `name` / `avatar_url` 只作为 Channel profile 展示快照，不参与计分、分组或行为生成。
- 不用 ghost 这个词做产品名；内部字段用 `opponent`。

### 5.2 原始锚点

| 字段 | 说明 |
| --- | --- |
| `source` | 固定 `wakatime_public_leaderboard` |
| `source_key_hash` | `HMAC(deployment_salt, 公开 user id)`；不可逆，用于同源周更新 |
| `anchor_seconds` | 该公开用户的周总量（秒） |
| `anchor_week` | 该总量对应的周 |
| `fetched_at` | 抓取时间 |
| `stale_weeks` | 没有新公开数据时累计；仅用于降低置信度，不造历史 |

- 只取公开周总量；公开资料缓存（`data/cache/wakatime-profiles.json`）不进入 AI 模型，也不向其他用户展示。
- `deployment_salt` 放在部署环境/未跟踪 secret 中，不写死进仓库；更换 salt 只影响 future anchor 匹配。
- 每周可选刷新一次 anchor；没有新数据就沿用旧 anchor，并增加 `stale_weeks`。不因为“缺数据”合成过去周。
- 一个 anchor 可以被多个 AI 角色复用；AI 角色 ID 独立，不暴露 anchor 对应关系。

### 5.3 段位强度带

AI 的绝对强度由段位带控制，anchor 只决定“在同段位里偏强还是偏弱”，避免 Bronze 出现 147 小时对手。

| 段位 | 周 XP 下限 | 周 XP 上限 | 内部 seconds 范围 |
| --- | ---: | ---: | ---: |
| Bronze | 600 | 5,000 | 3,600–30,000 |
| Silver | 3,000 | 9,000 | 18,000–54,000 |
| Gold | 6,000 | 14,000 | 36,000–84,000 |
| Sapphire | 10,000 | 20,000 | 60,000–120,000 |
| Ruby | 15,000 | 27,000 | 90,000–162,000 |
| Emerald | 20,000 | 35,000 | 120,000–210,000 |
| Amethyst | 26,000 | 44,000 | 156,000–264,000 |
| Pearl | 32,000 | 54,000 | 192,000–324,000 |
| Obsidian | 40,000 | 66,000 | 240,000–396,000 |
| Diamond | 50,000 | 80,000 | 300,000–480,000 |

规则：

- `base_target = floor + (cap - floor) * anchor_percentile`，`anchor_percentile` 是该 anchor 在匿名 anchor 池中的分位。
- `anchor_seconds` 原值保留用于分位计算和审计；**不直接当 target**，否则 Bronze 会直接出现 147 小时对手。
- 周因子：普通周 `w = 0.90 + (hash(seed, week, "week") % 21) / 100`（0.90–1.10）；约 1/12 概率为低产周 `w = 0.55–0.75`。
- 普通周 `target = clamp(base_target * w, floor, cap)`；低产周允许低于段位下限，但仍 `>= 0` 且不超过 cap。这样 AI 会有真实低谷，而不是每周都贴着段位带。
- 每个 15 人组的 14 个 AI 使用**无放回分位**，例如 `8, 14, 22, 30, 38, 46, 54, 62, 70, 76, 82, 86, 90, 93` 百分位，再按 `hash(group_id, seed)` 稳定打乱。
- 保证每组至少 1 个 AI 在 30 分位以下、至少 1 个在 80 分位以上：既可爬，也有压力。
- 上限保证“不是无法战胜”：Bronze 最高 5,000 XP；用户做到 5,100 XP 就能压过最强 AI。下限保证“不是永远刚好压你”：AI 目标在周初就固定，不读取用户当前 XP/名次。

### 5.4 行为维度

| 维度 | 取值 | 作用 |
| --- | --- | --- |
| `archetype` | 6 种：稳态、夜航、周末、前段冲、碎片、间歇 | 决定日权重/时段形状 |
| `volatility` | 0.85–1.15 | 周与周之间的基线波动 |
| `burst` | 0–1 | 一周内 1 个高日的概率/强度 |
| `fatigue` | 0.60–0.90 | 高日之后次日的衰减 |
| `comeback` | 1.00–1.20 | 自己上周低产后，本周的恢复幅度；不相对用户 |
| `discipline` | 0.55–0.95 | 达到 100 XP 后是否稳定打卡、是否补签 |
| `pace` | 0.80–1.20 | 日内前段/后段分配 |
| `taste` | 固定枚举 | 称号/边框/背景的偏好；纯展示 |

**明确不做**：

- 不读取用户当前 rank/XP 来调 AI 今日目标。
- 不因为用户快追上就临时加速。
- 不预言未来周；不模拟加入前的周。
- 不把 AI 的 24 小时切片说成 WakaTime 逐小时数据。

### 5.5 每周计划

在周建立/加入时，仅对**当前周、当前小组**生成：

```text
for each opponent in group:
    anchor = pick_anonymized_anchor(tier, percentile_slot)
    base = tier_floor + (tier_cap - tier_floor) * anchor.percentile
    week_factor = 0.90 + hash(seed, week_start, "week") % 21 / 100
    target_seconds = clamp(round(base * week_factor), tier_floor, tier_cap)
    target_xp = target_seconds // 6
    persist opponent_week_plan(
        opponent_id, week_start, anchor_id, target_seconds, target_xp,
        percentile, seed, archetype, behavior_params, algorithm_version
    )
```

- 只生成当前周，不生成未来周。
- 没有 anchor 的对手不允许创建；宁可少一个 AI，也不凭空造能力值。
- 周中新建的小组按剩余天数等比缩减周目标，避免“周三加入却面对整周满额 AI”；真人只计加入时刻之后的增量；双方都不补算过去几天。
- `algorithm_version` 写入记录；以后改模型不重算旧周。

### 5.6 每日计划与状态机

**日切只生成“今天”**，不预生成周内未来日；用 `remaining_target` / `remaining_days` 保证周末刚好收敛到周目标。

| 状态 | 进入条件 | 当日行为 | 转出 |
| --- | --- | --- | --- |
| `RESTING` | 权重低 / 周日休息 | 目标 0–50 XP，不打卡 | 次日 `WARMUP` |
| `WARMUP` | 周初或低目标日 | 目标 <100 XP，可能错过打卡 | 达标则 `ON_PACE` |
| `ON_PACE` | 正常日 | 目标 ≈ 剩余均值 | 高目标转 `PUSH` |
| `PUSH` | burst 日 / 落后自己的周目标 | 目标 1.2–1.6× 均值 | 次日 `FATIGUED` |
| `FATIGUED` | 昨日 `PUSH` | 目标 ×0.60–0.90 | 恢复 `ON_PACE` |
| `COMEBACK` | 自己上周低产或连续 2 天低 | 目标 ×1.05–1.20，不超上限 | 恢复 `ON_PACE` |
| `MISSED` | 日终 <100 XP 且未补签 | 连胜断；次日可补签 | 次日 `WARMUP` |

伪代码：

```text
def advance_opponent(opponent, now):
    for day in elapsed_unsettled_days(opponent, now):
        plan = load_or_create_day_plan(opponent, day)
        # 日内按 sessions 推进；对外只展示已发生的段
        for session in plan.sessions:
            if now >= session.end:
                settled_seconds += session.seconds
        if day_closed(now, day):
            xp = settled_seconds // 6
            checked = settled_seconds >= 600
            if not checked and 6 <= settled_seconds < 600:
                if embers >= 1 and deterministic_roll(opponent, day, "repair") < repair_threshold:
                    spend_ember(opponent, day, 1)
                    mark_checkin(opponent, day, source="repaired")
                    checked = True
            update_streak(opponent, day, checked)
            grant_embers(opponent, day)       # 与人类同一公式
            award_milestones(opponent, day)   # 与人类同一张表
            persist_day_state(opponent, day)  # UNIQUE(opponent, date)，幂等
```

**日内总额分配**：

- 周目标固定后，每天只分配“剩余目标”。`base_daily = remaining_target / remaining_days`，再乘 archetype 日权重和当日行为因子。
- 取整数秒，且 `today_target <= remaining_target`；最后一天取剩余全部。这样不需要预生成未来日，也能保证周末精确收敛到周目标。
- 若当日是低产周/休息日，允许 `today_target=0`；不补算。

**日内段**：

- 每天 2–4 段，固定本地时段（如 09:00、14:00、20:30），由 archetype + pace 决定。
- 段内每秒推进；对外只显示“已发生”的累计，不显示未来目标。
- 段不是 WakaTime 采样；UI 文案为“AI 今日行动”。

### 5.7 可复现与持久化

- 所有随机决策来自 `BLAKE2b/HMAC(seed, week, day, purpose, counter)`，不用未固定种子的 `random`。
- `seed` 在创建对手时生成一次并持久化；同一 `opponent_id/week/day/purpose` 永远同一结果。
- 已结算的 `opponent_day_state`、`weekly_results` 不可变；代码升级不重算旧数据。
- 动态/名次由持久化状态计算，刷新页面不会“换一个对手”。
- 测试用固定时钟推进到任意时刻，结果应与真实懒加载一致。

### 5.8 避免假历史

- 新 AI 的 `joined_week = 当前周`，`weekly_results` 为空；详情页只显示“第 1 周”。
- 所有已建立的组（包括 AI-only 组）都按同一周循环结算；不会因为没有真人而跳过，也不预生成未发生的过去周。
- 没有 `opponent_week_plan` 的过去周不生成；没有 `weekly_results` 的周不展示。
- AI 的称号只来自它真实参与并结算的周，不预置“周冠”。
- AI 的 anchor 只用于当前/未来周强度，不倒推过去。
- 详情页明确“AI 对手 · 游戏行为模拟”；只展示 Channel roster 带来的公开显示名/头像，不显示城市、bio 或社交账号。

### 5.9 段位内公平

- 每个 AI 的目标在周初锁定；用户无法通过“少做一点”让 AI 也变弱。
- 每组 AI 分位分布固定；最强 AI ≤ 段位上限的 93 分位，用户可通过超过上限来确保战胜。
- AI 会低产、错过打卡、不补签；不是完美机器。
- AI 升降级与真人同一规则；不因为“剧情需要”保送。
- AI 角色有真实的跨周履历：随小组升降级后，`weekly_results` 继续累积；未进入活跃小组时暂停，不后台补算。
- 新加入真人只在 Bronze；不会直接遇到高段 AI。
- 组内没有“动态难度”；跨周强度只由段位和 anchor 决定。

---

## 6. 奖励与成长

### 6.1 原则

- 奖励是**额外解锁和展示**，不是把已有自由拿走再还。
- 不提供付费变强，不卖数值；物品/称号只影响展示。
- 不引入可购买货币；余烬只修打卡，不能买外观。
- 不做随机抽奖/开箱；解锁条件确定、可预期。
- 不用“断连胜扣东西”制造损失厌恶；错过就是错过，补签是可选修复。

### 6.2 里程碑（v1）

| 触发 | 永久称号 | 永久物品 | 展示 |
| --- | --- | --- | --- |
| 首次 100 XP 打卡 | `点火` | `余烬`（frame） | 首页名字下、小组行 |
| 连续 3 天 | `三日不息` | — | 称号 |
| 连续 7 天 | `七日不熄` | `夜航`（backdrop） | 称号 + 背景 |
| 首次周榜前 3 | `登台` | — | 称号 |
| 首次周榜第 1 | `周冠` | `冠军环`（badge accent） | 称号 + badge |
| 首次晋级 | `向上` | — | 称号 |

- “连续 7 天”可以包含补签；补签只补真实发生过的低 XP 日，不伪造周结果。
- 当前 v1 只发以上 6 个里程碑；完美周、累计参赛、累计 XP 等留给后续。
- 里程碑只发一次；`UNIQUE(player_id, milestone_id)`。已结算周重跑幂等。
- 新 epoch 不回溯旧 `checkins` / `weekly_results`；没有历史就不补发。
- 所有 v1 奖励永久；表里保留 `season_id NULL`，未来赛季只加限定外观，不回溯。
- 里程碑只发一次；`UNIQUE(player_id, milestone_id)`。

### 6.3 物品与称号

| 类型 | 槽位 | 是否可装备 | 影响 |
| --- | --- | --- | --- |
| 称号 `title` | 1 个 | 是 | 仅文字展示 |
| 头像边框 `frame` | 1 个 | 是 | 仅视觉 |
| 卡片背景 `backdrop` | 1 个 | 是 | 仅视觉 |
| badge 环 `badge_accent` | 1 个 | 是 | 仅 SVG 视觉 |

- 没有属性加成、没有 XP 加成、没有排名加成。
- 收藏页显示“已解锁/未解锁”和触发条件；未解锁不显示隐藏概率。
- 不能购买、不能交易、不能赠送；没有商店。
- 装备变更即时生效，不消耗资源。

### 6.4 AI 也有称号

- AI 与真人共用同一张里程碑表和判定逻辑。
- AI 只能获得它真实参与并结算的周/日对应的称号；新 AI 没有称号。
- AI 的称号在小组行、AI 详情、每日动态中可见，旁边始终有“AI”标签。
- AI 的 `taste` 决定它优先装备哪个已解锁称号/边框；每次周结算后更新一次 loadout，不影响数值。
- 不给 AI 专属“剧情称号”来假装它很强；称号必须是可验证的事件。

### 6.5 展示位置

| 位置 | 文件/接口 | 内容 |
| --- | --- | --- |
| 首页段位卡 | `web/index.html` 的 `tier-card` / `web/app.js` `renderProfile()` | 名字 + 装备称号 + 边框 |
| 小组榜行 | `web/app.js` `renderStandingsList()` | 称号 chip、今日 XP、连胜 |
| 个人/对手详情 | `/v1/users/{id}` + `web/app.js` `renderUserDetail()` | 称号、收藏数 |
| 历史卡 | `web/index.html` `history-page` / `renderHistory()` | 周 XP、名次、升降级、本周获得称号、补签数 |
| badge/embed | `ghost_league/badge.py` | 称号一行、XP、打卡、余烬；不显示秒 |
| 每日动态 | 新 `/v1/league/feed` | “AI 青灯-07 今日 210 XP / 补签 / 获得三日不息” |

### 6.6 不做的奖励

- 不做金币、钻石、点券、抽卡、商店、通行证、付费轨。
- 不做“连续 30 天送大量资源”的滚雪球。
- 不做称号属性、战力值、装备强化。
- 不做“掉段惩罚性扣除已获得外观”。

---

## 7. 目标架构

### 7.1 形态

**模块化单体 + SQLite**。不引入微服务、Redis、消息队列、分布式锁。

```text
web/ PWA (vanilla JS)
  │
  ▼
FastAPI routers (ghost_league/api.py 拆分)
  ├─ identity/auth  → AccountsStore (data/api/accounts.db)
  ├─ increments     → EventStore (data/api/events.db)
  ├─ game           → GameStore (data/league/league.db)
  │    ├─ calendar     日/周边界、锁、结算时点
  │    ├─ matchmaking  当前周 15 人组、AI 填充
  │    ├─ opponents    anchor、周计划、日状态机、动态
  │    ├─ checkin     打卡、补签、Ember 账本
  │    ├─ progression 里程碑、物品、称号、装备
  │    └─ settlement  周结算、升降级、历史
  ├─ badge/embed    → 只读 status 投影
  ├─ webhooks       → 独立 outbox
  └─ social         → 保留但本轮冻结
        │
        ▼
   WakaTime adapter (fetch.py + wakatime.py)
      → 公开周总量 → 匿名 anchor_pool（无姓名/头像）
```

**单一事实来源**：身份 = `accounts.db`；原始事件 = `events.db`；游戏状态 = `league.db`。不再保留 `membership.json` / `state.json` / `weeks.json` 这类可写镜像。跨库只通过 `user_id` 关联，不做跨库事务；周结算、补签、资源账本都以 `league.db` 内的事务为准。

### 7.2 模块边界

| 模块 | 职责 | 不允许 |
| --- | --- | --- |
| `game/rules.py` | XP 换算、段位带、组大小、升降级、余烬公式 | 不读 HTTP、不读 WakaTime |
| `game/calendar.py` | Asia/Shanghai 日/周锁、结算时点 | 不做业务判定 |
| `game/matchmaking.py` | 当前周分组、15 人填充、AI 选择 | 不生成未来周 |
| `game/opponents.py` | anchor→强度、周计划、日状态机、动态 | 不读用户实时 XP 来调难度 |
| `game/checkin.py` | 打卡、补签、连胜、Ember 账本 | 不写周名次 |
| `game/progression.py` | 里程碑、物品、称号、装备 | 不影响数值 |
| `game/settlement.py` | 周结算、升降级、历史、幂等 | 不重算已结算周 |
| `game/store.py` | SQLite schema/migrations/事务 | 不包含业务规则 |
| `api/*.py` | HTTP 投影、鉴权、错误码 | 不直接拼 SQL 业务 |
| `badge.py` | 只读 SVG/HTML | 不访问 token |
| `wakatime.py` / `fetch.py` | 公开数据缓存/抓取 | 不把 profile 给 AI/其他用户 |

### 7.3 表/实体草案

**保留**

- `accounts.db.users`：身份、token 哈希、显示名、头像、活动标签、icon_theme。
- `events.db.drawing_events`：原始增量；新增 `epoch_id`、`late` 字段（或新库新表）。

**新库 `data/league/league.db`**

```text
meta(key, value)                          -- schema_version, epoch_id, algorithm_version
epochs(id, started_at, reason, status)    -- reset 审计；不是赛季
players(id, kind, account_id, codename, joined_week, created_at, is_active)
anchors(id, source, source_key_hash, anchor_seconds, anchor_week, fetched_at, stale_weeks)
opponents(player_id, anchor_id, archetype, seed, volatility, burst, fatigue,
          comeback, discipline, pace, taste, created_at)
weeks(week_start, epoch_id, status, settled_at, rules_version)
groups(id, week_start, tier, group_no, created_at)
group_members(group_id, player_id, week_start, tier_at_start, is_human,
              joined_at, UNIQUE(group_id, player_id))
weekly_scores(week_start, player_id, group_id, seconds, xp, source,
              locked_at, rank, promoted, demoted, PRIMARY KEY(week_start, player_id))
weekly_results(week_start, player_id, group_id, tier, rank, xp, promoted,
               demoted, badges_json, repaired_days, post_settlement_repairs,
               clean_checkins, settled_at, PRIMARY KEY(week_start, player_id))
opponent_week_plan(opponent_id, week_start, anchor_id, target_seconds, target_xp,
                   percentile, seed, behavior_json, algorithm_version,
                   PRIMARY KEY(opponent_id, week_start))
opponent_day_state(opponent_id, date, week_start, target_seconds, target_xp,
                   settled_seconds, checkin_state, repaired, sessions_json,
                   state_json, settled_at, PRIMARY KEY(opponent_id, date))
opponent_events(id, opponent_id, week_start, date, kind, public_text,
                payload_json, created_at)
checkins(player_id, date, source, seconds, xp, checked_at, repaired_at,
         repair_cost, status, PRIMARY KEY(player_id, date))
streaks(player_id, current, longest, clean_current, last_checked_date, updated_at)
ember_ledger(id, player_id, week_start, delta, balance_after, reason, ref,
             idempotency_key UNIQUE, created_at)
ember_balance(player_id, balance, week_earned, week_start, updated_at)
milestones(player_id, milestone_id, awarded_at, week_start, payload,
           UNIQUE(player_id, milestone_id))
catalog_titles(id, name, description, permanent)
catalog_items(id, name, slot, description, permanent)
player_titles(player_id, title_id, awarded_at, season_id NULL,
              UNIQUE(player_id, title_id))
player_items(player_id, item_id, awarded_at, season_id NULL,
             UNIQUE(player_id, item_id))
loadouts(player_id, title_id, frame_id, backdrop_id, badge_accent_id, updated_at)
```

**关键约束**

- `weekly_scores` / `weekly_results` 以 `(week_start, player_id)` 唯一；结算用 `INSERT ... ON CONFLICT DO NOTHING`。
- `opponent_day_state` 以 `(opponent_id, date)` 唯一；懒结算幂等。
- `checkins` 以 `(player_id, date)` 唯一；补签不能覆盖自然打卡。
- `ember_ledger.idempotency_key` 唯一；余额只在账本事务里改。
- `group_members` 必须满足：每组 15 人（v1），AI 数 = 15 - 真人数；不允许中途移除 AI。
- 周中新增真人进入**新组**（当前周、14 个 AI），不通过移除已有 AI 塞进旧组；旧组名单周内不变。
- 组内排名按 seconds 降序，tie-break 用 `player_id` 升序，保证可复现。
- 升降级按组独立：每个组内成员按 seconds 降序、`player_id` 升序排名，`quota = max(1, round_half_up(group_size * 0.2))`；`weekly_results.promoted/demoted` 写该组结果，`rank` 仍写组内名次；不做 tier 汇总排名。
- 所有时间字符串统一 `Asia/Shanghai` ISO；周起点为周一。

### 7.4 API 变化

**原则**

- 请求里的 raw 数据仍可用 `seconds`（客户端测量的是秒）；**响应/展示只给 XP**。
- 后端只存 seconds；`xp = seconds // 6`。
- 旧 `/v1/me/drawing-increments` 保留为别名。
- 不在公开响应中出现 `seconds`、`minutes`、`ghost`、`synthetic`。

| 端点 | 现状 | 目标 |
| --- | --- | --- |
| `POST /v1/me/increments` | 返回 `week_total_seconds` | 请求仍收 `seconds`；返回 `accepted`、`duplicate`、`week_xp`、`today_xp`、`event_id` |
| `GET /v1/me/status` | `*_seconds` | `week_xp`、`today_xp`、`required_xp=100`、`ember_balance`、`ember_cap`、`equipped_title`、`rank`、`group_size`、`version` |
| `GET /v1/me/streak` | 含 `required_seconds` | `today_xp`、`required_xp`、`current_streak`、`clean_streak`、`repair`（可补日期/窗口）、`next_checkin_at` |
| `POST /v1/me/repair` | 不存在 | `{date, idempotency_key}` → `{repaired, embers_spent, balance, current_streak, history_marker}` |
| `GET /v1/league/standings` | `seconds` + ghost | `week_xp`、`today_xp`、`title`、`streak`、`checkin_state`；不暴露 `kind`/`is_ai` 或未来 target |
| `GET /v1/me/league` | `week_total_seconds` | 同上；保留 `next_update_at` |
| `GET /v1/league/history` | 52 周 state | 真实 `weekly_results`；`week_xp`、rank、tier、promoted/demoted、titles、repaired_days；加入前为空 |
| `GET /v1/league/feed` | 不存在 | 当前组最近 N 条 AI/真人事件；只读、无隐藏目标 |
| `GET /v1/me/collection` | 不存在 | 已解锁称号/物品、装备状态 |
| `PATCH /v1/me/loadout` | 不存在 | 装备 `title_id`/`frame_id`/`backdrop_id` |
| `GET /v1/users/{id}` | 可返回 WakaTime bio/city | 增加展示用称号/边框；不返回 `kind`/`is_ai`；AI 不返回 WakaTime 资料；真人 WakaTime 资料最多自己可见 |
| `GET /v1/me/profile` | 基本可用 | 增加 `equipped_title`；其余不变 |
| `GET /badge/{user_id}.svg` | 已有 | 路由不变；数据换 XP/称号/余烬；无秒 |
| `GET /embed/{user_id}` | 已有 | 同上 |

### 7.5 与现有账号/增量/PWA/badge 的兼容

| 对象 | 兼容策略 |
| --- | --- |
| `accounts.db` | 不动表结构；token 继续有效；新增 `equipped_title` 可选（也可放 `loadouts`） |
| 增量客户端 | `POST /v1/me/increments` 路径、Bearer、`event_id` 幂等、`occurred_at` 规则不变；只改响应字段。旧客户端若只读 `week_total_seconds` 会失效，需在 beta 内通知并升级 |
| `events.db` | 表保留；reset 时旧库归档，新建空库；不把旧周带入新 epoch |
| PWA | 同步更新 `web/app.js`、`web/index.html`、`web/sw.js` 缓存版本；旧缓存通过 `skipWaiting`/版本号清理；新 UI 不显示 AI 标签，只展示 XP/称号/边框 |
| badge/embed | URL 不变；只读展示；外部嵌入不破坏；新增称号行需要检查 260/280px 布局 |
| webhook | 签名/重试协议不变；新增 `checkin.repaired`；`streak.broken` 只在未补签时发；不发送 AI 内部 target |
| 文档 | `docs/API.md` 改为 XP 字段；README 保留技术沿革，但产品段改 AI 对手 |
| 命令 | `python -m ghost_league.league_cli` 旧 `bootstrap/report` 删除；新增 `reset/settle-week/seed-anchors/audit` |

### 7.6 reset 迁移步骤（设计，不在本轮执行）

**目标**：所有人从 Bronze 开始；只保留账号，不保留旧联赛/旧 ghost/旧 52 周；reset 可重复执行且不重复破坏。

**备份（先做，失败即停）**

```text
data/api/accounts.db                 # 账号/token 哈希：保留
data/api/events.db                   # 旧真实增量：归档
data/api/membership.json             # 旧组：归档
data/league/state.json               # 旧 52 周：归档
data/league/weeks.json               # 旧 52 周：归档
data/api/social.db                   # 冻结保留
data/api/webhooks.db                 # 订阅保留
data/cache/cn-978.json               # 公开榜缓存：只保留匿名锚点
data/cache/wakatime-profiles.json    # 公开资料：不进入 AI；可保留
data/api/avatars/                    # 头像：保留
```

- 用 `sqlite3 .backup` 或停服后复制；同时复制 `-wal`/`-shm` 一致性处理，不要只 `cp` 正在写的库。
- 不备份/不打印明文 token（如 `data/api/token`）；`accounts.db` 只有 token 哈希。
- 备份目录使用 0700；记录 SHA-256 manifest；不回显任何账号密钥。
- 备份/归档目录放在仓库外（如部署机的 backup 卷），或在 `.gitignore` 中显式排除；不要把 reset 归档变成新的未跟踪仓库文件。
- `PRAGMA integrity_check` 通过后才继续。

**清理/归档**

| 动作 | 对象 |
| --- | --- |
| 归档 | `data/league/state.json`、`weeks.json` → `data/archive/reset-<timestamp>/` |
| 归档 | `data/api/membership.json` |
| 归档 | 旧 `events.db`；新建空 `events.db`（或新 epoch 表） |
| 新建 | `data/league/league.db`（空 `epochs` + 一个 active epoch） |
| 不删 | `accounts.db`、avatars、TLS、deploy 配置、social/webhooks（冻结） |
| 脱敏 | `cn-978.json` 只留 `id`、`rank`、`seconds`、公开 `name`、`avatar_url`；不写入游戏库，stats/raw 周总量不外传 |

**幂等步骤**

1. `reset --dry-run`：只打印将备份/归档/清空的计数，不写任何东西。
2. `reset --to-bronze --confirm`：
   - 检查 `meta.epoch_id`；如果已存在 active epoch 且没有 `--force-new-epoch`，直接退出 0（幂等）。
   - 建临时 `league.db.tmp`，写 schema、epoch、`schema_version`。
   - `os.replace` 原子切换；旧库改名为 `league.db.old-<timestamp>`，不删除。
   - 写 `data/archive/reset-<timestamp>/receipt.json`（旧/新 epoch、计数、manifest hash）。
   - 失败则保留旧库和备份，输出回滚命令。
3. `seed-anchors --from data/cache/cn-978.json`：只插匿名 anchor；`INSERT ... ON CONFLICT DO NOTHING`。
4. 启动服务；首次请求时 `ensure_player` 创建真人 player；`matchmaking` 创建当前周 Bronze 组 + 14 AI。
5. 验证：
   - `SELECT COUNT(*) FROM groups WHERE week_start = current_week` = 1；
   - `group_members` = 15，`is_human=1` 的数量 = 真人数，AI = 15 - 真人数；
   - `weekly_results` = 0；`/v1/league/history` 返回空；
   - `/v1/me/status` 的 rank 在 1..15，`week_xp=0`，`ember_balance=0`；
   - `/badge/{id}.svg` 200。
6. 回滚：停服 → 恢复备份目录 → `os.replace` 回旧库 → 重启；回滚也写 receipt。

**注意**

- 本轮只设计，不执行任何 reset。
- 不在代码里硬编码 owner ID、个人路径、内网 IP；reset 命令从环境/参数取路径。
- 所有迁移在 `game/store.py` 里版本化；应用启动只做 `CREATE TABLE IF NOT EXISTS` + 显式 migration，不自动删数据。

### 7.7 独立性与隐私边界

- 产品不依赖任何个人工作流、个人目录、内网 IP、owner 账号；部署参数只从环境/未跟踪配置文件读取。
- owner 只是普通账号之一；不作为 AI 对手池、不参与难度调整、不拥有隐藏权限。
- AI 对手的行为只使用 WakaTime **公开周总量**；公开姓名/头像只进入 `channel_players.profile_json` 展示快照，不进入 `players` 表或计分输入，bio/city/社交账号不入库。
- 真人资料只来自 `accounts.db`；WakaTime profile 不向其他用户展示，AI 也不读取。
- `docs/`、`README.md`、`web/` 的示例统一用 `your-host.example` 和 `$LEAGUE_TOKEN` 占位，不出现真实主机、路径、令牌。
- 本轮不做多用户社交、支付、原生客户端、新外部数据源；`social.db` 保留但冻结。

---

## 8. 首个纵向切片

如果只做一条能验证循环的最小链路，按顺序做 **7 件事**。每件都能独立验收，但不做完整赛季/商店/社交。

### 8.1 切片清单

1. **新库与 epoch/reset**
   - `data/league/league.db` 建表；`meta.epoch_id`；`reset --dry-run` / `--confirm`。
   - 验收：重复 reset 不重复创建；`PRAGMA integrity_check` 通过。
2. **当前周分组**
   - 真人首次请求时创建 player；当前周 Bronze 组 15 人；14 个 AI 从匿名 anchor 池选。
   - 不做 52 周；不做未来周；AI 中途不替换。
3. **AI 周计划/日状态机**
   - anchor → 段位带 → 周目标；日切只生成今天；2–4 段行动；自动打卡；低产/疲劳/ comeback。
   - 验收：同一 seed/时间重复读取结果一致；刷新不换人。
4. **打卡 + 余烬补签**
   - 600 秒/100 XP 自动打卡；余烬公式、持有上限 3、每周最多新赚 2、7 天窗口、1–599 秒条件。
   - 人和 AI 同一套；补签只恢复连胜，不改周名次。
   - 验收：`POST /v1/me/repair` 幂等；余额不足/超窗/0 XP 被拒。
5. **周结算**
   - 周一 00:00 锁分、00:05 结算；按每组独立配额升降、写 `weekly_results`、建下周组。
   - 不做重放；旧周的 XP/rank/升降级不可变，补签元数据只追加。
6. **最小成长层**
   - 3 个称号 + 3 个物品；装备接口；首页/榜单/详情展示；AI 也按同一表获得一个称号。
   - 不做商店/货币/赛季。
7. **API/PWA 读面与文案**
   - status/standings/feed/history XP 化；补签入口；称号 chip；`badge.py` 称号行与装备边框。
   - 验收：UI 不出现 ghost/幽灵/synthetic/模拟/伪实时/分钟；也不出现 AI 可见标签。

### 8.2 验收命令（建议）

```bash
# 1. 纯逻辑/模型/补签/结算测试
python -m pytest tests/test_game_rules.py tests/test_opponents.py \
  tests/test_checkin_repair.py tests/test_settlement.py -q

# 2. reset 只读预演（不写数据）
python -m ghost_league.league_cli reset --to-bronze --dry-run

# 3. 固定时钟的确定性检查（同一 seed 两次输出 hash 相同）
python -m pytest tests/test_opponents.py -q -k deterministic

# 4. 起服务（不打印 token）
./scripts/run_api.sh
curl -sS "http://127.0.0.1:8095/health"
# 需要 token 时从环境读取，不 echo；兼容期脚本仍可读 GHOST_LEAGUE_TOKEN
curl -sS "http://127.0.0.1:8095/v1/me/status" \
  -H "Authorization: Bearer $LEAGUE_TOKEN"

# 5. PWA（HTTPS 入口）
./scripts/run_pwa.sh
# 浏览器：https://127.0.0.1:8445/
# 路径：首页 → 小组榜 → 历史 → 我的 → 设置/集成文档
```

浏览器手动验收：

- 首页：今日 XP、100 XP 打卡环、余烬余额、名次、AI 今日动态。
- 小组榜：15 人、称号、每组比例配额升降标记。
- 历史：空状态；结算后出现真实周，含补签标记。
- 我的：收藏/称号装备；装备后首页和榜单同步。
- badge：`/badge/<user>.svg` 显示 XP/称号，不显示秒。

### 8.3 本轮明确不实现

- 不写任何 `ghost_league/`、`web/`、`tests/`、`data/` 文件；不执行 reset；不部署；不 commit/push。
- 不做多用户社交、关注扩展、支付、原生客户端、新外部数据源。
- 不做 8 周赛季、通行证、商店、可购买货币、交易。
- 不补造任何过去周；不在加入时预生成未来周。
- 不改 WakaTime 抓取协议；只做入库前匿名化。

---

## 9. 风险与开放问题

### 9.1 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| AI 被看成“刚好压我”的假对手 | 用户看穿后失去信任 | 周初锁目标、不读用户实时分数、内部 kind 与分位带用于审计；提供 audit 命令 |
| 补签被刷 | 连胜/称号失真 | 1–599 XP 条件、7 天窗、每周 2 枚、余额 3、服务端事务、幂等键 |
| reset 丢账号/旧数据 | 不可逆损失 | 先备份、integrity check、归档不删除、dry-run、receipt、回滚 |
| 旧 PWA 缓存打新 API | 白屏/字段缺失 | 升 `sw.js` 版本、强制更新提示、保留一版字段映射或明确 beta 破坏性升级 |
| WakaTime 数据过期/不可用 | AI 没有锚点 | anchor pool 持久化、stale_weeks、无新数据不造；启动不依赖网络 |
| 命名迁移面过大 | 引入回归 | 先改产品文案，再做机械 rename；保留一版 env/header alias |
| 奖励变成“导演发糖” | 用户站到导演视角 | 称号只证明真实竞争事件；不做商店/货币；每日反馈优先于奖励动画 |
| 工作日/周末节奏不公平 | 用户觉得被算法针对 | 段位带 + 固定分位；不按用户在线时间调 AI |

### 9.2 需要拍板的 5 个问题（附推荐）

1. **产品名是否用 “Momentum League / 势能联赛”？**
   - 推荐：是。产品文案先换；`ghost_league` 包名/env 在单独机械提交中改，保留一版 alias。仓库 slug 可暂留。
   - 备选：继续用中性的“活动联赛”，不引入新品牌。

2. **补签是否允许 0 XP 的日子？**
   - 推荐：不允许。只允许 1–599 秒（有真实活动但未达 100 XP）。0 XP 若确需覆盖，另做“请假”，每月最多 1 次，且不计入“完美周”。
   - 理由：否则资源会变成“买连胜”，与真实代价冲突。

3. **reset 时旧 `events.db` 是保留还是归档？**
   - 推荐：归档旧库，新建空库；账号保留。这样新 epoch 从零开始，不把旧 XP 带进 Bronze。
   - 备选：保留事件但加 `epoch_id` 过滤；复杂度更高，首版不推荐。

4. **AI 的 WakaTime anchor 是否每周刷新？**
   - 推荐：可选刷新，默认沿用；只存匿名 `source_key_hash + anchor_seconds + anchor_week`。公开姓名/头像只作为 Channel profile 展示快照给前端，不传 bio 或 raw 周总量。
   - 理由：WakaTime 周更不稳定；刷新是增强，不是运行依赖。

5. **周结算时点与“周日补签”如何处理？**
   - 推荐：周一 00:00 锁分、00:05 结算；周日补签在结算后只恢复连胜/历史标记，不改上周名次。补签窗为 7 天。
   - 备选：结算延到周一 12:00；会让周一早上没有新周，反馈变慢，不推荐。

---

## 10. 追加决策：Player–Source 同构（用户 2026-10-28 口径）

> 本节优先于第 5 节的 anchor pool + 段位分位描述；下一版设计需要按本节重构 source 层，再重写第 5 节。

用户明确要求：**不要拿整张排行榜当一个隐形的对手池，再按段位生成特殊对手。** 每个 AI 是一个独立 Player，绑定排行榜上的一条具体 source row；真人和 AI 在球员层同构，只在数据源适配器上不同。

- 真人 source：绘画软件/本机增量 → `LocalIncrementSource`。
- AI source：WakaTime 排行榜的单个行（周总量）→ `LeaderboardSource`；每个 AI 有自己的 `source_key_hash`，不是整池随机取样。
- 两者都通过同一个 `ingest_activity` / `activity_events` 入口写入，联赛只读 `weekly_scores`；联赛结算不感知“AI 生成层”，只感知 player 和 source。
- `player.kind` 或 `source_kind` 可以用于 UI 的“AI 对手”标签和审计，但不要用两套计分/结算逻辑。
- WakaTime 公开榜只有周总量；单个 AI 的日/小时行为仍然是由该锚点派生的模拟，不是逐小时真实数据。对外说“AI 行为模拟”，不冒充 WakaTime 逐小时。
- 绑定稳定性：优先使用 WakaTime 缓存里的稳定 id 做 HMAC，不用 rank 或 display_name；row 消失时只能标 stale/freeze，不能静默换一个人。
- 网络：一次抓取整张榜快照后在本地绑定，不为每个 AI 发一次 HTTP 请求。
- 段位公平：原始 anchor 只作审计/分位，进入 Bronze 等段位仍要按段位带缩放；否则顶级 WakaTime 的周总量会摧毁低段。
- 仍需拍板：AI 是否每周重新绑定 source（身份连续 vs 每周换源）；WakaTime 单个用户是否有可用的公开日粒度 stats。若没有，日粒度只能派生。

---

## 11. 追加：Source 系统 / 游戏系统分离与 AI 行为 v1（2026-10-28，10/28 修正）

用户进一步明确：把排行榜接入看成**独立的数据源系统**，行为与 `duolingo-poller` 同类；游戏系统只消费它产出的活动/锚点。两层不要混。

**Source 系统（沿用现有投影，不新建 per-AI 抓取）**

- 现有 WakaTime 周榜快照 + `schedule.py` 的 168 小时投影保持不变；伪实时增量按小时产生，走和真实用户相同的增量入口。唯一的区别是数据来源不同，不是算法不同。
- 一次抓完整榜、缓存整张快照；初始化/重置时从缓存创建当前周需要的 AI player，每个 AI 绑定一条 source row；不做 per-AI 网络请求，不预生成未来/过去周。
- 源数据过期只标 stale，不造数；投影结果必须可复现。
- **XP 是外生的**：AI 的周总量/每小时增量由排行榜投影决定，行为层不生成、不改写 XP。

**游戏系统**

- `Player`：`id / kind(human|ai) / controller(human|ai) / source_id / source_key_hash / joined_week`。
- `Source` 只负责产生或更新活动锚点/增量；`Game` 只负责打卡、补签、分组、结算、里程碑。
- `controller` 与 `source` 分开：现在 AI 的 controller=ai、source=leaderboard；将来“AI 托管真人账号”只是 controller 换成 ai，source 仍是真人客户端，不需要第二套 player 模型。
- 人类和 AI 在球员/事件/结算层同构，标签只用于展示和审计。

**AI 行为 v1：反应式，不产生 XP**

行为输入 = 固定 seed + 已发生的 XP/排名/打卡状态 + 收藏 + 当日时间；行为输出只影响展示、关注关系、称号/外观、补签和动态文案。行为不能改变 XP、周名次或段位。只做 5 个确定性决策：

1. **今日反应**：根据最近 XP、排名变化、是否接近晋级/降级，决定今天的公开状态文案、是否活跃发言；不决定今天做多少。
2. **打卡/补签**：XP 达到 100 自动打卡；只有漏打卡且有 1–599 秒记录时，才按 seed + discipline 概率决定是否花余烬补签。补签只恢复连胜/历史标记，不改 XP/名次。
3. **关注/对手**：从同组选 1 个关注对象（按名次邻近/历史交集/最近 XP 变化），只影响动态文案和“关注”展示，不改分数或难度。
4. **称号/外观**：从已解锁收藏里按固定 taste + 最近 XP 档位选一套 loadout；纯展示，不影响数值。
5. **状态反应**：低产周后的 comeback、冲刺后的收束、错过后的 `MISSED`/`WARMUP`；用状态机输出展示和行为选择，不改 XP。

**固定与变化**

- 固定：seed、archetype、taste、discipline、关注偏好、称号偏好；这些让同一个 AI 跨周仍是同一个人。
- 变化：最近 XP、排名、连胜、补签记录、已解锁收藏；这些让行为随经历变化，但不会反过来伪造 XP。
- 复杂的是 source 稳定性、增量幂等和公平性，不是行为本身；v1 不做 LLM、不做实时策略、不做针对用户的动态难度。

---

## 12. 追加：社交表情 / 标签与身份投影（2026-10-28）

用户要求 AI 能对玩家“做表情、打标签”，就像给 issue 里的帖子打标签；关注某人的 AI 也会给被关注者打标签。AI 的行为逻辑**不能区分**对方是人还是 AI；但数据库必须保留 `kind`，因为“附近的人”仍只列真人。

**身份分层**

- 持久层：`players.kind = human | ai`、`controller = human | ai`、`source_kind` 保留，用于 `nearby`、审计、管理操作；公开 UI 不显示 AI 标签。
- 社交/行为投影：AI 只拿到 `PlayerPublic`（`id / 显示名 / 称号 / 最近 XP / 排名 / 连胜 / 标签 / 帖子`），**不含 kind**；AI 的关注、反应、标签选择不得读取 `kind`。
- `nearby` 查询显式 `WHERE kind = 'human'`；AI 不会出现在“附近的人”里。小组榜、动态、帖子也不显示 AI 标签。
- 这样“AI 不知道对方是不是人”和“系统知道谁是真人”同时成立：行为无偏，功能可过滤。

**社交对象与表（v1 最小集）**

```text
posts(id, player_id, day, kind, snapshot_json, created_at)
  -- 每日打卡/活动卡；v1 不开放自由发帖
reactions(post_id, actor_id, emoji, created_at,
          UNIQUE(post_id, actor_id, emoji))
tags(id, slug, label, color, description)
post_tags(post_id, tag_id, tagged_by, created_at,
          UNIQUE(post_id, tag_id, tagged_by))
follows(follower_id, target_id, created_at, UNIQUE(follower_id, target_id))
```

- 标签用**受控词表**，不是自由文本；避免注入、刷屏和不可渲染字符。
- 每个 AI 对同一帖子最多 1 个表情、最多 2 个标签；每条帖子最多展示 5 个标签。
- 只允许关注者给被关注者的帖子打标签；AI 不可以给自己打标签。
- 标签/表情只影响展示和动态，不影响 XP、排名、段位、资源或里程碑。
- 用户可隐藏某条标签的展示；不删除审计记录。

**AI 行为 v1 扩展**

- 关注：同组内选 1 个对象，按名次邻近/历史交集/最近 XP 变化；不读 `kind`。
- 表情：从固定 emoji 集合按 seed + 帖子内容（XP/连胜/排名）选一个；不区分人/AI。
- 标签：从受控词表里按最近 XP/连胜/排名/称号选 0–2 个；同一 AI 对同一对象每天最多一次。
- 称号/外观：从已解锁收藏里按 taste 选，纯展示。
- 资源：只在补签时使用余烬；不改 XP/名次。

**文案边界**

- AI 标签使用中性/正向词表（如“稳定”“夜航”“冲刺”“回归”），不做羞辱性标签；低产不自动贴负面标签。
- UI 中 AI 始终有 `AI` 标签；帖子上的标签旁边可显示“由某 AI 标记”，但 AI 的行为逻辑不因此看到 `kind`。
- “附近的人”只列真人；AI 只在联赛小组/动态/帖子里出现。

**Task 104 已实现的最小切片**

- 表实际为 `feed_events(id, player_id, kind, day, week_start, body, payload_json, created_at)`、
  `feed_reactions(event_id, actor_id, emoji, created_at)`、
  `feed_tags(event_id, actor_id, tag, created_at)`；三个唯一键保证重跑幂等。
- 事件只来自真实 `checkins`（`checkin`）和已结算的 `weekly_results`
  （`promoted` / `champion`），不开放自由发帖。`checkin` 事件用当日 XP 写入短句，
  不出现秒/分钟。
- AI 从事件作者所在小组里按 `hash(event_id + actor_id)` 排序，最多选 3 个 AI；
  每个 AI 最多 1 个表情、1 个标签。AI 在事件写入时一次性生成，之后新 AI 加入不补历史。
- 标签按事件证据限定：`checkin` 可用“稳 / 慢热 / 夜航 / 手稳”，`promoted` 可用
  “敢冲 / 苦行 / 手稳”，`champion` 可用“狠 / 爆发 / 敢冲”；零 XP 事件永不发“爆发”。
- 公开读模型为 `GET /v1/league/feed`；真人回应走
  `POST /v1/league/feed/{event_id}/reactions`，只对可见事件生效且同一表情幂等。
  可见范围是事件周同组成员、我关注的人和我自己；没有小组时只有自己。
- v1 不做关注流、AI 自动关注、评论、图片上传；反应/标签只影响展示。

---

## 13. 修正：排行榜源与 AI 的边界（2026-10-28）

用户指正：排行榜只是我们的数据源，**不应当知道 ghost/AI 的存在**；ghost 也不能回写排行榜。段位带如果落在 source 上，或把 raw anchor 整段替换成段位 target，都是把两个系统耦合了。

最终选择：**在源层做通用缩尾，不做 ghost debuff**。

- 不在 ghost 层对领先者打折。否则人类玩家拿第一时也会被 debuff，或只能做成人机两套规则，都是坏设计。
- 在**源数据进入联赛之前**做通用的 outlier 压缩：对所有外部周榜行使用同一条规则，压缩极端长尾；source 不知道 ghost、段位或用户分组。
- 原始快照仍保留审计；压缩值只作为联赛输入，不回写外部榜单。
- 人类自己的事件不经过这个外部源，所以拿第一不会吃 debuff；这不是“人机不同规则”，而是两种数据源各自的归一化。
- 压缩规则必须是单调的，避免大量顶部分数压成同一个值；具体分位/软上限先用当前 978 行数据模拟，给出前后对照表再定。
- task87 的“所有 AI 按段位带重算 target”方向撤回；先做源层缩尾，再决定是否还需要任何 ghost 层 cap。

下一步实现前，先在 source 层定义并测试缩尾；ghost 层不改 raw 排序语义。

## 附录 A：命名迁移表（内部）

| 旧 | 新 |
| --- | --- |
| `GHOST_COUNT` | `OPPONENT_COUNT` |
| `ghost_ids` | `opponent_ids` |
| `ghost_seconds` | `opponent_anchor_seconds` |
| `ghost_names` | `opponent_codenames` |
| `ghost_tiers` | `opponent_tiers` |
| `ghost_avatar_urls` | 删除旧全局头像表；AI 头像只从 Channel profile 读取 |
| `_load_ghost_avatars()` | 删除 |
| `_available_ghosts()` | `_available_opponents()` |
| `_place_user()` 的 ghost 填充 | `_place_human_with_opponents()` |
| `GHOST_LEAGUE_*` | `LEAGUE_*`（一版 alias 兼容旧名；品牌确定后再加 `MOMENTUM_*`） |
| `X-Ghost-*` | `X-League-*`（一版 alias） |
| `Ghost League API` | `Momentum League API` |
| `ghost_league` 包名 | `momentum_league`（独立机械提交；过渡期保留 import alias） |
| `synthetic` / `模拟` / `伪实时` | 产品文案删除；技术文档可说明历史 |

## 附录 B：本次只读核对

- 已读：`ghost_league/league.py`、`beta.py`、`history.py`、`generate.py`、`models.py`、`schedule.py`、`wakatime.py`、`fetch.py`、`leaderboard.py`、`api.py`、`accounts.py`、`badge.py`、`pwa.py`、`webhooks.py`、`social.py`、`themes.py`、`web/app.js`、`web/index.html`、`web/manifest.webmanifest`、`README.md`、`docs/API.md`、`tests/` 相关断言、`data/league/*.json` 的聚合统计、`data/api/membership.json` 的结构。
- 已跑只读测试：`python -m pytest tests/test_core.py tests/test_league.py -q`、`python -m pytest tests/test_api.py -q`，均通过。
- 已检查本机 gaming 技能目录：只有 Minecraft/Pokemon 服务器运维类 skill，没有只读文档型 gamification / game design skill；未安装任何可执行插件，改用 MDA / core loop / progression。
- 未读取/输出 token、账号密钥、真实用户隐私；未修改 live 数据。
