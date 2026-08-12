# AkShare 数据源验证报告

- 生成日期：2026-08-03
- AkShare 版本：1.18.12
- 检查项：4
- 成功：4
- 失败：0

## 检查结果

### 五大核心指数历史行情：通过

```json
{
  "沪深300": {
    "symbol": "sh000300",
    "source": "ak.stock_zh_index_daily_tx",
    "rows": 346,
    "columns": [
      "date",
      "open",
      "close",
      "high",
      "low",
      "amount"
    ],
    "first_date": "2025-03-03",
    "last_date": "2026-07-31",
    "last_close": 4588.2,
    "last_amount": 279243698.0
  },
  "中证500": {
    "symbol": "sh000905",
    "source": "ak.stock_zh_index_daily_tx",
    "rows": 346,
    "columns": [
      "date",
      "open",
      "close",
      "high",
      "low",
      "amount"
    ],
    "first_date": "2025-03-03",
    "last_date": "2026-07-31",
    "last_close": 7493.99,
    "last_amount": 216635960.0
  },
  "中证1000": {
    "symbol": "sh000852",
    "source": "ak.stock_zh_index_daily_tx",
    "rows": 346,
    "columns": [
      "date",
      "open",
      "close",
      "high",
      "low",
      "amount"
    ],
    "first_date": "2025-03-03",
    "last_date": "2026-07-31",
    "last_close": 7075.51,
    "last_amount": 283219421.0
  },
  "创业板指": {
    "symbol": "sz399006",
    "source": "ak.stock_zh_index_daily_tx",
    "rows": 346,
    "columns": [
      "date",
      "open",
      "close",
      "high",
      "low",
      "amount"
    ],
    "first_date": "2025-03-03",
    "last_date": "2026-07-31",
    "last_close": 3343.96,
    "last_amount": 236170945.0
  },
  "科创50": {
    "symbol": "sh000688",
    "source": "ak.stock_zh_index_daily_tx",
    "rows": 346,
    "columns": [
      "date",
      "open",
      "close",
      "high",
      "low",
      "amount"
    ],
    "first_date": "2025-03-03",
    "last_date": "2026-07-31",
    "last_close": 1635.96,
    "last_amount": 14507410.0
  }
}
```

### 市场广度与涨跌停统计：通过

```json
{
  "spot_source": "ak.stock_zh_a_spot",
  "limit_up_source": "ak.stock_zt_pool_em",
  "limit_down_source": "ak.stock_zt_pool_dtgc_em",
  "limit_date": "20260731",
  "stock_count": 5534,
  "rising_count": 3717,
  "falling_count": 1689,
  "flat_count": 128,
  "invalid_pct_count": 0,
  "rising_ratio": 0.671666,
  "total_amount": 1374435211215.0,
  "limit_up_count": 99,
  "limit_down_count": 0,
  "limit_down_empty_columns": [],
  "spot_columns": [
    "代码",
    "名称",
    "最新价",
    "涨跌额",
    "涨跌幅",
    "买入",
    "卖出",
    "昨收",
    "今开",
    "最高",
    "最低",
    "成交量",
    "成交额",
    "时间戳"
  ],
  "limit_up_columns": [
    "序号",
    "代码",
    "名称",
    "涨跌幅",
    "最新价",
    "成交额",
    "流通市值",
    "总市值",
    "换手率",
    "封板资金",
    "首次封板时间",
    "最后封板时间",
    "炸板次数",
    "涨停统计",
    "连板数",
    "所属行业"
  ]
}
```

### 同花顺行业板块行情：通过

```json
{
  "summary_source": "ak.stock_board_industry_summary_ths",
  "history_source": "ak.stock_board_industry_index_ths",
  "board_count": 90,
  "board_columns": [
    "序号",
    "板块",
    "涨跌幅",
    "总成交量",
    "总成交额",
    "净流入",
    "上涨家数",
    "下跌家数",
    "均价",
    "领涨股",
    "领涨股-最新价",
    "领涨股-涨跌幅"
  ],
  "sample_board": "风电设备",
  "sample_board_up_count": 29,
  "sample_board_down_count": 2,
  "hist_rows": 346,
  "hist_columns": [
    "日期",
    "开盘价",
    "最高价",
    "最低价",
    "收盘价",
    "成交量",
    "成交额"
  ],
  "hist_first_date": "2025-03-03",
  "hist_last_date": "2026-07-31"
}
```

### 中证指数成分与权重：通过

