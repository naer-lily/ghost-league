# 任务系统

Status: implemented, 2026-11-04.

## 范围

Ghost 自有任务系统有五类任务：

| 来源 | 谁创建 | 完成方式 | 宝箱池 |
| --- | --- | --- | --- |
| `checkin` | Ghost 每天自动生成 | 系统条件（当天打卡） | `checkin` |
| `daily_manual` | 当前用户在 Ghost 内配置 | 上传一张照片 | 难度 1/2/3 → `daily_1/2/3` |
| `repair` | Ghost 自动生成 | 系统条件（补签） | `repair` |
| `weekend` | Ghost 自动生成 | 系统条件（周末 XP） | `weekend` |
| `weekly_chain` | Ghost 每周自动生成 | 系统条件（本周累计 XP） | `weekly_chain_1/2/3/4` |

用户只能配置每日手动任务的标题、描述和 1–3 难度；系统任务没有 DSL
编辑器，也不在设置里出现。所有任务按 `user_id` 归属，当前只有登录用户本人。

## 时间口径

- 每个任务都有独立的 `starts_at` / `ends_at`，按整点存。前端用
  `GET /v1/me/tasks` 返回的 `server_now` 计算相对剩余时间：`还剩 X 小时 Y 分`、
  不足 1 小时 `还剩 Y 分`、到点 `已到期`；不显示绝对截止时间，也不依赖手机时钟。
- 判定窗口是 `starts_at <= now < ends_at`；到 `ends_at` 即隐藏。
- 完成后到截止前仍显示；截止时未领取的宝箱变为 `forfeited`。
- 任务进度和系统条件统一走 `GameStore.daily_activity_on_day()` /
  `daily_xp_between()`。任务模块不另写 `checkins` 或 `channel_events`
  fallback。

## 每日打卡任务

- 每次 `tasks_for()` / `ensure_user_tasks()` 都幂等生成当天实例，`system_key`
  为 `checkin:YYYY-MM-DD`；没有 `definition_id`，用户不能在设置里编辑或停用。
- 字段固定：`title='每日打卡'`、`description='画满 10 分钟，开个小宝箱。'`、
  `difficulty=1`、`chest_tier=1`（占位）、`chest_pool='checkin'`、
  `sort_order=0`，`starts_at=当天 00:00`、`ends_at=次日 00:00`、
  `completion_mode='dsl'`。
- `condition_json` 为 `checkin_source(task.start) == 'verified'`。当天经 daily
  resolver 达到 `CHECKIN_SECONDS=600`（100 XP）并生成 verified 打卡后，读取
  任务列表时由 `refresh_task_states()` 自动完成，不另写事件监听或 cron。
- 它排在每日手动任务之前；完成后按前端现有规则处理，宝箱未领时留在原位。
- 部署前当天已经打卡的用户，部署后第一次读取即变成 `completed` +
  `chest_status='available'`。

## 每日手动任务

- `task_definitions` 保存用户定义；同一用户最多 20 条 active 定义。
- `task_definitions.sort_order` 决定每日任务组内顺序：新建为当前 active
  最大值 + 10；批量重排接口按数组顺序写 10、20、30…。旧库迁移时按原有
  `created_at, id` 顺序回填 10、20…。
- 读取任务列表时 `ensure_user_tasks()` 为每个 active 定义生成当天实例，
  幂等键 `daily:<definition_id>:<YYYY-MM-DD>`；实例也保存 `sort_order`。
- 当天已有 **active** 实例时，`ensure_user_tasks()` 用当前定义的
  `title` / `description` / `difficulty` / `chest_tier` / `chest_pool` /
  `sort_order` 同步该实例；编辑或重排后下一次读取即生效，不需要手工改库。
  `completed` / `expired` 实例保留历史快照，不改标题也不改顺序。
- 当天实例：`starts_at` = 当天 00:00，`ends_at` = 次日 00:00，
  `completion_mode='manual'`，`chest_tier=difficulty`（占位），
  `chest_pool=daily_<difficulty>`。
- 完成接口要求 `multipart/form-data` 的 `file` 图片；成功后
  `status='completed'`、`chest_status='available'`。
- 图片存到 `data/api/task-proofs/<user_id>/<task_id>.<ext>`，目录 700、
  文件 600；只允许本人按 task id 读取。
