# flomo-kb-tool 📝

**把 Flomo 笔记变成本地知识库。全文搜索、标签索引、AI Agent 直接调用。**

---

## 为什么做这个？

Flomo 很好，但有两个问题：

1. **搜索太弱**：只能搜标题，不能全文搜、不能按标签+时间组合筛选
2. **数据在云端**：你的 3000+ 条笔记，想导出分析？想接入 AI？想本地备份？都不方便

这个工具把你的 Flomo 笔记全部同步到本地，建成一个可搜索、可查询、可被 AI 调用的知识库。

## 谁适合用

- 你用 Flomo 记了很多笔记，想本地备份
- 你想让 AI Agent 能搜索你的历史笔记
- 你想按标签、时间、关键词组合查询
- 你想把 Flomo 数据接入自己的知识管理系统（Obsidian 等）

## 它能做什么

| 功能 | 说明 |
|------|------|
| 🔄 增量同步 | 从 Notion 拉取最近 48 小时的 Flomo 笔记，自动去重 |
| 📁 本地知识库 | 按年/月目录存储，每条笔记一个 Markdown 文件 |
| 🏷️ 标签索引 | 自动建立标签 → 笔记的反向索引 |
| 🔍 全文搜索 | 按关键词、标签、时间范围组合查询 |
| 📊 统计 | 月度笔记数量分布 |
| 🤖 AI 友好 | 可被 OpenClaw / Claude Code 直接调用 |

## 前置条件

Flomo 笔记需要先同步到 Notion（通过 Flomo 的官方 Notion 集成）。本工具从 Notion API 读取数据。

你需要：
1. 一个 Notion Integration（API Key）
2. Flomo 同步到的 Notion Database ID

## 快速开始

### 1. 配置环境变量

```bash
export NOTION_API_KEY="你的 Notion API Key"
export NOTION_DATABASE_ID="你的 Flomo Notion 数据库 ID"
```

### 2. 首次全量同步

```bash
# 同步最近 48 小时的笔记到本地知识库
python3 flomo_kb_incremental_sync.py --hours 8760  # 365天，首次全量拉取
```

### 3. 日常增量同步

```bash
# 拉最近 48 小时的新增/修改
python3 flomo_kb_incremental_sync.py
```

### 4. 搜索笔记

```bash
# 按关键词搜索
python3 search_flomo.py --q "焦虑"

# 按标签搜索
python3 search_flomo.py --tag "project/日记"

# 组合查询：关键词 + 时间范围
python3 search_flomo.py --q "健身" --from-date "2025-01-01" --to-date "2025-12-31"

# 限制结果数
python3 search_flomo.py --q "读书" --limit 5
```

### 5. 同步到 Inbox（可选）

如果你用 Obsidian 或类似的知识管理系统，可以把新笔记同步到 inbox：

```bash
python3 flomo_sync_to_inbox.py
```

会在指定目录生成带 YAML frontmatter 的 Markdown 文件，方便被其他管线处理。

## 数据结构

```
flomo_kb/
├── parsed/
│   ├── notes_md/           # 笔记正文
│   │   ├── 2022/10/
│   │   ├── 2023/01-12/
│   │   ├── ...
│   │   └── 2026/04/
│   └── indexes/            # 索引
│       ├── flomo_notes.json    # 主索引（全部笔记元数据）
│       ├── tag_index.json      # 标签 → 笔记 ID 反向索引
│       ├── month_counts.json   # 月度计数
│       └── .sync_state.json    # 同步状态
```

### 笔记文件格式

```markdown
---
id: flomo-01927
created: 2025-03-03 17:03:38
source: notion_incremental_sync
tags:
  - area/解决焦虑的方法
has_audio: false
has_image: false
---

## 笔记

完全接纳自己的情绪和思维。不要试图控制...
```

## 作为 OpenClaw Skill 使用

跟你的 Agent 说：

> "学习这个 skill：https://github.com/OutmanSay/flomo-kb-tool"

然后就可以：

> "搜一下我之前写的关于焦虑的笔记"
> "我去年写了多少条 Flomo"
> "找一下带'读书'标签的笔记"

## 所有命令

### flomo_kb_incremental_sync.py

```bash
python3 flomo_kb_incremental_sync.py              # 默认最近 48 小时
python3 flomo_kb_incremental_sync.py --hours 168   # 最近 7 天
python3 flomo_kb_incremental_sync.py --hours 8760  # 最近 1 年（首次全量）
python3 flomo_kb_incremental_sync.py --dry-run     # 只看不写
python3 flomo_kb_incremental_sync.py --limit 50    # 最多拉 50 条
```

### search_flomo.py

```bash
python3 search_flomo.py --q "关键词"
python3 search_flomo.py --tag "标签名"
python3 search_flomo.py --q "关键词" --tag "标签"
python3 search_flomo.py --from-date "2025-01-01" --to-date "2025-12-31"
python3 search_flomo.py --limit 20
```

### flomo_sync_to_inbox.py

```bash
python3 flomo_sync_to_inbox.py    # 同步到 inbox capture 目录
```

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `NOTION_API_KEY` | ✅ | Notion Integration Token |
| `NOTION_DATABASE_ID` | ✅ | Flomo 同步到的 Notion 数据库 ID |
| `NOTION_DATA_SOURCE_ID` | 可选 | 如果有，跳过自动发现 |
| `FLOMO_SYNC_HOURS` | 可选 | 同步回看小时数（默认 30） |
| `FLOMO_SYNC_MAX_ITEMS` | 可选 | 单次最多拉取条数（默认 50） |

## License

MIT