```json
{
  "沪深300": {
    "symbol": "000300",
    "constituent_rows": 300,
    "weight_rows": 300,
    "weight_sum": 100.008,
    "weight_columns": [
      "日期",
      "指数代码",
      "指数名称",
      "指数英文名称",
      "成分券代码",
      "成分券名称",
      "成分券英文名称",
      "交易所",
      "交易所英文名称",
      "权重"
    ],
    "top_weights": {
      "rows": 5,
      "columns": [
        "日期",
        "指数代码",
        "指数名称",
        "指数英文名称",
        "成分券代码",
        "成分券名称",
        "成分券英文名称",
        "交易所",
        "交易所英文名称",
        "权重"
      ],
      "sample": [
        {
          "日期": "2026-06-30",
          "指数代码": "000300",
          "指数名称": "沪深300",
          "指数英文名称": "CSI 300",
          "成分券代码": "300308",
          "成分券名称": "中际旭创",
          "成分券英文名称": "ZHONGJI INNOLIGHT CO., LTD.",
          "交易所": "深圳证券交易所",
          "交易所英文名称": "Shenzhen Stock Exchange",
          "权重": "5.008"
        },
        {
          "日期": "2026-06-30",
          "指数代码": "000300",
          "指数名称": "沪深300",
          "指数英文名称": "CSI 300",
          "成分券代码": "300750",
          "成分券名称": "宁德时代",
          "成分券英文名称": "Contemporary Amperex Technology Co., Limited.",
          "交易所": "深圳证券交易所",
          "交易所英文名称": "Shenzhen Stock Exchange",
          "权重": "3.675"
        },
        {
          "日期": "2026-06-30",
          "指数代码": "000300",
          "指数名称": "沪深300",
          "指数英文名称": "CSI 300",
          "成分券代码": "300502",
          "成分券名称": "新易盛",
          "成分券英文名称": "Eoptolink Technology Inc., Ltd",
          "交易所": "深圳证券交易所",
          "交易所英文名称": "Shenzhen Stock Exchange",
          "权重": "2.992"
        }
      ]
    }
  },
  "中证500": {
    "symbol": "000905",
    "constituent_rows": 500,
    "weight_rows": 500,
    "weight_sum": 99.991,
    "weight_columns": [
      "日期",
      "指数代码",
      "指数名称",
      "指数英文名称",
      "成分券代码",
      "成分券名称",
      "成分券英文名称",
      "交易所",
      "交易所英文名称",
      "权重"
    ],
    "top_weights": {
      "rows": 5,
      "columns": [
        "日期",
        "指数代码",
        "指数名称",
        "指数英文名称",
        "成分券代码",
        "成分券名称",
        "成分券英文名称",
        "交易所",
        "交易所英文名称",
        "权重"
      ],
      "sample": [
        {
          "日期": "2026-06-30",
          "指数代码": "000905",
          "指数名称": "中证500",
          "指数英文名称": "CSI 500",
          "成分券代码": "688498",
          "成分券名称": "源杰科技",
          "成分券英文名称": "Yuanjie Semiconductor Technology Co., Ltd",
          "交易所": "上海证券交易所",
          "交易所英文名称": "Shanghai Stock Exchange",
          "权重": "1.662"
        },
        {
          "日期": "2026-06-30",
          "指数代码": "000905",
          "指数名称": "中证500",
          "指数英文名称": "CSI 500",
          "成分券代码": "300604",
          "成分券名称": "长川科技",
          "成分券英文名称": "Hangzhou Chang Chuan Technology Co.,Ltd.",
          "交易所": "深圳证券交易所",
          "交易所英文名称": "Shenzhen Stock Exchange",
          "权重": "1.341"
        },
        {
          "日期": "2026-06-30",
          "指数代码": "000905",
          "指数名称": "中证500",
          "指数英文名称": "CSI 500",
          "成分券代码": "001309",
          "成分券名称": "德明利",
          "成分券英文名称": "Shenzhen Techwinsemi Technology Co., Ltd.",
          "交易所": "深圳证券交易所",
          "交易所英文名称": "Shenzhen Stock Exchange",
          "权重": "1.324"
        }
      ]
    }
  },
  "中证1000": {
    "symbol": "000852",
    "constituent_rows": 1000,
    "weight_rows": 1000,
    "weight_sum": 99.986,
    "weight_columns": [
      "日期",
      "指数代码",
      "指数名称",
      "指数英文名称",
      "成分券代码",
      "成分券名称",
      "成分券英文名称",
      "交易所",
      "交易所英文名称",
      "权重"
    ],
    "top_weights": {
      "rows": 5,
      "columns": [
        "日期",
        "指数代码",
        "指数名称",
        "指数英文名称",
        "成分券代码",
        "成分券名称",
        "成分券英文名称",
        "交易所",
        "交易所英文名称",
        "权重"
      ],
      "sample": [
        {
          "日期": "2026-06-30",
          "指数代码": "000852",
          "指数名称": "中证1000",
          "指数英文名称": "CSI 1000",
          "成分券代码": "688766",
          "成分券名称": "普冉股份",
          "成分券英文名称": "Puya Semiconductor (Shanghai) Co., Ltd.",
          "交易所": "上海证券交易所",
          "交易所英文名称": "Shanghai Stock Exchange",
          "权重": "0.815"
        },
        {
          "日期": "2026-06-30",
          "指数代码": "000852",
          "指数名称": "中证1000",
          "指数英文名称": "CSI 1000",
          "成分券代码": "603083",
          "成分券名称": "剑桥科技",
          "成分券英文名称": "CIG ShangHai CO., LTD.",
          "交易所": "上海证券交易所",
          "交易所英文名称": "Shanghai Stock Exchange",
          "权重": "0.72"
        },
        {
          "日期": "2026-06-30",
          "指数代码": "000852",
          "指数名称": "中证1000",
          "指数英文名称": "CSI 1000",
          "成分券代码": "000636",
          "成分券名称": "风华高科",
          "成分券英文名称": "Guangdong Fenghua Advanced Technology (Holding) Co Ltd",
          "交易所": "深圳证券交易所",
          "交易所英文名称": "Shenzhen Stock Exchange",
          "权重": "0.686"
        }
      ]
    }
  }
}
```
