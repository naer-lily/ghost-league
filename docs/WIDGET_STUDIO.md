# Widget Studio

Widget Studio 是 Ghost League PWA 内的图片模版编辑器。它不新增服务、端口或虚拟环境：
编辑器静态页由现有 `ghost_league/pwa.py` 的 `StaticFiles` 提供，API 挂在现有 FastAPI
应用上，生产图由现有 Ghost 进程渲染。

```text
web/widget-studio/              # 编辑器静态页（index.html / styles.css / app.js）
        │  Bearer: localStorage["gl.token.v1"]；只有 Ctrl/Cmd+S 或“保存”才 PUT
        ▼
/v1/widget-studio/...           # 读写模版、上传资源、资源库、缩略图
        │  权威数据
        ▼
data/widgets/<id>/              # template.json + flame.png + backgrounds/*.png
        │  每次请求重新读取
        ▼
/v1/widgets/<user_id>/<template_id>.png  # Android 图片组件的固定生产图
web/assets/tiers, frames        # 通过 ghost:assets/... 原地引用，不复制
```

## 路径与地址

- 编辑器：`https://<ghost-host>/widget-studio/`（复用现有 TLS 入口，不新增端口）。
- API 前缀：`/v1/widget-studio`。
- 生产图固定两层路径：`https://<ghost-host>/v1/widgets/<user_id>/<template_id>.png`。
  `user_id` 是 Ghost 账号 ID，`template_id` 是外层模版目录 ID；一个用户 + 一个模版
  = 一个固定 URL。换底图、文字或条件，URL 不变；换外层模版，`template_id` 变。
- 生产图不接受数据 query；`streak`/`xp`/`rank`/`name`/`hour`/`weekday`/`completed`/
  `league`/`event`/`bg`/`text`/`token` 等参数都不改变渲染。
- 需要 1x 时用单独路径 `/v1/widgets/<user_id>/<template_id>-1x.png`。
- 运行时数据：`data/widgets/<id>/`。目录中的 JSON 与 PNG 是唯一真相源，不写数据库，
  不依赖前端缓存；修改文件后下一次生产请求立即生效，无需重启。
- Ghost 段位卡/头像框：`web/assets/tiers/card/*.png`、`web/assets/frames/*.png` 只读，
  用 `ghost:assets/...` 引用，不复制到模版目录。

`data/widgets/` 被 `.gitignore` 排除（仅保留 `.gitkeep`）。部署时目录由进程自动创建。

## 认证

- 编辑器从 Ghost PWA 现有的 `localStorage["gl.token.v1"]` 读取 Bearer token。
- token 不放进 URL、不写进 `template.json`，也不写进页面地址。
- 没有 token 时页面只显示“先登录 Ghost”和令牌输入框，不做重定向，不显示登录墙后的内容。
- 模版列表/详情和所有写接口要求现有 Bearer 认证；写接口不能匿名。
- 编辑器用的图片读取接口（`assets`、`thumb`、`library`）只读且不需要 Bearer，便于
  `<img>` 和 Canvas 加载；模版 JSON 不公开。
- 生产图不需要 Bearer，也不需要 token：URL 里的 `user_id` 与 `template_id` 就是全部
  寻址信息。用户不存在、模版目录不存在、路径非法或 JSON 损坏一律 `404`，不泄露
  其他信息。

## 模版 schema（version 3）

styles 是全局唯一样式源；每张底图只拥有自己的摆位与文字变体。

```json
{
  "version": 3,
  "id": "nijika",
  "name": "Nijika",
  "updated_at": "2026-10-30T23:30:00+08:00",
  "canvas": { "width": 1536, "height": 914, "radius": 128 },
  "styles": {
    "label": {
      "width": 520,
      "height": 100,
      "fontSize": 64,
      "fontWeight": 400,
      "color": "#17324d",
      "align": "left",
      "lineHeight": 1.15,
      "shadow": { "color": "rgba(255,255,255,0.65)", "blur": 0, "offsetX": 0, "offsetY": 2 }
    },
    "streak": {
      "width": 360,
      "height": 180,
      "fontSize": 132,
      "fontWeight": 400,
      "color": "#ffb020",
      "align": "left",
      "lineHeight": 1,
      "shadow": { "color": "rgba(255,255,255,0.75)", "blur": 0, "offsetX": 0, "offsetY": 3 }
    },
    "flame": { "width": 120, "height": 140, "opacity": 1 }
  },
  "backgrounds": [
    {
      "id": "bg-default",
      "name": "默认",
      "src": "backgrounds/bg-default.png",
      "when": {},
      "priority": 0,
      "fit": "cover",
      "offsetX": 0,
      "offsetY": 0,
      "scale": 1,
      "layout": {
        "texts": [
          { "id": "text-1", "text": "连续学习", "x": 760, "y": 540 },
          { "id": "text-2", "text": "今天也继续", "x": 760, "y": 540 }
        ],
        "streak": { "x": 760, "y": 300 },
        "flame": { "x": 660, "y": 280 }
      }
    }
  ]
}
```

