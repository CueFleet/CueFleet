# CueFleet 信号项目与服务 v1

导出策略项目或接入外部信号时，统一使用 `cuefleet.signal.v1`。导出的 Python 项目自带启动脚本和协议适配器。已有服务可使用任意语言，按本页实现两个 HTTP 接口后直接接入 CueFleet。

## 可运行的 Python 项目

导出保留策略原有的相对路径。下面以一个包含模型权重和特征参数的项目为例。

```text
my-signal/
├── cuefleet_signal/
│   ├── signal.json          # 版本、名称、策略入口及行情需求
│   ├── start.py            # 准备虚拟环境并启动服务
│   ├── serve.py            # HTTP 协议适配器
│   └── example_strategy.py # 可用于验证连接的示例
├── requirements.lock       # 锁定运行依赖及哈希
├── README-CueFleet.md
├── strategy_pkg/           # 用户的策略和特征代码
└── weights/                # 按需包含权重、归一化参数等
```

`cuefleet_signal/signal.json` 声明 `version`、`name`、`strategy` 和 `marketRequirements`。`version` 为 `cuefleet.signal.v1`。旧版缺少 `version` 的项目可继续加载。`strategy` 为 `module:function`，入口接收完整的预测请求并返回 `LONG`、`SHORT` 或 `NO_SIGNAL`。模型、特征转换、归一化和推理都留在项目内。项目的相对路径以项目根目录为准。

创建可运行的示例服务。

```sh
python "$SKILL/scripts/signal_project.py" --output ./example-signal --symbol ETHUSDT --warmup 2
cd ./example-signal
python cuefleet_signal/start.py --port 18781
```

启动需要 Python 3.11+。脚本根据 Python 环境和 `requirements.lock` 准备独立的 `.venv`，再打印监听地址。只使用标准库的项目可用空依赖锁，示例策略返回 `NO_SIGNAL`。

已有策略可以按原目录结构导出。

```sh
python "$SKILL/scripts/signal_project.py" --output ./my-signal --project ./experiment \
  --include strategy_pkg --include weights --include requirements.lock \
  --strategy strategy_pkg.inference:predict --name 'ETH 趋势' --warmup 120
```

`--include` 可重复。选择推理用到的代码、权重、特征参数、只读数据和依赖锁。按需在目标机器重建虚拟环境。导出器会跳过虚拟环境、常见缓存及 `.env` 文件。运行凭据由部署环境提供。

## 外部服务接口

CueFleet 主动调用服务。已有推送式信号源可以用适配器接收上游信号，再实现下面的查询接口。适配器结合请求中的标的、周期和 `market.asOf` 判断信号是否有效。缺少匹配信号时返回 `NO_SIGNAL`。

| 端点 | 输入 | 成功响应字段 |
| --- | --- | --- |
| `GET /health` | 无请求体 | `version`、`name`、`marketRequirements` |
| `POST /v1/predict` | `version`、`requestId`、`symbol`、`period`、`market` | `version`、`requestId`、`decision`、`observedAt` |

成功响应使用 UTF-8 JSON 和 `Content-Type: application/json`，字段按表格提供。服务名称最多 80 个字符，去掉首尾空白。v1 每个标的可声明一个行情窗口，支持 `BTCUSDT` 和 `ETHUSDT`。下面的健康响应声明需要 1 根永续合约收盘 K 线。

```json
{
  "version": "cuefleet.signal.v1",
  "name": "ETH 趋势",
  "marketRequirements": [
    {
      "source": "binance-usdm-perpetual",
      "symbol": "ETHUSDT",
      "interval": "1m",
      "minClosedCandles": 1
    }
  ]
}
```

预测请求中的 `period` 为事件合约到期周期，取 `10m`、`30m`、`1h` 或 `1d`。`market.interval` 是服务声明的 K 线粒度。`market.candles` 按时间升序提供连续收盘 K 线，每路最多 600 根。使用指数行情时 `volume` 为 `null`。需要更长的历史时，在策略项目内保存同源历史并与实时窗口连续拼接。 [预测请求 JSON 与行情字段](realtime-market-data.md)

响应原样回传请求的 UUID `requestId`，并将 `market.asOf` 原样写入 `observedAt`。服务等待合适的交易信号时仍可正常返回 `NO_SIGNAL`。以下响应对应行情文档中的预测请求样例。

```json
{
  "version": "cuefleet.signal.v1",
  "requestId": "00000000-0000-4000-8000-000000000001",
  "decision": "NO_SIGNAL",
  "observedAt": 1760000100100
}
```

CueFleet 仅将行情与场景发给服务。账号、金额、交易模式和下单凭据由 CueFleet 管理。客户端会核验响应时间和观测时间，过期或无效响应会被跳过。

## 验证与部署

先用合成行情验证两个接口、协议版本和回传字段。以下命令要求 Python 3.11+。配置了访问密钥时，通过环境变量 `CUEFLEET_SIGNAL_TOKEN` 提供给检查器。

```sh
python "$SKILL/scripts/check_signal_service.py" --url http://127.0.0.1:18781 --symbol ETHUSDT --period 10m
```

本机回环地址可使用 HTTP。远程服务使用 HTTPS，建议给两个端点启用同一个 Bearer Token。Python 示例默认监听 `127.0.0.1`，可在其前面部署 HTTPS 反向代理。CueFleet Linux WebUI 的回环地址指运行客户端执行器的服务器。

从「AI 交易 → 信号服务」添加服务根地址和访问密钥，先点「测试连接」，保存后点「预览信号」。在支持「本地跟单」的版本里，从「我的模拟」选择该信号服务并启动任务，验证信号时序、断线恢复和缺 K 线行为。
