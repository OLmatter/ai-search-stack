"""chat-scraper v3.1.0 —— 中国平台聚合搜索（bilibili 官方 API + 百度 site: 路由）。

诚实声明：v3 从零重写；旧版（宣称 32+ 平台）代码损失为纯 NUL 空壳，不可考。
实测覆盖与已知限制见 README.md，不要按平台数量估算本工具能力。
"""
from .search import list_platforms, search

__version__ = "3.1.0"
__all__ = ["search", "list_platforms", "__version__"]
