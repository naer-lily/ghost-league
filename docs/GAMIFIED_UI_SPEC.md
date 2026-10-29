# 游戏化 UI 规格（GAMIFIED_UI_SPEC）

> 平台无关规范 · 适用于 Web/PWA 与 Android/Compose
> 本文件是设计真相；`web/` 与未来的 Android 工程是它的实现。
> 规范层变更必须先进本文件，再改实现。

| 项目 | 值 |
| --- | --- |
| 文档版本 | `1.0.0` |
| 状态 | 生效（Normative） |
| 更新日期 | 2026-10-29 |
| 适用平台 | Web/PWA、Android/Compose |
| 设计基准 | `concept_home.png`、`concept_league.png`、`concept_profile.png` 及对应生成参数 |
| 规范范围 | 首页、联赛、个人页、全局组件、token、文案、tooltip、平台映射、验收流程 |
| 不包含 | 后端规则、接口字段、数据迁移、Android 工程实现、PWA 实现 |
| 实现状态 | PWA：部分实现，存在待迁移差距；Android：未实现 |

## 60 秒读法

- **首页**：先看今天还差多少 XP，按一个按钮去行动，再顺手看自己在组里第几。
- **联赛**：看本周小组、结算倒计时、前 N 晋级 / 后 N 降级，以及“我”那一行。
- **个人页**：看头像框、称号、三项统计和收藏；外观不加数值，设置放最后。

---

## 0. 规范性语言与数值来源

### 0.1 关键词

| 词 | 含义 |
| --- | --- |
| **必须** | 强制要求。违反即验收失败。 |
| **应当** | 默认要求。只有记录在案的平台限制才能偏离，并要在实现记录里写明理由。 |
| **可以** | 允许的选择，不影响跨端一致性。 |
| **不得** | 明确禁止。 |
| **必须一致** | Web 与 Android 的实现值必须相同，或落在本表规定的同一档位内。 |
| **可调** | 允许实现按平台微调；调整后仍须满足同级关系、对比度和触控要求，并在实现记录中注明。 |

### 0.2 数值来源

本文件所有设计数值都来自下表来源。未标来源的数值按 `[S]` 处理，默认 **可调**；标为“必须一致”的除外。

| 代码 | 来源 | 本文件使用范围 |
| --- | --- | --- |
| `[C]` | 三屏概念稿生成参数：`home.json`、`league.json`、`profile.json` | 390×844 画幅、深海军蓝 `#0B1020`、薄荷绿 `#5CE0BE`、金色 `#F5C84C`、珊瑚色 `#FF6B6B`、28px 卡片、四 Tab、各屏信息顺序 |
| `[I]` | 现有 PWA：`web/style.css`、`web/DESIGN-NOTES.md`、`web/index.html` | 动效时长与缓动、部分组件尺寸、现有文案对照、390/1440 行为 |
| `[A]` | WCAG 2.2 与通用无障碍基线 | 文本 4.5:1、大字 3:1、焦点可见、减少动效、触控目标 |
| `[M]` | Material 3 / Jetpack Compose | `ColorScheme`、`Typography`、`Shapes`、`NavigationBar`、`TooltipBox`、48dp 触控 |
| `[R]` | `docs/AVATAR_FRAME_SPEC.md` | 头像框 `1.36D` 画布、`1.00D` 开孔、`1.08` 辉光 |
| `[S]` | 本规格的定稿决定 | 未列入 `[C]`/`[I]`/`[A]`/`[M]`/`[R]` 的尺寸、阈值、验收项 |

### 0.3 规范层与实现层

| 层 | 内容 | 允许的变更 |
| --- | --- | --- |
| **规范层（本文件）** | 语义 token、组件契约、页面信息结构、文案上限、tooltip 规则、跨端验收 | 只能通过版本化修改；先改 spec，再改实现 |
| **实现层（Web / Android）** | CSS、Compose、状态管理、资源加载、具体动画实现 | 可以在不改变语义、尺寸档位、文案和可访问性的前提下选择技术方案 |
| **数据层（API）** | XP、余烬、名次、结算、分组 | 不在本文件定义；UI 只消费字段，不自行改变游戏规则 |

---

## 1. 定位与原则

### 1.1 一句话定位

**多邻国暗色模式的轻快、饱满、游戏化：把用户当小孩哄着往前走，但不幼稚、不居高临下。**

只提炼方法：大目标、短句、即时反馈、明确的下一步、可预期的奖励。**不得**复制多邻国的品牌、角色、logo、角色台词或原文案。

### 1.2 五条原则

| 原则 | 必须做到 | 判断标准 | 反例 |
| --- | --- | --- | --- |
| **图标优先** | 功能入口先给矢量图标，再给短标签 | 390px 宽下，用户不读长句也能认出“首页/联赛/收藏/我的” | 用一段说明文字代替按钮；用 emoji 当唯一图标 |
| **短句** | 一屏只讲一个动作；状态句不超过 18 个字符 | 扫一眼就知道“现在差多少、下一步做什么” | “您的本周活动数据已成功完成同步” |
| **强反馈** | 每次有效行动都有即时、可感知的结果 | XP、火焰、名次、晋级至少有一项在 620ms 内给出回执 | 点完按钮毫无变化，等下一次轮询 |
| **低解释成本** | 规则放在需要它的位置；主界面不写说明书 | 用户不用离开当前屏就能理解为什么晋级/降级 | 首页堆三段规则；把关键状态藏进帮助页 |
| **可预期** | 同一动作、同一位置、同一反馈 | 按钮、导航、奖赏、错误的位置固定 | 同一功能今天叫“去画”，明天叫“开始创作” |

> 本表引用的 390px、18 字符、620ms 分别来自 2.3、4.1、2.5；对应上限为必须一致。

### 1.3 “把用户当小孩”的边界

这句话只描述**语气与信息密度**，不是能力侮辱：

- **是**：更少选择、更大按钮、更直接的因果、更具体的鼓励、更短的回执。
- **是**：用户做对时立刻说“点火成功”，做错时说“没连上。再试一次”。
- **不是**：叠字、奶音、“乖/宝宝/棒棒”、居高临下的说教。
- **不是**：用“为你好”的语气替用户做决定；不制造虚假损失，不用羞辱驱动。
- **不是**：把复杂规则删掉；规则要有，但放在 tooltip、帮助页或结算说明里。

“主人”只允许出现在问候语里，作为节奏和亲近感，不构成服务关系；任务、错误、奖励文案里不得称呼“主人”。

### 1.4 体验目标

| 目标 | 量化标准 | 来源/约束 |
| --- | --- | --- |
| 3 秒内回答“我在哪、我现在怎样、下一步做什么” | 首页第一屏同时出现问候、XP 环、主 CTA | `[C]` / 必须一致 |
| 每屏只有一个主操作 | 首页“去画一笔”；联赛“回到我 / 查看我的行”；个人页“设置”不是主操作 | `[S]` / 必须一致 |
| 反馈不打断阅读 | 庆祝浮层不超过 3s；一次状态更新只进入一个反馈序列 | `[I]` / 必须一致 |
| 不制造无意义运动 | 背景不循环漂浮；加载 spinner 只在加载时运行 | `[I][A]` / 必须一致 |
| 可离线理解 | 无网络时保留上一次数据，错误原因和重试入口同时可见 | `[I][A]` / 必须一致 |

### 1.5 反目标

- 不做通用 SaaS 仪表盘：不允许一排同权重卡片、表格化指标、灰色说明段落。
- 不做赌场：不用高频闪烁、虚假倒计时、随机奖励掩盖真实进度。
- 不做“成长系统说明书”：首页不解释完整规则，规则去 tooltip/帮助。
- 不做“可爱到不可读”：emoji、圆角、动效都不得牺牲对比度和信息密度。

---

## 2. 设计令牌

### 2.1 Token 分层

```text
原始色/字/尺寸
      ↓
语义 token（本文件的主表）
      ↓
组件 token（组件契约引用语义 token）
      ↓
实现层 CSS 变量 / Compose Theme 字段
```

组件不得直接写十六进制色值、字号或时长；只能引用语义 token。Web 的 CSS 变量名与 Android 的 `ColorScheme` / `Typography` / `Shapes` 字段都从同一张语义表映射。

### 2.2 色彩

#### 2.2.1 语义色表

| 语义 token | 值 | 用途 / 配对 | 最低对比度 | 来源/约束 |
| --- | --- | --- | --- | --- |
| `color.bg.canvas` | `#0B1020` | 页面底色；正文用 `text.primary` | 17.67:1 | `[C]` / 必须一致 |
| `color.bg.surface` | `#121A30` | 卡片、TopBar 实体底 | 16.11:1 | `[C][S]` / 必须一致 |
| `color.bg.raised` | `#1A2440` | tooltip、toast、底部面板 | 14.30:1 | `[S]` / 必须一致 |
| `color.bg.scrim` | `rgba(4,7,17,0.74)` | 模态遮罩 | 非文本 | `[S]` / 必须一致 |
| `color.border.subtle` | `rgba(167,179,209,0.14)` | 卡片 1px 描边、分隔线 | 非文本 | `[S]` / 必须一致 |
| `color.border.strong` | `rgba(167,179,209,0.55)` | 输入框、次级按钮、可交互容器 | 3.24:1 on raised | `[S]` / 必须一致 |
| `color.text.primary` | `#F4F7FF` | 标题、正文、数字 | 17.67:1 / 16.11:1 | `[I]` / 必须一致 |
| `color.text.secondary` | `#A7B3D1` | 辅助说明、未选中标签 | 9.03:1 / 8.23:1 | `[I]` / 必须一致 |
| `color.text.tertiary` | `#8491AD` | 微标签、时间、占位符 | 5.98:1 / 5.46:1 / 4.84:1 | `[S]` / 必须一致 |
| `color.text.onAccent` | `#071018` | 薄荷/金色/珊瑚填充上的文字 | 11.59:1 / 11.94:1 / 6.82:1 | `[S]` / 必须一致 |
| `color.action.primary` | `#5CE0BE` | 主 CTA、当前导航、进度弧 | 11.59:1 on canvas | `[C]` / 必须一致 |
| `color.action.primaryPressed` | `#46C7A7` | 主按钮按下 | 9.00:1 on canvas | `[S]` / 必须一致 |
| `color.action.primarySoft` | `rgba(92,224,190,0.16)` | 选中行、active chip 底色 | 非文本 | `[S]` / 必须一致 |
| `color.reward.primary` | `#F5C84C` | 连胜、奖牌、满环、奖励数字 | 11.94:1 on canvas | `[C]` / 必须一致 |
| `color.reward.soft` | `rgba(245,200,76,0.16)` | 奖励 chip、奖牌底 | 非文本 | `[S]` / 必须一致 |
| `color.warning.primary` | `#FF6B6B` | 降级区、危险操作、错误图标 | 6.82:1 on canvas | `[C]` / 必须一致 |
| `color.warning.primaryPressed` | `#E45555` | 危险按钮按下 | 5.17:1 on canvas | `[S]` / 必须一致 |
| `color.warning.soft` | `rgba(255,107,107,0.14)` | 降级行、错误提示底 | 非文本 | `[S]` / 必须一致 |
| `color.tier.current` | `#C88358`（青铜默认） | 当前段位强调；实际值随段位素材 | 4.99:1 on raised | `[C][I]` / 可调（逐段位） |
| `color.focus` | `#5CE0BE` | 2px 焦点环 | 11.59:1 on canvas | `[A]` / 必须一致 |

**用色规则：**

- 对比度按 WCAG 2.2 的 sRGB 相对亮度公式计算；表中取该 token 的最低配对。
- 薄荷绿只表示“现在可做/正在做/已选中”；金色只表示“奖励/连胜/满环”；珊瑚色只表示“降级/错误/危险”。不得混用语义。
- 珊瑚色不做大面积背景；只做 1px 边框、图标、文字和 `warning.soft` 底色。
- 金色不得做主 CTA，否则主操作和奖励争夺注意力。
- 不使用纯黑 `#000000` 或纯白 `#FFFFFF` 作为页面/卡片底色。
- 降级区用珊瑚色；单纯“名次下降”用金色 + 下箭头，避免把正常波动误读为危险。
- 文本对比度最低要求：正文 4.5:1，大字（≥24px 或 ≥19px 粗体）3:1；本表已给出关键配对。
- 可交互控件边界/焦点 ≥3:1；`border.subtle` 只做装饰分隔线，不单独承担控件边界。
- 珊瑚填充上只允许 `color.text.onAccent`，不得用白字（白字对比度 2.59:1）。

#### 2.2.2 语义别名

| 别名 | 指向 | 使用位置 |
| --- | --- | --- |
| `color.xp.track` | `rgba(255,255,255,0.10)` | XP 环轨道 |
| `color.xp.progress` | `color.action.primary` | XP 环进行中 |
| `color.xp.complete` | `color.reward.primary` | 满 100 XP 后的环 |
| `color.streak.lit` | `color.reward.primary` | 已点火火焰 |
| `color.streak.unlit` | `color.text.tertiary` | 未点火火焰 |
| `color.rank.promotion` | `color.action.primary` | 晋级区线/标签 |
| `color.rank.demotion` | `color.warning.primary` | 降级区线/标签 |
| `color.rank.me` | `color.action.primary` | “我”的行 |
| `color.skeleton` | `rgba(167,179,209,0.12)` | 加载占位 |
| `color.overlay.hover` | `rgba(255,255,255,0.06)` | 指针悬停 |
| `color.overlay.pressed` | `rgba(255,255,255,0.08)` | 按下 |
| `color.disabled.bg` | `rgba(255,255,255,0.06)` | 禁用容器 |
| `color.disabled.text` | `rgba(167,179,209,0.38)` | 禁用文字（不要求对比度） |

