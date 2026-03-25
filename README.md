# Dan Flow Cursor

AI 编码会话监控与 OpenSpec 规范驱动工作流工具集，用于 Cursor 和 Claude Code 的协同开发。

## 功能概览

| 工具 | 说明 |
|------|------|
| **Session Hub** | Web 看板 — 实时查看所有 Cursor / Claude Code 会话的对话内容 |
| **Session Hub Watcher** | 终端监听器 — 在终端实时输出活跃会话的新消息 |
| **OpenSpec 工作流** | 基于 `opsx-*` 命令的规范驱动变更流程（Cursor / Claude 双端可用） |

## 环境要求

- **Python 3.10+**（仅依赖标准库，无需安装第三方包）
- **Cursor IDE** 或 **Claude Code**（至少安装其中之一）
- 浏览器需能访问 CDN（Session Hub 前端加载 marked / highlight.js / DOMPurify）

## 快速开始

### 1. Session Hub — Web 看板

```bash
python3 session-hub.py
```

启动后访问 **http://localhost:7890** 即可打开看板。

看板会自动发现并展示以下路径的会话记录：

- `~/.cursor/projects/**/agent-transcripts/**/*.jsonl`（Cursor 会话）
- `~/.claude/projects/**/*.jsonl`（Claude Code 会话及子代理）

支持的功能：
- 按项目分组查看所有会话
- 实时更新（2 秒轮询）
- 活跃会话高亮（10 分钟内有活动）
- Markdown 渲染 + 代码高亮
- 区分 user / assistant / thinking 角色

### 2. Session Hub Watcher — 终端监听

```bash
python3 session-hub-watcher.py
```

以彩色流式输出所有活跃会话的新增消息，适合在终端侧栏常驻。首次启动时跳至文件末尾，只显示启动后的新消息。

### 3. OpenSpec 工作流

OpenSpec 是规范驱动的变更流程，通过 Cursor 命令面板（`Cmd+Shift+P`）或 Claude Code 的 `/opsx-*` 命令触发。

#### 可用命令

| 命令 | 用途 |
|------|------|
| `/opsx-new` | 新建变更 — 开始一个新功能或修复 |
| `/opsx-continue` | 继续 — 推进当前变更到下一阶段 |
| `/opsx-ff` | 快进 — 一键生成所有剩余 artifact |
| `/opsx-apply` | 实施 — 根据变更 artifact 进行代码实现 |
| `/opsx-verify` | 验证 — 检查实现是否匹配变更规范 |
| `/opsx-sync` | 同步 — 将 delta spec 合并到主 spec |
| `/opsx-archive` | 归档 — 完成并归档单个变更 |
| `/opsx-bulk-archive` | 批量归档 — 一次归档多个完成的变更 |
| `/opsx-explore` | 探索 — 思维伙伴模式，探索想法或理清需求 |
| `/opsx-onboard` | 引导 — 完整工作流演练 |

#### OpenSpec 配置

配置文件位于 `openspec/config.yaml`，可自定义项目上下文和各 artifact 规则：

```yaml
schema: spec-driven

# 项目上下文（可选）
# context: |
#   Tech stack: TypeScript, React, Node.js
#   Domain: e-commerce platform

# 按 artifact 设置规则（可选）
# rules:
#   proposal:
#     - Keep proposals under 500 words
#   tasks:
#     - Break tasks into chunks of max 2 hours
```

## 项目结构

```
dan-flow-cursor/
├── session-hub.py              # Web 看板服务（端口 7890）
├── session-hub.html            # 看板前端页面
├── session-hub-watcher.py      # 终端实时监听器
├── openspec/
│   ├── config.yaml             # OpenSpec 配置
│   ├── changes/                # 变更目录
│   │   └── archive/            # 已归档变更
│   └── specs/                  # 项目规范
├── .cursor/
│   ├── commands/               # Cursor 端 opsx-* 命令
│   └── skills/                 # Cursor 端 Agent Skills
└── .claude/
    ├── commands/opsx/           # Claude Code 端 opsx 命令
    └── skills/                 # Claude Code 端 Agent Skills
```

## 常见问题

**Q: Session Hub 页面样式异常？**
前端依赖 CDN 加载样式和脚本库，请确保网络可访问 cdnjs.cloudflare.com 和 cdn.jsdelivr.net。

**Q: 看板上看不到任何会话？**
确认 Cursor 或 Claude Code 已产生过会话记录（`~/.cursor/projects/` 或 `~/.claude/projects/` 下存在 `.jsonl` 文件）。

**Q: 端口 7890 被占用？**
端口在 `session-hub.py` 中硬编码为 `PORT = 7890`，如需修改请直接编辑该文件。
