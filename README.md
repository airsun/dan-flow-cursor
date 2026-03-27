# Dan Flow Cursor

Cursor / Claude Code 会话看板。实时监控所有 AI 编码会话，一眼看清哪些在跑、哪些等你输入。

## 快速启动

```bash
python3 session-hub.py
```

打开 **http://localhost:7890**

## 看板功能

- **Workbench 首页** — 所有会话以卡片网格展示，按 全部 / 活跃 / Cursor / Claude 筛选
- **Needs Input 置顶** — 等待输入的会话琥珀色高亮浮到顶部，区分 BLOCKED（hard）和 IDLE?（soft），支持 dismiss
- **状态感知** — 三色状态点：🟢 执行中 / 🟠 等待输入 / ⚪ 空闲
- **子代理聚合** — 主会话卡片上用点阵展示子代理状态，点击展开浮层查看详情并可跳转子代理对话
- **对话详情** — 点击卡片查看完整对话，Markdown 渲染 + 代码高亮
- **可收起侧栏** — 扁平列表仅显示主会话，子代理数量以角标形式呈现

## 技术细节

- Python 3 标准库，零依赖，单文件后端
- 自动扫描 `~/.cursor/projects/` 和 `~/.claude/projects/` 下的 `.jsonl` 转录文件
- 自动识别 `subagents/` 目录下的子代理文件并与主会话建立父子关系
- 2 秒轮询，后端推断会话状态（user → 执行中，assistant → 等待输入，AskQuestion tool_use → hard blocked）
- 前端通过 CDN 加载 marked / highlight.js / DOMPurify
- 默认端口 `7890`，如需修改编辑 `session-hub.py` 中的 `PORT`

## 终端监听（可选）

```bash
python3 session-hub-watcher.py
```

彩色流式输出活跃会话的新消息，适合终端侧栏常驻。