- `styles` 是全局唯一样式源。编辑器与 API 都**不允许**按底图改样式；编辑器只读展示。
- 每张底图必须有 `layout.texts`，至少一条，可以有几十条。每条只有 `id`、`text`、
  `x`、`y`；宽度/高度/字体/颜色/阴影/行高都取 `styles.label`，`x/y` 是文字盒左上角。
- `layout.streak`、`layout.flame` 只有 `x/y`；尺寸/字体/颜色/透明度取全局 styles。
- 没有全局 `layers`：version 3 只接受底图自有摆位；带 `layers` 或 `version: 2` 的
  JSON 明确报错，不做静默兼容。
- 每份模版至少一张底图，并且至少一个 `when: {}` fallback。
- `backgrounds[].id` 必须唯一；同一底图内 `layout.texts[].id` 必须唯一。
- `src` 只允许两种形式：
  - 模版本地相对路径：`backgrounds/<bg-id>.png`、`flame.png`，相对
    `data/widgets/<id>/`；
  - Ghost 资源库：`ghost:assets/...`，相对 `web/`。
- `src` 拒绝绝对路径、URL、反斜杠、`.`/`..` 段，以及逃出允许根目录的路径。
- 文本占位符：`{streak}`、`{xp}`、`{rank}`、`{name}`；缺失上下文时渲染为空字符串。
- 文字按 `styles.label.width` 自动换行（中文逐字、英文按词），超出
  `styles.label.height` 截断并写 warning 日志；连胜数字使用 `{streak}` 与
  `styles.streak`。

### nijika-ref 对照模板

`data/widgets/nijika-ref/` 是 1536×914 的对照模版，用来固定火焰/数字/文字的比例：

```json
{
  "styles": {
    "label": { "width": 560, "height": 110, "fontSize": 76 },
    "streak": { "width": 300, "height": 220, "fontSize": 132 },
    "flame": { "width": 170, "height": 220, "opacity": 1 }
  },
  "layout": {
    "texts": [{ "id": "text-1", "text": "期待重逢！", "x": 1040, "y": 360 }],
    "streak": { "x": 1260, "y": 150 },
    "flame": { "x": 1080, "y": 95 }
  }
}
```

- 火焰按 alpha 可见区域缩放，再保留约 9% 内边距；170×220 的样式盒渲染出的可见
  火焰约 200px 高。数字字号 132 的可见高度约 96–100px，所以火焰高度 ≥ 数字的 1.8 倍。
- 服务端和编辑器 Canvas 使用同一套缩放规则；编辑器按火焰图片的 alpha bbox 裁掉透明
  边距后再绘制，不能只改服务端。
- 数字 `x=1260` 在火焰右侧，文字 `y=360` 在数字下方；三者像素 bbox 不重叠。

未完成状态（见下节）只改颜色，不改坐标、字号、宽高或火焰 alpha。

### v2 → v3 迁移

`scripts/migrate_widget_template_v3.py` 是一次性迁移工具，不是运行时兼容层：

```bash
python3 scripts/migrate_widget_template_v3.py data/widgets/nijika/template.json
```

它把原 `layers` 中的 label 文字/坐标复制成每张底图的 `layout.texts[0]`，把
number/flame 坐标复制成 `layout.streak` / `layout.flame`，并把字号/颜色/阴影等
收进全局 `styles`。迁移后的样例是 `data/widgets/nijika/template.json`。

## 条件 `when`

字段全部按 AND 组合；字段缺省表示不限：

| 字段 | 规则 |
| --- | --- |
| `hour_from` / `hour_to` | `0–23`，区间 `[from, to)`，支持跨夜（如 `22→5`） |
| `weekdays` | `1=周一 … 7=周日`，数组内 OR |
| `streak_min` / `streak_max` | 整数，包含边界 |
| `completed_today` | 布尔 |
| `league` | 段位字符串 |
| `event` | 事件标签字符串 |

选择顺序：

1. 只看带条件的底图，按 `priority` 降序、同优先级按数组顺序；
2. 第一个所有条件都命中的底图胜出；
3. 全部不命中时使用数组顺序中的第一个 `when: {}` fallback。

fallback 不参与“按 priority 抢占”，因此低优先级 fallback 不会遮住具体规则。

## API

统一前缀 `/v1/widget-studio`，JSON 请求/响应；`Auth` 表示现有 Bearer 依赖。

