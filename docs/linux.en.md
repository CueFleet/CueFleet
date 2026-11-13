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

Set a window password. For access from your phone or another computer, choose **yes** when asked to set up free HTTPS. Confirm or enter your server’s public IPv4 address. CueFleet renews the certificate automatically. Leave the terminal open after startup.

Allow public inbound TCP `80` in your cloud and server firewalls for certificate issuance and renewal. The default WebUI port is TCP `19425`. You can restrict it to the connecting device’s public IP.

## 2. Open WebUI in your browser

Open the HTTPS address shown by the wizard on your phone or computer and enter the window password.

![CueFleet window unlock page in a phone browser](../assets/linux-window-lock-en.webp)

## 3. Add a Binance account

Open **Binance Accounts → Add account**, accept the agreement, and complete sign-in in the official Binance window.

![Add account in CueFleet WebUI](../assets/linux-binance-account-en.webp)

![Binance account connection prompt in CueFleet WebUI](../assets/linux-binance-login-en.webp)

<details>
<summary>If certificate setup fails or you already have a certificate</summary>

If certificate setup fails, check your server’s public IPv4 and the inbound rules for TCP `80`, then retry. If you skipped HTTPS, run `sh ./setup.sh` again. If an existing website uses TCP `80`, you can use your own trusted certificate.

Stop the running client. Replace the domain and certificate paths, then run:

```bash
CUEFLEET_HTTPS_HOST=your-domain.example \
CUEFLEET_HTTPS_CERT=/path/to/fullchain.pem \
CUEFLEET_HTTPS_KEY=/path/to/privkey.pem \
sh ./start.sh
```

Open `https://your-domain.example:19425/`. If you use a custom port, use that same port to start the client and open the page.

For access directly from the server, use the local address shown by the wizard. Public HTTP is unencrypted. Use trusted HTTPS to sign in or trade remotely.

</details>

See the included `README.md` for upgrades and manual startup.
