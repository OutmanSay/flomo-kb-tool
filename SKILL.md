---
name: flomo-kb
description: 搜索本地 Flomo 知识库。按关键词、标签、时间范围查询历史笔记。
homepage: https://github.com/OutmanSay/flomo-kb-tool
metadata:
  openclaw:
    emoji: "📝"
    requires:
      bins: ["python3"]
    install:
      - id: clone
        kind: git
        repo: https://github.com/OutmanSay/flomo-kb-tool.git
        label: "Clone flomo-kb-tool"
---

# flomo-kb — 本地 Flomo 知识库搜索

搜索你的 Flomo 历史笔记，按关键词、标签、时间范围组合查询。

## 安装

```bash
git clone https://github.com/OutmanSay/flomo-kb-tool.git ~/.openclaw/workspace/skills/flomo-kb
```

## 配置

需要设置环境变量：
```bash
export NOTION_API_KEY="你的 key"
export NOTION_DATABASE_ID="你的数据库 ID"
```

## 使用

### 搜索笔记

当用户说"搜一下 Flomo"、"找一下我之前写的"、"我的笔记里有没有"等内容时：

```bash
python3 search_flomo.py --q "关键词"
python3 search_flomo.py --tag "标签名"
python3 search_flomo.py --q "关键词" --from-date "2025-01-01" --to-date "2025-12-31"
python3 search_flomo.py --limit 10
```

### 同步新笔记

当用户说"同步 Flomo"、"拉一下最新的笔记"时：

```bash
python3 flomo_kb_incremental_sync.py
```

### 统计

当用户问"我写了多少条 Flomo"、"哪个月写得最多"时：

读取 `flomo_kb/parsed/indexes/month_counts.json` 返回统计数据。

### 规则

1. 搜索结果返回笔记的创建时间、标签、内容预览
2. 如果用户想看完整内容，读取对应的 .md 文件
3. 默认返回最新的 10 条，用户说"多看几条"就加大 limit
