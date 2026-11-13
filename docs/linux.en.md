# Linux WebUI Setup Guide

[简体中文](linux.md) · [Back to the project](../README.en.md)

Requires **Ubuntu 24.04 (x86-64)**. Install on the server, then open WebUI from your computer or phone.

## 1. Install CueFleet

**Download the .deb · No sudo needed** · [SHA-256 checksum](https://cuefleet.com/download/linux-deb.sha256)

```bash
curl -fL https://cuefleet.com/download/linux-deb -o CueFleet-linux-amd64.deb
```

**Install the package · Administrator access required**

```bash
sudo apt install ./CueFleet-linux-amd64.deb
```

If you signed in as root, omit `sudo`. APT installs the dependencies.

**First-time setup · Use your current account**

```bash
cuefleet setup --lang en
```

Regular users run the wizard directly. It shows any administrator commands needed for automatic HTTPS before running them. When you run setup as root, CueFleet runs under a dedicated account.

To connect from a phone or another computer, choose an HTTPS option and set a window password.

| Access | Choose in the wizard |
| --- | --- |
| Set up HTTPS automatically | Confirm your server’s public IPv4 address. CueFleet issues and renews the certificate. |
| Use your own certificate | Enter the domain or IP you’ll use and the PEM paths for its certificate chain and private key. |
| Local access only | Open the HTTP address shown by the wizard on the server. |

For remote access, have the server administrator allow the WebUI TCP port. The default is `19425`. Leave the terminal open after startup.

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

## 4. Start CueFleet or change the password

Run `cuefleet start` with the same account that ran setup. Keep the `--port` argument if the wizard showed a custom port.

To change the window password, stop the client and run `cuefleet set-password`. To change access mode, run `cuefleet setup` again.

<details>
<summary>Use the portable .tar.gz archive</summary>

[Download the portable archive](https://cuefleet.com/download/linux), extract it, then run `sh ./setup.sh --lang en`. To start again, use the `sh ./start.sh` command shown by the wizard.

</details>