| 方法 | 路径 | Auth | 说明 |
| --- | --- | --- | --- |
| GET | `/templates` | 是 | 列表：`id,name,updated_at,background_count,text_count`。坏 JSON 跳过并记录 warning |
| POST | `/templates` | 是 | body `{name}`，从名称生成 slug，冲突加 `-2`，并写入默认 fallback 底图 |
| GET | `/templates/{id}` | 是 | 完整 JSON |
| PUT | `/templates/{id}` | 是 | 校验 v3 + 原子写，返回完整 JSON。没有 publish |
| DELETE | `/templates/{id}` | 是 | 删除整个 `data/widgets/<id>/` |
| POST | `/templates/{id}/assets/background` | 是 | multipart `file` + `bg_id`；只写 `backgrounds/<bg_id>.png`，返回 `{src}`，**不改 JSON** |
| POST | `/templates/{id}/assets/flame` | 是 | multipart `file`；只写 `flame.png`，返回 `{src}`，**不改 JSON** |
| GET | `/templates/{id}/assets/{filename}` | 否 | 模版本地图片，`Cache-Control: no-store` |
| GET | `/templates/{id}/backgrounds/{bg_id}/thumb?w=240` | 否 | 缩略图，列表不加载 1536 大图 |
| GET | `/library` | 否 | Ghost 资源库 `{id,label,url,src,group}`，`src` 形如 `ghost:assets/tiers/card/bronze.png` |
| GET | `/v1/widgets/{user_id}/{template_id}.png` | 否 | 固定生产图，见下 |
| GET | `/v1/widgets/{user_id}/{template_id}-1x.png` | 否 | 368×219 生产图 |

上传接口只负责落文件；编辑器把返回的 `src` 写进当前内存模版并标“未保存”，用户点
“保存”或按 Ctrl/Cmd+S 后才 PUT `template.json`。非法 id、`../`、非图片、超大文件、
未知 kind、缺 fallback、重复 bg id、非法 `ghost:` 路径都返回 4xx。

## 生产图

```text
GET /v1/widgets/<user_id>/<template_id>.png
GET /v1/widgets/<user_id>/<template_id>-1x.png
```

- 路径只有 `user_id` 和 `template_id`，没有数据 query。所有数据由服务端按
  `user_id` 从 `GameService.status_for_user(user_id)` 读取；带任意数据参数（例如
  `streak=999`）与不带参数渲染结果完全一致。
- 默认 `1536×914` RGBA，圆角 `128`，圆角外 alpha=0；`-1x.png` 由 1536 LANCZOS
  缩到 `368×219`。
- 每次都从 `data/widgets/<template_id>/` 重新读取 JSON 和图片，保存后下一次请求即生效。
- 用底图自己的 `when` / `priority` / fallback 选底图，再在该底图 `layout.texts` 中
  **随机选一条**文字；数字和火焰使用该底图的坐标。
- 响应头：`X-Widget-Background: <bg_id>`、`X-Widget-Text: <text_id>`、
  `X-Widget-Completed: 0|1`、`Cache-Control: no-store`。`X-Widget-Completed` 只用于调试，
  不改变 URL，也不接受 query。
- 未知 `user_id`、非法路径、模版目录不存在、`template.json` 坏 JSON 一律 `404`，
  不返回 `500`，不泄露其他信息。

服务端上下文：

| context | 来源 |
| --- | --- |
| `streak` | `status["streak"]["current"]` |
| `xp` | `status["xp"]` |
| `rank` | `status["rank"]`（可能为 null） |
| `name` | `status["display_name"]` |
| `league` | `status["tier"].lower()` |
| `completed_today` | 按 `status["checkin"]` 实际结构：字符串 source 非空为 true，`None` 为 false；布尔或对象字段（`completed` / `completed_today` / `checked_in` / `created` / `source`）也识别。字段缺失或结构未知时回退到 `today_xp >= required_xp` |
| `hour` / `weekday` | 服务端 `now_fn()` 的 Ghost 本地时区（`Asia/Shanghai`），`weekday` 为 1=周一 … 7=周日 |
| `event` | 固定 `null`；不接受 query |

### 今日未完成状态

`completed_today=false` 时只改颜色，不改坐标、尺寸或文字：

- 火焰：保留 alpha 和形状，RGB 转灰度并略降亮度（×0.85）；不把整张图变透明。
- 数字：主色替换为纯灰 `#9a9a9a`（R=G=B，不带蓝调），阴影替换为
  `rgba(0,0,0,0.28)`；不用橙色。
- 文字：保持白色和原阴影，不变灰。
- `completed_today=true` 时火焰恢复原色，数字恢复橙金。
- 编辑器预览使用同一个 `completed_today`：右侧“今日已完成 是/否”切换会立即重绘
  画布；生产图的状态仍由服务端从 `status_for_user` 读取，URL 不变。

