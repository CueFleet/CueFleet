# Linux WebUI 使用教程

[English](linux.en.md) · [返回项目主页](../README.md)

支持 **Ubuntu 24.04（x86-64）**。在服务器安装，用电脑或手机浏览器打开。

## 1. 安装 CueFleet

**下载和解压** · 在自己的空目录执行，普通用户无需 `sudo`。

```bash
curl -fL https://cuefleet.com/download/linux -o CueFleet-Linux-x64.tar.gz &&
tar -xzf CueFleet-Linux-x64.tar.gz &&
cd CueFleet-Linux-x64
```

**安装和配置** · 在解压目录运行同一条命令。

```bash
sh ./setup.sh
```

| 当前登录身份 | 系统权限怎么用 |
| --- | --- |
| `root` | 直接执行。向导会用专用的普通权限账号运行 WebUI。 |
| 有 `sudo` 权限的普通用户 | 直接执行。向导只在安装系统依赖、配置沙箱或启用自动 HTTPS 等系统操作时调用 `sudo`。 |

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

**日常启动** · 用安装时的同一用户，在安装目录执行向导显示的 `sh ./start.sh` 命令。向导指定了端口时保留 `--port` 参数。普通用户无需 `sudo`。

要改窗口密码，先停止客户端，再运行 `sh ./start.sh --set-password`。

要更改访问方式，先停止客户端，再运行 `sh ./setup.sh`。
