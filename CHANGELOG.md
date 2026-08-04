# Changelog

所有版本变更记录。

## [2.0.0] - 2026-08-05

### 🎉 重大重构：从单工具到 toolbox

- **新设计哲学**：5 个独立工具 + 4 个元文档，**不强行统一 API**
- **新结构**：
  ```
  docs/                  元文档（横切所有工具）
  tools/google-bridge/   Chrome 桥（原 search_helper）
  tools/searxng/         公网元搜（新增）
  tools/hackernews/      HN Algolia（新增）
  tools/github/          GitHub API（新增）
  tools/chat-scraper/    32+ 中国平台（从 OLmatter/chat-scraper 合并入）
  ```
- **每个工具独立**：
  - 自带 `README.md`（工具介绍）
  - 自带 `SOP.md`（部署 + 启动 + 维护）
  - 自带 `SKILL.md`（调用技巧 + 何时用）
  - 自带 `requirements.txt`
  - 可单独用 / 单独换 / 单独维护
- **4 个元文档**：
  - `docs/choosing-tool.md` —— 决策树 + 决策矩阵
  - `docs/composition-patterns.md` —— 4 个工作流（找+验 / 跨语言 / 兜底链 / 监控+验证）
  - `docs/quality-gate.md` —— 3 维信号过滤
  - `docs/query-design.md` —— query 怎么写

### Added

- `tools/searxng/client.py` —— SearXNG 元搜索客户端
- `tools/hackernews/client.py` —— HN Algolia 客户端
- `tools/github/client.py` —— GitHub Releases / Advisories / Repo Search
- `tools/chat-scraper/` —— 32+ 中国平台 scraper（从 chat-scraper 合并入）

### Changed

- `tools/google-bridge/search_helper.py`（原 root search_helper.py）—— 移入子目录
- README 重新设计：toolbox 模式 + 工具对比表
- ARCHITECTURE 调整：toolbox 模型
- CI 升级：5 个 tool 矩阵语法检查

### Migration from v1.0

- 旧调用：`curl http://localhost:18799/search?q=...&vendor=claude&role=primary`
- 新调用：`curl http://localhost:18799/search?q=...&vendor=claude&role=primary`（**路径不变**，仍用 18799）
- 旧目录：`./search_helper.py` → 新目录：`tools/google-bridge/search_helper.py`
- 旧 symlink 可加：`ln -s tools/google-bridge/start_search_helper.sh start_search_helper.sh`

[2.0.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v2.0.0

## [1.0.0] - 2026-08-05

### Added
- 首个稳定版
- `search_helper.py` v23.7（Chrome 桥）
- `start_search_helper.sh` / `start_mihomo.sh` / `auto_select_node.py`
- README + ARCHITECTURE + CHANGELOG + CONTRIBUTING + .github CI
- MIT License

[1.0.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v1.0.0
