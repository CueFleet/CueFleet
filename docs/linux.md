# Linux WebUI 使用教程

[English](linux.en.md) · [返回项目主页](../README.md)

支持 **Ubuntu 24.04（x86-64）**。在服务器安装，用电脑或手机浏览器打开。

## 1. 安装 CueFleet

**下载 .deb · 无需 sudo** · [SHA-256 校验文件](https://cuefleet.com/download/linux-deb.sha256)

```bash
curl -fL https://cuefleet.com/download/linux-deb -o CueFleet-linux-amd64.deb
```

**安装软件包 · 需要管理员权限**

```bash
sudo apt install ./CueFleet-linux-amd64.deb
```

已经用 root 登录时，去掉 `sudo`。APT 会一并安装依赖。

**首次配置 · 用当前账号执行**

```bash
cuefleet setup --lang zh
```

普通用户直接执行。自动 HTTPS 需要提权时，向导会先显示要执行的命令。root 启动向导时，CueFleet 由专用账号运行。

用手机或其他电脑访问时，选择一种 HTTPS 配置并设置窗口密码。

| 访问方式 | 在安装向导中选择 |
| --- | --- |
| 自动配置 HTTPS | 确认服务器公网 IPv4，证书自动申请和续期。 |
| 使用自己的证书 | 填写访问用的域名或 IP，以及匹配该地址的证书链和私钥 PEM 路径。 |
| 仅本机访问 | 在服务器本机打开向导显示的 HTTP 地址。 |

远程访问时，由服务器管理员放行 WebUI 的 TCP 端口，默认 `19425`。启动后保持终端打开。

<details>
<summary>自动签发条件和 80 端口占用</summary>

在云安全组和系统防火墙放行公网入站 TCP `80`，供证书签发和续期。如果已有网站使用该端口，让公网 IP 对应的 HTTP 站点从 `/var/lib/cuefleet-webui-acme` 提供 `/.well-known/acme-challenge/` 文件，保留原 URL 路径。配置好后，在向导中选择使用现有 Web 服务。

</details>

## 2. 在浏览器打开

用手机或电脑打开向导显示的 HTTPS 地址，输入窗口密码。

![手机浏览器中的 CueFleet 窗口解锁页](../assets/linux-window-lock.webp)

## 3. 添加币安账号

点击「币安账号 → 添加账号」，同意协议后在窗口中完成币安官方登录。

![CueFleet WebUI 的添加账号入口](../assets/linux-binance-account.webp)

![CueFleet WebUI 的币安账号连接提示](../assets/linux-binance-login.webp)

## 4. 日常启动与改密码

用首次配置时的账号运行 `cuefleet start`。向导显示自定义端口时，保留 `--port` 参数。

要改窗口密码，先停止客户端，再运行 `cuefleet set-password`。要更改访问方式，重新运行 `cuefleet setup`。

<details>
<summary>使用便携压缩包 .tar.gz</summary>

[下载便携压缩包](https://cuefleet.com/download/linux)，解压后运行 `sh ./setup.sh --lang zh`。日常启动时运行向导显示的 `sh ./start.sh` 命令。

</details>