示例：

```text
https://<ghost-host>/v1/widgets/naer-lily/nijika.png
https://<ghost-host>/v1/widgets/naer-lily/nijika-1x.png
```

## 编辑器行为

- 顶部“我的小组件”显示当前 Bearer 账号的 `user_id`、当前外层模版 `template_id` 和
  固定 URL（`/v1/widgets/<user_id>/<template_id>.png`），带复制按钮；当前用户来自
  `/v1/me/profile`，不在前端伪造。
- 换外层模版会改变 URL 中的 `template_id`；换底图、文字或条件 URL 不变。
- 主画布固定逻辑坐标 `1536×914`，CSS 等比缩放；用 Canvas 2D 绘制当前底图、当前选中
  文字变体、连胜数字和火焰。
- **显式保存**：拖动、pointerup、输入文字、改条件、改 x/y 都不发 PUT；只有顶部
  “保存”按钮或 `Ctrl/Cmd+S` 才发送完整 snapshot。
- 状态：干净 `已保存 · data/widgets/<id>`；有改动 `未保存`；保存中 `保存中…`；
  失败 `保存失败：<原因>` 并保留 dirty 以便重试。保存按钮无改动时禁用，有改动时高亮。
- `beforeunload` 在 dirty 时提示；切换模版/新建/复制/删除前 `confirm`，取消则不切换。
- 右侧只编辑摆位与文字内容：
  - 当前底图的文字变体列表（摘要 + x/y），可新增/删除/选中；新增复制当前文字与坐标，
    至少保留一条；
  - 文字内容 textarea，只改 `text`；
  - 文字、连胜数字、火焰的 x/y；
  - 全局样式只读展示，不提供字号/字重/颜色/阴影/行高/宽高输入。
- 切换底图时文字变体列表和 x/y 跟着切换，不复用上一张底图的坐标。
- 画布拖动只改 x/y，不做缩放/旋转/宽高调整；方向键 1px，`Shift+方向键` 10px，
  拖动时按住 `Shift` 吸附 8px 网格；元素至少保留 40px 在画布内。
- 自动/手动底图预览选择规则与 task123 一致；切换预览上下文只改变当前选中的底图，
  不改变已保存坐标。右侧“今日已完成 是/否”只影响画布，把 `completed_today` 传给
  `draw()`，火焰/数字按同一规则变灰或恢复，文字保持白色；不写文件、不改 URL。
- “生产预览”和“随机预览”都直接请求固定 URL，不带任何数据 query；有未保存改动时提示
  “生产预览显示已保存的版本”。弹窗显示响应头里的 `X-Widget-Background` /
  `X-Widget-Text` / `X-Widget-Completed`。主画布始终显示当前选中的文字变体，不随机跳。
- 底图列表只加载 `thumb`；当前底图按需加载并缓存。
- 只使用两个 localStorage key：`gl.token.v1` 与上次打开的模版 id；模版内容只落文件。

## 测试

```bash
cd /opt/ghost-league
PYTHONPATH=. pytest -q
ruff check ghost_league scripts tests
python3 -m compileall -q ghost_league scripts

# 真实浏览器 E2E（使用共享 Playwright 环境，不新增 venv）
/opt/ui-venv/bin/python tests/e2e_widget_studio.py
```

E2E 会启动临时端口上的临时 Ghost 实例（仅测试进程，不新增 systemd），验证顶部固定
URL 的 `user_id` / `template_id`、换外层模版改 URL、换底图/文字/条件不改 URL、上传后
JSON 不变、拖动/输入等待 >1.5s 仍 0 PUT、Ctrl+S/保存按钮才 PUT、脏状态切换/刷新确认、
同一底图多个文字变体、无 query 直接打开固定 URL、固定 URL 响应头属于已保存底图、
底图 B 独立坐标、刷新恢复、nijika-ref 的“今日已完成”灰度切换和火焰/数字比例，以及
1440×900 / 390×844 截图。截图在 `artifacts/widget-studio-*.png` 和
`artifacts/nijika-ref-{completed,incomplete}-{1440,390}.png`（本地产物，不进 Git）。

## 边界

- 不新增服务、端口、venv、ORM、SQLite 或图片 base64 JSON。
- 不复制 Ghost 的 tiers/frames；只读引用 `ghost:assets/...`。
- 不做样式编辑；样式全局统一，只调位置。
- 不做自动保存；只有 Ctrl/Cmd+S 或“保存”按钮写 JSON。
- 不做缩放/旋转/宽高调整、版本历史、备份、动画、用户可配置滤镜、渐变、描边、任意形状、
  自由绘画或图层混合；未完成灰度是固定状态，不是编辑器样式选项。
- 目录文件是权威；没有 publish/版本表。
