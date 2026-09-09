"""chat-scraper v3.6.0 —— 中国平台聚合搜索（bilibili 官方 API + 百度 site: 路由
+ 知乎官方 API 内容线 + 通用阅读器）。

诚实声明：v3 从零重写；旧版（宣称 32+ 平台）代码损失为纯 NUL 空壳，不可考。
实测覆盖与已知限制见 README.md，不要按平台数量估算本工具能力。

v3.6.0：本工具箱（连同 hackernews/github/searxng/google-bridge/doctor）可经
`python tools/mcp_server.py` 以 stdio MCP server 形态被任何 MCP 客户端直接
调用——接入层原样透传，本包 API 不变。
"""
from .search import list_platforms, search

__version__ = "3.6.0"
__all__ = ["search", "list_platforms", "__version__"]
