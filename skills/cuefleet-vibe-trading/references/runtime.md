# CueFleet 本地信号接口 v1

接入代码以一次调用处理一条信号。模型只返回 `decision` 和行情的观测时间 `observedAt`。调用方使用自己的行情时间戳校验模型回传的时间，再用操作人选定的交易参数构造执行请求。模型可以由用户自行托管，或由调用方在本机执行。只传入这次判断所需的行情、标的、周期和策略规则。CueFleet API 密钥由运行脚本的父进程注入，模型进程应使用单独的环境。

## 生成模型输出

```json
{"decision":"NO_SIGNAL","observedAt":1760000000000}
```

- `decision` 接受 `LONG`、`SHORT`、`NO_SIGNAL`。先完成版本、格式和时间校验。`NO_SIGNAL` 不调用交易接口。
- `observedAt` 是观测行情时的 Unix 毫秒时间戳。方向信号从观测到提交最多 30 秒。
- 请求 UUID 由调用方生成并保存。同一个决策使用同一个 UUID。模型输出包含其他字段时拒绝处理。

## 调用运行脚本

Node.js 18 或更高版本。API 地址固定为 `http://127.0.0.1`，`CUEFLEET_API_PORT` 默认 `17687`。只通过父进程的 `CUEFLEET_API_KEY` 提供 CueFleet 本地 API 密钥。

运行 `node scripts/runtime.cjs run`，通过 stdin 写入一个 JSON 文档。示例中的时间戳和 UUID 在实际调用时替换为本次信号的值。

```json
{
  "version": "cuefleet.vibe-trading.v1",
  "requestId": "00000000-0000-4000-8000-000000000001",
  "mode": "simulation",
  "symbol": "ETHUSDT",
  "period": "10m",
  "amount": "5",
  "signal": {"decision":"NO_SIGNAL","observedAt":1760000000000}
}
```

- `mode` 是操作人指定的 `simulation` 或 `live`。`live` 须有独立实盘授权。
- `symbol` 接受 `BTCUSDT`、`ETHUSDT`。`period` 接受 `10m`、`30m`、`1h`、`1d`。`amount` 为正十进制字符串。
- 接入多个账号时须给出授权的 `accountId`，值为 CueFleet 连接 UUID。单账号可省略，由脚本读取该账号的当前支付率。模式、账号和金额来自操作人配置。

脚本写出一行 `{version,mode,requestId,state,...}`。`accepted` 表示已受理。`rejected` 表示被拒绝。`blocked` 表示受阻。`unknown` 和 `processing` 要继续核对原请求。

使用 `node scripts/runtime.cjs receipt` 并输入 `{version,mode,requestId}` 查询原编号。超时或断线时脚本只发回执查询。回执缺失时保持 `unknown`，再查一次原回执或对照交易所记录，保留原 UUID。脚本会在发送前写入本地标记。使用同一 UUID 再次运行也只查询回执。标记默认保存在 `~/.cuefleet/vibe-trading/requests`，可用 `CUEFLEET_VIBE_STATE_DIR` 指定绝对路径。同一控制台的调用方应共用这个目录。

## 控制台对接条件

目前发布的 CueFleet 本地 API 提供实盘接口，`GET /v1/status` 缺少执行模式。方向信号会停止在 `execution_mode_unsupported`。模拟和实盘的提交需要控制台实现以下契约。

- `/v1/status` 的 `data.executionMode` 必须明确返回 `simulation` 或 `live`，与请求模式相同。`data.access` 须报告有效 VIP，控制台在接受订单时再次核验权限。
- `/v1/accounts/{accountId}/market` 返回该模式的可用目录和账号状态。脚本从同账号、标的、周期及方向取当前支付率，仍由控制台校验金额、在途和订单权限。
- 脚本发送 `X-CueFleet-Execution-Mode`。`POST /v1/orders` 须在接收订单且选定交易路径前原子核验此值。模式有变化时返回 `execution_mode_mismatch`。`simulation` 只进入模拟账本，`live` 进入现有已授权的实盘接口。
- `POST /v1/orders` 同时带原 `Idempotency-Key` 和 `X-CueFleet-Observed-At`。控制台在进入提交路径前校验时间窗口并沿用原 UUID。模式与 UUID 共同定位原始记录。
- 对已受理、拒绝、受阻及进行中的响应，`data.id` 和 `data.executionMode` 须为原始请求值。`GET /v1/requests/{requestId}` 按请求头指定的原始模式查询历史回执。当前模式切换或资格到期后，仍按原回执权限读取。
