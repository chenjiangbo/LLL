# A股及ETF选股系统——数据源验证任务 V1.0

## 一、任务目的

本任务不是开发正式选股系统，也不要提前设计完整数据库。

本次只进行一次“数据源可用性验证”，最终回答以下问题：

1. 当前 TuShare 约2200积分权限到底能够调用哪些我们需要的数据。
2. TuShare能否满足A股第一轮选股所需要的基础数据。
3. TuShare当前权限能否提供ETF基础信息、日K和复权数据。
4. ETF日K如果TuShare无法提供，AKShare是否能够可靠补充。
5. BaoStock、掘金量化是否能够作为进一步备用数据源。
6. 是否值得把TuShare升级到5000积分。
7. 第一版系统最终建议采用什么数据源组合。

不要根据官方文档直接判断权限。

所有接口都必须使用当前真实Token/API进行一次实际调用，并记录真实结果。

---

# 二、本阶段选股真正需要的数据

第一版不要测试财务报表、公告、股权质押、解禁、减持等数据。

这些以后在候选股票已经筛出来以后再研究。

第一轮选股只验证以下数据。

## A股

必须：

- 股票基本信息
- 日K OHLC
- 成交量
- 成交额
- 复权
- 换手率
- 总市值
- 流通市值
- 涨跌停状态
- 交易日历

暂不需要：

- 分钟K
- 财务报表
- 公告
- 资金流
- 龙虎榜
- 股东数据
- 解禁
- 质押

## ETF

必须：

- ETF代码
- ETF名称
- 上市状态
- 上市日期
- 日K OHLC
- 成交量
- 成交额
- 能正确处理分红、拆分等造成的价格跳变

最好有但不是第一版必须：

- 跟踪指数
- ETF类型
- 基金公司
- 基金规模

暂时不需要：

- 1分钟
- 5分钟
- 15分钟
- 30分钟
- 60分钟

分钟数据只验证“能不能获得”，不下载历史数据库。

---

# 三、测试程序要求

建立独立目录：

data_source_validation/

建议结构：

data_source_validation/
    run_validation.py
    providers/
        tushare_test.py
        akshare_test.py
        baostock_test.py
        gm_test.py
    validation/
        quality_check.py
        compare.py
    output/
        summary.md
        api_matrix.csv
        stock_quality.csv
        etf_quality.csv
        cross_source_compare.csv
        errors.log
        raw_samples/

Token、账号等不得写死在源码。

从环境变量读取：

TUSHARE_TOKEN

如掘金量化已有Token，则读取：

GM_TOKEN

没有GM Token时不要报错退出，标记：

NOT_CONFIGURED

所有异常必须完整记录：

- API名称
- 请求参数
- HTTP/API错误
- 权限错误信息
- 是否返回空DataFrame
- 请求时间
- 返回行数

---

# 四、TuShare权限实测

这是本次测试最重要的部分。

不要依据预计权限直接跳过接口。

即使官方说需要5000或8000积分，也调用一次小规模请求，以确认当前Token真实权限。

统一状态：

PASS

PERMISSION_DENIED

EMPTY

API_ERROR

TIMEOUT

---

# 五、A股核心接口测试

## T01 stock_basic

调用：

stock_basic(list_status='L')

字段至少：

ts_code
symbol
name
market
exchange
list_date
list_status

记录：

总股票数量

主板数量

创业板数量

科创板数量

北交所数量

检查：

ts_code唯一

不存在空代码

上市日期格式正确

保存前20条样例。

结论：

必须PASS。

---

## T02 daily

选择以下代表股票：

000001.SZ

600519.SH

300750.SZ

688981.SH

再动态选择：

一只最近一年上市的新股

一只当前ST股票，如果存在

测试两个模式。

模式A：

单股票历史数据。

获取最近约3年。

字段：

ts_code
trade_date
open
high
low
close
pre_close
vol
amount

模式B：

按一个交易日期获取全市场。

检查返回股票数量。

质量检查：

不得存在重复：

ts_code + trade_date

OHLC逻辑：

low <= open <= high

low <= close <= high

high >= low

vol >= 0

amount >= 0

价格不得为负数或0，特殊停牌情况除外。

---

## T03 adj_factor

测试：

000001.SZ

600519.SH

300750.SZ

至少取最近5年。

检查：

是否正常返回。

是否存在重复日期。

是否存在空复权因子。

记录复权因子变化日期。

随机选择至少一个发生过除权除息的股票，验证复权因子确实发生变化。

---

## T04 daily_basic