#### 2.2.3 PWA CSS 变量与 Compose 字段对应

| 语义 token | Web CSS 变量（目标） | 现有 CSS（迁移对照，不是规范） | Compose 字段 |
| --- | --- | --- | --- |
| `color.bg.canvas` | `--color-bg-canvas` | `--bg: #070a14` | `background` |
| `color.bg.surface` | `--color-bg-surface` | `--panel-solid: #11172c` | `surface` |
| `color.bg.raised` | `--color-bg-raised` | `--panel-raised` | `surfaceVariant` |
| `color.border.subtle` | `--color-border-subtle` | `--border` | `outlineVariant` |
| `color.border.strong` | `--color-border-strong` | `--border-strong` | `outline` |
| `color.text.primary` | `--color-text-primary` | `--text` | `onBackground` / `onSurface` |
| `color.text.secondary` | `--color-text-secondary` | `--muted` | `onSurfaceVariant` |
| `color.text.tertiary` | `--color-text-tertiary` | `--faint` | 自定义 `ghostColors.textTertiary` |
| `color.action.primary` | `--color-action-primary` | `--mint` | `primary` |
| `color.reward.primary` | `--color-reward-primary` | `--gold` | `secondary` + 自定义 `reward` |
| `color.warning.primary` | `--color-warning-primary` | `--danger` | `tertiary` + `error` |
| `color.tier.current` | `--color-tier-current` | `--tier` | 自定义 `ghostColors.tier` |
| `color.focus` | `--color-focus` | 未定义，复用 `--mint` | `primary`（焦点环） |
| `color.xp.track` | `--color-xp-track` | 组件内硬编码 | 自定义 `ghostColors.xpTrack` |

> 现有值仅用于迁移对照。目标实现以本表左列为准；现有 `#070a14`、24px 卡片圆角、5 个底部 Tab 都是实现差距，不是本规格的例外。

### 2.3 字体与排版

#### 2.3.1 字体家族与回退

| 角色 | Web 字体栈 | Android 字体 | 规则 |
| --- | --- | --- | --- |
| Display / 数字 / 标题 | `"Avenir Next Rounded", "Nunito", "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif` | `FontFamily.SansSerif`；平台提供圆体时使用其 rounded typeface 资源 | 圆体是增强，不是依赖；缺字时回退无衬线 |
| Body / UI | `"Avenir Next", "Segoe UI", "PingFang SC", "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif` | `FontFamily.SansSerif` | 中文优先系统字体，不下载远程字体 |
| 分数 / 数字 | `"DIN Alternate", "Bahnschrift", "Roboto", "SF Pro Rounded", sans-serif` | `FontFamily.SansSerif` + `FontFeatureSettings("tnum")` | 必须等宽数字；XP/名次/倒计时不跳动 |
| 图标 | 不使用字体图标 | Vector Drawable / Material Symbols 转 drawable | 功能图标必须是矢量，见第 3 节 |

- Web 不得通过 CDN、`@import` 或运行时下载字体；离线 PWA 必须保持同一字体栈。
- Android 不打包中文字体；使用系统 `sans-serif`，OEM 字体差异属于允许差异。
- 字重只用 `500 / 600 / 700 / 800`。正文 500，标签 600/700，标题 800。不得用 300 做正文。
- 中文字距默认 `0`；仅全大写英文微标签用 `0.06em`。数字用 `font-variant-numeric: tabular-nums`。

#### 2.3.2 字号层级

| Token | 390px 字号/行高 | 1440px 字号/行高 | 字重 | 字距 | 用途 | Web | Compose | 来源/约束 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `type.score` | 44 / 48 | 56 / 60 | 800 | -0.02em | XP 环数字、名次大数字 | `--font-score` | `displayLarge` | `[C][S]` / 必须一致 |
| `type.h1` | 28 / 34 | 32 / 40 | 800 | -0.01em | 页面主标题 | `h1` | `headlineLarge` | `[S]` / 必须一致 |
| `type.h2` | 22 / 28 | 24 / 30 | 800 | 0 | 卡片标题、组名 | `.card-title` | `headlineMedium` | `[S]` / 必须一致 |
| `type.title` | 16 / 24 | 16 / 24 | 700 | 0 | 行内姓名、TopBar 名称 | `h3` | `titleMedium` | `[S]` / 必须一致 |
| `type.value` | 16 / 20 | 16 / 20 | 800 | 0 | 榜单 XP、连胜数字 | `.value` | 自定义 `value` | `[S]` / 必须一致 |
| `type.body` | 16 / 24 | 16 / 24 | 500 | 0 | 正文、状态说明 | `body` | `bodyLarge` | `[S]` / 必须一致 |
| `type.bodySmall` | 14 / 20 | 14 / 20 | 500 | 0 | 辅助句、tooltip 正文 | `.body-sm` | `bodyMedium` | `[S]` / 必须一致 |
| `type.label` | 14 / 20 | 15 / 22 | 700 | 0 | 按钮、chip 值、tab | `button` | `labelLarge` | `[S]` / 必须一致 |
| `type.caption` | 12 / 16 | 12 / 16 | 600 | 0 | 元信息、zone 标签 | `.caption` | `labelMedium` | `[S]` / 必须一致 |
| `type.micro` | 11 / 16 | 11 / 16 | 700 | 0.06em（仅大写英文） | 眉题、角标、倒计时前缀 | `.micro` | `labelSmall` | `[S]` / 必须一致 |

**排版规则：**

- 390px 下正文行宽不超过 28 个中文字符；1440px 下正文栏宽不超过 560px。
- 按钮和 chip 内文字不换行；超长时截断标签，不截断数值。
- 姓名最多显示 12 个中文字符，超出用省略号；完整名称通过无障碍标签提供。
- 字体缩放：Web 支持 200% 浏览器缩放；Android 支持系统 `fontScale` 到 2.0。不得锁死字体缩放或裁切文字。
- 1440px 的 `type.h1`/`type.score` 升档只用于 PWA 宽屏；Android 手机用 390 列，平板 expanded 可用 1440 列。
- 行高是精确值，不用 unitless 行高替代；Web 用 `px`，Android 用 `sp`。

### 2.4 圆角、间距、阴影、描边、图标与触控

#### 2.4.1 圆角

| Token | 值 | 用途 | Web | Compose | 来源/约束 |
| --- | --- | --- | --- | --- | --- |
| `radius.xs` | 8 | 小标签、角标 | `--radius-xs` | `Shapes.small` 的局部覆盖 | `[S]` / 可调 |
| `radius.sm` | 12 | 图标容器、微型面板 | `--radius-sm` | `Shapes.small` | `[S]` / 必须一致 |
| `radius.md` | 16 | tooltip、输入框、toast | `--radius-md` | `Shapes.medium` | `[S]` / 必须一致 |
| `radius.lg` | 20 | 嵌套卡片、收藏 tile | `--radius-lg` | `Shapes.large` | `[S]` / 必须一致 |
| `radius.xl` | 28 | 主卡片、页面 hero、底部面板顶部 | `--radius-card` | `Shapes.extraLarge` | `[C]` / 必须一致 |
| `radius.full` | 999 | 按钮、chip、头像 | `--radius-pill` | `CircleShape` | `[S]` / 必须一致 |

- 主卡片固定 28px；现有 PWA 的 24px 是待迁移差距。
- 圆角不得随卡片宽度缩放；1440px 仍是 28px。

#### 2.4.2 间距

| Token | 值 | 用途 | 来源/约束 |
| --- | --- | --- | --- |
| `space.1` | 4 | 图标与文字的最小间隙 | `[S]` / 必须一致 |
| `space.2` | 8 | chip 内图标与标签、按钮图标与文字 | `[S]` / 必须一致 |
| `space.3` | 12 | 行内元素、收藏格间距 | `[S]` / 必须一致 |
| `space.4` | 16 | 卡片之间、卡片内区块 | `[S]` / 必须一致 |
| `space.5` | 20 | 390 页面边距、卡片内边距 | `[S]` / 必须一致 |
| `space.6` | 24 | 区块之间、1440 卡片内边距 | `[S]` / 必须一致 |
| `space.8` | 32 | 页面大区块、空态内边距 | `[S]` / 必须一致 |
| `space.10` | 40 | 1440 页面边距 | `[S]` / 必须一致 |
| `space.12` | 48 | 触控目标、图标按钮 | `[A][M]` / 必须一致 |
| `space.16` | 64 | 390 TopBar 高度、底部导航视觉高度 | `[I][S]` / 必须一致 |
| `space.20` | 88 | 1440 导航栏宽度 | `[S]` / 必须一致 |

#### 2.4.3 布局常量

| Token | 390px | 1440px | 用途 | 来源/约束 |
| --- | --- | --- | --- | --- |
| `layout.topbar` | 64 | 72 | 顶栏高度，不含状态栏 | `[I][S]` / 必须一致 |
| `layout.bottomnav` | 64 | — | 底部导航视觉高度，另加安全区 | `[C][I]` / 必须一致 |
| `layout.navrail` | — | 88 | 1440 左侧导航宽度 | `[S]` / 必须一致 |
| `layout.contentMax` | 350（视口减 40） | 1200 | 内容最大宽度 | `[S]` / 必须一致 |
| `layout.gutter` | 20 | 40 | 页面水平边距 | `[S]` / 必须一致 |
| `layout.cardPad` | 20 | 24 | 主卡片内边距 | `[S]` / 必须一致 |
| `layout.sectionGap` | 24 | 24 | 区块间距 | `[S]` / 必须一致 |
| `layout.cardGap` | 16 | 16 | 卡片间距 | `[S]` / 必须一致 |
| `layout.pageBottom` | 96 | 40 | 内容底部留白，避开导航 | `[S]` / 必须一致 |

#### 2.4.4 阴影与描边

| Token | Web 值 | Compose elevation | 用途 | 来源/约束 |
| --- | --- | --- | --- | --- |
| `shadow.none` | `none` | 0dp | 默认卡片使用描边而非阴影 | `[S]` / 必须一致（语义） |
| `shadow.card` | `0 8px 24px rgba(0,0,0,0.28)` | 2dp | 需要抬起的卡片 | `[S]` / 可调（平台渲染） |
| `shadow.overlay` | `0 20px 48px rgba(0,0,0,0.40)` | 6dp | tooltip、toast | `[S]` / 可调（平台渲染） |
| `shadow.modal` | `0 28px 64px rgba(0,0,0,0.50)` | 12dp | 底部面板、模态 | `[S]` / 可调（平台渲染） |
| `border.hairline` | 1px | 1dp | 卡片、输入框、次级按钮 | `[S]` / 必须一致 |
| `border.focus` | 2px | 2dp | `:focus-visible` / Compose focus indicator | `[A]` / 必须一致 |
| `divider` | 1px `color.border.subtle` | 1dp | 行分隔 | `[S]` / 必须一致 |

- 深色主题优先用“表面色 + 1px 描边”建立层级；阴影是增强，不是唯一层级手段。
- Android 允许用 tonal elevation 替代 Web 阴影，但卡片表面色、描边和圆角必须保持。

#### 2.4.5 图标与触控尺寸

| Token | 值 | 用途 | 来源/约束 |
| --- | --- | --- | --- |
| `icon.xs` | 16 | chip 内图标、行内状态 | `[S]` / 必须一致 |
| `icon.sm` | 20 | 按钮内图标、火焰、奖牌 | `[S]` / 必须一致 |
| `icon.md` | 24 | 导航、TopBar 动作、tooltip 触发 | `[M]` / 必须一致 |
| `icon.lg` | 32 | 卡片角标、次级空态 | `[S]` / 可调 |
| `icon.xl` | 40 | BadgeTile 预览 | `[S]` / 可调 |
| `icon.hero` | 48 | 空态、段位 hero | `[S]` / 可调 |
| `icon.stroke` | 2（24 网格）；1.5（16/20） | 线性图标描边 | `[S]` / 可调（1.5–2） |
| `touch.min` | 48 | 所有可点击目标的最小正方形 | `[A][M]` / 必须一致 |
| `touch.gap` | 8 | 相邻触控目标最小间距 | `[A]` / 必须一致 |
| `avatar.sm` | 36（390）/ 40（1440） | TopBar、榜单行 | `[S]` / 必须一致 |
| `avatar.md` | 48 | 邀请、设置行 | `[S]` / 必须一致 |
| `avatar.xl` | 96 | 个人页头像 | `[S]` / 必须一致 |

- 视觉 icon 可以 16/20/24，但可点击容器必须是 48×48；视觉尺寸小不代表触控目标小。
- 头像框按 `[R]`：框体画布 `1.36D`、开孔 `1.00D`、辉光 `1.08 × 1.36D`；头像本体仍按 `D` 圆形裁切。
- 触控目标之间至少 8px/dp；底部导航每项至少 64×48。

### 2.5 动效

#### 2.5.1 时长与缓动