- 前端上传前先调用 `compressTaskProof()`：已不超过 1,000,000 字节的文件原样
  上传；更大的可解码图片按长边 2400 / 1600 / 1200 / 800、JPEG 质量
  0.9 / 0.75 / 0.6 / 0.45 逐档压到 ≤1MB，返回 `.jpg` + `image/jpeg`。
  浏览器无法解码（典型是 Chrome/Android 的 HEIC）时原样返回原文件，不报错，
  交给服务端转换。
- 支持 JPEG / PNG / WebP / HEIC / HEIF；HEIC/HEIF 用 pillow-heif 解码后
  迭代缩质量/尺寸转成 RGB JPEG，最终 proof ≤ 1,000,000 字节，仍以 `.jpg` +
  `image/jpeg` 存储，不保存原文件。客户端上传的 JPEG/PNG/WebP 原本
  ≤1MB 时保持原字节和格式；超过 1MB 的也转成 JPEG 并压到 ≤1MB。
  单文件上传上限 8 MB、总像素 ≤ 40 MP；空文件、非图片和超限都按 `415`
  拒绝，超过 8 MB 为 `413`。其他图片路径不因此接受 HEIC/HEIF。

## 补断联任务

- `ensure_repair_tasks()` 检查 `today-7 ... today-1` 这 7 个已结束日期；
  今天不算断联。
- 某天 `daily_activity_on_day(day).xp < 100` 且 `seconds > 0` 时生成一条
  `repair:<YYYY-MM-DD>` 任务；0 秒和已达到 100 XP 的日期不生成。
- 标题 `补断联 · MM/DD`，描述只写当天实际 XP。
- 任务 payload 的 `missed_date` 为该断联日的 ISO 日期；其他来源恒为 `null`。
  数据只从现有 `system_key=repair:<YYYY-MM-DD>` 解析，不新增表或接口。
- `starts_at` = 发现当天 00:00，`ends_at` = 被断联日 +8 天 00:00。
- 条件是该日期存在 `checkins.source='repaired'`；读取任务列表时自动完成，
  用户不需要再点完成。

## 周末任务

- 只在本地日期为周六或周日时生成 `weekend:<周六日期>`；周一起不再生成。
- `starts_at` = 周六 00:00，`ends_at` = 周一 00:00。
- 条件为周六、周日两天经 daily resolver 累计 XP ≥ 1000；自动完成。
- 标题 `周末 · 1000 XP`，描述 `周六周日累计 1000 XP。`。

## 周连续任务

- `ensure_weekly_chain_tasks()` 每次读取任务时调用；窗口固定为当前周一
  `00:00` 到下周一 `00:00`。`system_key` 为
  `weekly_chain:<week_start>:<step>`，每个阶段一条独立实例。
- 阶段表只在 `game_config.task_chain_weekly`，默认四段
  `1000 / 2000 / 3000 / 5000 XP`，每段指定一个 `chest_pool`。代码只保留
  默认值；阶段数、目标 XP 和阶段→池子映射都从配置读取，配置缺失或非法时
  回退到默认阶段表，不能 500。
- 同一周只物化一个当前段：已有 active 段时不重复生成；已有
  `completed + chest_status='available'` 段时挡住下一段；只有前面所有段都已
  `claimed` 时才生成下一段；全部段领取后不再生成第五段。
- 新段标题 `本周 <target> XP`，`completion_mode='dsl'`，条件为
  `xp_between(task.start, task.end) >= target`，`chest_pool` 取阶段配置。
  本周 XP 已超过目标时，生成后由 `refresh_task_states()` 立即完成，宝箱可领。
- 领取仍复用 `claim_task_chest()`，没有另一套奖励逻辑。已领取段不删除，
  留在同周的任务列表里；前端把它们沉到已完成区。跨周后旧段过期，新周从第
  1 段重新开始。
- `progress` 返回本周累计 XP / 当前段目标；前端对 `weekly_chain` 显示
  `1200 / 2000 XP`。任务设置页不提供连续任务编辑。

## 宝箱

权威常量在 `ghost_league/game/tasks.py`。实例生成时只写占位的
`chest_tier`；**完成时**按实例的 `chest_pool` 抽一次档位并写回
`chest_tier`，之后不再改变。已完成的旧实例不追溯重抽。

