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
/v1/widgets/<id>.png?token=...  # Android 图片组件拉取的公开生产图
web/assets/tiers, frames        # 通过 ghost:assets/... 原地引用，不复制
```

## 路径与地址

- 编辑器：`https://<ghost-host>/widget-studio/`（复用现有 TLS 入口，不新增端口）。
- API 前缀：`/v1/widget-studio`。
- 生产图：`https://<ghost-host>/v1/widgets/<id>.png?token=<render_token>...`。
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
  `<img>` 和 Canvas 加载；模版 JSON 与 `render_token` 不公开。
- 生产图不需要 Bearer，只认每份模版独立的 `render_token`。无 token 或错 token 一律
  `404`，不返回 `401`，不暴露模版是否存在。

## 模版 schema（version 3）

styles 是全局唯一样式源；每张底图只拥有自己的摆位与文字变体。

```json
{
  "version": 3,
  "id": "nijika",
  "name": "Nijika",
  "updated_at": "2026-10-30T23:30:00+08:00",
  "render_token": "32 lowercase hex chars",
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
3. 全部不命中时使用数组顺序中的第一个 `when: {}` fallback；
4. 调试参数 `bg=<bg_id>` 强制底图，但仍必须带正确的 `render_token`。

fallback 不参与“按 priority 抢占”，因此低优先级 fallback 不会遮住具体规则。

## API

统一前缀 `/v1/widget-studio`，JSON 请求/响应；`Auth` 表示现有 Bearer 依赖。

| 方法 | 路径 | Auth | 说明 |
| --- | --- | --- | --- |
| GET | `/templates` | 是 | 列表：`id,name,updated_at,background_count,text_count`。坏 JSON 跳过并记录 warning |
| POST | `/templates` | 是 | body `{name}`，从名称生成 slug，冲突加 `-2`，生成 `render_token`，并写入默认 fallback 底图 |
| GET | `/templates/{id}` | 是 | 完整 JSON |
| PUT | `/templates/{id}` | 是 | 校验 v3 + 原子写；`render_token` 保持不变，返回完整 JSON。没有 publish |
| DELETE | `/templates/{id}` | 是 | 删除整个 `data/widgets/<id>/` |
| POST | `/templates/{id}/assets/background` | 是 | multipart `file` + `bg_id`；只写 `backgrounds/<bg_id>.png`，返回 `{src}`，**不改 JSON** |
| POST | `/templates/{id}/assets/flame` | 是 | multipart `file`；只写 `flame.png`，返回 `{src}`，**不改 JSON** |
| GET | `/templates/{id}/assets/{filename}` | 否 | 模版本地图片，`Cache-Control: no-store` |
| GET | `/templates/{id}/backgrounds/{bg_id}/thumb?w=240` | 否 | 缩略图，列表不加载 1536 大图 |
| GET | `/library` | 否 | Ghost 资源库 `{id,label,url,src,group}`，`src` 形如 `ghost:assets/tiers/card/bronze.png` |
| GET | `/v1/widgets/{id}.png` | token | 生产图，见下 |

上传接口只负责落文件；编辑器把返回的 `src` 写进当前内存模版并标“未保存”，用户点
“保存”或按 Ctrl/Cmd+S 后才 PUT `template.json`。非法 id、`../`、非图片、超大文件、
未知 kind、缺 fallback、重复 bg id、非法 `ghost:` 路径都返回 4xx。

## 生产图

```text
GET /v1/widgets/<id>.png
    ?token=<render_token>
    &streak=12&xp=345&rank=3&name=<name>
    &hour=10&weekday=1&completed=1&league=bronze&event=rush
    [&size=1x]
    [&bg=<bg_id>]
    [&text=<text-id>]
```

- 默认 `1536×914` RGBA，圆角 `128`，圆角外 alpha=0；`size=1x` 由 1536 LANCZOS
  缩到 `368×219`。
- 每次都从 `data/widgets/<id>/` 重新读取 JSON 和图片，保存后下一次请求即生效。
- 选底图后，在该底图 `layout.texts` 中**随机选一条**文字；数字和火焰使用该底图的坐标。
- `text=<text-id>` 只用于调试/预览时固定文字；不传则随机。id 不属于当前底图时 `404`。
- 响应头：`X-Widget-Background: <bg_id>`、`X-Widget-Text: <text_id>`、
  `Cache-Control: no-store`。
- `hour`/`weekday` 缺省使用 `Asia/Shanghai` 当前时间；`streak/xp/rank` 缺省 0；
  `completed` 缺省 false；`league/event` 缺省空。
- `bg=` 仅用于调试，强制某张底图，仍需要正确 token。

示例：

```text
https://<ghost-host>/v1/widgets/nijika.png?token=<render_token>&streak=12&xp=345&rank=3&name=%E9%82%A3%E5%B0%94&hour=10&weekday=1&completed=1&league=bronze&event=rush
```

## 编辑器行为

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
  不改变已保存坐标。
- “生产预览”固定当前底图与文字变体；`随机预览` 清掉 `text=` 参数重新请求生产图，
  并在弹窗显示响应头里的 `X-Widget-Text`。主画布始终显示当前选中的文字变体，不随机跳。
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

E2E 会启动临时端口上的临时 Ghost 实例（仅测试进程，不新增 systemd），验证上传后
JSON 不变、拖动/输入等待 >1.5s 仍 0 PUT、Ctrl+S/保存按钮才 PUT、脏状态切换/刷新确认、
同一底图多个文字变体、`text=` 固定预览、随机预览响应头、底图 B 独立坐标、刷新恢复和
1440×900 / 390×844 截图。截图在 `artifacts/widget-studio-*.png`（本地产物，不进 Git）。

## 边界

- 不新增服务、端口、venv、ORM、SQLite 或图片 base64 JSON。
- 不复制 Ghost 的 tiers/frames；只读引用 `ghost:assets/...`。
- 不做样式编辑；样式全局统一，只调位置。
- 不做自动保存；只有 Ctrl/Cmd+S 或“保存”按钮写 JSON。
- 不做缩放/旋转/宽高调整、版本历史、备份、动画、滤镜、任意形状、自由绘画或图层混合。
- 目录文件是权威；没有 publish/版本表。
