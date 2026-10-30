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
  = 一个固定 URL。换底图、文字、组件样式或条件，URL 不变；换外层模版，`template_id` 变。
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

## 模版 schema（version 4）

样式按底图存：顶层没有 `styles`，每张 `backgrounds[]` 自带 `styles.label` 与
`styles.counter`。火焰和数字是一个 `counter` 组件，`layout.counter` 只有火焰左上角锚点。

```json
{
  "version": 4,
  "id": "nijika-ref",
  "name": "Nijika Ref",
  "canvas": { "width": 1536, "height": 914, "radius": 128 },
  "backgrounds": [
    {
      "id": "bg-nijika",
      "name": "Nijika",
      "src": "backgrounds/bg-nijika.png",
      "when": {},
      "priority": 0,
      "fit": "cover",
      "offsetX": 0,
      "offsetY": 0,
      "scale": 1,
      "styles": {
        "label": {
          "width": 560,
          "height": 110,
          "fontSize": 76,
          "fontWeight": 700,
          "letterSpacing": 0,
          "strokeWidth": 0,
          "strokeColor": "#ffffff",
          "color": "#ffffff",
          "align": "left",
          "lineHeight": 1.2,
          "shadow": { "color": "rgba(0,0,0,0.35)", "blur": 6, "offsetX": 0, "offsetY": 4 }
        },
        "counter": {
          "scale": 1.0,
          "gap": 30,
          "flame": { "width": 170, "height": 220, "opacity": 1.0 },
          "number": {
            "width": 300,
            "height": 220,
            "fontSize": 132,
            "fontWeight": 700,
            "color": "#f7a61b",
            "align": "left",
            "lineHeight": 1,
            "shadow": { "color": "rgba(95,48,0,0.35)", "blur": 3, "offsetX": 0, "offsetY": 4 }
          }
        }
      },
      "layout": {
        "counter": { "x": 1080, "y": 95 },
        "texts": [
          { "id": "text-1", "text": "期待重逢！", "x": 1040, "y": 360 }
        ]
      }
    }
  ]
}
```

- `backgrounds[].styles` 是**该底图唯一**的样式源。切换底图时编辑面板和渲染都切换
  到该底图的 styles；改一张底图不影响其他底图。
- `counter.scale`：`0.5–2.0`。同时缩放火焰图像和数字字号，两者比例与相对位置锁定。
- `counter.gap`：`0–160` px。可见火焰右缘到数字可见左缘的距离，独立于 `scale`。
- 数字在组件内相对火焰**垂直居中**；水平位置 = 火焰可见右缘 + `gap`。数字底边因此
  明显高于火焰底边，两者底部不齐平。
- `layout.counter` 只有 `{x, y}`，是火焰样式盒左上角锚点；`layout.texts` 是文字变体。
  没有 `layout.streak` / `layout.flame`。
- 文字样式新增：
  - `letterSpacing`：`-10–40` px；
  - `strokeWidth`：`0–12` px；
  - `strokeColor`：默认等于 `color`，字段保留，可单独调整；
  - `fontWeight`：`100–900`。
- 一张底图的多个文字变体共用该底图的 `styles.label`；每条 `layout.texts[]` 只有
  `id`、`text`、`x`、`y`，位置各自独立。
- 每份模版至少一张底图，并且至少一个 `when: {}` fallback。
- `backgrounds[].id` 必须唯一；同一底图内 `layout.texts[].id` 必须唯一。
- `src` 只允许两种形式：
  - 模版本地相对路径：`backgrounds/<bg-id>.png`、`flame.png`，相对
    `data/widgets/<id>/`；
  - Ghost 资源库：`ghost:assets/...`，相对 `web/`。
- `src` 拒绝绝对路径、URL、反斜杠、`.`/`..` 段，以及逃出允许根目录的路径。
- 文本占位符：`{streak}`、`{xp}`、`{rank}`、`{name}`；缺失上下文时渲染为空字符串。
- 文字按 `styles.label.width` 自动换行（中文逐字、英文按词），超出
  `styles.label.height` 截断并写 warning 日志；描边绘制在填充下面。