| 档位 | 名称 | 钻石（闭区间） |
| --- | --- | --- |
| 1 | 木箱 | 3–6 |
| 2 | 铜箱 | 8–14 |
| 3 | 银箱 | 18–30 |
| 4 | 金箱 | 45–70 |
| 5 | 星箱 | 100 或一颗普通星 |

池子存 `game_config.task_chest_pool_<pool>`，值是整数百分比的 JSON 权重，
按 1–5 档，总和必须为 100；缺省档位视为 0。默认池子：

```text
checkin   : 木70 铜25 银5  金0  星0
daily_1   : 木55 铜35 银10 金0  星0
daily_2   : 木35 铜35 银25 金5  星0
daily_3   : 木20 铜30 银35 金13 星2
repair    : 木60 铜30 银9  金1  星0
weekend   : 木0  铜15 银45 金30 星10
weekly_chain_1 : 木60 铜30 银10 金0  星0
weekly_chain_2 : 木30 铜40 银25 金5  星0
weekly_chain_3 : 木10 铜30 银45 金15 星0
weekly_chain_4 : 木0  铜0  银0  金0  星100
```

- 缺失、非 JSON、含未知档位、负值或总和不等于 100 时 fail closed：回退到该
  来源最保守的池子（`checkin` / `daily_1/2/3` / `repair` /
  `weekly_chain_1/2/3` → 木箱 100%，`weekend` → 铜箱 100%，
  `weekly_chain_4` → 星箱 100%），领取本身不会失败。
- 手动任务在 `complete_manual_task()` 抽档；自动任务在
  `refresh_task_states()` 变成 `completed` 时抽档。领取前再次刷新不会重抽。
- 领取时按档位决定内容：
  - 1–3 档：默认钻石；在本地时间 `task_chest_boost_cutoff_hour`（默认 21）
    之前，按 `task_chest_boost_chance`（整数百分比，默认 10）抽经验宝。
  - 4–5 档：永不出经验宝；5 档先按 `task_chest_star_chance`（整数百分比，
    默认 10）抽星，未命中则固定 100 钻。
- 经验宝时长读 `task_chest_boost_minutes`（默认 25）。出经验宝时把结果写进
  `task_instances.chest_reward_type='boost'`、`chest_boost_minutes`，不写
  `diamond_ledger`、不发钻石；21:00 及以后任何档位都不出经验宝。
- 经验宝复用 `diamond_boosts`：当前 buff 未过期就从原 `expires_at` 顺延，否则
  从领取时刻起算；倍率继续读 `diamond_boost_multiplier`（默认 2×），只作用于
  XP→钻石，不乘 XP、宿敌或下注派彩。
- 星箱命中星时创建一行 `player_stars`：`kind='normal'`、`season_key=NULL`、
  `source='task_chest'`、`price_diamonds=0`，名字与外观用现有
  `roll_star_rarity` / `roll_star_type` / `make_star_visual` /
  `generate_star_name` / `_new_catalog_code_with` 生成；`chest_star_id` 写回
  实例。重复领取返回同一颗星，不重复创建。
- 出钻石时写 `diamond_ledger`：`reason='task_chest'`、`ref_type='task'`、
  `ref_id=<task_id>`、幂等键 `task-chest:<task_id>`、`boost=False`；
  `chest_reward_type='diamonds'`，`chest_amount` 保持原字段。
- 配置缺失或非法（概率不在 0–100、时长 ≤0、缺失、非整数）时 fail closed：
  不出经验宝/星，仍按钻石档发，领取不能因此失败。
- 重复领取幂等返回同一 `reward_type` / `amount` / `boost_minutes` / `star`，
  不重复发 buff 或星；到期未领取的宝箱作废。
- 宝箱奖励不产生 XP、不写 `weekly_scores`。

## DSL 求值器

`ghost_league/game/tasks.py::evaluate_condition` 是系统任务的统一入口，只读
`GameStore`，不执行任意 Python，不使用 `eval`。

- 变量：`task.start`、`task.end`、`task.missed_date`、`now`
- 函数：`xp_between(start,end)`、`checkin_source(date)`
- 操作：`eq`、`gte`、`lte`、`and`、`or`、`not`、整数/字符串常量
- 未知变量/函数/操作、非法结构、超过递归深度或节点上限都 fail closed
  （返回 `False` 并记 warning）。

