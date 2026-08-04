# Contributing

欢迎贡献！请遵守以下规则。

## 提交 PR 之前

1. **先 issue 讨论** —— 大的改动先开 issue 说清楚要做什么、为什么
2. **小改动直接 PR** —— typo / 文档修正 / 单文件 bug 修复
3. **保持向后兼容** —— search_helper.py 的 API 已稳定，新功能默认不加 breaking change
4. **本地测试** —— 跑过才能 push

## 本地开发

```bash
# clone
git clone https://github.com/OLmatter/ai-search-stack
cd ai-search-stack

# 装依赖
pip install -r requirements.txt

# 配环境
cp example_config.sh .env
vim .env  # 填你的 Chrome / chromedriver / mihomo 路径

# 跑
source .env
bash start_search_helper.sh

# 测
curl http://localhost:18799/health
curl "http://localhost:18799/search?q=test&num=5&since=7d&vendor=test&role=primary"
```

## 代码风格

- Python: PEP 8
- Bash: `shellcheck` 通过
- 注释用中文（项目面向中文用户）
- 提交 message 英文或中文都行，但说清楚"为什么"

## 版本发布

1. 改 `CHANGELOG.md` 加新版本
2. `git tag v1.x.x && git push --tags`
3. GitHub Release 自动建
4. 不发 PyPI / Docker Hub（项目目前用 git clone 即用）

## Issue 报告

bug report 请包含：
- 复现步骤
- 期望行为 vs 实际
- search_helper.py 版本（`git rev-parse HEAD`）
- OS / Chrome 版本
- honeypot.jsonl 相关行（脱敏后）

## License

贡献者协议：你的贡献按 MIT 发布。
