# Broker SDK Probe

独立的国投掘金 Broker SDK 技术验证项目。当前阶段仅执行环境探测、SDK 能力识别和只读账户查询，不连接现有交易系统，不执行下单或撤单。

## Windows 运行

```powershell
$python = "D:\QMT\workspace\broker_sdk_probe\.venv-gmtrade\Scripts\python.exe"
& $python D:\QMT\workspace\broker_sdk_probe\run_probe.py --mode environment
& $python D:\QMT\workspace\broker_sdk_probe\run_probe.py --mode api-surface
```

配置文件为 Windows 本地的 `config.local.json`，禁止提交到 Git。token 不写入日志或报告；账户 ID 只显示末四位。

账户连接验证需要配置 `gm_token`、`gmtrade_account_id` 和明确的本地终端 endpoint。程序不会在连接失败时切换云端 endpoint，也不会切换账户。

## 阶段边界

- `environment`：Windows、Python、QMT 进程和包版本探测。
- `api-surface`：读取当前安装版本实际暴露的模块、函数和签名。
- `readonly`：只有在本地配置完整且 QMT 仿真账户已登录时执行账户只读查询。
- 下单/撤单测试暂未开放，必须在只读证据完成并确认仿真账户后单独实现。
