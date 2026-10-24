# MCP 集成说明 — mcd-swap

## 1. 使用的 MCP Server

| 项 | 值 |
|---|---|
| 地址 | `https://mcp.mcd.cn` |
| 协议 | Streamable HTTP（MCP `2025-06-18`） |
| 鉴权 | `Authorization: Bearer <MCD_MCP_TOKEN>` |
| 限流 | 600 次/分钟，超限 429 |

Token 只从环境变量 `MCD_MCP_TOKEN` 或 `~/.mcd_token` 读取，不进仓库。

## 2. 调用的 Tool

| Tool | 作用 | 调用时机 |
|---|---|---|
| `query-nearby-stores` | 由城市/关键词定位门店，取 `storeCode` | 首次使用 |
| `query-meals` | 拉门店在售餐品（编码、现价、原价） | 刷新快照 |
| `query-meal-detail` | 拉套餐选配树：候选项、默认项、`diffPrice` | 刷新快照 |
| `list-nutrition-foods` | 官方营养表（热量/蛋白/脂肪/碳水/钠/钙） | 刷新快照、单品查询 |
| `calculate-price` | **复核方案实付价**：把最终组合（含 `roundList` 换购）发给官方计费引擎 | 每次输出方案 |
| `query-my-coupons` | 检查可用券，判断还能不能再省 | 可选 |

未使用下单、支付、订单、积分、商城类工具。

## 3. 调用流程

```
用户约束（热量/蛋白质/预算）
   ▼
① 载入快照：query-meals + query-meal-detail + list-nutrition-foods
   ▼
② 名字对齐：套餐子项名 → 营养表条目（mcd_swap/nutrition.py）
   ▼
③ 穷举换购空间：每份套餐每一轮选配做笛卡尔积
   ▼   18,928 种合法组合，其中 4,148 种营养数据完整
④ 约束过滤 + 目标排序（性价比 / 最高蛋白 / 贴近目标热量 / 最便宜）
   ▼
⑤ calculate-price 复核 Top-N 实付价，对不上就标 ✗
   ▼
⑥ 输出方案 + 与默认配餐的差异（换了什么、差多少钱、差多少卡）
```

## 4. 数据快照

`data/` 下是官方 MCP 的**原样返回**，可自行核验：

- `data/menu.json` — query-meals 返回的 102 个在售 SKU
- `data/details/*.json` — 每个 SKU 的 query-meal-detail 原样返回
- `data/nutrition.json` — list-nutrition-foods 返回的 160 项营养数据

快照用于离线演示；实时价格以官方返回为准（`scripts/refresh_data.py` 可重新拉取）。

## 5. 业务价值

- **不是推荐，是求解**：在官方真实换购规则里穷举 + 约束优化，答案附带“为什么是这一套”。
- **价格可信**：每份方案实付价都经 `calculate-price` 复核。
- **可审计**：对齐表、原始快照、复核结果全部落盘。
- **零侵入**：只读接口，不下单、不支付、不碰隐私数据。

## 6. 异常处理

| 情况 | 处理 |
|---|---|
| 401 Token 无效 | 提示重新申请 |
| 429 限流 | 串行化 + 重试，不并发轰炸 |
| 营养表缺新品 | 该项从候选中剔除，**不猜测、不估算** |
| 官方计价与本地价不符 | 标红 `✗计价不符`，不隐瞒 |
