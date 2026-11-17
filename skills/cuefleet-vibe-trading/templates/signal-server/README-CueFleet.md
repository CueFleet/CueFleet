# CueFleet 信号服务 · Signal service

## 项目结构 · Project layout

```text
<project>/
├── README-CueFleet.md
├── requirements.lock
└── cuefleet_signal/
    ├── signal.json
    ├── start.py
    ├── serve.py
    └── example_strategy.py
```

策略代码、特征和权重放在项目根目录下，保留各自的相对路径。启动时自动生成 `.venv`。

Keep strategy code, features, and weights at their original paths relative to the project root. Startup creates `.venv`.

清单 `cuefleet_signal/signal.json` 声明 `version`（`cuefleet.signal.v1`）、服务名称 `name`、策略入口 `strategy` 和行情需求 `marketRequirements`。

The `cuefleet_signal/signal.json` manifest declares `version` (`cuefleet.signal.v1`), the service `name`, the `strategy` entry point, and `marketRequirements`.

## 启动 · Start

在项目根目录运行。Run from the project directory.

```sh
python cuefleet_signal/start.py --port 18781
```

Python 3.11+。启动脚本在项目内创建独立的 `.venv`，并从 `requirements.lock` 安装带哈希的锁定依赖。服务监听 `127.0.0.1`，终端打印地址。在 CueFleet 添加该地址并测试连接。

Python 3.11+. Startup creates an isolated `.venv` inside the project and installs hash-pinned dependencies from `requirements.lock`. Add the printed loopback address to CueFleet and test the connection.

- 在 `cuefleet_signal/signal.json` 设置策略入口和最少收盘 K 线根数。入口是 `module:function`，接收预测请求并返回 `LONG`、`SHORT` 或 `NO_SIGNAL`。示例返回 `NO_SIGNAL`。
- Set the `module:function` strategy entry point and warm-up length in `cuefleet_signal/signal.json`. The function receives a prediction request and returns `LONG`, `SHORT`, or `NO_SIGNAL`. The example returns `NO_SIGNAL`.
- 同机可选设置 `CUEFLEET_SIGNAL_TOKEN`。远程运行时，在服务前配置 HTTPS 反向代理，同时设置 Token，再把代理地址和 Token 填入 CueFleet。
- `CUEFLEET_SIGNAL_TOKEN` is optional on loopback. For remote access, configure an HTTPS reverse proxy, set a token, and enter the proxy address and token in CueFleet.

导出需包含训练得到的权重、特征代码和运行依赖。策略服务只生成信号。模型项目内的相对路径以项目根目录为准，不需要交易密钥或浏览器会话。

Export the trained weights, feature code, and runtime dependencies. The signal service generates decisions. Resolve project-relative paths from the project root.
