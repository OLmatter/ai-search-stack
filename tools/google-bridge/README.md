# google-bridge

> **undetected-chromedriver Chrome 桥** —— 真 Google 结果，绕开数据中心 IP 封锁。

通用搜索主力。**任何主题、任何语言**的广度搜索首选。配合 mihomo 节点切换几乎不会 CAPTCHA。

## 何时用

| 场景 | 适用 |
|---|---|
| 通用主题搜索 | ✅ 真 Google 结果，无平台限制 |
| 实时事件（24h） | ✅ 配合 since=24h |
| 中文 / 英文 / 任何语言 | ✅ 全部支持 |
| 任意 vendor（claude/chatgpt/...） | ✅ URL 参数 vendor 自由定义 |
| **特定中国平台内容（知乎/B站/小红书/微信公众号）** | ❌ 改用 `chat-scraper` |
| **GitHub 项目/release/CVE** | ❌ 改用 `github` 工具 |
| **社区反应/讨论（HN/Reddit）** | ❌ 改用 `hackernews` 工具 |

## 快速开始

```bash
# 1. 装依赖
pip install -r requirements.txt

# 2. 配环境
cp example_config.sh .env
vim .env  # 填 Chrome / chromedriver / mihomo 路径
source .env

# 3. 启动
bash start_search_helper.sh

# 4. 测试
curl "http://127.0.0.1:18799/health"
curl "http://127.0.0.1:18799/search?q=ENCODED&num=10&since=7d&vendor=claude&role=primary"
```

详见 `SOP.md`（部署步骤）+ `SKILL.md`（调用技巧）。

## 工具链

- `search_helper.py` — HTTP 桥（端口 18799）
- `start_search_helper.sh` — Linux 启动器（Xvfb + Chrome + 桥）
- `start_mihomo.sh` — mihomo 代理启动
- `auto_select_node.py` — 自动选最快 mihomo 节点
- `example_config.sh` — 环境变量模板

## 配套文档

- `SOP.md` — 部署 + 启动 + 失败回滚
- `SKILL.md` — 调用技巧 + 何时用 / 何时不用

## 关联

- ↔️ `mihomo`（必须）— 绕数据中心 IP 封锁
- ↔️ `searxng`（可选）— 主工具 CAPTCHA 锁时的兜底
- ↔️ `hackernews`（可选）— 社区反应验证
- ↔️ `github`（可选）— 代码/CVE 验证
- ↔️ `chat-scraper`（替代）— 32+ 中国平台