| Token | 值 | 缓动 | 用途 | 来源/约束 |
| --- | --- | --- | --- | --- |
| `motion.press` | 90ms | `ease-standard` | 按钮按下缩放/覆盖 | `[S]` / 必须一致 |
| `motion.fast` | 140ms | `ease-standard` | hover、focus、开关、焦点 | `[I]` / 必须一致 |
| `motion.base` | 240ms | `ease-out` | 卡片进入、chip 出现、tooltip | `[I]` / 必须一致 |
| `motion.slow` | 420ms | `ease-out` | 列表首次进入、刷新图标 | `[I]` / 必须一致 |
| `motion.score` | 620ms | `ease-out` | XP 数字、进度环、周累计条 | `[I]` / 必须一致 |
| `motion.celebrate` | 900ms | `ease-out` | 庆祝高光关键帧 | `[I]` / 必须一致 |
| `motion.confetti` | 1300ms | `ease-out` | 彩带粒子生命周期 | `[I]` / 可调（1200–1400） |
| `motion.overlayHold` | 3000ms | — | 高光浮层停留 | `[I]` / 可调（2500–3000） |
| `motion.toast` | 2800ms | — | 普通 toast 停留 | `[I]` / 可调（2400–3200） |
| `motion.toastAction` | 4000ms | — | 带操作 toast 停留 | `[S]` / 可调（3500–4500） |
| `motion.stagger` | 24ms/行，最多 8 行 | — | 列表首次进入 | `[S]` / 可调（20–28） |
| `motion.tooltipShow` | 120ms | `ease-out` | tooltip 出现 | `[S]` / 可调 |
| `motion.tooltipHide` | 80ms | `ease-standard` | tooltip 消失 | `[S]` / 可调 |

**动效参数：**

| 参数 | 值 | 用途 | 来源/约束 |
| --- | --- | --- | --- |
| `motion.enterOffset` | 8px/dp | 页面/卡片进入时的上移距离 | `[S]` / 可调（8–12） |
| `motion.pressScale` | 0.98 | 按钮按下缩放 | `[S]` / 必须一致 |
| `motion.flamePulse` | 240ms | 火焰一次性脉冲 | `[S]` / 必须一致 |
| `motion.confettiParticles` | 24–64 | 一次庆祝的粒子数上限 | `[I]` / 可调 |
| `motion.reducedDuration` | 1ms | reduced-motion 下的动画时长 | `[A]` / 必须一致 |

缓动曲线必须一致：

```text
ease-standard = cubic-bezier(0.20, 0.70, 0.20, 1.00)
ease-out      = cubic-bezier(0.22, 1.00, 0.36, 1.00)
ease-spring   = cubic-bezier(0.34, 1.56, 0.64, 1.00)   # 只用于 chip/火焰的轻回弹
```

Compose 对应 `CubicBezierEasing(0.20f, 0.70f, 0.20f, 1.00f)` 等；弹簧曲线不得改变持续时间档位。

#### 2.5.2 三档动效

| 档位 | 时长 | 内容 | 规则 |
| --- | --- | --- | --- |
| **进入（Enter）** | 240ms；列表 420ms | 页面/卡片淡入 + 8px 上移；列表首次 stagger | 只在首次进入；不能每次轮询重播；最多 8 行；总时长不超过 420ms |
| **反馈（Feedback）** | 90 / 140 / 240 / 620ms | 按压、hover、焦点、chip、火焰、XP 数字/环 | 一次状态更新只进入一个反馈序列；数字和环同时开始、同时结束 |
| **庆祝（Celebrate）** | 900 / 1300 / 3000ms | 晋级、首次打卡、首次小组第一：高光浮层 + 有限彩带 | 同一时刻最多 1 个高光；彩带 24–64 粒、1300ms；浮层 3s 后收起；不循环 |

**反馈优先级**（从高到低）：

1. 段位晋级
2. 今日首次打卡
3. 首次小组第一
4. 其他变化：XP 芯片、排名芯片、连胜芯片、行位移

一次更新只执行最高优先级的一个庆祝序列；低优先级变化不叠加彩带。

#### 2.5.3 性能与可预期

- 只动 `transform` / `opacity`；进度环动 `stroke-dashoffset` 或 Compose `Canvas` 的进度值，不触发布局。
- 不在 `requestAnimationFrame` 中读取布局；不循环播放背景粒子、视差、呼吸光。
- 加载 spinner 是唯一允许循环的动画，且只在加载时运行；页面不可见时暂停。
- 数字和环必须使用同一时长（620ms）；更新中断时从当前值继续，不回到 0。
- 任何状态更新都可以被下一次更新打断；旧动画不得覆盖新状态。

#### 2.5.4 减少动效

**Web/PWA：**

- 必须响应 `@media (prefers-reduced-motion: reduce)`：所有动画/过渡压到 1ms；移除位移、缩放、火焰脉冲和彩带；进度环和数字直接写终值。
- 高光浮层在 reduced-motion 下仍显示静态文字，3s 后收起；信息不丢失。
- `scroll-behavior: auto`；不自动播放视频/Canvas 庆祝。
- 页面隐藏（`visibilitychange`）时停止轮询、动画和 Canvas。

**Android/Compose：**

- 必须读取 `LocalMotionDurationScale.current.scaleFactor`：`0f` 时直接写终值，不使用动画；`0 < scale < 1` 时按时长乘算；不得覆盖系统设置。
- 系统“移除动画”/Animator duration scale 为 0 时，等同 `scaleFactor = 0`；彩带、脉冲、进度动画全部跳过。
- `animate*AsState` / `Animatable` 必须走同一时长 token；自定义 `Canvas` 动画也要检查 scale factor，不能绕过。
- 减少动效时保留静态高光卡片、静态进度环和所有文字；不得把状态藏起来。

---

## 3. 图标与 emoji

### 3.1 功能图标

| 项目 | 规则 | 来源/约束 |
| --- | --- | --- |
| 来源 | Web 用内联 SVG 或现有本地 assets；Android 用 Material Symbols Rounded 或 vector drawable | `[S]` / 必须一致 |
| 网格 | 24×24 viewBox；所有图标按同一网格绘制 | `[M]` / 必须一致 |
| 线宽 | 24 网格 2px；16/20 视觉尺寸用 1.5px | `[S]` / 可调（1.5–2） |
| 端点 | 圆头 `stroke-linecap: round`；圆角连接 `stroke-linejoin: round` | `[S]` / 必须一致 |
| 内角 | 拐角半径 2px（视觉） | `[S]` / 可调 |
| 颜色 | Web `currentColor`；Android `tint`；不得硬编码多色 | `[S]` / 必须一致 |
| 填充 | 默认线性；选中/已获得/奖牌用填充；错误可线性 + 珊瑚色 | `[S]` / 必须一致 |
| 可访问名 | 图标按钮必须有 `aria-label` / `contentDescription`；装饰图标隐藏 | `[A]` / 必须一致 |
| 禁止 | 不用字体图标承担关键导航；不用 emoji 代替功能图标；不混用两套线宽 | `[S]` / 必须一致 |

**尺寸：**

| 场景 | 视觉尺寸 | 容器/触控 | 备注 | 来源/约束 |
| --- | --- | --- | --- | --- |
| 行内状态、chip | 16 | 48（如可点） | 与 11–14px 文字对齐 | `[S]` / 必须一致 |
| 按钮、火焰、奖牌 | 20 | 按钮高度 48/52 | 与 14px 标签对齐 | `[S]` / 必须一致 |
| 底部导航、TopBar 动作 | 24 | 48×48 | 导航图标固定 24 | `[M]` / 必须一致 |
| 空态/错误 | 48 | 64 圆形底 | 不参与点击 | `[S]` / 可调 |
| 段位/头像框 hero | 48–64 | 随容器 | 保持 1.36D 框比例 | `[R]` / 可调 |

**线性 vs 填充：**

- 默认动作：线性。
- 当前导航、已选中 tab、已装备：填充。
- 前三名奖牌、已获得徽章：填充 + 金色/银色/青铜色。
- 错误/降级：线性 + 珊瑚色，不靠填充制造恐慌。
- 同一图标不得一半线性一半填充；同一屏内同功能只出现一种。

### 3.2 emoji

emoji 只做情绪/氛围，不承担唯一语义。下表的数量上限为 `[S]`，必须一致。

| 规则 | 要求 |
| --- | --- |
| 数量 | 每个组件最多 1 个装饰 emoji；每屏最多 2 个；TopBar、BottomNav、按钮、tooltip、错误提示中不得使用 |
| 语义 | emoji 旁边必须有文字或矢量图标；去掉 emoji 后信息不丢失 |
| 无障碍 | emoji 节点 `aria-hidden="true"` / `contentDescription = null`；不进入可访问名 |
| 动作区分 | 同一动作不得只靠 emoji 区分（如“继续/补签/分享”必须有不同矢量图标和文字） |
| 品牌 | 不用品牌角色、logo、猫头鹰、多邻国相关形象 |
| 世界观 | 不用幽灵、亡者、冥界、转世、灵魂等设定词/形象；不用 👻 💀 |
| 敏感 | 不用货币、武器、旗帜、宗教、身体部位、指人手势、性别/种族刻板形象 |
| 失败场景 | 错误/降级不用 😂 🤖 ⚠️ 作为唯一提示；必须用矢量图标 + 文字 |

**白名单原则（可以用于装饰）：**

- 庆祝：✨ 🎉
- 鼓励：💪
- 火焰：🔥（只在连胜数字旁，数字始终可见）
- 创作：🎨（只在收藏/创作语境，不替代收藏图标）
- 成长：🌱（只在“本周进步”类静态装饰）

**黑名单原则（不得使用）：**

- 👻 💀 🧟（世界观/死亡）
- 🤖（AI/机器人）
- 💰 💎（货币/付费暗示，产品没有可购买货币）
- 🔫 🩸（暴力）
- 🫵 👉（指人/冒犯）
- 任何旗帜、宗教符号、身体部位、性别/种族刻板 emoji
- 任何单独承担“成功/失败/晋级/降级”语义的 emoji

### 3.3 Android emoji 与无 emoji 回退

- Android 的 emoji 字形随 OEM 字体变化，**不得**把 emoji 作为功能图标的唯一实现。
- 功能图标必须有 vector drawable 回退；emoji 只放在独立 `Text` 节点，允许在字体不支持时隐藏该节点。
- 可以使用 `EmojiCompat` 提升一致性，但不得依赖下载字体；未初始化或字形缺失时，布局不得出现 tofu 方块。
- 验收至少覆盖一台非 Pixel OEM 字体环境（或关闭 emoji 字体的模拟环境）；去掉 emoji 后，所有状态和动作仍可识别。
- TalkBack 不朗读装饰 emoji；功能图标的 `contentDescription` 不包含 emoji 名称。

---

## 4. 文案与语气

### 4.1 长度上限

字符按“可见字符”计（含数字、空格；不含句末标点）。英文按独立上限。

| 元素 | 中文上限 | 英文上限 | 行数 | 来源/约束 |
| --- | --- | --- | --- | --- |
| 主按钮 | 6 | 14 | 1 | `[S]` / 必须一致 |
| 次按钮 | 8 | 18 | 1 | `[S]` / 必须一致 |
| 图标按钮可访问名 | 8 | 20 | 1 | `[S]` / 必须一致 |
| 页面标题 | 10 | 24 | 1 | `[S]` / 必须一致 |
| 卡片标题 | 10 | 24 | 1 | `[S]` / 必须一致 |
| 状态句 | 18 | 40 | 2（390） | `[S]` / 必须一致 |
| 辅助句 | 24 | 56 | 2 | `[S]` / 必须一致 |
| tooltip 标题 | 10 | 24 | 1 | `[S]` / 必须一致 |
| tooltip 正文 | 60 | 140 | 3，每行 20 中文字符 | `[S]` / 必须一致 |
| toast | 18 | 40 | 1 | `[S]` / 必须一致 |
| 空态标题 | 10 | 24 | 1 | `[S]` / 必须一致 |
| 空态正文 | 30 | 64 | 2 | `[S]` / 必须一致 |
| chip 标签 | 6 | 14 | 1 | `[S]` / 必须一致 |
| 姓名显示 | 12 | 24 | 1，超出省略 | `[S]` / 必须一致 |

- 卡片内不得出现超过 2 行的说明段落；规则超过 3 行时改用帮助页/底部面板，不塞进 tooltip。
- 主按钮只写动作，不写对象解释；例如“去画一笔”，不写“点击这里开始记录你的创作时间”。
- 任何文案不得为了凑长度写“请”“稍后”“系统正在处理”。

### 4.2 语气

| 维度 | 要求 | 好例子 | 坏例子 |
| --- | --- | --- | --- |
| 短 | 一句话只做一件事 | “再 40 XP，点火。” | “您当前距离今日目标还差 40 XP，继续努力即可完成打卡。” |
| 直接 | 用动词开头，少用被动 | “去画一笔”“查看完整榜” | “榜单详情可在此处进行查看” |
| 有戏剧性 | 用具体动作制造节奏：点火、上场、追上、守住、反超 | “火没灭。明天见。” | “继续保持良好的连续记录。” |
| 鼓励不谄媚 | 给具体下一步，不空夸 | “再 25 XP，超过前面那位。” | “你太棒了！你是最厉害的！” |
| 不居高临下 | 平视，短句，不训话 | “没连上。先看旧榜。” | “请检查您的网络连接后重试。” |
| 不幼稚 | 可以俏皮，但不奶音 | “早早早，主人！”（仅问候） | “宝宝今天也要乖乖画画哦～” |

**节奏：**

- 问候允许三连节奏：“早早早，主人！”；只用于首页早晨问候。其他时段用“下午好，画手。”“晚上好，画手。”，不重复“主人”。
- 奖励句用“结果 + 下一步”，不使用空洞感叹号：“点火成功。火焰 +1。”
- 一屏最多 1 个感叹号；不得出现“！！！”或连续感叹句。
- 不写“加油”“冲鸭”作为唯一鼓励；必须带具体差距或动作。
- 不写“恭喜您”“感谢您的使用”等客服腔。

### 4.3 禁用与避免

以下词只用于本规范的黑名单检查，**不得进入任何 UI 文案、按钮、toast、tooltip、空态、错误提示**。