- 旧 v3 / v2 数据不再接受：JSON API 返回 `422`，错误信息提示运行
  `scripts/migrate_widget_template_v4.py`；生产固定 URL 对坏/旧 JSON 仍按 `404` 处理。

### nijika-ref 对照模板

`data/widgets/nijika-ref/` 是 1536×914 的对照模版，用来固定火焰/数字/文字的比例：

```json
{
  "backgrounds": [{
    "styles": {
      "label": { "width": 560, "height": 110, "fontSize": 76, "fontWeight": 700, "color": "#ffffff" },
      "counter": {
        "scale": 1.0,
        "gap": 30,
        "flame": { "width": 170, "height": 220, "opacity": 1 },
        "number": { "width": 300, "height": 220, "fontSize": 132, "fontWeight": 700, "color": "#f7a61b" }
      }
    },
    "layout": {
      "counter": { "x": 1080, "y": 95 },
      "texts": [{ "id": "text-1", "text": "期待重逢！", "x": 1040, "y": 360 }]
    }
  }]
}
```

- 火焰按 alpha 可见区域缩放，再保留约 9% 内边距；170×220 的样式盒渲染出的可见
  火焰约 199px 高。数字字号 132 的可见高度约 100px，所以火焰高度约数字的 2 倍。
- 数字垂直中心与火焰可见中心对齐：数字底边约在 255px，火焰底边约在 304px，
  数字底边明显更高，两者不齐平。
- 服务端和编辑器 Canvas 使用同一套缩放/居中规则；编辑器按火焰图片的 alpha bbox
  裁掉透明边距后再绘制。
- 未完成状态（见下节）只改颜色，不改坐标、字号、宽高或火焰 alpha。

### v3 → v4 迁移

`scripts/migrate_widget_template_v4.py` 是幂等迁移工具，不是运行时兼容层：

```bash
python3 scripts/migrate_widget_template_v4.py data/widgets/*/template.json
```

- 把旧顶层 `styles` 深拷贝到每一张 background 的 `styles`，之后各底图可独立修改；
- `styles.streak` → `counter.number`，`styles.flame` → `counter.flame`；
- `counter.scale = 1.0`、`counter.gap = 30`；
- 旧 `layout.flame` → `layout.counter`；删除 `layout.streak` / `layout.flame`；
- 文字样式补 `letterSpacing: 0`、`strokeWidth: 0`、`strokeColor = color`；
- 已是 v4 的文件再次运行保持原样。

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
| GET | `/templates/{id}` | 是 | 完整 JSON；旧版本返回 422 + 迁移提示 |
| PUT | `/templates/{id}` | 是 | 校验 v4 + 原子写，返回完整 JSON。没有 publish |
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
未知 kind、缺 fallback、重复 bg id、非法 `ghost:` 路径、越界 scale/gap/字距/描边都
返回 4xx。

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
  **随机选一条**文字；组件和文字都只读**该底图自己的** `styles`，不读任何全局样式。
- 组件渲染：火焰按 `flame.width/height * counter.scale` 缩放；数字按
  `number.fontSize * counter.scale`；数字垂直中心对齐火焰可见中心，左缘位于
  火焰可见右缘 + `gap`。改变 `gap` 只移动数字，火焰不动。
- 响应头：`X-Widget-Background: <bg_id>`、`X-Widget-Text: <text_id>`、
  `X-Widget-Completed: 0|1`、`Cache-Control: no-store`。`X-Widget-Completed` 只用于调试，
  不改变 URL，也不接受 query。
- 未知 `user_id`、非法路径、模版目录不存在、`template.json` 坏 JSON/旧版本一律 `404`，
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

`completed_today=false` 时只改组件颜色，不改坐标、尺寸、文字样式或文字颜色：

- 火焰：保留 alpha 和形状，RGB 转灰度并略降亮度（×0.85）；不把整张图变透明。
- 数字：主色替换为纯灰 `#9a9a9a`（R=G=B，不带蓝调），阴影替换为
  `rgba(0,0,0,0.28)`；不用橙色。