每日打卡、补断联、周末和周连续任务的条件都保存在
`task_instances.condition_json`，读取列表时评估。

## API 摘要

- `GET /v1/me/tasks`：生成并刷新当天任务与本周连续任务当前段，返回可见的
  active/completed 任务。
- `POST /v1/me/tasks/{id}/complete`：手动任务拍照完成。
- `GET /v1/me/tasks/{id}/proof`：本人读取完成照片。
- `POST /v1/me/tasks/{id}/chest`：领取宝箱，返回 `reward_type`、
  `boost_minutes`、`star`、`diamond_boost`。
- `GET/POST/PATCH/DELETE /v1/me/task-definitions`：管理每日手动定义。
- `PUT /v1/me/task-definitions/order`：按 `{"ids": [...]}` 批量保存每日任务顺序。

完整字段和错误码见 [`API.md`](API.md)。

## 前端

- 后端 `GET /v1/me/tasks` 只保证稳定数据顺序
  （`ends_at, sort_order, created_at, id`），不包含任何展示分组。
- 首页“任务”区在前端用 `useMemo` 对返回数组生成排序副本，不改原数组：
  先按 bucket 排，active 或 `completed + chest_status='available'` 为 bucket 0，
  其余 completed（宝箱已领取/作废/无宝箱）为 bucket 1 沉底；bucket 内按
  `ends_at`、`sort_order`、`id` 升序。未领取宝箱的 completed 任务留在原位，
  补断联、周末和周连续任务按各自截止时间参与排序。
- 设置里拖拽仍写 `sort_order`；重排后首页按新的 `sort_order` 生效，刷新保持。
- 没有任务时只留极简空态。
- 任务卡显示相对剩余时间，由 `/v1/me/tasks` 的 `server_now` 驱动；任务查询每
  30 秒刷新，倒计时本身每秒随服务端时间前进。
- 手动任务：隐藏 file input + `capture="environment"`；选图后先在浏览器里
  调用 `compressTaskProof()` 压到 ≤1MB（HEIC 解不了则原样交给服务端），
  压缩期间按钮显示“处理中…”，随后上传并显示“上传中…”，避免重复点击。
- 系统任务：显示进度，例如 `420 / 1000 XP`；每日打卡自动完成，不显示拍照按钮。
  周连续任务同样显示 `current / target XP`，标题为 `本周 1000 XP` 这类，
  不加“连续任务”解释；完成后下一段出现时仍按同一排序键占住原列表位置，
  已领取段按现有规则沉到已完成区并保留奖励标签。
- active 的补断联任务显示“用余烬补”，点击调用既有的
  `POST /v1/me/repair`（`{date: missed_date, idempotency_key: ...}`）；成功后
  刷新任务和首页，提示“补上了。”，任务在下一次刷新时变为 `completed`，
  宝箱仍需用户手动领取。completed / expired 任务不显示该按钮。
- 完成后任务卡显示“开宝箱”按钮；点击只打开 `ChestOpenDialog`，不直接领奖。
  弹层先显示合上的宝箱、任务标题和「开启 / 取消」；点「开启」后按钮禁用，
  宝箱轻抖/呼吸 0.5–0.7 秒，同时调用 `POST /v1/me/tasks/{id}/chest`。
  成功才进入揭晓态（箱盖打开、光晕扩散、奖励卡缩放出现），显示
  「经验宝 25 分钟」、「X 钻」或「星星：名字」，并允许「收下」；失败退出
  开启动画、显示 `describeApiError`，保留弹层供重试或取消。奖励只取 claim
  返回值，不展示池子、概率或档位说明，关闭弹层后不保留旧结果。
  `prefers-reduced-motion` 为真时跳过抖动和光晕，直接淡入结果；按钮和 API
  行为不变。开箱音效留 TODO，不在本单实现。
- 首页 buff 区按 `diamond_boost` 显示经验宝剩余时间；没有 buff 时不占位。
- “设置”打开 `TaskSettingsDialog`，只管理每日手动定义，不出现 DSL、
  系统任务或宝箱档位。
- 每日任务每行有独立拖拽手柄；用 Pointer Events 拖拽（不依赖 HTML5 drag，
  兼容 Android WebView）。松手后立即调用批量重排接口，失败回滚到拖动前顺序
  并提示；编辑、停用按钮与手柄分开，避免点按时误拖。