| 类别 | 禁用词/表达 | 原因 | 替代 |
| --- | --- | --- | --- |
| 世界观/内部身份 | 幽灵、ghost、AI、机器人、模拟、synthetic、真人、伪实时、channel、ingest、player_ref、kind、source | 暴露实现或世界观设定，破坏产品语气 | 用“小组”“榜单”“对手”“同组的人”（如业务允许） |
| 系统/说明书腔 | 用户、您、系统、服务器、接口、数据库、算法、检测到、同步失败、请稍后、请重试 | 距离感、模板化、把责任推给系统 | “你”“没连上”“再试一次”“没存上” |
| 时间单位 | 秒、分钟（联赛 UI 与文案中） | 产品只展示 XP，不展示原始时长 | “XP”“再画 2,000 XP” |
| AI 模板句 | 让我们一起、在这个……时代、不仅……而且、总而言之、值得注意的是、赋能、闭环、打造 | 空泛、像生成文案 | 直接写动作和结果 |
| 贬低/幼稚 | 乖、宝宝、棒棒、笨蛋、菜鸟、废物 | 违背“不幼稚、不居高临下” | 平视短句 |
| 品牌 | 多邻国、Duolingo、猫头鹰、任何品牌角色/logo/原文案 | 禁止复制品牌 | 只使用本项目自己的语言 |

**世界观禁用词**按上表第一类执行；不写“幽灵/亡者/冥界/转世/灵魂/阴间”等设定词，也不把内部代号写进 UI。

### 4.4 改写示例（旧 → 新）

旧文案取自当前 PWA，只作对照，不代表新规范。新文案必须满足 4.1 的长度上限。

| # | 场景 | 旧文案 | 新文案 | 规则 |
| --- | --- | --- | --- | --- |
| 1 | 首页 · 今日进度 | 今天累积满 100 XP，点亮火焰。 | 再 40 XP，点火。 | 具体差距 + 动词；≤18 |
| 2 | 首页 · 名次辅助 | 继续行动，名次会往上走。 | 再 25 XP，超过前面那位。 | 把“努力”换成可执行差距 |
| 3 | 首页 · 动态空态 | 组里还没人动 | 组里静悄悄。你先动。 | 空态给下一步，不卖惨 |
| 4 | 联赛 · 页头 | 只显示你所在的小组 | 你的小组，就这一张榜。 | 短、有归属感 |
| 5 | 联赛 · 榜单空态 | 暂时没有榜单数据。 | 还没人得分。第一笔算你的。 | 空态也有行动暗示 |
| 6 | 联赛 · 加载 | 等待数据 | 榜单上场中… | 6 字以内，保留节奏 |
| 7 | 个人页 · 页头 | 只影响你自己的资料和体验。 | 你的样子，你的战绩。 | 身份 + 结果，不写说明 |
| 8 | 个人页 · 保存失败 | 资料保存失败。 | 网络断了，没存上。再试一次。 | 原因 + 恢复动作，≤18 |
| 9 | 刷新成功 | 联赛数据已刷新。 | 榜更新了。 | 结果具体，不报“数据” |
| 10 | 打卡成功 | 今日打卡完成，火焰续上了。 | 点火成功。火焰 +1。 | 结果 + 奖励，戏剧性 |
| 11 | 连胜保持 | 今天的目标已完成，保持火焰。 | 火没灭。明天见。 | 短句，有画面 |
| 12 | 余烬不足 | 余烬不足，先累积本周 XP 获得余烬。 | 还差 1 枚。再攒 2,000 XP。 | 具体差额 + 获得方式 |
| 13 | 刷新失败 | 刷新失败，正在显示上一次的数据。 | 没连上。先看旧榜。 | 错误原因 + 保留旧数据 |
| 14 | 外观 tooltip | — | 不加 XP，也不改名次。 | 规则一句话，去恐惧 |

### 4.5 数字、标点与动态字段

- XP 用阿拉伯数字 + 空格 + 大写单位：`110 XP`、`2,000 XP`；四位以上用逗号。
- 名次用 `#4`；句中用“第 4”；不要写“4th”。
- 倒计时：`2 天 06:12`；不足 1 天用 `06:12`；结算中写“结算中…”。不显示秒。
- 数量：`1 枚余烬`、`3 天`；中文量词不省略。
- 英文缩写只在 XP 保留；不在 UI 里写 `streak`、`tier`、`rank` 等内部字段。
- 动态文案用占位符，不在代码里拼句子；Android 用 string resource + 参数，Web 用数据绑定。
- 空值统一“等待数据”或“还没上场”，不显示 `null`、`undefined`、`—` 作为最终状态；`—` 只用于首屏加载前的占位。
- 错误文案必须包含“发生了什么 + 怎么办”；不得只写“失败”。

---

## 5. tooltip 规则

### 5.1 什么必须放 tooltip

| 主题 | 必须解释 | 触发位置 | 文案模板（≤60 字符，`[S]`） |
| --- | --- | --- | --- |
| 晋级/降级规则 | 前 N 晋级、后 N 降级、按组内名额、结算时间 | 联赛 zone 标题旁的 `?` | “前 3 晋级，后 3 降级。周日 24:00 结算。” |
| 计算口径 | XP 与打卡/余烬的换算关系，不展示秒/分钟 | XP 环或“本周 XP”旁的 `?` | “有效时间自动折算 XP。100 XP 点火，2,000 XP 得 1 枚余烬。” |
| 段位升降 | 当前段位、下一段位条件、结算后生效 | 段位标题旁的 `?` | “本周结算后按名次升降。前 3 晋级。” |
| 余烬用途 | 只补签，不加 XP、不改名次 | 余烬 chip/余额旁的 `?` | “只补签。不加 XP，不改名次。” |
| 装备是否影响数值 | 头像框/称号/背景只改外观 | 收藏标题旁的 `?` | “不加 XP，也不改名次。” |

> N 是服务端返回的实际名额，不得写死 3；小组不足 15 人时按比例配额显示。

### 5.2 什么不能只放 tooltip

| 内容 | 必须放在哪里 | 原因 |
| --- | --- | --- |
| 主操作 | 按钮本身可见的文字/图标 | 用户不能先找 `?` 才知道点哪 |
| 关键状态 | 页面内联：已点火/未点火、晋级区/降级区、离线、结算中 | 状态必须一眼可见 |
| 错误原因 | 错误发生的位置内联 + 重试按钮 | tooltip 不能承担恢复路径 |
| 奖励/惩罚结果 | 结果屏、toast 或行内 chip | 结果不能藏在 hover 里 |
| 解锁条件 | BadgeTile 下方内联或详情面板 | 用户需要知道怎么获得 |
| 数据为空 | EmptyState 标题 + 正文 + 动作 | 空态本身就是说明 |

### 5.3 触发与关闭

| 平台 | 打开 | 关闭 | 键盘/读屏 |
| --- | --- | --- | --- |
| Web/PWA | hover 120ms 后；focus 立即；点击 `?` 切换 | 再次点击、点击外部、`Escape`、焦点移出、滚动离开视口 | `Tab` 到 trigger 显示；`Escape` 关闭；trigger 有 `aria-describedby`；tooltip 不可聚焦 |
| Android/Compose | 点击 `?` 切换；行内长按打开 | 再次点击、点击外部、返回键/back、切换页面 | TalkBack 自定义动作“查看说明”；`TooltipBox` + `PlainTooltip`；焦点不进入气泡 |

- Web 的 hover 只作为增强；触屏和键盘必须能打开同一内容。
- tooltip 不自动消失，直到用户关闭或离开；不在获得焦点时自动隐藏。
- 滚动时如果 trigger 离开视口，关闭 tooltip；窗口尺寸变化时重新定位。
- tooltip 不可包含链接、按钮、表单或第二个 tooltip；需要交互时改用 popover/dialog/bottom sheet。
- 120ms 来自 `motion.tooltipShow`，80ms 来自 `motion.tooltipHide`；dismiss 本身无动画。

### 5.4 尺寸、行数与内容

| 项目 | 规则 | 来源/约束 |
| --- | --- | --- |
| Trigger | 视觉 20/24；触控 48×48 | `[A][S]` / 必须一致 |
| Trigger 与气泡间距 | 8 | `[S]` / 可调 |
| 最大宽度 | 280px/dp；390 下不超过“屏宽 − 40” | `[S]` / 必须一致 |
| 最小宽度 | 200px/dp | `[S]` / 可调 |
| 内边距 | 垂直 12，水平 14 | `[S]` / 可调 |
| 圆角 | 16 | `[S]` / 必须一致 |
| 背景 | `color.bg.raised` + 1px `color.border.subtle` + `shadow.overlay` | `[S]` / 必须一致 |
| 标题 | `type.label` 14/20 700；最多 1 行 | `[S]` / 必须一致 |
| 正文 | `type.bodySmall` 14/20 500；最多 3 行，每行 20 中文字符，总计 60 | `[S]` / 必须一致 |
| 指针 | 可以省略；有指针时 8×8，指向 trigger | `[S]` / 可调 |
| 位置 | 优先 trigger 上方；空间不足翻到下方；不得遮住主 CTA | `[S]` / 必须一致 |
| 层级 | 高于卡片，低于模态 | `[S]` / 必须一致 |

### 5.5 Anatomy

```text
                  ┌──────────────────────────┐
                  │ 晋级怎么算？             │  ← title 14/20 700
                  │ 前 3 晋级，后 3 降级。   │  ← body 14/20 500
                  │ 周日 24:00 结算。        │     最多 3 行
                  └────────────▲─────────────┘
                               │ 8px
                        ┌──────┴──────┐
                        │   ?  24px   │  ← trigger 图标
                        │  48×48 触控 │
                        └─────────────┘
```

1. **Trigger**：圆形 `?`，视觉 20/24，触控 48×48；必须是有可访问名的 button。
2. **Bubble**：`role="tooltip"`（Web）；非模态，不可聚焦。
3. **Title**：一个问题或主题，≤10 字符。
4. **Body**：一条规则 + 一个结果；≤3 行/60 字符。
5. **Pointer**：可选；不指向错误位置。
6. **Dismiss**：见 5.3；不提供“知道了”按钮（tooltip 不是对话框）。

### 5.6 可访问性要求

- trigger 必须有 `aria-label` / `contentDescription`，包含主题，例如“规则说明：晋级与降级”；不能只叫“帮助”。
- Web：`aria-describedby="<tooltip-id>"`；tooltip 显示时 `aria-hidden="false"`；不可聚焦；`Escape` 关闭后焦点回到 trigger。
- Android：`TooltipBox` 的 trigger 有可访问名；TalkBack 用户可以通过自定义动作或帮助页获得同一内容，不能依赖长按。
- 键盘：`Tab` 可到 trigger；`Enter`/`Space` 切换；`Escape` 关闭；不得被 tooltip 捕获焦点。
- 触屏：点击打开，点击外部/再次点击关闭；不以 hover 为唯一入口。
- 对比度：正文 ≥4.5:1；边框/指针不作为唯一指示。
- 动效：tooltip 出现 120ms；reduced-motion 下直接显示，不淡入。
- 文本缩放：200% 下仍不溢出；超过 3 行时改用 bottom sheet，不缩小字体。
- 同一屏最多同时显示 1 个 tooltip。

---

## 6. 组件契约

**通用状态词：**

- `default`：默认。
- `active`：选中/当前/已装备。
- `disabled`：不可用。
- `loading`：数据或动作进行中。
- `error`：失败/降级/不可恢复态；没有该语义的组件写“不适用”。

所有组件都必须引用第 2 节语义 token，不得写死颜色、字号、圆角、时长。状态表中的尺寸/时长若未单独标源，均引用 2.4/2.5 或该组件尺寸表，按 `[S]` 处理；组件尺寸表未列出的文字尺寸引用 2.3.2，不新增字号。

### 6.1 AppShell / TopBar

**用途**：提供安全区、顶栏身份、全局状态和页面内容槽；TopBar 是页面的一部分，不是卡片。

**Anatomy：**

1. 安全区（状态栏/刘海）。
2. TopBar：leading 头像（36/40）+ 问候/名称；trailing 连胜 chip、最多 1 个图标动作（个人页为设置）。
3. 可选同步/离线条：紧贴 TopBar 下方，内联，不使用 toast 代替。
4. 内容槽：页面主体，底部留出导航高度。
5. Overlay host：toast、tooltip、庆祝层。

**状态：**

| 状态 | 视觉 | 行为 |
| --- | --- | --- |
| default | `surface` 底 + 1px 底边；头像/问候/连胜可见 | 页面可滚动；TopBar 固定 |
| active | 当前页头像有 2px mint 环；导航项 `aria-current` | 切换页面不重建 TopBar |
| disabled | 不适用 | — |
| loading | 头像/名称/连胜显示 skeleton；`aria-busy="true"` | 不显示假数据 |
| error | TopBar 不变；下方出现离线/错误条：“没连上。先看旧榜。” + 重试 | 保留旧数据；不整页清空 |

**尺寸：**

| 项目 | 390 | 1440 | 来源/约束 |
| --- | --- | --- | --- |
| TopBar 高度 | 64 | 72 | `[I][S]` / 必须一致 |
| 水平内边距 | 20 | 40 | `[S]` / 必须一致 |
| 头像 | 36 | 40 | `[S]` / 必须一致 |
| 动作按钮 | 48×48 | 48×48 | `[A][M]` / 必须一致 |
| 问候 | `type.micro` 11/16 | 11/16 | `[S]` / 必须一致 |
| 名称 | `type.title` 16/24 | 16/24 | `[S]` / 必须一致 |

**Web 映射**：语义 `<header>` + `role="banner"`；`position: sticky; top: 0`；`padding-top: env(safe-area-inset-top)`；跳过链接指向主内容；焦点环 2px。

**Android 映射**：`Scaffold(topBar = { TopAppBar(...) })`；`WindowInsets.statusBars` / `safeDrawing`；`TopAppBar` 高 64dp（expanded 72dp）；`IconButton` 至少 48dp；边缘到边缘。

