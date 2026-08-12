# ETF_DATA_DECISION

1. TuShare 2200能否获取ETF名单？PASS
2. fund_basic能否可靠过滤出ETF？YES_WITH_FILTER
3. etf_basic当前Token是否有权限？PERMISSION_DENIED
4. fund_daily当前Token是否有权限？AVAILABLE
5. fund_adj当前Token是否有权限？PASS
6. ETF日K最早可以获取到什么时候？见 etf_quality.csv 的 first_date。
7. TuShare ETF日K如果没有权限，AKShare能否替代？API_ERROR
8. AKShare ETF日K和公开行情是否一致？本脚本记录跨源/质量结果；人工抽查结论需补充。
9. AKShare ETF接口是否存在明显稳定性问题？见 api_matrix.csv 调用耗时与错误。
10. BaoStock是否支持ETF？NOT_TESTED
11. 掘金是否支持ETF且当前账号可用？NOT_TESTED
12. 是否值得为了ETF升级TuShare到5000积分？维持TuShare 2200
13. 是否值得升级到8000积分？仅在 etf_basic 为 PAID_PERMISSION 且业务确实需要增强ETF元数据时再评估。
14. 目前是否需要购买分钟行情权限？不需要，第一轮候选扫描不依赖30分钟数据。

明确建议：维持TuShare 2200