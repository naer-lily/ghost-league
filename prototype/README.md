# 点火联赛 · 交互原型

`docs/GAMIFIED_UI_SPEC.md` 1.2.1 的可点击原型。独立于现有 `web/`，不接后端，不改生产前端。

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

## 技术

- Vite + React + TypeScript。
- 纯 CSS + CSS 自定义属性，设计 token 全部在 `src/styles.css` 顶部；没有 Tailwind。
- `lucide-react` 提供功能图标；不使用 emoji 承担语义。
- `@radix-ui/react-tooltip` 提供 hover / focus / 点击 / 键盘可访问的 tooltip。
- 头像框与段位素材从现有 `web/assets/` 复制到 `public/assets/`，原型不引用生产路径。
- Mock 数据集中在 `src/data.ts`，页面动作由 `src/store.tsx` 驱动。

## 页面

| Tab | 内容 | 真实动作 |
| --- | --- | --- |
| 首页 | XP 环、今日状态、连续天数、三张统计卡、组内位置、最近动态 | 分享战绩、补签、刷新、声音、查看完整榜、查看全部动态、查看余烬、回应动态、进我的 |
| 小组榜 | 段位 / 组名、结算倒计时、前三、晋级区、降级区、15 行 | 切小组 / 好友榜、打开成员详情、关注 |
| 余烬 | 余额、获取规则、补签入口、流水 | 补签（同一个补签面板） |
| 历史 | 已结束周、周详情、空态、加载态 | 打开周详情 |
| 我的 | 头像、资料、图标主题、收藏、集成、附近的人、开关、账号 | 选图预览、保存资料、切图标主题、筛选 / 装备收藏、打开说明 / 附近、声音 / 触觉、退出 |

动作按现有 DOM/事件/API 收敛：没有创作入口，打卡只由今日 XP 自动触发，没有“回到我的行”，没有商店。

## Mock 行为

- 刷新：转圈 600ms，随后 toast「已更新」。
- 分享：toast「战绩卡已生成」，不生成图片。
- 补签：选一个候选日，点击后扣 1 枚余烬并写一条流水；余烬不足或没有候选时确认按钮禁用。
- 头像：`input[type=file]` + 本地预览；保存资料只更新内存和名称 / 主题的本地偏好。
- 收藏：头像框 / 勋章 / 背景各有一个已装备项；筛选与装备状态都可用图标 + 文字识别。
- 声音 / 触觉：本地偏好；触觉调用 `navigator.vibrate`（设备不支持时静默跳过）。
- 退出：二次确认后进入本地登录页，再点「重新进入」回到首页。

## 状态预览

历史页支持两个 URL 参数，方便验收空态和加载态：

```text
http://127.0.0.1:4173/?history=empty
http://127.0.0.1:4173/?history=loading
```

它们只是预览入口，界面上没有伪造的状态切换按钮。

## 验收

```bash
cd prototype
CHROME_PATH=/path/to/chrome npm run test:e2e
```

`CHROME_PATH` 可选；如果 Playwright 自带的 Chromium 已安装，直接运行 `npm run test:e2e`。

脚本会：

- 在 390×844 与 1440×900 截图 5 个页面（另有完整页面、tooltip、详情、补签、空态 / 加载态、筛选、登录等补充截图）。
- 点击 5 个 tab，验证刷新、分享、补签、tooltip（hover / focus / tap / Esc）、成员详情（Esc / 遮罩）、收藏筛选 / 装备、声音 / 触觉、图标主题、头像预览、退出 / 重新进入。
- 检查 console error、page error、横向溢出、可见按钮触控尺寸 ≥44px、禁用文案。
- 输出 `artifacts/prototype/report.json`，含关键元素 bounding box 与各项检查结果。

截图根目录：`artifacts/prototype/`。

## 已知缺口

- 15 人榜单在 1440×900 首屏不能全部铺开，需要滚动；完整列表在 `artifacts/prototype/full/1440-league.png`。
- 不实现 30 人小组规则，UI 只声称 15 人。
- 后端全部为 mock：刷新、分享、补签、上传、关注、登录都没有网络请求。
- 声音开关不播放音频；图标主题只改变描边 / 填充。
- 历史空态 / 加载态通过 URL 参数预览。
- 联赛是一级导航 Tab，按规格不设返回按钮；详情 sheet 的关闭 / Esc / 遮罩承担返回。
- 没有 4 Tab 合并、等级进度条、商店、锦标赛或创作入口。
- 这是独立原型，不是生产 PWA。