**约束**：TopBar 不放大卡片圆角；不使用滚动模糊/半透明玻璃；390 下最多 1 个图标动作 + 连胜 chip；声音/安装等低频动作进设置或溢出菜单。

### 6.2 PrimaryButton / SecondaryButton / IconButton

**用途**：主操作、次操作、图标动作。

**Anatomy：**

1. 容器（pill）。
2. 可选 leading 图标 20。
3. 标签（`type.label`）。
4. 可选 trailing 进度 16。
5. 可选 badge 点（仅 IconButton）。

**尺寸：**

| 类型 | 高度 | 内边距 | 图标 | 圆角 | 来源/约束 |
| --- | --- | --- | --- | --- | --- |
| PrimaryButton | 52 | 水平 24 | 20 | full | `[S]` / 必须一致 |
| SecondaryButton | 48 | 水平 20 | 20 | full | `[S]` / 必须一致 |
| IconButton | 48×48 | 0 | 24 | full | `[A][M]` / 必须一致 |
| Compact 次按钮 | 40 视觉，触控 48 | 水平 16 | 18 | full | `[S]` / 可调 |

**状态：**

| 状态 | Primary | Secondary | IconButton |
| --- | --- | --- | --- |
| default | mint 填充、`onAccent` 字 | 透明 + 1px strong 边框 | 透明、primary 图标 |
| active | 不适用（按下用 pressed） | mint soft 底 + mint 边框 | mint soft 底 + mint 图标 |
| disabled | 45% 不透明度、无指针 | 45% 不透明度 | 45% 不透明度 |
| loading | 保留宽度；16 spinner + 标签；`aria-busy`；禁用重复点击 | 同左 | 图标替换为 16 spinner；`contentDescription="加载中"` |
| error | 仅危险操作使用 danger variant：珊瑚填充 + `onAccent` 字 | 珊瑚边框/文字，不填充 | 不适用；错误用行内提示 |

**行为**：按下缩放 0.98、90ms；hover 只增强亮度/底色，不改变布局；焦点环 2px mint、offset 2；loading 时宽度不跳；错误后按钮回到 default，错误原因内联显示。

**Web 映射**：`<button>`；`disabled` + `aria-busy`；`:focus-visible`；不使用 `div` 模拟按钮；图标按钮有 `aria-label`。

**Android 映射**：`Button` / `FilledTonalButton` / `IconButton`；`Modifier.sizeIn(minHeight = 48.dp)`；`CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)`；ripple 允许。

**约束**：每屏最多 1 个 PrimaryButton；Primary 不写长解释；IconButton 必须有可访问名；加载中不得改变按钮宽度。

### 6.3 XP ProgressRing

**用途**：今日 XP 进度与点火状态的主视觉。

**Anatomy：**

1. 轨道圆（16/18）。
2. 进度弧（16/18，圆头）。
3. 中心：火焰/余烬小形象 56/72。
4. 数字：`type.score`。
5. 状态：`type.bodySmall` 或 `type.caption`；例如“再 40 XP，点火。”。
6. 环旁 `?` tooltip trigger（计算口径）。

**尺寸：**

| 项目 | 390 | 1440 | 来源/约束 |
| --- | --- | --- | --- |
| 环外径 | 224 | 280 | `[C][S]` / 必须一致 |
| 轨道/进度线宽 | 16 | 18 | `[S]` / 可调（14–18） |
| 中心形象 | 56 | 72 | `[S]` / 可调 |
| 数字 | 44/48 | 56/60 | `[C][S]` / 必须一致 |
| 状态文字 | 14/20 | 14/20 | `[S]` / 必须一致 |

**状态：**

| 状态 | 视觉 | 行为 |
| --- | --- | --- |
| default | 0 XP；轨道 + 0 弧；中心“0 XP” | 状态句“画一笔，点火。” |
| active | 1–99 XP；mint 弧；数字同步 | 数字与弧 620ms 同步；从中断值继续 |
| disabled | 不适用 | — |
| loading | 轨道 skeleton；中心不显示假数字 | `aria-busy`；保留环尺寸 |
| error | 保留上一次值；环不重置；下方内联“没连上。先看旧榜。” | 重试按钮；不把环变红 |
| complete | 100+ XP；满弧；`color.xp.complete` 金色；状态“已点火” | 只脉冲一次 240ms；不每次刷新放彩带 |

**Web 映射**：内联 SVG 两个 `<circle>`；`stroke-dasharray` / `stroke-dashoffset`；容器 `role="progressbar"`、`aria-valuemin=0`、`aria-valuemax=100`、`aria-valuenow=min(xp,100)`、`aria-valuetext="今日 110 XP，已点火"`。

**Android 映射**：`Canvas` + `drawArc(useCenter=false, style=Stroke(width, cap=Round))`；`animateFloatAsState` 620ms；`Modifier.semantics { progressBarRangeInfo = ProgressBarRangeInfo(current, 0f..1f) }`；减少动效时直接写终值。

**约束**：环只表达今日目标，不表达周 XP；超过 100 不超圈；数字与弧必须同起同止；不得用环做按钮。

### 6.4 StatChip

**用途**：把 1 个关键数字和图标压缩成可扫读的 chip。

**Anatomy**：图标 16 + 标签（`type.caption`）+ 值（`type.label` 700）+ 可选 delta。

**尺寸：**

| 项目 | 390 | 1440 | 来源/约束 |
| --- | --- | --- | --- |
| chip 高度 | 32 | 32 | `[S]` / 必须一致 |
| 水平内边距 | 10 | 10 | `[S]` / 必须一致 |
| 图标-文字间距 | 6 | 6 | `[S]` / 可调 |
| 圆角 | full | full | `[S]` / 必须一致 |
| chip 宽度 | 三等分，最小 96 | 最大 264，不拉伸 | `[S]` / 可调 |

**状态：**

| 状态 | 视觉 | 行为 |
| --- | --- | --- |
| default | `overlay.hover` 底 + 1px subtle 边框 | 静态或可点 |
| active | mint soft 底 + mint 边框/图标 | 选中筛选/当前项 |
| disabled | 45% 不透明度 | 不响应 |
| loading | 60×12 skeleton，保留 chip 宽度 | 不显示 0 假值 |
| error | 不适用；数据错误显示“—”，并保留上一值 | 不用红色 chip 代替错误说明 |

**Web 映射**：`span`/`button`；可点时 48 高触控区、`aria-pressed`；不可点时无 role。

**Android 映射**：`Row` + `Modifier.heightIn(min=48.dp)`（可点）或 32dp（静态）；`Surface` + `RoundedCornerShape(50)`；可点用 `selectable`。

**约束**：一屏最多 3 个 chip；标签 ≤6 字；值不截断；不得用 emoji 做图标。

### 6.5 StreakFlame

**用途**：显示连续点火天数，并把“今天是否已点火”变成可感知状态。

**Anatomy**：火焰图标 20 + 数字（`type.value` 16/20 800）+ “天”（11/16）+ 可选“今天还差 40 XP”状态点。

**尺寸：**

| 项目 | 390 | 1440 | 来源/约束 |
| --- | --- | --- | --- |
| 火焰图标 | 20 | 20 | `[S]` / 必须一致 |
| 数字 | 16/20，800 | 16/20，800 | `[S]` / 必须一致 |
| 单位 | 11/16 | 11/16 | `[S]` / 必须一致 |
| 组件高度 | 32 | 32 | `[S]` / 可调 |

**状态：**

| 状态 | 视觉 | 行为 |
| --- | --- | --- |
| default/unlit | 灰色火焰 + 0 天 | 状态句提示“画一笔，点火。” |
| active/lit | 金色火焰 + 数字 | 显示“连续 N 天” |
| milestone | 金色 + 一次性 240ms 脉冲 | 只在新里程碑触发；reduced 无脉冲 |
| disabled | 不适用 | — |
| loading | skeleton 20×20 + 24×12 | 不显示 0 |
| error | 保留上一值；旁边小珊瑚点 + 内联错误 | 不清零、不闪烁 |

**Web 映射**：内联 SVG 火焰；`aria-label="连续 3 天，今天已点火"`；数字是文本节点。

**Android 映射**：vector drawable；`contentDescription` 同左；脉冲用 `animateFloatAsState` 240ms 或直接静态。

**约束**：火焰不是唯一语义，数字必须始终可见；不得循环燃烧动画；不得用红色火焰羞辱断签。

### 6.6 LeagueRow（含 me / promotion / demotion / medal）

**用途**：在 15 人小组中展示名次、身份、XP 和区段。

**Anatomy：**

1. 左侧 rank 28（`type.label` 800）。
2. 头像 36/40 + 头像框（1.36D）。
3. 姓名 14/20 700 + 称号/状态 11/16（可选）。
4. 前三奖牌 20（金/银/铜）。
5. 右侧周 XP `type.value` 16/20 800。
6. “我” chip（仅在 me 行）。
7. 区段左条 4px（promotion/demotion）。
8. 行分隔线 1px。

**状态：**

| 状态 | 视觉 | 行为 |
| --- | --- | --- |
| default | 透明底；1px 分隔线 | 点击打开资料 |
| active/me | mint soft 底 + 1px mint 边框 + “我”文字 chip | 不重复；滚出视口时由定位条接替 |
| promotion | 前 N 名；前三有奖牌；4px mint 左条；分区标签“前 N 晋级” | 不把整行染绿 |
| demotion | 末尾 N 名；4px 珊瑚左条；分区标签“后 N 降级” | 不用红色闪烁 |
| disabled | 不适用；隐藏成员不显示行 | — |
| loading | 15 行 skeleton，保持 56/52 高度 | 不引起布局跳动 |
| error | 头像加载失败用首字母/默认图；行仍可读 | 不整行消失 |

**尺寸：**

| 项目 | 390 | 1440 | 来源/约束 |
| --- | --- | --- | --- |
| 行高 | 56 | 52 | `[S]` / 必须一致 |
| 水平内边距 | 16 | 20 | `[S]` / 必须一致 |
| 头像 | 36 | 40 | `[S]` / 必须一致 |
| 名次宽 | 28 | 32 | `[S]` / 可调 |
| 奖牌 | 20 | 20 | `[S]` / 必须一致 |

**Web 映射**：`<ol>` + `<li>`；整行 `<button>` 或带 `role="button"` 的可聚焦行；`aria-label` 包含“第 4 名，名字，1,100 XP，我的行”；me 行不只靠颜色。

**Android 映射**：`LazyColumn` + `ListItem`/`Row`；`clickable`；`semantics { selected = isMe }`；头像 `AsyncImage` + fallback。

**约束**：名次和 XP 右对齐可扫读；长名字省略；前三必须有文字/可访问名；区段线不遮住内容；15 行不做分页；自己的行必须能找到。

### 6.7 BadgeTile

**用途**：收藏中的徽章/头像框/背景 tile。

**Anatomy**：1:1 tile + 预览图标 40 + 名称 `type.caption` 12/16 + 类型标签 `type.micro` 11/16 + 装备标记 + 锁定原因。

**尺寸：**

| 项目 | 390 | 1440 | 来源/约束 |
| --- | --- | --- | --- |
| tile | 96×96 | 112×112 | `[S]` / 可调 |
| 圆角 | 20 | 20 | `[S]` / 必须一致 |
| 预览图标 | 40 | 48 | `[S]` / 可调 |
| 网格 | 3 列，gap 12 | 4 列，gap 16 | `[S]` / 必须一致 |

**状态：**

| 状态 | 视觉 | 行为 |
| --- | --- | --- |
| default/owned | raised 底 + subtle 边框 | 点击预览/装备 |
| active/equipped | mint 2px 边框 + 勾选 + “已装备” | `aria-pressed`/selected |
| disabled/locked | 40% 不透明度 + 锁图标 + 内联解锁条件 | 不可装备；原因不藏 tooltip |
| loading | 96×96 skeleton | 保持网格 |
| error | 素材失败显示通用矢量占位 + 名称 | 不显示破图 |

**Web 映射**：`<button>` + `aria-pressed`；图片 `alt` 用名称；锁定原因在 tile 下方。

**Android 映射**：`Card`/`Surface` + `selectable(selected=...)`；`Icon`/`Image` + `contentDescription`；锁定时 `enabled=false`。

**约束**：外观不影响 XP/名次；个人页收藏预览最多 6 个（390）/ 12 个（1440）；收藏全量在“收藏”Tab；装备状态不能只靠颜色。

### 6.8 Tooltip

**用途**：解释规则/口径，不承担主操作和错误恢复。完整规则见第 5 节。

**Anatomy**：trigger 48×48 + bubble（title + body + 可选 pointer）。

**状态：**

| 状态 | 视觉 | 行为 |
| --- | --- | --- |
| default | trigger 为 `?`，可聚焦 | hover/focus/tap 打开 |
| active | bubble 显示，`role=tooltip`；trigger 有焦点环 | 不抢焦点；再次触发关闭 |
| disabled | trigger 隐藏或不可用 | 数据未就绪时不显示空 tooltip |
| loading | 不适用；需要加载时禁用 trigger | 不显示“加载中”气泡 |
| error | 不适用；内容不可用时不显示 trigger | 错误信息内联 |

**Web 映射**：`role="tooltip"`、`aria-describedby`、`Escape`、`:focus-visible`；`pointer-events: none`。

**Android 映射**：`TooltipBox` + `PlainTooltip`；长内容改 `ModalBottomSheet`；`rememberTooltipState`；TalkBack 自定义动作。

**约束**：≤3 行/60 字；不自动消失；不嵌套；不放置链接/按钮。

### 6.9 Toast

