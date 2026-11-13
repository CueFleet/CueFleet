# Linux WebUI Setup Guide

[简体中文](linux.md) · [Back to the project](../README.en.md)

Requires **Ubuntu 24.04 (x86-64)**. Install on the server, then open WebUI from your computer or phone.

## 1. Install CueFleet

Sign in to the server as a regular user with sudo access and run these commands in an empty directory.

```bash
curl -fL https://cuefleet.com/download/linux -o CueFleet-Linux-x64.tar.gz &&
tar -xzf CueFleet-Linux-x64.tar.gz &&
cd CueFleet-Linux-x64 &&
sh ./setup.sh
```

To connect from a phone or another computer, choose an HTTPS option and set a window password.

| Access | Choose in the wizard |
| --- | --- |
| Set up HTTPS automatically | Confirm your server’s public IPv4 address. CueFleet issues and renews the certificate. |
| Use your own certificate | Enter the domain or IP you’ll use and the PEM paths for its certificate chain and private key. |
| Local access only | Open the HTTP address shown by the wizard on the server. |

For remote access, allow the WebUI TCP port, which defaults to `19425`. Leave the terminal open after startup.

<details>
<summary>Automatic certificates and port 80</summary>

Allow inbound public TCP `80` in your cloud and server firewalls for issuance and renewal. If a website already uses it, configure the HTTP site for your server’s public IP to serve `/.well-known/acme-challenge/` from `/var/lib/cuefleet-webui-acme` with the request path intact. Then choose to use the existing web server in the wizard.

</details>

## 2. Open WebUI in your browser

Open the HTTPS address shown by the wizard on your phone or computer and enter the window password.

![CueFleet window unlock page in a phone browser](../assets/linux-window-lock-en.webp)

## 3. Add a Binance account

Open **Binance Accounts → Add account**, accept the agreement, and complete sign-in in the official Binance window.

![Add account in CueFleet WebUI](../assets/linux-binance-account-en.webp)

![Binance account connection prompt in CueFleet WebUI](../assets/linux-binance-login-en.webp)

To restart, run the command shown by the wizard. To change the access mode, stop the client and run `sh ./setup.sh`.
