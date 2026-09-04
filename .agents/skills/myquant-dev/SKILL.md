---
name: myquant-dev
description: |
  掘金量化 (myquant) SDK 开发助手。当用户提到以下内容时触发：
  - 掘金量化、myquant、gm.api
  - 编写或修改量化交易策略
  - 使用 subscribe、order_volume、context.data 等掘金 API
  - 调试掘金策略、回测配置
  - 任何与掘金终端、仿真交易、实盘交易相关的开发
  Make sure to use this skill whenever the user mentions myquant, 掘金量化, gm.api, or wants to write/debug quantitative trading strategies for the myquant platform.
---

# 掘金量化 (myquant) 开发指南

## 文档索引

本 skill 包含掘金量化 Python SDK 完整文档（共 29 篇），位于 `references/` 目录：

| 编号 | 文档                               | 说明                                         |
| ---- | ---------------------------------- | -------------------------------------------- |
| 01   | 快速开始                           | 策略结构、定时任务、数据事件驱动示例         |
| 02   | 策略程序架构                       | init/on_bar/on_tick 事件处理函数             |
| 03   | 变量约定                           | Symbol格式、mode、context对象                |
| 04   | 数据结构                           | Tick/Bar对象、Account/Order/Position等交易类 |
| 05   | 基本函数                           | init/schedule/run/stop/timer                 |
| 06   | 数据订阅                           | subscribe函数                                |
| 07   | 数据事件                           | on_bar/on_tick回调                           |
| 08   | 行情数据查询函数（免费）           | history等                                    |
| 09   | 通用数据函数（免费）               | get_symbol_infos等                           |
| 10   | 股票财务数据及基础数据函数（免费） |                                              |
| 11   | 股票增值数据函数（付费）           |                                              |
| 12   | 期货基础数据函数（免费）           |                                              |
| 13   | 期货增值数据函数（付费）           |                                              |
| 14   | 基金增值数据函数（付费）           |                                              |
| 15   | 可转债增值数据函数（付费）         |                                              |
| 16   | 交易函数                           | order_volume/place_order等                   |
| 17   | 交易查询函数                       | get_position/get_orders等                    |
| 18   | 两融交易函数                       | 融资融券相关                                 |
| 19   | 算法交易函数                       | VWAP/TWAP等算法单                            |
| 20   | 新股新债交易函数                   |                                              |
| 21   | 基金交易函数                       |                                              |
| 22   | 债券交易函数                       |                                              |
| 23   | 交易事件                           | on_order_status/on_execution_report          |
| 24   | 动态参数                           | add_parameter/on_parameter                   |
| 25   | 标的池                             |                                              |
| 26   | 其他函数                           | log/sleep等                                  |
| 27   | 其他事件                           | on_error/on_backtest_finished                |
| 28   | 枚举常量                           | OrderSide/PositionEffect等常量值             |
| 29   | 错误码                             | 错误码含义                                   |

---

## 快速参考

### Symbol 格式
`交易所代码.交易标代码`，如 `SHSE.600519`

| 市场   | 代码  | 示例                              |
| ------ | ----- | --------------------------------- |
| 上交所 | SHSE  | SHSE.600000                       |
| 深交所 | SZSE  | SZSE.000001                       |
| 中金所 | CFFEX | CFFEX.IC2011                      |
| 上期所 | SHFE  | SHFE.rb2011 / SHFE.RB（主力连续） |
| 大商所 | DCE   | DCE.m2011                         |
| 郑商所 | CZCE  | CZCE.FG101                        |

### 模式
- `MODE_BACKTEST` - 回测模式
- `MODE_LIVE` - 实时模式（仿真/实盘）

### Token 配置
```python
from gm.api import set_token
set_token('your_token')  # 或从环境变量 os.getenv('GM_TOKEN')
```

### context 核心属性
- `context.symbols` - 已订阅代码集合
- `context.now` - 当前时间
- `context.mode` - 运行模式
- `context.data(symbol, frequency, count, fields)` - 滑窗数据
- `context.account()` - 账户信息（获取总资产：`account.cash.nav`）
- `context.backtest_start_time` - 回测开始时间
- `context.backtest_end_time` - 回测结束时间

