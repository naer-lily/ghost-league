# Ghost League v2 · 交互原型

Duolingo-close 的暗色可交互原型：先同构（周路径 / 领奖台 / 四宫格 / 5 Tab），再 Ghost 化。
保留 React + Vite + TypeScript，独立于现有 `web/`，不接后端。v1 留在 git 历史里。

## 启动

```bash
cd prototype
npm install
npm run dev -- --host 127.0.0.1 --port 4173
```

打开 `http://127.0.0.1:4173/`。

构建：

```bash
npm run build
```

## 页面结构

| Tab | 结构 | 真实动作 |
| --- | --- | --- |
| 首页 | 三资源状态条、绿色 unit banner、周一至周日垂直蜿蜒路径、余烬精灵 | 刷新、声音、节点详情、分享、补签、小组榜、全部动态、余烬 |
| 小组榜 | 段位徽章 + 组名 + 倒计时、前三领奖台、15 人榜、晋级/降级细条 | 切小组/好友、成员详情、关注 |
| 余烬 | 大号余烬精灵 + 余额 + 补签、紧凑流水 | 补签、查看流水 |
| 历史 | 大排名数字 + 段位图标 + XP、周详情 | 查看周详情 |
| 我的 | 头像 + 名字 + 段位、四宫格统计、横向收藏图标网格 | 编辑头像/名字、收藏筛选/装备、设置、集成说明、附近的人、声音/触觉、退出 |

规则说明收在 `?` tooltip；页面正文只保留名字、数字、状态词和按钮标签。
「首页」不出现解释段落，分享 / 补签 / 榜单 / 动态都从顶部状态或节点详情 sheet 进入。

## 技术

- Vite + React + TypeScript。
- 纯 CSS + CSS 自定义属性；Duolingo 暗色 token 在 `src/styles.css` 顶部：
  `#131f24` / `#202f36` / `#37464f` / `#58cc02` / `#1cb0f6` / `#ff9600` / `#ffc800` / `#ff4b4b`。
- 2px 实线边框 + 16–20px 圆角；主按钮 4px 3D 底边，按下位移 2px。
- `lucide-react` 提供线性图标；`@radix-ui/react-tooltip` 提供 hover / focus / 点击 / 键盘 tooltip。
- 余烬精灵、路径节点、领奖台、榜单行、统计格均为自绘 / CSS，不复制 Duolingo 角色或品牌素材。
- Mock 数据集中在 `src/data.ts`，页面动作由 `src/store.tsx` 驱动。

## 响应式

- `< 960px`：固定底部 5 Tab，390×844 首屏可见完整 7 天路径。
- `≥ 960px`：左侧 rail。
- `≥ 1200px`：左侧 rail + 中间 560px 主列 + 右侧 300px 窄栏，不做三列 dashboard。

## 验收

```bash
cd prototype
npm run build
CHROME_PATH=/usr/bin/google-chrome npm run test:e2e
```

`CHROME_PATH` 可选；Playwright 自带 Chromium 已安装时直接运行 `npm run test:e2e`。

脚本会：

- 在 390×844 与 1440×900 截图 5 个页面，并输出完整页、tooltip、节点详情、补签、分享 / 动态、成员详情、好友榜、设置、编辑资料、收藏筛选、周详情、历史空态 / 加载态、登录页和触屏 tooltip。
- 验证 5 个 Tab、7 天路径、今日 XP、三资源状态条、倒计时、15 人榜、绿色个人行、晋级 / 降级条、tooltip、补签消耗、关注、收藏筛选 / 装备、声音 / 触觉、图标主题、头像预览 / 保存、退出 / 重新进入。
- 检查 console error、page error、横向 overflow、可见交互元素 ≥44px、禁用词。
- 统计首页可见文本（`document.body.innerText`，去空白）：v2 390 为 52 字符（v1 263，减少 80.2%）；v2 1440 为 125 字符（v1 318，减少 60.7%）。
- 输出 `artifacts/prototype-v2/report.json`。

截图根目录：`artifacts/prototype-v2/`。必看：

```text
390/home.png  390/league.png  390/embers.png  390/history.png  390/me.png
1440/home.png 1440/league.png 1440/embers.png 1440/history.png 1440/me.png
```

## 已知缺口

- 全部为本地 mock：刷新、分享、补签、关注、上传头像、保存资料、登录都没有网络请求。
- 分享不生成真实分享图；头像只在本机预览，不上传。
- 声音开关只切换状态与提示，不播放音频；触觉调用 `navigator.vibrate`（设备不支持时静默）。
- 15 人榜在 390×844 首屏需要滚动；完整榜单见 `full/390-league.png`。
- 历史空态 / 加载态通过 `?history=empty` / `?history=loading` 预览，没有额外界面开关。
- 不实现 30 人小组规则；UI 只按 15 人组声称前 3 晋级 / 后 3 降级。
- 图标主题只改变描边 / 填充，不改变信息架构。
- 这是独立原型，不是生产 PWA；未修改 `web/`、`ghost_league/`、`tests/`。
