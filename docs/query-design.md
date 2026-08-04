# Query 设计原则

> 怎么写 query？99% 的 search 失败是因为 query 太复杂或太模糊。

## 核心原则

**简单直接，时间窗让工具做，多角度多语言**。

## 好 query 的 4 特征

1. **简单直接**：人话化，不要工程化组合
2. **时间窗内**：用 since=7d 配合，不要在 query 里嵌日期
3. **关键词具体到动作**：bug / 漏洞 / 涨价 / outage / 报错 / 复盘
4. **多角度**：同一事件用 2-3 种说法搜（中/英/缩写/全称）

## 差 query 的 4 反模式

| 反模式 | 例子 | 失败原因 |
|---|---|---|
| site: 限制 | `site:reddit.com/r/X Y Z 2026-07-29` | 限制引擎去索引别的域，命中率差 |
| 引号精确匹配 | `site:x.com "exact phrase" 2026` | 召回率低 |
| 具体日期 | `claude exploit july 29 2026 specific incident` | Google 算法已做时间过滤 |
| 4+ token 组合 | `claude max payment exploit vulnerability july 2026` | 过于具体 = 返 0 |

## 5 类 query 模板

| 信号类型 | 中文 query | 英文 query |
|---|---|---|
| 支付漏洞 / exploit | `<产品> 白嫖 / 支付漏洞 / 油猴 / SEPA` | `<vendor> payment exploit / vulnerability` |
| 服务中断 / outage | `<厂商> 崩了 / 宕机 / 服务中断` | `<vendor> down / outage / incident` |
| 定价变化 | `<厂商> 涨价 / 降价 / 调价 / 改版` | `<vendor> pricing change / update` |
| 新模型 / 产品 | `<厂商> 新模型 / 发布 / 公测` | `<vendor> new model / release / launch` |
| 安全漏洞 | `<产品> CVE / RCE / 沙盒逃逸` | `<product> CVE / advisory / RCE` |

## 多角度

```python
# 同一事件 3 个角度
queries = [
    "claude max exploit",          # 英文通用
    "Claude SEPA 漏洞",             # 中文技术
    "anthropic checkout_capabilities",  # 厂商内部术语
]
```

## URL 参数必传

```bash
# ❌ 错
curl "...search?q=test&num=10&since=7d"

# ✅ 对
curl "...search?q=test&num=10&since=7d&vendor=claude&role=primary"
```

- `vendor` 自定义分类（不要让工具默认 = "?"）
- `role` primary / fallback / verify

详见各工具的 `SKILL.md`。

## 反面案例

- ❌ "请详细分析 2026 年 7 月 26 日发生的 Claude Max 支付漏洞事件" → 工具不会自然语言处理
- ❌ `q=claude+exploit+2026+07+26+claude.ai+payment+max+20x` → 13 个 token 100% 返 0
- ❌ 一次只发一个 query → 漏多角度信号

## 实战数据

7×24 cron 跑 30+ 天，query 命中规律：
- `claude max 白嫖` （7d）→ 11 结果，含 B 站 / X / CSDN
- `chatgpt 支付漏洞 零元`（7d）→ 11 结果
- `claude max SEPA vulnerability 2026`（7d）→ 5 结果
- `claude exploit july 29 2026 specific incident` → **0 结果**（过于精确）