### 回调函数
- `init(context)` - 策略初始化
- `on_bar(context, bars)` - K线回调
- `on_tick(context, tick)` - Tick回调
- `on_order_status(context, order)` - 委托状态变化
- `on_execution_report(context, execution)` - 委托执行回报
- `on_account_status(context, account)` - 交易账户状态变化
- `on_parameter(context, parameter)` - 动态参数修改
- `on_backtest_finished(context, indicator)` - 回测完成

### 下单函数
- `order_volume()` - 按指定量委托
- `order_value()` - 按指定价值委托
- `order_percent()` - 按总资产比例委托
- `order_target_volume()` - 调仓到目标持仓量
- `order_target_value()` - 调仓到目标持仓额
- `order_target_percent()` - 调仓到目标持仓比例
- `order_batch()` - 批量委托
- `order_cancel()` - 撤销委托
- `order_cancel_all()` - 撤销所有委托

### 交易枚举常量
```python
# 委托方向
OrderSide_Buy = 1   # 买入
OrderSide_Sell = 2  # 卖出

# 委托类型
OrderType_Limit = 1    # 限价委托
OrderType_Market = 2   # 市价委托

# 开平仓
PositionEffect_Open = 1   # 开仓
PositionEffect_Close = 2  # 平仓
PositionEffect_CloseToday = 3  # 平今
PositionEffect_CloseYesterday = 4  # 平昨

# 持仓方向
PositionSide_Long = 1   # 多仓
PositionSide_Short = 2  # 空仓

# 委托状态
OrderStatus_New = 1              # 已报
OrderStatus_PartiallyFilled = 2  # 部成
OrderStatus_Filled = 3          # 已成
OrderStatus_Canceled = 5         # 已撤
OrderStatus_Rejected = 8         # 已拒绝
```

---

## 策略模板

### 模板1：定时任务策略
```python
# coding=utf-8
from __future__ import print_function, absolute_import
from gm.api import *

def init(context):
    # 每天14:50定时执行algo任务
    schedule(schedule_func=algo, date_rule='1d', time_rule='14:50:00')

def algo(context):
    # 市价买入200股浦发银行
    order_volume(symbol='SHSE.600000', volume=200, side=OrderSide_Buy,
                 order_type=OrderType_Market, position_effect=PositionEffect_Open, price=0)

def on_backtest_finished(context, indicator):
    print(indicator)

if __name__ == '__main__':
    run(strategy_id='strategy_id',
        # 不要修改main.py
        filename='main.py',
        mode=MODE_BACKTEST,
        token='token_id',
        # !当天住前推3个月
        backtest_start_time='2020-11-01 08:00:00',
        # !使用当天时间
        backtest_end_time='2020-11-10 16:00:00',
        backtest_adjust=ADJUST_PREV,
        backtest_initial_cash=10000000,
        backtest_commission_ratio=0.0001,
        backtest_slippage_ratio=0.0001)
```

### 模板2：数据事件驱动策略
```python
# coding=utf-8
from __future__ import print_function, absolute_import
from gm.api import *

def init(context):
    # 订阅浦发银行日线和分钟bar
    subscribe(symbols='SHSE.600000', frequency='1d')
    subscribe(symbols='SHSE.600000', frequency='60s', count=50)

def on_bar(context, bars):
    # 获取数据滑窗
    data = context.data(symbol=bars[0].symbol, frequency='60s', count=50, fields='close,eob')
    # 计算均线
    data['ma5'] = data['close'].rolling(window=5).mean()
    print(data.tail())

if __name__ == '__main__':
    run(strategy_id='strategy_id',
        # 不要修改main.py
        filename='main.py',
        mode=MODE_BACKTEST,
        token='token_id',
        # !当天住前推3个月
        backtest_start_time='2020-11-01 08:00:00',
        # !使用当天时间
        backtest_end_time='2020-11-10 16:00:00',
        backtest_adjust=ADJUST_PREV,
        backtest_initial_cash=10000000,
        backtest_commission_ratio=0.0001,
        backtest_slippage_ratio=0.0001)
```

