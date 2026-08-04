# Changelog

所有版本变更记录。格式基于 [Keep a Changelog](https://keepachangelog.com/)。

## [1.0.0] - 2026-08-05

### Added
- 首个稳定版
- `search_helper.py` v23.7（undetected-chromedriver + 持久 UDD + CAPTCHA 指数 backoff + honeypot + query-metrics 字段）
- `start_search_helper.sh`（Xvfb + Chrome + 桥一键启动）
- `start_mihomo.sh`（mihomo 节点启动）
- `auto_select_node.py`（自动选最快 mihomo 节点，绕 IP 黑名单）
- `requirements.txt`、`example_config.sh`、`.gitignore`
- `README.md`（setup + API + 实测数据）
- `ARCHITECTURE.md`（为什么这样设计）
- MIT License

### Features
- URL 参数必传 `vendor` / `role`（指标可信的唯一保障）
- since 默认 7d（不是 24h）—— 2-3 天前的稳定信号
- CAPTCHA 锁立即切 fallback（实测 162s retry 浪费 vs 立即切）
- 3 维 Quality Gate（来源 / 完整性 / 时效）
- 多源验证 ≥2
- 7×24 cron 跑 30+ 天实测 0 永久锁 + 60% 命中率

### Tested with
- no1_agent 实例 A：27 条真事件已推送
- 0 CAPTCHA 永久锁
- 命中率 ~60%

[1.0.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v1.0.0
