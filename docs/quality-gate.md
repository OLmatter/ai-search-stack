# Quality Gate（3 维信号过滤）

> 任何工具返回的结果，都要过这 3 维过滤。**单维"看起来像"不够，3 维都通过才是真信号**。

## 3 维

| 维度 | 拒绝 | 接受 |
|---|---|---|
| **来源** | 个人博客无来源 / 营销聚合 / 第三方中转 | 官方域 / 技术社区 / 主流媒体 / 带 PoC 的安全研究 |
| **完整性** | 标题党 / 纯吐槽 / 无复现步骤 | 5 步可复现 / 附代码 / 附截图 / 附 PoC |
| **时效** | > 7d 旧闻（除非深度研究） | 24h 内的硬事件 / 7d 内的稳定信号 |

## 怎么用

任何工具返回 results 后，逐条过 3 维。任一维不通过 → 丢弃。

```python
def quality_gate(result):
    # 来源维度
    if result["url"].endswith((".example.com", ".test")):
        return False, "个人博客无来源"
    if "营销" in result["title"] or "汇总" in result["title"]:
        return False, "营销聚合"
    if "/c/" in result["url"] and "redirect" in result["url"]:
        return False, "中转站"

    # 完整性维度
    if len(result.get("content", "")) < 50:
        return False, "无复现步骤"
    if "步骤" not in result.get("content", "") and "code" not in result.get("content", "").lower():
        return False, "无技术细节"

    # 时效维度
    age = now() - parse_ts(result.get("ts", ""))
    if age > timedelta(days=7) and not result.get("deep_research"):
        return False, "过期"

    return True, "通过"
```

## 多源验证

除 3 维外，**≥2 独立来源** 才是可推信号：

- 2 个不同平台（CSDN + X / HN + Reddit / GitHub advisory + Google 命中）
- 至少 1 个是技术拆解（不是纯吐槽/新闻通稿）
- 排除：单源 / 单平台 / 单 X 用户 / 单 Reddit 帖

```python
def multi_source_verify(signal, vendor):
    sources = [signal]
    # 用其他工具验证
    hn = hn_search(signal["title"], role="verify", vendor=vendor)
    gh = get_advisories(...)  # 适用
    sources.extend([r for r in hn if r["points"] >= 20])
    return len(sources) >= 2
```

## 反面案例

- ❌ 只看标题党 → 误信"白嫖 1 折教程"营销
- ❌ 只看时间 → 漏 2-3 天前的真信号
- ❌ 单源就推 → spam 风险
- ❌ 不看来源 → 中转站污染
- ❌ 不看完整性 → 5 步文章 vs 标题党同一对待

## 实战数据

7×24 cron 跑 30+ 天，3 维 + ≥2 源过滤后：
- 命中率 ~60%（vs 不过滤的 ~10%）
- 真事件推送 27 条（vs 不过滤 200+ spam）
- 0 误推营销号（vs 不过滤每周 5+ 条）