### 模板3：完整均线策略
```python
# coding=utf-8
from __future__ import print_function, absolute_import, unicode_literals
from gm.api import *

def init(context):
    context.symbol = 'SHSE.600004'
    context.period = 30
    subscribe(symbols=context.symbol, frequency='1d', count=context.period)

def on_bar(context, bars):
    data = context.data(symbol=context.symbol, frequency='1d',
                        count=context.period, fields='close')
    ma = data['close'].rolling(5).mean()
    positions = get_position()
    # ⚠️ Position 对象：用 .symbol 和 .side，不能用 ['position_side']
    has_long = any(p.symbol == context.symbol and
                   p.side == PositionSide_Long
                   for p in positions)
    close = data['close'].values[-1]
    if not has_long and close < ma.values[-1]:
        order_volume(symbol=context.symbol, volume=100,
                     side=OrderSide_Buy, order_type=OrderType_Limit,
                     position_effect=PositionEffect_Open, price=close)
    elif has_long and close > ma.values[-1]:
        order_volume(symbol=context.symbol, volume=100,
                     side=OrderSide_Sell, order_type=OrderType_Limit,
                     position_effect=PositionEffect_Close, price=close)

def on_backtest_finished(context, indicator):
    # ⚠️ Indicator 对象：用 .pnl_ratio / .max_drawdown / .sharp_ratio 等属性
    print("回测完成，最终收益率: {:.2f}%".format(indicator.pnl_ratio * 100))
```

---

## 常见问题

1. **数据获取失败**：必须先 `subscribe()` 订阅，才能用 `context.data()` 获取
2. **count 参数**：`context.data()` 的 count 必须 ≤ `subscribe()` 中的 count
3. **symbol 大小写**：必须是 `SHSE.600519` 而非 `shse.600519`
4. **期货下单**：期货 volume 是"手"，最小交易单位为1手
5. **沪市市价单**：必须填写保护限价 price（有效范围为当前价~涨停价）
6. **股票买卖单位**：买入最小100股，卖出最小1股
7. **回测函数里的filename必须为main.py** 为了确保在将回测的代码能够拷贝到掘金终端进行回测，回测代码的 main函数 里的filename=main.py不要修改
---

## 参考文档（references/ 目录）

按需查阅详细文档：

**基础入门：**
- `references/01_快速开
- 始.md` - 快速开始、策略结构示例
- `references/02_策略程序架构.md` - 策略架构、事件处理函数
- `references/03_变量约定.md` - Symbol格式、mode、context
- `references/04_数据结构.md` - Tick/Bar/Account/Order数据结构

**API 函数：**
- `references/05_基本函数.md` - init/schedule/run/stop/timer
- `references/06_数据订阅.md` - subscribe 订阅行情
- `references/07_数据事件.md` - on_bar/on_tick 回调
- `references/16_交易函数.md` - order_volume 等下单函数
- `references/17_交易查询函数.md` - get_position/get_orders
- `references/23_交易事件.md` - on_order_status/on_execution_report
- `references/24_动态参数.md` - add_parameter/on_parameter
- `references/28_枚举常量.md` - 所有枚举常量值

**数据查询（按需取用）：**
- `references/08_行情数据查询函数（免费）.md` - history（免费）
- `references/09_通用数据函数（免费）.md` - get_symbol_infos等（免费）
- `references/12_期货基础数据函数（免费）.md` - （免费）
- `references/15_可转债增值数据函数（付费）.md` - 可转债数据

## 官方文档

- 官方文档: https://www.myquant.cn/docs2/sdk/python/
- gm-api 安装: `pip install gm`


## 注意 
生成的策略，回测的默认值 backtest_start_time:当前生成的时间-3个月 backtest_end_time: 当前时间
如果用户创建了一个新的策略，如果是回测，确保TOKEN填写后 ,自已跑一遍，如果报错，自我调试修复，确保没有问题。