选择最近一个已经完整结束的交易日。

不要写死日期。

使用trade_cal自动取得最近一个已经完成的A股交易日。

取得全市场：

daily_basic(trade_date=xxx)

只重点保留：

ts_code
trade_date
turnover_rate
turnover_rate_f
total_mv
circ_mv
limit_status

如果volume_ratio容易取得也保留。

检查：

股票覆盖数量

重复数据

turnover_rate异常值

total_mv <= 0

circ_mv <= 0

daily_basic.close 与 daily.close 是否一致。

统计：

能够和daily成功匹配的股票比例。

目标：

>=99%。

---

## T05 trade_cal

验证：

能够获得最近一年交易日。

能够正确找到：

最近一个交易日

最近一个已结束交易日

前一个交易日

不要在系统代码中通过“周一到周五”判断交易日。

---

# 六、TuShare ETF专项测试

这是此次实验最重要的部分之一。

## E01 fund_basic

调用：

fund_basic(market='E', status='L')

记录：

返回总数

name包含ETF的数量

type/fund_type属于ETF的数量，如果字段能够识别

随机输出50条场内基金。

必须判断：

fund_basic是否能够可靠区分：

ETF

LOF

封闭式基金

其他场内基金

最终回答：

是否可以仅依靠fund_basic构建“当前上市ETF名单”。

答案只能是：

YES

YES_WITH_FILTER

NO

并说明理由。

---

## E02 etf_basic

调用一次：

etf_basic(list_status='L')

预期官方文档要求8000积分，但不要直接写FAIL。

真实调用一次。

记录：

PASS

或

PERMISSION_DENIED

如果PASS：

记录ETF数量以及：

ts_code
extname
index_code
index_name
list_date
exchange
mgr_name
etf_type

如果权限不足：

保存完整错误信息。

---

## E03 fund_daily

这是最关键的权限测试。

测试ETF：

510300.SH

159915.SZ

588000.SH

513100.SH

分别请求最近20个交易日。

再测试：

fund_daily(trade_date=最近完整交易日)

如果接口支持这种查询。

记录：

权限是否成功

返回字段

返回行数

最新日期

官方文档目前要求5000积分，但必须以真实Token结果为准。

最终必须明确回答：

当前2200积分Token：

ETF日K = AVAILABLE / NOT_AVAILABLE

---

## E04 pro_bar ETF

另外尝试TuShare通用封装接口，例如：

pro_bar

使用ETF资产类型请求510300.SH日K。

目的：

确认是否存在通过pro_bar正常取得ETF日K的方式。

如果底层仍然触发fund_daily权限，则如实记录。

不能因为fund_daily失败就自动假定pro_bar失败。

---

## E05 fund_adj

测试：

510300.SH

159915.SZ

588000.SH

513100.SH

取尽量长的数据。

记录：

是否PASS

最早日期

最新日期

复权因子是否发生变化

是否存在空值

---

## E06 ETF历史分钟

调用一次极小范围：

etf_mins(
    ts_code='510300.SH',
    freq='30min',
    最近一个交易日
)

只测试权限。

禁止批量下载。

记录：

PASS

PERMISSION_DENIED

OTHER_ERROR

如果权限不足，保存TuShare返回的完整错误。

本次测试结束后，不因为分钟接口失败而判定TuShare不合格。

分钟数据不是当前系统必需数据。

---

# 七、指数与申万只做权限验证

这些不是第一版筛选系统的强制依赖。

只做小规模测试。

## I01 index_daily

测试：

沪深300

创业板指

中证1000或中证500

分别取最近20个交易日。

确认2200积分实际可用。

---

## I02 index_classify

取得：

申万2021一级行业。

检查是否正常返回31个左右一级行业分类。

记录实际数量。

---

## I03 index_member_all

测试：

随机一个一级行业

随机一个二级或三级行业

以及：

index_member_all(ts_code='000001.SZ')

验证能否得到股票所属申万分类。

检查：

in_date

out_date

is_new

是否存在。

---

## I04 sw_daily

调用一个申万一级行业最近10个交易日行情。

官方文档当前要求5000积分。

仍然真实调用一次。

记录当前Token真实权限。

如果失败：

不认为是当前系统阻塞项。

---

# 八、AKShare验证

AKShare不是第一数据源。

仅验证TuShare缺失数据和交叉核对能力。

使用测试时最新稳定版本，并记录：

Python版本

AKShare版本

安装时间

---

## A01 A股日线交叉验证

使用：

stock_zh_a_hist

验证：

000001

600519

300750

688981