**用途**：短暂回执，不替代内联错误/状态。

**Anatomy**：图标 20 + 文案 14/20 + 可选操作（14/700 mint）+ 可选关闭。

**尺寸：**

| 项目 | 值 | 来源/约束 |
| --- | --- | --- |
| 宽度 | 280–360 | `[S]` / 可调 |
| 高度 | 48–64 | `[S]` / 可调 |
| 内边距 | 垂直 12，水平 16 | `[S]` / 必须一致 |
| 圆角 | 16 | `[S]` / 必须一致 |
| 距底部导航 | 16（再叠加安全区） | `[S]` / 必须一致 |
| 图标 | 20 | `[S]` / 必须一致 |

**状态：**

| 状态 | 视觉 | 行为 |
| --- | --- | --- |
| default | raised 底 + 边框 + shadow.overlay | 2.8s 后消失 |
| active | 带操作时 4s；hover/focus/按住暂停计时 | 操作可键盘访问 |
| disabled | 不适用 | — |
| loading | 不适用；加载用按钮 spinner/skeleton | — |
| error | 珊瑚图标 + `role="alert"`；4s | 同时保留内联错误原因 |

**Web 映射**：`role="status"`（成功）/`role="alert"`（错误）；`aria-live`；不抢焦点；最多 1 个可见。

**Android 映射**：`SnackbarHost` + `Snackbar`；`SnackbarDuration.Short`/`Long`；`actionLabel` 可点；无障碍朗读。

**约束**：不堆叠；队列最多 2；错误不能只靠 toast；表单错误内联。

### 6.10 EmptyState

**用途**：解释为什么空 + 给出下一步。

**Anatomy**：图标 48（64 圆底）+ 标题 `type.h2` + 正文 `type.bodySmall` + 主/次动作。

**尺寸：**

| 项目 | 值 | 来源/约束 |
| --- | --- | --- |
| 最大宽度 | 320 | `[S]` / 可调 |
| 内边距 | 垂直 32，水平 16 | `[S]` / 必须一致 |
| 图标 | 48，底 64 | `[S]` / 可调 |
| 按钮最小高度 | 48 | `[A][M]` / 必须一致 |

**状态：**

| 状态 | 视觉 | 行为 |
| --- | --- | --- |
| default/empty | 中性图标 + 标题 + 下一步 | 动作可点 |
| active | 不适用 | — |
| disabled | 不适用 | — |
| loading | 2–3 个 skeleton 行，保留高度 | 不显示空态闪烁 |
| error | 珊瑚图标 + 原因 + 重试 | `role="alert"`；保留旧数据 |

**Web 映射**：`role="status"`（空）/`role="alert"`（错）；标题用 heading；动作是 `<button>`。

**Android 映射**：`Column` + `Icon` + `Text` + `Button`；语义标题；错误 `liveRegion=Assertive`。

**约束**：标题 ≤10、正文 ≤30；不用“暂无数据”单独结尾；空态不写长段落。

### 6.11 BottomNav

**用途**：四个一级目的地的稳定导航。

**Anatomy**：4 个 item；每个 item 图标 24 + 标签 11/16 700；active 背景 pill；可选 badge 点 6。

**尺寸：**

| 项目 | 390 | 1440 | 来源/约束 |
| --- | --- | --- | --- |
| 高度 | 64 + 安全区 | 导航 rail 88 | `[C][I]` / 必须一致 |
| item 最小 | 64×48 | 88×56 | `[A]` / 必须一致 |
| 图标 | 24 | 24 | `[M]` / 必须一致 |
| 标签 | 11/16 700 | 12/16 700 | `[S]` / 可调 |
| active pill | 32×24 | 32×24 | `[S]` / 可调 |
| badge 点 | 6 | 6 | `[S]` / 可调 |

**状态：**

| 状态 | 视觉 | 行为 |
| --- | --- | --- |
| default | 未选中：`text.secondary` 图标/标签 | 点击切换页面 |
| active | mint 图标 + mint 标签 + 32×24 mint soft pill | `aria-current="page"` |
| disabled | 目的地不可用时 40% 不透明度 | 不跳转；说明原因 |
| loading | 不适用；数据加载不改变导航 | 保留导航稳定 |
| error | 不适用；离线时可用旧数据 | 不隐藏导航 |

**四个目的地：**

1. 首页（home）
2. 联赛（trophy）
3. 收藏（palette；徽章/头像框/背景）
4. 我的（person）

> 概念稿第三个 Tab 是 palette；本规格把它定义为“收藏”，个人页的收藏预览深链到该 Tab。它不是一个额外的业务页，也不承担“开始创作”动作；主 CTA 仍在首页。

**Web 映射**：`<nav aria-label="主导航">`；按钮/链接；`aria-current="page"`；`padding-bottom: env(safe-area-inset-bottom)`；内容底部留 96。

**Android 映射**：`NavigationBar` + `NavigationBarItem`（4 项，`alwaysShowLabel = true`）；`WindowInsets.navigationBars`；平板用 `NavigationRail`。

**约束**：不超过 4 项；不使用中心 FAB；不因滚动隐藏；标签始终可见。

---

## 7. 页面蓝图

### 7.1 共享布局规则

| 断点 | 宽度 | 导航 | 列 | 边距 | 字号档 | 来源/约束 |
| --- | --- | --- | --- | --- | --- | --- |
| compact | < 600 | 底部导航 64 | 1 | 20 | 390 档 | `[C][S]` / 必须一致 |
| medium | 600–959 | 底部导航 | 2 | 24 | 390 档 | `[S]` / 可调 |
| expanded | ≥ 960 | 左侧 rail 88 | 3 | 40 | 1440 档 | `[S]` / 必须一致 |

- 390px：单列、20 边距、卡片间距 16、底部导航固定、页面底部 96。
- 1440px：左侧 rail 88、内容最大 1200、三列、列距 24、页面边距 40。
- 所有页面使用同一 TopBar 高度和同一卡片圆角 28；页面不横向滚动。
- 断点只改变布局，不改变信息优先级和文案。
- 页面蓝图使用 slot，不绑定 PWA DOM 结构；Web 和 Compose 各自实现。
- 以下页面数值引用 2.4 与第 6 节的 token；页面专用值在每屏表格标源，未标注者按 `[S]` 处理。

### 7.2 首页

**信息优先级：**

| 优先级 | 内容 | 位置 | 原因 |
| --- | --- | --- | --- |
| P0 | 问候 + 头像/火焰、XP 环、主 CTA | 第一屏中心 | 先回答“我是谁、今天差多少、下一步” |
| P1 | 三个 StatChip、组内位置 | 环下/CTA 下 | 提供上下文，不抢主操作 |
| P2 | 最近动态 | 首屏下方 | 氛围与社交，不要求首屏读完 |

**关键尺寸：**

| 项目 | 390 | 1440 | 来源/约束 |
| --- | --- | --- | --- |
| 基准画幅 | 390×844 | 1440×900 | `[C][S]` / 390 必须一致；1440 可调 |
| TopBar | 64 | 72 | `[I][S]` / 必须一致 |
| 环 | 224 | 280 | `[C][S]` / 必须一致 |
| 主 CTA | 350×52 | 320×52 | `[S]` / 必须一致（宽度可调） |
| StatChip 行 | 3×32 | 3×32（纵排） | `[S]` / 必须一致 |
| 组内行高 | 56 | 52 | `[S]` / 必须一致 |
| 最近动态 | 最多 3 条 | 最多 3 条 | `[S]` / 必须一致 |
| 页面底部留白 | 96 | 40 | `[S]` / 必须一致 |

**390 布局：**

```text
┌────────────────────────────── 390 ─────────────────────────────┐
│ TopBar 64：头像36 + 早早早，主人！        [火焰 1 天] [动作] │
│ 20 边距                                                       │
│                     XP 环 224                                 │
│                  110 XP / 再 40 XP，点火。                    │
│                                                               │
│ [            去画一笔 52            ]                          │
│ [小组 4/15] [余烬 0] [本周 110]  32                           │
│ ┌ 组内位置 28 ──────────────────────────────┐                 │
│ │ 前 3 晋级 · 第 4 · 后 3 降级               │                 │
│ │ 1 ... 2 ... 3 ... 我 4 ...                 │                 │
│ │ 查看完整榜 →                              │                 │
│ └────────────────────────────────────────────┘                 │
│ ┌ 最近动态（首屏下方） ─────────────────────┐                  │
│ └────────────────────────────────────────────┘                 │
│ BottomNav 64 + 安全区：首页 / 联赛 / 收藏 / 我的              │
└────────────────────────────────────────────────────────────────┘
```

- 第一屏必须同时可见：问候、XP 环、主 CTA、至少 2 个 StatChip；组内位置至少露出标题。
- 环居中；CTA 全宽 350；chips 三等分；组内位置只显示前 3 + 我 + 1 个邻近名次（去重后最多 5 行），完整 15 行去联赛页。
- 最近动态最多 3 条；空态“组里静悄悄。你先动。”。

**1440 布局：**

```text
TopBar 72（内容最大 1200）
┌ NavRail 88 ┬──── 264 ────┬──────── 560 ────────┬──── 328 ────┐
│ 首页        │ 头像/问候   │       XP 环 280     │ 组内位置     │
│ 联赛        │ 火焰/连胜   │    110 XP / 点火     │ 5 行 compact │
│ 收藏        │ 3 chips 纵排│   [去画一笔 320]    │ 最近动态 3 条│
│ 我的        │ 本周回顾    │   今日状态/提示      │              │
└─────────────┴─────────────┴─────────────────────┴──────────────┘
```

- 三列宽度 264 / 560 / 328，gap 24，总宽 1200；不把手机卡片拉宽。
- 左列是身份与统计，中心是环和 CTA，右列是组内位置与动态。
- 环 280，CTA 320 居中；右列行高 52；最近动态 3 条。
- DOM/阅读顺序：左列身份 → 中心 hero → 右列组内位置/动态；焦点顺序与视觉列一致。

**状态：**

| 状态 | 首页表现 |
| --- | --- |
| loading | 环 skeleton、按钮禁用、chips skeleton；不显示 0 假值 |
| empty | 组内位置空态“还没分组。先画一笔。”；动态空态 |
| error/offline | 保留旧环/旧榜；TopBar 下错误条 + 重试；不整页清空 |
| reduced motion | 环/数字直接终值；无彩带；静态高光 |

**为什么这样排**：环是每日唯一目标，放中心；CTA 紧跟环，形成“看到差距 → 立即行动”；chips 是上下文，放 CTA 下；组内位置是社交比较，放在个人进度之后；动态最后，避免首页变成信息流。

### 7.3 联赛

**信息优先级：**

| 优先级 | 内容 | 位置 | 原因 |
| --- | --- | --- | --- |
| P0 | 组名/段位、结算倒计时、自己的行、晋级/降级区 | 页头 + 榜内 | 先回答“这是什么局、还剩多久、我在哪、会升还是降” |
| P1 | 前三奖牌、15 行、行内 XP | 榜单主体 | 提供可比较的竞争信息 |
| P2 | 称号、连胜小图标、说明 tooltip | 行内/标题旁 | 增强，不抢主信息 |

**关键尺寸：**

| 项目 | 390 | 1440 | 来源/约束 |
| --- | --- | --- | --- |
| TopBar | 64 | 72 | `[I][S]` / 必须一致 |
| Hero 内边距 | 20 | 24 | `[S]` / 必须一致 |
| 段位图标 | 64 | 72 | `[S]` / 可调 |
| 倒计时 chip | 高 32 | 高 32 | `[S]` / 必须一致 |
| 榜单行高 | 56 | 52 | `[S]` / 必须一致 |
| 榜单列宽 | 350（全宽） | 816 | `[S]` / 必须一致（结构） |
| 自己行定位条 | 48 | 不显示（全部可见） | `[S]` / 可调 |
| 15 行是否首屏可见 | 否，滚动 | 是 | `[S]` / 必须一致 |

**390 布局：**

```text
┌────────────────────────────── 390 ─────────────────────────────┐
│ TopBar 64：联赛 + 头像/动作                                   │
│ ┌ Hero 28 ────────────────────────────────────┐                │
│ │ [段位 64] 青铜 · G01        [2 天 06:12]     │                │
│ │ 前 3 晋级 · 后 3 降级 · [?]                  │                │
│ └──────────────────────────────────────────────┘                │
│ ┌ 榜单 28 ────────────────────────────────────┐                │
│ │ 1 [金] 头像 名字                 1,240 XP    │                │
│ │ 2 [银] 头像 名字                 1,180 XP    │                │
│ │ 3 [铜] 头像 名字                 1,150 XP    │                │
│ │ ───── 前 3 晋级 ─────────────────────────    │                │
│ │ 4 [我] 头像 名字                 1,100 XP    │                │
│ │ ... 15 行（滚动）                             │                │
│ │ ───── 后 3 降级 ─────────────────────────    │                │
│ └──────────────────────────────────────────────┘                │
│ BottomNav 64 + 安全区                                          │
└────────────────────────────────────────────────────────────────┘
```

- 行高 56；页头 hero 内边距 20；首屏至少看到前 4 行；自己是第 4 名时必须在首屏，否则由定位条接替。
- 自己的行不在视口时，在导航上方显示 48 高定位条“我 · 第 12 · 1,100 XP →”，点击滚动到自己的行；定位条出现时，页面底部留白从 96 增至 128，不遮挡最后一行。
- 晋级/降级线用实线 + 文本，不只靠颜色；N 由服务端配额决定，不写死 3。
- 15 行完整显示，不分页；行内 XP 右对齐；长名字省略。

**1440 布局：**

