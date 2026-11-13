# CueFleet Linux WebUI 使用教程

[English](linux.en.md) · [返回项目主页](../README.md)

适用于 **Ubuntu 24.04（x86-64）**。CueFleet 安装在你的 Linux 电脑或服务器上，用浏览器打开 WebUI。以下命令以 **0.5.66** 为例。

## 1. 安装

安装系统依赖。下载、解压和运行客户端请使用普通 Linux 用户。

```bash
sudo apt update
sudo apt install curl dbus-daemon xvfb xauth openssl libgtk-3-0t64 libnss3 libgbm1 libasound2t64 libcups2t64 libatk-bridge2.0-0t64 libxss1 fonts-liberation
```

在新目录中下载客户端与校验文件。校验通过后再解压。

[下载 0.5.66 安装包](https://cuefleet.com/downloads/linux/CueFleet-0.5.66-linux-x64.tar.gz) · [SHA-256 校验文件](https://cuefleet.com/downloads/linux/CueFleet-0.5.66-linux-x64.tar.gz.sha256)

```bash
archive=CueFleet-0.5.66-linux-x64.tar.gz
base=https://cuefleet.com/downloads/linux
curl -fLO "$base/$archive" &&
  curl -fLO "$base/$archive.sha256" &&
  sha256sum -c "$archive.sha256" &&
  tar -xzf "$archive" &&
  cd CueFleet-Linux-x64
```

## 2. 选择访问方式

### 本机访问或 SSH 转发

在 Linux 机器的 `CueFleet-Linux-x64` 目录启动客户端。

```bash
sh ./start.sh
```

在同一台机器用浏览器打开 [http://127.0.0.1:19425/](http://127.0.0.1:19425/)。如果客户端运行在远程服务器，在自己的电脑另开终端执行以下命令，再打开同一个地址。

```bash
ssh -N -L 19425:127.0.0.1:19425 user@server
```

把 `user@server` 换成实际 SSH 用户和服务器地址。SSH 转发时只需要能连接服务器的 SSH 端口。若 `19425` 已占用，可用 `sh ./start.sh --port 19426` 启动，再相应修改转发命令和浏览器地址。

### 直接通过公网 IP 访问（HTTP）

在服务器交互终端设置至少 12 个字符的独立窗口密码，终端会隐藏输入。再指定服务器的公网 IPv4 地址、端口和闲置锁定时间。

```bash
sh ./start.sh --set-password
sh ./start.sh --public-http 203.0.113.10 --port 19426 --idle-minutes 10
```

把 `203.0.113.10` 换成实际公网 IP。在云防火墙和服务器防火墙放行所选 TCP 端口，来源建议限制为自己的公网 IP。然后用浏览器访问 `http://你的公网IP:19426/`，先解锁窗口，再登录 CueFleet。

- 端口范围为 `1024–65535`，默认 `19425`。
- 闲置锁定可设置 `1–120` 分钟，默认 `10` 分钟。锁定后再次输入窗口密码即可，客户端仍在后台运行。
- 修改窗口密码时，先停止客户端，再运行 `sh ./start.sh --set-password`。

**公网 HTTP 明文传输，窗口密码和登录会话可能被截获。** 私人远程使用优先选 SSH 转发。

## 3. 无图形界面服务器上登录币安

登录 CueFleet 后，进入「币安账号 → 添加账号」，同意接入协议并打开币安官方登录窗口。用同一个 Linux 用户在服务器另开终端，进入客户端目录，安装并启动临时登录查看器。

```bash
sudo apt install x11vnc
EVENTFOLO_NODE="$PWD/bin/node" sh ./scripts/linux-executor.sh login "${XDG_STATE_HOME:-$HOME/.local/state}/cuefleet/run"
```

在自己的电脑另开终端，用 SSH 转发终端打印的 `login.sock` 路径。将以下命令的套接字路径和 `user@server` 换成实际值。

```bash
ssh -N -L 5901:/home/user/.local/state/cuefleet/run/login.sock user@server
```

用 VNC 客户端连接本机 `127.0.0.1` 的 `5901` 端口，在币安官方窗口完成登录和验证。确认 WebUI 已显示账号后，可关闭临时查看器和这条 VNC 隧道。币安登录保存在运行 CueFleet 的 Linux 机器上，换机器时需要重新验证。

## 4. 更新客户端

从官网下载新版并解压到新目录。停止旧客户端（如果在前台运行，按 `Ctrl+C`），再从新目录启动。沿用相同的 Linux 用户、`XDG_STATE_HOME` 和启动参数，可继续使用已有的窗口密码和币安绑定。未设置 `XDG_STATE_HOME` 时，状态保存在 `~/.local/state/cuefleet`。重启会短暂中断接收跟单信号。

[官网下载](https://cuefleet.com/#download) · [联系支持](mailto:support@cuefleet.com)
