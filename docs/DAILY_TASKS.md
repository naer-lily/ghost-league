# 任务系统

Status: implemented, 2026-11-04.

## 范围

Ghost 自有任务系统只有三类任务：

| 来源 | 谁创建 | 完成方式 | 宝箱档位 |
| --- | --- | --- | --- |
| `daily_manual` | 当前用户在 Ghost 内配置 | 上传一张照片 | 难度 1/2/3 → 木/铜/银 |
| `repair` | Ghost 自动生成 | 系统条件（补签） | 木箱 |
| `weekend` | Ghost 自动生成 | 系统条件（周末 XP） | 星箱 |

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

## 每日手动任务

- `task_definitions` 保存用户定义；同一用户最多 20 条 active 定义。
- 读取任务列表时 `ensure_user_tasks()` 为每个 active 定义生成当天实例，
  幂等键 `daily:<definition_id>:<YYYY-MM-DD>`。
- 当天已有 **active** 实例时，`ensure_user_tasks()` 用当前定义的
  `title` / `description` / `difficulty` / `chest_tier` 同步该实例；编辑定义后
  下一次读取即生效，不需要手工改库。`completed` / `expired` 实例保留历史快照。
- 当天实例：`starts_at` = 当天 00:00，`ends_at` = 次日 00:00，
  `completion_mode='manual'`，`chest_tier=difficulty`。
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

## 宝箱

权威常量在 `ghost_league/game/tasks.py`：

| 档位 | 名称 | 钻石（闭区间） |
| --- | --- | --- |
| 1 | 木箱 | 3–6 |
| 2 | 铜箱 | 6–10 |
| 3 | 银箱 | 10–16 |
| 4 | 金箱 | 18–28 |
| 5 | 星箱 | 30–48 |

- 领取金额由服务端用 `secrets.randbelow` 在闭区间内均匀抽取；客户端不能传金额。
- 领取成功写 `diamond_ledger`：`reason='task_chest'`、`ref_type='task'`、
  `ref_id=<task_id>`、幂等键 `task-chest:<task_id>`、`boost=False`。
- 宝箱只出钻石，不产生 XP、不加经验倍率、不写 `weekly_scores`。
- 重复领取幂等返回原金额；到期未领取的宝箱作废。

## DSL 求值器

`ghost_league/game/tasks.py::evaluate_condition` 是系统任务的统一入口，只读
`GameStore`，不执行任意 Python，不使用 `eval`。

- 变量：`task.start`、`task.end`、`task.missed_date`、`now`
- 函数：`xp_between(start,end)`、`checkin_source(date)`
- 操作：`eq`、`gte`、`lte`、`and`、`or`、`not`、整数/字符串常量
- 未知变量/函数/操作、非法结构、超过递归深度或节点上限都 fail closed
  （返回 `False` 并记 warning）。

补断联和周末任务的条件都保存在 `task_instances.condition_json`，读取列表时评估。

## API 摘要

- `GET /v1/me/tasks`：生成并刷新当天任务，返回可见的 active/completed 任务。
- `POST /v1/me/tasks/{id}/complete`：手动任务拍照完成。
- `GET /v1/me/tasks/{id}/proof`：本人读取完成照片。
- `POST /v1/me/tasks/{id}/chest`：领取宝箱。
- `GET/POST/PATCH/DELETE /v1/me/task-definitions`：管理每日手动定义。

完整字段和错误码见 [`API.md`](API.md)。

## 前端

- 首页“任务”区按 `ends_at` 升序显示；没有任务时只留极简空态。
- 任务卡显示相对剩余时间，由 `/v1/me/tasks` 的 `server_now` 驱动；任务查询每
  30 秒刷新，倒计时本身每秒随服务端时间前进。
- 手动任务：隐藏 file input + `capture="environment"`；选图后先在浏览器里
  调用 `compressTaskProof()` 压到 ≤1MB（HEIC 解不了则原样交给服务端），
  压缩期间按钮显示“处理中…”，随后上传并显示“上传中…”，避免重复点击。
- 系统任务：显示进度，例如 `420 / 1000 XP`。
- active 的补断联任务显示“用余烬补”，点击调用既有的
  `POST /v1/me/repair`（`{date: missed_date, idempotency_key: ...}`）；成功后
  刷新任务和首页，提示“补上了。”，任务在下一次刷新时变为 `completed`，
  宝箱仍需用户手动领取。completed / expired 任务不显示该按钮。
- 完成后显示宝箱按钮，领取后轻量 dialog 显示钻石数。
- “设置”打开 `TaskSettingsDialog`，只管理每日手动定义，不出现 DSL、
  系统任务或宝箱档位。
