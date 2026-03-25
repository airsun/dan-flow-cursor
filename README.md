# Dan Flow Cursor

Cursor / Claude Code 会话看板。实时监控所有 AI 编码会话，一眼看清哪些在跑、哪些等你输入。

## 快速启动

```bash
python3 session-hub.py
```

打开 **http://localhost:7890**

## 看板功能

- **Workbench 首页** — 所有会话以卡片网格展示，支持按 全部 / 活跃 / Cursor / Claude 分类筛选
- **Needs Input 置顶** — 等待用户输入的会话自动浮到顶部，琥珀色高亮
- **状态感知** — 三色状态点：🟢 执行中 / 🟠 等待输入 / ⚪ 空闲
- **对话详情** — 点击卡片查看完整对话，Markdown 渲染 + 代码高亮
- **可收起侧栏** — 展开看全貌，收起省空间（状态点始终可见）

## 技术细节

- Python 3 标准库，零依赖，单文件后端
- 自动扫描 `~/.cursor/projects/` 和 `~/.claude/projects/` 下的 `.jsonl` 转录文件
- 2 秒轮询，后端推断会话状态（最后一条对话消息是 user → 执行中，assistant → 等待输入）
- 前端通过 CDN 加载 marked / highlight.js / DOMPurify
- 默认端口 `7890`，如需修改编辑 `session-hub.py` 中的 `PORT`

## 终端监听（可选）

```bash
python3 session-hub-watcher.py
```

彩色流式输出活跃会话的新消息，适合终端侧栏常驻。
