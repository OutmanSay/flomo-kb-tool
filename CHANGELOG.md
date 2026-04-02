# Changelog

## v1.0.0 (2026-04-02)

### 首次发布

- Notion → 本地知识库增量同步（`flomo_kb_incremental_sync.py`）
- 全文搜索 + 标签搜索 + 时间范围查询（`search_flomo.py`）
- Inbox 同步（`flomo_sync_to_inbox.py`）
- 自动建立三级索引：主索引 / 标签索引 / 月度统计
- 按年/月目录存储，Markdown 格式 + YAML frontmatter
- 自动去重（date + text_preview[:80]）
- OpenClaw Skill 支持