```text
TopBar 72
┌ NavRail 88 ┬──── 360 ─────────────┬────────── 816 ──────────────┐
│ 首页        │ 段位 64            │ 15 行 × 52，全部可见         │
│ 联赛        │ 青铜 · G01         │ 前三奖牌 + 自己行高亮        │
│ 收藏        │ 2 天 06:12         │ 前 N 晋级 / 后 N 降级线      │
│ 我的        │ 区段图例/说明       │ 无横向滚动                   │
└─────────────┴────────────────────┴─────────────────────────────┘
```

- 左列 360：段位、组名、倒计时、区段图例；右列 816：15 行，行高 52。
- 全部 15 行在 1440 首屏可见；不出现横向滚动；榜单不拆成两列（会破坏名次顺序）。
- 区段线跨整行；自己的行 mint soft 底 + 1px 边框 + “我”文字。

**状态：**

| 状态 | 联赛表现 |
| --- | --- |
| loading | 15 行 skeleton；页头保留组名/倒计时；不显示假名次 |
| empty | “还没分组。等名单。”；不伪造 15 人 |
| error/offline | 保留上一次快照；页头下“没连上。先看旧榜。”+ 重试；不清空 |
| settlement | 倒计时变“结算中…”；榜单只读；不弹多个庆祝 |

**为什么这样排**：倒计时制造真实赛季压力；前三奖牌给即时地位；晋级/降级线把规则画在榜上，减少解释；自己的行高亮，解决“15 人里我在哪”；XP 右对齐，便于纵向扫描。

### 7.4 个人页

**信息优先级：**

| 优先级 | 内容 | 位置 | 原因 |
| --- | --- | --- | --- |
| P0 | 头像框、名字、称号/等级 | 页首 | 身份先于数据 |
| P1 | 三项统计（连胜/本周 XP/名次） | 身份下 | 用数字证明状态 |
| P1 | 收藏预览 + 已装备 | 统计下 | 奖励与身份表达 |
| P2 | 设置、账号、退出 | 页尾 | 低频，不抢首屏 |

**关键尺寸：**

| 项目 | 390 | 1440 | 来源/约束 |
| --- | --- | --- | --- |
| TopBar | 64 | 72 | `[I][S]` / 必须一致 |
| 头像 | 96 | 96 | `[R]` / 必须一致 |
| 头像框画布 | 130.56（1.36D） | 130.56 | `[R]` / 必须一致 |
| 统计 tile | 104×72 ×3 | 104×72 ×3 | `[S]` / 可调 |
| 收藏网格 | 3 列，gap 12 | 4 列，gap 16 | `[S]` / 必须一致 |
| 设置行高 | 56 | 56 | `[S]` / 必须一致 |
| 页面底部留白 | 96 | 40 | `[S]` / 必须一致 |

**390 布局：**

```text
┌────────────────────────────── 390 ─────────────────────────────┐
│ TopBar 64：我的 + [设置 48]                                    │
│ 头像 96 + 1.36D 框；名字 22；[等级] [称号]                     │
│ [连续 3 天] [本周 110 XP] [小组 #4]  3 × 104                   │
│ 收藏 28 + [?] “不加 XP，也不改名次。”                          │
│ [徽章 96] [头像框 96] [背景 96]                                │
│ [徽章] [头像框] [背景]                     [全部收藏 →]         │
│ 设置：声音 / 触感 / 图标主题 / 账号          4 × 56            │
│ 退出登录（危险区，页尾）                                        │
│ BottomNav 64 + 安全区                                          │
└────────────────────────────────────────────────────────────────┘
```

- 头像 96，框体画布 `1.36D = 130.56`，开孔 `1.00D`；辉光 `1.08 × 1.36D`。
- 三项统计等宽，每项 104×72；数字用 `type.h2`，标签 `type.caption`。
- 390 首屏收藏 3×2；第 6 个后可“全部收藏”；已装备项 mint 边框 + 勾。
- 设置行高 56；退出登录独立分组，不与设置混排。

**1440 布局：**

```text
TopBar 72
┌ NavRail 88 ┬──── 360 ────────┬──────── 520 ────────┬──── 272 ────┐
│ 我的        │ 头像/名字/称号  │ 收藏 4 列 × 3 行     │ 设置列表     │
│             │ 3 项统计        │ 已装备/未解锁        │ 账号/退出    │
│             │ 收藏预览        │ 全部收藏             │              │
└─────────────┴─────────────────┴──────────────────────┴─────────────┘
```

- 左列 360 固定身份与统计；中列 520 收藏 4 列；右列 272 设置。
- 中列 4 列 tile 112 + gap 16；一屏 12 个；不横向滚动。
- 设置与危险区放右列底部；退出登录仍需二次确认。

**状态：**

| 状态 | 个人页表现 |
| --- | --- |
| loading | 头像/名字 skeleton；统计 skeleton；收藏 skeleton；不显示 0 假值 |
| empty | 收藏空态“还没有收藏。先拿一枚徽章。” |
| error/offline | 保留旧资料；保存失败内联“网络断了，没存上。再试一次。”；不丢输入 |
| success | 保存/装备用 toast“已保存。”“已装备。”；不弹全屏 |

**为什么这样排**：头像框和称号是玩家最想展示的身份；统计是“我这周怎么样”；收藏是奖励与个性；设置低频，放最后；外观 tooltip 紧贴收藏标题，防止“外观是否加数值”的误解。

### 7.5 概念稿元素映射

| 概念稿元素 | 规格落点 | 为什么这样排 |
| --- | --- | --- |
| 首页顶部头像 + 余烬环 + “早早早，主人！” + 火焰 1 天 | TopBar / StreakFlame（6.1、6.5） | 先给身份与连续状态，建立“这是我的局” |
| 巨大 XP 环围绕小余烬 + 110 XP + “还差 40 XP 就点火” | XP ProgressRing（6.3）+ 首页 P0 | 单目标、单数字、单动作；环是首屏视觉锚点 |
| 画笔图标主按钮“去画一笔” | PrimaryButton（6.2）+ 首页 CTA | 图标先于文字；一个主操作 |
| 三个紧凑 StatChip：小组 4/15、余烬 0、本周 110 | StatChip（6.4） | 把上下文压缩到 32 高，不抢环 |
| 四个 icon-first Tab | BottomNav（6.11） | 稳定导航；palette 映射为收藏，避免第五个 Tab |
| 联赛：段位图标、G01、倒计时 chip | 联赛 hero（7.3） | 身份、组别、剩余时间一眼读完 |
| 15 人榜、圆形头像/框、前三奖牌、自己第 4 行高亮 | LeagueRow（6.6）+ 联赛 P0 | 竞争结构可视化；自己在哪不需要找 |
| 绿色“前 N 晋级”线、珊瑚“后 N 降级”线（概念稿为 3/3） | zone 线 + tooltip（5.1） | 把规则画进榜，不用读说明书 |
| 联赛 `?` tooltip“周日结算” | Tooltip（6.8、5） | 规则就近解释，不占主界面 |
| 个人页大头像 + 余烬框、名字、等级/称号 chip | 个人页 P0 + `[R]` | 身份与成就先展示 |
| 收藏网格、已装备标记、统计 tile、齿轮、外观 tooltip | BadgeTile（6.7）+ 个人页 P1/P2 | 奖励可见、可装备；设置不抢首屏 |
| 深海军蓝 + 薄荷/金/珊瑚、28px 卡片、短中文、图标优先 | 第 2 节 token + 第 4 节文案 | 统一跨端语气与视觉节奏 |

---

## 8. 平台映射

### 8.1 边界

- **规范层**决定：语义 token、尺寸档位、组件 anatomy/状态、文案、tooltip 规则、页面信息优先级。
- **实现层**决定：CSS/Compose 写法、状态管理、资源加载、动画实现细节。
- 实现层不得新增语义色、字号档、组件状态或页面主操作；需要时先改 spec。
- 平台差异只允许出现在 8.5 列出的项目；其余必须一致。

### 8.2 Web / PWA

> 本节表中的尺寸、时长、比例均引用 2.2–2.5 的 token；除标“可调”外，均为必须一致。

| 项目 | 要求 |
| --- | --- |
| Token | 全部用 CSS custom properties；`:root` 定义；组件只引用 `var(--...)` |
| 色彩模式 | 固定深色；`color-scheme: dark`；不跟随浅色主题改变语义 |
| 图标 | 内联 SVG；`viewBox="0 0 24 24"`；`stroke="currentColor"`；装饰图标 `aria-hidden="true"` |
| tooltip | `role="tooltip"` + `aria-describedby`；不可聚焦；`Escape` 关闭 |
| 焦点 | 全局 `:focus-visible`；2px `color.focus`；offset 2；不得移除轮廓 |
| 动效降级 | `@media (prefers-reduced-motion: reduce)`；1ms；无位移/彩带；直接写终值 |
| 安全区 | `viewport-fit=cover`；`env(safe-area-inset-top/bottom)`；底部导航和内容留白 |
| 静态资源 | 本地 SVG/PNG/字体子集；不使用 CDN；离线可加载 |
| 触控 | 可点元素 `min-height/min-width: 48px`；hover 只做增强 |
| 文本缩放 | 200% 不裁切；不用固定高度锁文字 |
| 布局 | 390 单列 / 1440 rail + 三列；不横向溢出；长名字 `min-width: 0` + 省略 |

**最小样式契约（示意，不是完整实现）：**

```css
:root {
  --color-bg-canvas: #0B1020;
  --color-action-primary: #5CE0BE;
  --color-text-primary: #F4F7FF;
  --color-focus: #5CE0BE;
  --radius-card: 28px;
  --motion-score: 620ms;
}

:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 1ms !important;
    transition-duration: 1ms !important;
    scroll-behavior: auto !important;
  }
}
```

- 上例只展示映射方式；不得把 PWA 的 CSS 细节当成 Android 规范。
- Service Worker 缓存版本必须随样式/资源变更升级；本规格不规定具体缓存列表。

### 8.3 Android / Compose

> 本节表中的尺寸、时长、比例均引用 2.2–2.5 的 token；除标“可调”外，均为必须一致。

| 项目 | 要求 |
| --- | --- |
| 主题 | `MaterialTheme(colorScheme = darkColorScheme(...), typography = ..., shapes = ...)`；禁用动态取色 |
| 色彩 | `ColorScheme` 字段见 8.4；额外语义色用 `CompositionLocal` 的 `GhostColors` |
| 字体 | `FontFamily.SansSerif`；圆体可选；数字 `FontFeatureSettings("tnum")`；不打包中文字体 |
| 形状 | `Shapes(extraLarge = RoundedCornerShape(28.dp), large = 20.dp, medium = 16.dp, small = 12.dp)` |
| 导航 | 手机 `NavigationBar`（4 项）；平板/展开 `NavigationRail`；`WindowInsets.navigationBars`；若 Material 版本强制 80dp 高，保持 item 48dp 并同步底部留白，不裁切标签 |
| tooltip | `TooltipBox` + `PlainTooltip`；长内容 `ModalBottomSheet`；`rememberTooltipState` |
| 进度环 | `Canvas` + `drawArc(useCenter = false, style = Stroke(..., cap = StrokeCap.Round))`；`animateFloatAsState` 620ms |
| 动效 | `animate*AsState` / `Animatable` 使用 2.5 时长；读取 `LocalMotionDurationScale.current.scaleFactor` |
| 降低动效 | `scaleFactor == 0f` 直接写终值；`0 < scale < 1` 乘算；彩带/脉冲跳过 |
| 触控 | 48dp 最小；`Modifier.minimumInteractiveComponentSize()`；目标间距 ≥8dp |
| 图标 | Vector Drawable；24dp viewport；`tint`；装饰 `contentDescription = null` |
| emoji | 只做装饰；OEM 字体缺失时隐藏；功能图标必须有 vector 回退 |
| 边到边 | `enableEdgeToEdge()`；`WindowInsets.safeDrawing`；状态栏透明、浅色图标 |
| 深色 | 固定深色主题；不提供浅色主题；系统栏图标保持可读 |
| 字号缩放 | 跟随系统 `fontScale`；不锁 `sp`；2.0 下不裁切 |

### 8.4 Compose Theme 字段对照

> 8.4 的字段名来自 `[M]` Material 3；字段值是 2.2–2.5 的 token 映射。除注明“可调”外，均为必须一致。

#### 8.4.1 ColorScheme

| Compose 字段 | 语义 token | 值/说明 |
| --- | --- | --- |
| `primary` | `color.action.primary` | `#5CE0BE` |
| `onPrimary` | `color.text.onAccent` | `#071018` |
| `primaryContainer` | `color.action.primarySoft` | mint 16% |
| `onPrimaryContainer` | `color.action.primary` | `#5CE0BE` |
| `secondary` | `color.reward.primary` | `#F5C84C` |
| `onSecondary` | `color.text.onAccent` | `#071018` |
| `secondaryContainer` | `color.reward.soft` | gold 16% |
| `onSecondaryContainer` | `color.reward.primary` | `#F5C84C` |
| `tertiary` | `color.warning.primary` | `#FF6B6B` |
| `onTertiary` | `color.text.onAccent` | `#071018` |
| `background` | `color.bg.canvas` | `#0B1020` |
| `onBackground` | `color.text.primary` | `#F4F7FF` |
| `surface` | `color.bg.surface` | `#121A30` |
| `onSurface` | `color.text.primary` | `#F4F7FF` |
| `surfaceVariant` | `color.bg.raised` | `#1A2440` |
| `onSurfaceVariant` | `color.text.secondary` | `#A7B3D1` |
| `outline` | `color.border.strong` | rgba(167,179,209,0.55) |
| `outlineVariant` | `color.border.subtle` | rgba(167,179,209,0.14) |
| `error` | `color.warning.primary` | `#FF6B6B` |
| `onError` | `color.text.onAccent` | `#071018` |
| `errorContainer` | `color.warning.soft` | coral 14% |
| `onErrorContainer` | `color.warning.primary` | `#FF6B6B` |
| `scrim` | `color.bg.scrim` | rgba(4,7,17,0.74) |
| `surfaceTint` | `color.bg.raised` | 中性，不用绿色 elevation overlay |
| `inverseSurface` | `color.text.primary` | `#F4F7FF` |
| `inverseOnSurface` | `color.bg.canvas` | `#0B1020` |
| `inversePrimary` | `color.action.primaryPressed` | `#46C7A7` |

