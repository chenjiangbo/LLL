# 数据源验证 summary

- 生成日期：2026-08-07
- 默认策略：TuShare 优先；AkShare 只用于 TuShare 缺失项补充和交叉核对。
- 接口测试数：36
- 股票质量记录：2
- ETF质量记录：2
- 跨源比较记录：0

| 数据需求 | TuShare2200 | AKShare | BaoStock | 掘金 | 推荐主源 |
|---|---|---|---|---|---|
| A股列表 | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | TuShare |
| A股日K | PASS | FAIL | NOT_TESTED | NOT_TESTED | TuShare |
| A股复权 | PASS | LIMITED | NOT_TESTED | NOT_TESTED | TuShare |
| 换手/市值 | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | TuShare |
| ETF列表 | LIMITED | FAIL | NOT_TESTED | NOT_TESTED | TuShare优先 |
| ETF日K | PASS | FAIL | NOT_TESTED | NOT_TESTED | TuShare |
| ETF复权 | PASS | FAIL | NOT_TESTED | NOT_TESTED | TuShare |
| 指数日K | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | TuShare |
| 申万分类 | PASS | NOT_TESTED | NOT_TESTED | NOT_TESTED | TuShare |
| 申万行业日K | PAID_PERMISSION | NOT_TESTED | NOT_TESTED | NOT_TESTED | TuShare或暂缓 |
| ETF 30分钟 | PAID_PERMISSION | FAIL | NOT_TESTED | NOT_TESTED | 暂不作为第一版主源 |

## 说明

- PASS：本次真实调用成功。
- FAIL：调用失败或核心质量检查未通过。
- LIMITED：部分接口可用，但字段、权限、稳定性或覆盖范围不足。
- PAID_PERMISSION：真实调用返回权限不足或积分限制。
- NOT_TESTED：未测试或当前环境未配置。

最终建议：维持TuShare 2200

详细 ETF 结论见 `data_source_validation/output/ETF_DATA_DECISION.md`。