- 文字：保持原色和原描边/阴影，不变灰。
- `completed_today=true` 时火焰恢复原色，数字恢复样式里的颜色。
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
- 换外层模版会改变 URL 中的 `template_id`；换底图、文字、组件样式或条件 URL 不变。
- 主画布固定逻辑坐标 `1536×914`，CSS 等比缩放；用 Canvas 2D 绘制当前底图、当前选中
  文字变体、以及火焰+数字组件。
- **火焰+数字是一个可选组件**：一个选择框覆盖可见火焰和数字；拖动组件同时移动两者，
  相对位置不变；方向键 1px，`Shift+方向键` 10px。不再分别选择/拖动火焰或数字。
  拖动时按住 `Shift` 吸附 8px 网格。
- 右侧属性面板按**当前底图**显示，并明确标出“当前底图：<id>”：
  - 组件：`组 X`、`组 Y`、`整体缩放`（0.5–2.0）、`火焰与数字间隔`（0–160）；
  - 文字：`字号`、`字重`、`字间距`、`描边宽度`、`文字颜色`、`描边颜色`
    （默认跟随文字颜色，可单独改）；
  - 当前底图的文字变体列表（摘要 + x/y），可新增/删除/选中；新增复制当前文字与坐标，
    至少保留一条。
- 修改只作用于当前底图；切换底图时控件值和画布随之切换，不复用上一张底图的样式或坐标。
- **显式保存**：拖动、pointerup、输入文字、改条件、改样式都不发 PUT；只有顶部
  “保存”按钮或 `Ctrl/Cmd+S` 才发送完整 snapshot。
- 状态：干净 `已保存 · data/widgets/<id>`；有改动 `未保存`；保存中 `保存中…`；
  失败 `保存失败：<原因>` 并保留 dirty 以便重试。保存按钮无改动时禁用，有改动时高亮。
- `beforeunload` 在 dirty 时提示；切换模版/新建/复制/删除前 `confirm`，取消则不切换。
- 自动/手动底图预览选择规则与 task123 一致；切换预览上下文只改变当前选中的底图，
  不改变已保存数据。右侧“今日已完成 是/否”只影响画布，火焰/数字按同一规则变灰或
  恢复，文字保持原色；不写文件、不改 URL。
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
node --check web/widget-studio/app.js

# 真实浏览器 E2E（使用共享 Playwright 环境，不新增 venv）
/opt/ui-venv/bin/python tests/e2e_widget_studio.py
```

E2E 会启动临时端口上的临时 Ghost 实例（仅测试进程，不新增 systemd），验证顶部固定
URL 的 `user_id` / `template_id`、换外层模版改 URL、换底图/文字/条件不改 URL、上传后
JSON 不变、拖动/输入等待 >1.5s 仍 0 PUT、Ctrl+S/保存按钮才 PUT、脏状态切换/刷新确认、
同一底图多个文字变体、无 query 直接打开固定 URL、固定 URL 响应头属于已保存底图、
组件拖动、底图独立坐标/样式、缩放/间隔/字重/字间距/描边保存与刷新恢复、nijika-ref 的
“今日已完成”灰度切换和火焰/数字比例，以及 1440 / 390 全页截图。截图在
`artifacts/widget-studio-{1440,390}.png`、
`artifacts/nijika-ref-{completed,incomplete}-{1440,390}.png` 和
`artifacts/nijika-ref-styled*.png`（本地产物，不进 Git）。

## 边界

- 不新增服务、端口、venv、ORM、SQLite 或图片 base64 JSON。
- 不复制 Ghost 的 tiers/frames；只读引用 `ghost:assets/...`。
- 不做自动保存；只有 Ctrl/Cmd+S 或“保存”按钮写 JSON。
- 不做旋转、版本历史、备份、动画、用户可配置滤镜、渐变、任意形状、自由绘画或图层混合；
  未完成灰度是固定状态，不是编辑器样式选项。
- 目录文件是权威；没有 publish/版本表。