取最近60个交易日不复权行情。

与TuShare daily比较：

date

open

high

low

close

volume

amount

注意先统一成交量和成交额单位。

统计：

日期匹配率

OHLC一致率

成交量差异

成交额差异

OHLC允许因为数据精度存在极小舍入误差。

如果大面积不一致必须列出差异样本。

---

## A02 ETF列表

使用AKShare当前ETF实时列表接口，例如：

fund_etf_spot_em

记录：

ETF总数

代码

名称

交易所信息，如果有

与TuShare：

fund_basic

和如果可用的：

etf_basic

进行ETF代码覆盖率比较。

输出：

TuShare有、AKShare没有

AKShare有、TuShare没有

双方都有

三组数量。

---

## A03 ETF日K

使用：

fund_etf_hist_em

测试：

510300

159915

588000

513100

分别取最近3年：

不复权

前复权

如果支持再测试后复权。

检查：

OHLC

volume

amount

turnover

历史起始日期

最新交易日

重复日期

缺失日期

零价格

异常价格。

其中：

510300

159915

588000

至少随机人工抽查几个日期，与东方财富或其他行情页面核对。

---

## A04 ETF 30分钟

使用：

fund_etf_hist_min_em

只测试：

510300

频率：

30分钟

测试三个时间段：

最近5个交易日

约3个月前

约1年前

目的不是下载数据，而是确认AKShare当前接口到底能提供多长历史范围。

输出：

可获取最早日期

是否支持前复权

是否稳定返回

请求是否出现限流或异常。

本项仅作未来参考，不参与当前数据源最终评分。

---

# 九、BaoStock验证

BaoStock只作为第三优先级。

主要测试它能否作为A股行情备用源。

测试：

000001

600519

300750

最近3年日线。

取得：

open
high
low
close
volume
amount

并测试其复权方式。

与TuShare最近60个交易日进行比较。

同时实验性调用ETF：

510300

159915

如果BaoStock能够返回ETF行情：

继续做ETF质量测试。

如果不能：

直接记录：

ETF_NOT_SUPPORTED

不要花时间寻找非官方绕过方式。

最终回答：

BaoStock是否适合：

A股备用源

ETF备用源

分别给出结论。

---

# 十、掘金量化验证

如果环境中没有GM Token：

不要注册账号。

标记：

NOT_CONFIGURED

如果已经有Token：

使用官方Python SDK：

history

或

history_n

测试：

SHSE.600519

SZSE.300750

以及对应格式的：

510300 ETF

159915 ETF

验证：

1d

以及实验性的：

1800s / 30m

具体频率名称以当前SDK文档为准。

记录：

历史覆盖范围

字段完整性

复权方式

是否免费

是否有限制

是否可以批量使用

不得因为存在接口就直接判断“免费可无限使用”。

必须根据当前账号真实权限记录。

---

# 十一、数据质量统一测试

所有数据源统一执行下面测试。

## 1 唯一性

股票：

(ts_code, trade_date)

ETF：

(code, trade_date)

必须唯一。

---

## 2 OHLC合法性

必须满足：

high >= low

high >= open

high >= close

low <= open

low <= close

---

## 3 成交数据

volume >= 0

amount >= 0

---

## 4 日期排序

统一转换datetime。

检查重复。

检查乱序。

---

## 5 数据完整度

对连续上市、非停牌股票：

和交易日历比较。

计算：

理论交易日数量

实际记录数量

缺失数量

缺失比例。

不得简单把停牌视为数据错误。

---

## 6 最新数据

找到最近一个已经完成的交易日。

检查每个数据源是否已经有该日数据。

记录：

AVAILABLE

DELAYED

MISSING

---

# 十二、跨数据源一致性测试

使用TuShare作为基准源。

A股比较：

TuShare vs AKShare

TuShare vs BaoStock

TuShare vs GM（如果可用）

ETF如果TuShare fund_daily可用：

TuShare vs AKShare

如果fund_daily不可用：

AKShare ETF日线需要另外人工抽查。

最近60个交易日：

比较OHLC。

股票允许误差：

0.01元以内。

ETF允许误差：

0.001元以内。

同时输出：

完全一致比例

允许误差内比例

超出误差比例

最大误差日期

最大误差代码。

成交量和成交额必须先统一单位再比较。

---

# 十三、稳定性测试

不要高频压测。

每个核心接口连续调用3次即可。

间隔随机1～3秒。

测试：

是否全部成功

返回行数是否一致

是否偶发超时

是否出现反爬/限流。

重点观察AKShare。

记录：

