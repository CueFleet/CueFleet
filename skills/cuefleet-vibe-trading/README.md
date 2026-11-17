# CueFleet 策略工程

用 Codex、Claude Code 或其他编码智能体创建一个策略工程，再交给 CueFleet 启动和运行。工程可以包含推理代码、特征处理和模型权重，CueFleet 通过 `cuefleet.signal.v1` 读取方向。

## 用智能体创建工程

把本目录交给你的编码智能体，并给它下面的任务。

> 阅读 `SKILL.md` 和 `references/signal-project.md`。实现一个 BTCUSDT 10m 策略，使用两根已收盘的 1m K 线判断方向。把策略打包为独立工程，写明依赖。用合成行情验证 `/health` 和 `/v1/predict`，最后给我工程目录。

使用 Python 3.11 或更新版本也能直接生成同一个示例。在本目录打开终端，运行以下命令。

```powershell
python scripts/signal_project.py --project examples --include market_momentum.py --strategy market_momentum:predict --symbol BTCUSDT --warmup 2 --name "BTC 双 K 线示例" --output ./my-btc-signal
```

## 在 CueFleet 运行

1. 打开「AI 交易 → 信号服务 → 加载策略工程」，选择 `my-btc-signal`。支持目录导入的版本才会显示这个按钮。使用 0.5.86 时，请先运行工程根目录的启动脚本，再在「AI 交易」添加其地址。
2. 核对工程信息，点击「启动服务」，再点「预览信号」检查连接。
3. 在「本地跟单 → 我的模拟」新建跟单、选择信号并启动。点击跟单卡片查看记录，打开单笔查看策略版本、价格和时序。0.5.86 的自动模拟可在信号卡片操作，适用现有 VIP 条件。

策略进程使用机器上运行它的用户权限。加载后启动你审阅过的工程。服务从 CueFleet 接收行情，交易账号和资金设置在客户端配置。

已有信号服务的用户可直接按 [信号协议与工程规范](references/signal-project.md) 接入。编写特征代码时参考 [实时行情输入](references/realtime-market-data.md)。如果希望按固定区间复现结果，参考 [Skill 中的回测步骤](SKILL.md)。
