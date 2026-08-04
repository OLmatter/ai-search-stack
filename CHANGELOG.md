# Changelog

## [2.1.0] - 2026-08-05

### 🎯 重大调整：从分散 SOP+SKILL 到 1 顶层 SOP+SKILL

**用户原话**："不是一个工具一个sop。是只有一个sop和skill当做路由。根据任务把他们引导到不同工具。"

### Changed

- ❌ 删除 `tools/*/SOP.md`（5 份分散 SOP）
- ❌ 删除 `tools/*/SKILL.md`（5 份分散 SKILL）
- ❌ 删除 `docs/` 目录（choosing-tool / composition-patterns / quality-gate / query-design）
- ✅ 新增顶层 `SOP.md` —— 唯一 SOP：怎么选工具（路由）+ 怎么用（5 步流程）
- ✅ 新增顶层 `SKILL.md` —— 唯一 SKILL：4 个组合模式 + 3 维信号过滤 + query 模板
- ✅ `tools/<tool>/README.md` 保留（工具自己的部署 / 启动 / 失败回滚）
- ✅ README + ARCHITECTURE 重新设计（强调 1 SOP + 1 SKILL 路由）

### 设计变化

| v2.0.0 | v2.1.0 |
|---|---|
| 4 元文档（choosing / composition / quality-gate / query-design）| **1 顶层 SOP + 1 顶层 SKILL** |
| 5 per-tool SOP.md | 0 per-tool SOP.md（合并到顶层 SOP）|
| 5 per-tool SKILL.md | 0 per-tool SKILL.md（合并到顶层 SKILL）|
| 路由分散在 5 处 | **路由集中在 1 处** |

### 兼容

- 工具代码 / 启动脚本 / 客户端 / 部署流程：**完全不变**
- 用户只读 `SOP.md` + `SKILL.md` 就能用整个工具箱
- 想了解某个工具细节时，单独看 `tools/<tool>/README.md`

[2.1.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v2.1.0

## [2.0.0] - 2026-08-05

### Added
- 5 个独立工具：google-bridge / searxng / hackernews / github / chat-scraper
- 4 元文档 + 5 per-tool SOP/SKILL（**已被 v2.1 取代**）

[2.0.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v2.0.0

## [1.0.0] - 2026-08-05

### Added
- 首个稳定版
- `search_helper.py` v23.7
- README + ARCHITECTURE + CHANGELOG + .github CI
- MIT License

[1.0.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v1.0.0