成功率

平均响应时间

最长响应时间

错误类型。

这里的目的是比较“个人长期使用可靠性”，不是测试服务器极限性能。

---

# 十四、轻量级全市场测试

不要现在下载十年数据。

只做以下实验。

TuShare：

选最近20个完整交易日。

每天分别获取：

daily

daily_basic

保存到本地。

统计：

总请求次数

总记录数

失败请求数

重复记录

数据缺失

文件大小

总执行耗时。

目的是验证未来每天按trade_date增量更新是否现实。

如果daily和daily_basic都能稳定一次获取整个市场，则优先采用：

按交易日下载

而不是：

逐股票下载。

---

# 十五、ETF专项决策测试

最终必须单独生成：

ETF_DATA_DECISION.md

回答以下问题：

1. TuShare 2200能否获取ETF名单？

2. fund_basic能否可靠过滤出ETF？

3. etf_basic当前Token是否有权限？

4. fund_daily当前Token是否有权限？

5. fund_adj当前Token是否有权限？

6. ETF日K最早可以获取到什么时候？

7. TuShare ETF日K如果没有权限，AKShare能否替代？

8. AKShare ETF日K和公开行情是否一致？

9. AKShare ETF接口是否存在明显稳定性问题？

10. BaoStock是否支持ETF？

11. 掘金是否支持ETF且当前账号可用？

12. 是否值得为了ETF升级TuShare到5000积分？

13. 是否值得升级到8000积分？

14. 目前是否需要购买分钟行情权限？

---

# 十六、最终决策规则

根据测试结果给出推荐。

## 方案A

如果：

TuShare股票核心接口全部PASS

并且

fund_daily当前Token也PASS

推荐：

TuShare作为股票+ETF主数据源。

AKShare只做备用核对。

---

## 方案B

如果：

TuShare股票核心接口全部PASS

fund_daily失败

AKShare ETF日K质量正常且稳定

推荐：

股票：
TuShare

ETF：
AKShare

ETF复权可同时保留TuShare fund_adj用于交叉验证。

暂不升级TuShare。

---

## 方案C

如果：

TuShare股票正常

fund_daily失败

AKShare ETF存在明显稳定性或质量问题

推荐进一步评估：

TuShare升级5000积分。

升级后重新测试fund_daily。

注意：

即使5000积分可以获得ETF日K，

etf_basic仍可能需要8000积分。

所以不能把“升级5000”和“获得所有ETF数据”混为一谈。

---

## 方案D

如果：

AKShare不可靠

但BaoStock或掘金能够稳定提供ETF日K

比较：

数据质量

历史长度

调用限制

使用成本

稳定性

再决定备用源。

---

# 十七、目前对30分钟数据的判断

本测试必须在报告中单独写：

“当前A/B/C池第一轮候选扫描是否需要30分钟数据？”

默认设计假设：

不需要。

理由：

当前策略持有周期为几天到几个月。

A/B/C池识别主要依赖：

长期趋势

底部结构

趋势调整

突破

前高前低

成交量变化

波动率

阶段涨跌幅

以上均可以通过日K完成。

周线可以通过日K本地聚合。

30分钟数据仅可能用于候选股进入人工观察阶段后的入场时机分析。

因此：

不得因为TuShare没有30分钟权限而决定购买历史分钟权限。

只有以后策略明确出现：

“没有30分钟结构就无法产生交易信号”

时，再重新评估分钟数据。

---

# 十八、最终需要提交的报告

请输出：

summary.md

api_matrix.csv

stock_quality.csv

etf_quality.csv

cross_source_compare.csv

ETF_DATA_DECISION.md

errors.log

其中summary.md必须有一张最终表：

| 数据需求 | TuShare2200 | AKShare | BaoStock | 掘金 | 推荐主源 |
|---|---|---|---|---|---|
| A股列表 | | | | | |
| A股日K | | | | | |
| A股复权 | | | | | |
| 换手/市值 | | | | | |
| ETF列表 | | | | | |
| ETF日K | | | | | |
| ETF复权 | | | | | |
| 指数日K | | | | | |
| 申万分类 | | | | | |
| 申万行业日K | | | | | |
| ETF 30分钟 | | | | | |

每个单元格只使用：

PASS

FAIL

LIMITED

NOT_TESTED

PAID_PERMISSION

并在表后解释。

最后必须给出一句明确建议：

“维持TuShare 2200”

或者

“建议升级TuShare 5000”

或者

“暂不升级，采用TuShare + XXX组合”

不得只罗列测试结果而不给结论。