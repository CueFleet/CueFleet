# CueFleet Linux WebUI 使用教程

[English](linux.en.md) · [返回项目主页](../README.md)

适用于 **Ubuntu 24.04（x86-64）**。CueFleet 运行在你的 Linux 电脑或服务器上，操作界面在浏览器里打开。

## 1. 运行安装向导

[下载 0.5.67 安装包](https://cuefleet.com/downloads/linux/CueFleet-0.5.67-linux-x64.tar.gz) · [SHA-256 校验文件](https://cuefleet.com/downloads/linux/CueFleet-0.5.67-linux-x64.tar.gz.sha256)

将压缩包放到运行 CueFleet 的 Linux 机器上，以普通用户在文件所在目录打开终端。

```bash
tar -xzf CueFleet-0.5.67-linux-x64.tar.gz
cd CueFleet-Linux-x64
sh ./setup.sh
```

向导会检查系统依赖，带你选择访问方式和端口，然后启动 CueFleet。保留此终端并记下向导显示的重启命令。首次安装依赖或配置浏览器沙箱时，系统可能提示输入 sudo 密码。使用 `sh ./setup.sh --lang zh` 可切换到中文。

## 2. 在浏览器打开

- **在这台 Linux 电脑上用**。打开向导显示的本机地址，默认是 `http://127.0.0.1:19425/`。
- **在远程服务器上用**。选择本机或 SSH 方式启动。在你自己的电脑另开终端，连接服务器并保持终端打开，然后在同一台电脑的浏览器访问 `http://127.0.0.1:19425/`。

```bash
ssh -N -L 19425:127.0.0.1:19425 user@server
```

将 `user@server` 换成 SSH 用户名和服务器地址。如果向导选了其他端口，将命令里的两个端口和浏览器地址一并修改。

## 3. 连接币安账号

登录 CueFleet，进入「币安账号 → 添加账号」，同意接入协议并打开币安官方登录窗口。

币安登录窗口通过临时查看器打开。在运行 CueFleet 的 Linux 机器上另开终端，以同一用户进入客户端目录，运行下列命令。

```bash
sh ./start.sh --binance-login
```

- **本机 Linux 桌面**。将显示的 `vncviewer` 命令复制到本机另一个终端执行。如果尚未安装查看器，先运行 `sudo apt install tigervnc-viewer`。
- **远程 Linux 服务器**。将显示的 SSH 转发命令复制到自己电脑的终端，把 `SERVER` 换成 SSH 服务器地址，再用 VNC 查看器连接本机 `127.0.0.1` 的 `5901` 端口。

在币安官方窗口完成登录。看到账号出现在 WebUI 后，可关闭查看器和 VNC 隧道。服务器无需开放 VNC 端口。

## 进阶设置

### 服务器只有 root 账号

先以 root 登录服务器，用以下命令创建普通用户并切换。下载和解压请在新用户的主目录操作。

```bash
adduser cuefleet
usermod -aG sudo cuefleet
su - cuefleet
```

如果服务器使用 SSH 密钥登录，为新用户添加你的公钥，并确认可用 `cuefleet@server` 登录，再使用 SSH 转发。

### 直接通过公网 IP 访问

在向导里选择公网 HTTP，输入服务器的公网 IPv4 地址，设置独立的窗口密码和闲置锁定时间。云防火墙和服务器防火墙需允许所选 TCP 端口，来源可限制为自己的公网 IP。打开向导给出的地址，先解锁窗口，再登录 CueFleet。

**公网 HTTP 使用明文传输，密码和登录会话可能被截获。** 私人远程访问优先使用 SSH 转发。

### 手动启动与修改密码

向导已完成依赖安装后，可以直接使用启动命令。

```bash
sh ./start.sh
sh ./start.sh --port 19426
```

上面分别为默认启动和指定端口的示例。端口范围为 `1024–65535`，默认 `19425`。若要设置或修改窗口密码，先停止客户端，再运行 `sh ./start.sh --set-password`。密码至少 12 个字符，输入时终端会隐藏内容。

```bash
sh ./start.sh --public-http 203.0.113.10 --port 19426 --idle-minutes 10
```

将 `203.0.113.10` 换成实际公网 IPv4 地址。闲置锁定时间可设为 `1–120` 分钟，默认 `10` 分钟。窗口锁定时，客户端继续在后台运行。

### 在服务器下载并校验

在空目录内运行以下命令。若没有 `curl`，先运行 `sudo apt install curl`。

```bash
archive=CueFleet-0.5.67-linux-x64.tar.gz
base=https://cuefleet.com/downloads/linux
curl -fLO "$base/$archive" &&
  curl -fLO "$base/$archive.sha256" &&
  sha256sum -c "$archive.sha256"
```

通过校验后，回到第一步解压并运行向导。

### 更新客户端

将新版解压到新目录，停止旧版（在终端前台运行时按 `Ctrl+C`），在新目录运行 `sh ./setup.sh`。沿用同一个 Linux 用户、相同的 `XDG_STATE_HOME` 和启动参数，可继续使用已有的窗口密码和币安绑定。默认状态目录为 `~/.local/state/cuefleet`。重启会短暂中断跟单信号接收。

[官网下载](https://cuefleet.com/#download) · [联系支持](mailto:support@cuefleet.com)
