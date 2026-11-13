# Linux WebUI 使用教程

[English](linux.en.md) · [返回项目主页](../README.md)

支持 **Ubuntu 24.04（x86-64）**。在服务器安装，用电脑或手机浏览器打开。

## 1. 安装 CueFleet

用有 sudo 权限的普通用户登录服务器，在空目录运行。

```bash
curl -fL https://cuefleet.com/download/linux -o CueFleet-Linux-x64.tar.gz &&
tar -xzf CueFleet-Linux-x64.tar.gz &&
cd CueFleet-Linux-x64 &&
sh ./setup.sh
```

按向导设置窗口密码。要从手机或其他电脑访问，在「自动配置免费 HTTPS？」选择是，核对或输入服务器公网 IPv4。证书会自动续期。启动后保持终端打开。

在云安全组和系统防火墙放行公网入站 TCP `80`，供证书签发和续期。WebUI 端口默认是 TCP `19425`，来源可限制为访问设备的公网 IP。

## 2. 在浏览器打开

用手机或电脑打开向导显示的 HTTPS 地址，输入窗口密码。

![手机浏览器中的 CueFleet 窗口解锁页](../assets/linux-window-lock.webp)

## 3. 添加币安账号

点击「币安账号 → 添加账号」，同意协议后在窗口中完成币安官方登录。

![CueFleet WebUI 的添加账号入口](../assets/linux-binance-account.webp)

![CueFleet WebUI 的币安账号连接提示](../assets/linux-binance-login.webp)

<details>
<summary>证书签发失败或已有证书</summary>

签发失败时，核对服务器公网 IPv4 和 TCP `80` 的入站规则，再重试。初次跳过后，可重新运行 `sh ./setup.sh` 配置。若 TCP `80` 已被现有网站占用，可沿用自己的可信证书。

停止正在运行的客户端，将域名和证书路径替换成自己的配置，然后运行：

```bash
CUEFLEET_HTTPS_HOST=your-domain.example \
CUEFLEET_HTTPS_CERT=/path/to/fullchain.pem \
CUEFLEET_HTTPS_KEY=/path/to/privkey.pem \
sh ./start.sh
```

用 `https://你的域名:19425/` 打开。若使用自定义端口，启动和访问时沿用同一个端口。

服务器本机可用向导显示的本机地址访问。公网 HTTP 为明文传输，请通过可信 HTTPS 登录和交易。

</details>

升级与手动启动见安装包内的 `README.md`。