**`GhostColors` 扩展：**

| 字段 | 语义 token |
| --- | --- |
| `textTertiary` | `color.text.tertiary` |
| `reward` | `color.reward.primary` |
| `warning` | `color.warning.primary` |
| `tier` | `color.tier.current` |
| `xpTrack` | `color.xp.track` |
| `streakUnlit` | `color.streak.unlit` |
| `skeleton` | `color.skeleton` |
| `overlayHover` | `color.overlay.hover` |
| `overlayPressed` | `color.overlay.pressed` |

#### 8.4.2 Typography

| Compose 字段 | 字号/行高 | 字重 | 对应 token |
| --- | --- | --- | --- |
| `displayLarge` | 44/48（手机）；56/60（平板） | 800 | `type.score` |
| `headlineLarge` | 28/34（手机）；32/40（平板） | 800 | `type.h1` |
| `headlineMedium` | 22/28（手机）；24/30（平板） | 800 | `type.h2` |
| `titleMedium` | 16/24 | 700 | `type.title` |
| `value`（自定义） | 16/20 | 800 | `type.value` |
| `bodyLarge` | 16/24 | 500 | `type.body` |
| `bodyMedium` | 14/20 | 500 | `type.bodySmall` |
| `labelLarge` | 14/20（手机）；15/22（平板） | 700 | `type.label` |
| `labelMedium` | 12/16 | 600 | `type.caption` |
| `labelSmall` | 11/16 | 700 | `type.micro` |

- 数字样式加 `fontFeatureSettings = "tnum"`；标题字距 `-0.01em`，分数 `-0.02em`。
- 字段值是默认 Typography，不是固定写死；仍跟随系统 fontScale。

#### 8.4.3 Shapes / Dimens / Motion

| 类别 | 字段 | 值 | 来源/约束 |
| --- | --- | --- | --- |
| `Shapes` | `extraLarge` | 28dp | `[C][M]` / 必须一致 |
| `Shapes` | `large` | 20dp | `[M]` / 必须一致 |
| `Shapes` | `medium` | 16dp | `[M]` / 必须一致 |
| `Shapes` | `small` | 12dp | `[M]` / 必须一致 |
| `Dimens` | `topBarHeight` | 64dp（compact）/ 72dp（expanded） | `[I][S]` / 必须一致 |
| `Dimens` | `bottomNavHeight` | 64dp | `[C][I]` / 必须一致 |
| `Dimens` | `navRailWidth` | 88dp | `[S]` / 必须一致 |
| `Dimens` | `pageGutter` | 20dp（compact）/ 40dp（expanded） | `[S]` / 必须一致 |
| `Dimens` | `cardPadding` | 20dp / 24dp | `[S]` / 必须一致 |
| `Dimens` | `touchMin` | 48dp | `[A][M]` / 必须一致 |
| `Motion` | `press` | 90ms | `[S]` / 必须一致 |
| `Motion` | `fast` | 140ms | `[I]` / 必须一致 |
| `Motion` | `base` | 240ms | `[I]` / 必须一致 |
| `Motion` | `slow` | 420ms | `[I]` / 必须一致 |
| `Motion` | `score` | 620ms | `[I]` / 必须一致 |
| `Motion` | `celebrate` | 900ms | `[I]` / 必须一致 |
| `Motion` | `confetti` | 1300ms | `[I]` / 必须一致 |

**从 spec 生成 Compose Theme 的步骤：**

1. 按 8.4.1 映射 `darkColorScheme(...)`；`surfaceTint` 用 `bg.raised`，关闭绿色泛光。
2. 按 8.4.2 生成 `Typography`；数字样式加 tabular。
3. 按 8.4.3 生成 `Shapes`、`Dimens`、`Motion` 对象。
4. 用 `CompositionLocalProvider(LocalGhostColors provides ...)` 提供扩展色。
5. 用 token 对比度脚本验证；用 390dp 和 expanded 预览检查。

### 8.5 必须一致与允许差异

> 表中 token 数值见 2.2–2.5；列宽的 8dp 级微调为 `[S]`。

| 必须一致 | 允许差异 |
| --- | --- |
| 语义色及配对（mint/gold/coral/navy） | 状态栏高度、颜色、图标明暗 |
| 字号角色、行高、字重档位 | 字体光栅化、字距微调、OEM 字形 |
| 卡片 28、tooltip 16、pill 999 | 阴影/tonal elevation 的具体渲染 |
| 间距刻度、页面边距、内容最大宽 | 滚动回弹、滚动物理 |
| 动效时长与曲线语义 | 触摸 ripple、触觉反馈强度 |
| 48dp 触控、8dp 间距 | 系统手势区域、导航栏形式 |
| 4 个导航目的地与顺序 | 手机底部导航 / 平板 rail 的呈现 |
| 文案上限、禁用词、tooltip 上限 | tooltip 触发方式（hover vs tap/long-press），但都必须可键盘/读屏访问 |
| 图标网格、尺寸档、线宽 | 图标微调、圆角端点的光学修正 |
| 信息优先级、首屏内容 | 列宽在允许范围内的 8dp 级微调（`[S]`） |

---

## 9. Spec Driven 工作流

### 9.1 单一设计真相

- 本文件是唯一设计真相；设计稿、Figma、截图、实现代码都不得覆盖它。
- 改视觉的顺序：**改 spec → 评审 → 改 token/组件 → 改实现 → 截图验收**。
- 新组件/新页面必须先在 spec 增加契约（用途、anatomy、状态、尺寸、Web/Android 映射、a11y），再落地。
- 实现可以提出反例；反例先变成 spec 的修订，不在代码里“先做再说”。

### 9.2 版本号规则

语义化版本 `MAJOR.MINOR.PATCH`：

| 变更 | 版本位 | 例子 |
| --- | --- | --- |
| 导航结构、页面信息架构、token 语义、组件删除/重命名 | `MAJOR` | 5 Tab 改 4 Tab；珊瑚色语义改变 |
| 新增组件/状态/页面、新增 token、文案上限调整 | `MINOR` | 新增“周结算”组件；tooltip 上限 60→72 |
| 文案修正、错别字、澄清、不改变视觉的验收补充 | `PATCH` | 改一个错字；补一条对比度说明 |

**变更记录格式：**

```text
[版本] - YYYY-MM-DD
- 变更：...
- 原因：...
- 影响：Web / Android / 资源 / 文案
- 迁移：...
```

### 9.3 本轮变更记录

#### [1.0.0] - 2026-10-29

- 变更：首次定稿三屏平台无关规格；建立色彩、排版、间距、圆角、动效、图标、文案、tooltip、组件、页面蓝图与平台映射。
- 原因：把已选定的三屏概念沉淀为 PWA 与 Android 的共同实现依据。
- 影响：仅新增本文件；未改 `web/`、`ghost_league/`、`tests/`、`AGENTS.md`；Android 未实现。
- 迁移：PWA 现有 `#070a14`、24px 卡片、5 Tab、无 tooltip 等为后续实现差距；按本 spec 分单迁移。

### 9.4 新组件/新页面准入

新增前必须回答：

1. 它解决什么用户任务？为什么现有组件不够？
2. 它的信息优先级是什么？在 390/1440 放在哪里？
3. 它的 default/active/disabled/loading/error 分别是什么？
4. 它使用哪些语义 token？有没有新 token？新 token 的对比度是多少？
5. 文案是什么？长度是否在上限内？有没有禁用词？
6. 它需要 tooltip 吗？哪些规则不能只放 tooltip？
7. Web 映射和 Android 映射分别是什么？
8. 键盘、读屏、减少动效、200% 缩放怎么验收？

### 9.5 验收

| 验收项 | 方法 | 通过标准 | 证据 |
| --- | --- | --- | --- |
| Token 对照 | 对照本文件 2.2–2.5 与 Web CSS/Compose Theme | 语义色、字号、圆角、间距、动效时长 100% 有映射；无硬编码 | token diff / 主题文件 |
| 对比度 | 用 sRGB 公式计算文本/背景配对 | 正文 ≥4.5:1；大字 ≥3:1；UI 边界 ≥3:1 | 对比度报告 |
| 文案长度 | 脚本按 4.1 计数 | 全部不超上限；无禁用词；tooltip ≤3 行/60 字 | 文案检查输出 |
| tooltip 可访问性 | 只用键盘、读屏、触屏各走一遍 | 可打开/关闭；焦点不进入气泡；`Escape`/返回可用；读屏可读 | 录屏/检查表 |
| 390/1440 截图 | 三屏各两档；含 loading/empty/error/reduced-motion | 无横向溢出；首屏元素符合 7.2–7.4；信息优先级正确 | 截图目录 |
| Android 实现 | 至少一张 Compose 预览，或明确“未实现” | 若未实现，在实现状态中记录；若实现，预览覆盖三屏 | 预览截图/状态表 |
| 动效 | 检查时长、中断、减少动效 | 620ms 数字/环同步；一次只有一个庆祝；reduced 下无位移/彩带 | 动画检查 |
| 图标/emoji | 去 emoji、OEM 字体、TalkBack | 无 emoji 时功能仍可识别；无 tofu；无 emoji 唯一语义 | 检查表 |
| 触控 | 390 视口点击所有主要目标 | 目标 ≥48×48；间距 ≥8；无重叠 | 触控检查 |

**本轮（spec-only）验收：**

- 本文件新增，未改任何代码/数据/测试。
- 文档内数值均有 `[C]`/`[I]`/`[A]`/`[M]`/`[R]`/`[S]` 来源或标“可调”。
- 三屏主要元素均有映射和“为什么这样排”的解释。
- 未看过项目的人读完 60 秒读法和第 7 节，能说出三屏各放什么。
- 本地 commit 只包含 `docs/GAMIFIED_UI_SPEC.md`；`git status --short` 为空。

### 9.6 实现状态

| 平台 | 状态 | 说明 |
| --- | --- | --- |
| Web/PWA | 部分实现 | 现有深色联赛、XP 环、榜单、收藏可用；与 1.0.0 的差距：背景 `#070a14`、卡片 24px、5 个底部 Tab、无 tooltip 组件、金色/珊瑚色值不同 |
| Android/Compose | 未实现 | 本文提供可直接转成 `ColorScheme`/`Typography`/`Shapes`/`NavigationBar`/`Canvas` 的字段和规则；本轮不创建 Android 工程 |

---

## 附录 A：数值来源与可调性索引

| 数值组 | 值 | 来源 | 可调性 |
| --- | --- | --- | --- |
| 画幅 | 390×844 概念基准 | `[C]` | 必须一致（基准）；其他尺寸按断点 |
| 主色 | `#0B1020` / `#5CE0BE` / `#F5C84C` / `#FF6B6B` | `[C]` | 必须一致 |
| 卡片圆角 | 28 | `[C]` | 必须一致 |
| 动效 | 90–3000ms（含 1300/2800/3000 停留） | `[I]` | 必须一致 |
| 缓动 | 0.20,0.70,0.20,1 等 | `[I]` | 必须一致 |
| 触控 | 48 | `[A][M]` | 必须一致 |
| 字号 | 11–56 | `[C][I][S]` | 档位必须一致；1440 升档可调 |
| 间距 | 4–88 | `[S]` | 刻度必须一致；页面值可调 |
| 行高 | 16–60 | `[S]` | 必须一致 |
| 头像框 | 1.36D / 1.00D / 1.08 | `[R]` | 必须一致 |
| 文案上限 | 6–60 字符 | `[S]` | 必须一致 |
| 触控间距 | 8 | `[A]` | 必须一致 |

## 附录 B：tooltip 文案库

| 主题 | 文案 |
| --- | --- |
| 晋级/降级 | 前 3 晋级，后 3 降级。周日 24:00 结算。 |
| 段位升降 | 本周结算后按名次升降。前 3 晋级。 |
| 计算口径 | 有效时间自动折算 XP。100 XP 点火，2,000 XP 得 1 枚余烬。 |
| 余烬用途 | 只补签。不加 XP，不改名次。 |
| 外观影响 | 不加 XP，也不改名次。 |

> 以上文案均 ≤60 字符、≤3 行；N 按服务端配额替换，不写死。

## 附录 C：参考

- 概念稿：`/root/.hermes/imagegen-work/ghost-ui/concept_home.png`、`concept_league.png`、`concept_profile.png`、`concept_contact_sheet.jpg`
- 概念参数：同目录 `home.json`、`league.json`、`profile.json`
- 现有实现：`web/index.html`、`web/style.css`、`web/app.js`、`web/DESIGN-NOTES.md`
- 头像框：`docs/AVATAR_FRAME_SPEC.md`
- 游戏循环：`docs/GAME_LOOP_DESIGN.md`
- 无障碍：WCAG 2.2；Material 3 / Compose 组件与 window insets 文档

**图像审查说明**：本轮运行模型不声明图像输入，`read_image` 无法把概念图像素送入上下文。本规格依据概念生成参数（明确写出布局、文案、色值、28px 卡片、四 Tab）与现有实现的文字/代码证据整理，不声称逐像素目视确认。实现阶段必须用 390/1440 截图做视觉验收。
