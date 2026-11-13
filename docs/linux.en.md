# CueFleet Linux WebUI Setup Guide

[简体中文](linux.md) · [Back to the project](../README.en.md)

This guide is for **Ubuntu 24.04 (x86-64)**. Install CueFleet on your Linux computer or server and open its WebUI in a browser. The examples use **0.5.66**.

## 1. Install CueFleet

Install the system dependencies. Use a regular Linux user to download, extract, and run the client.

```bash
sudo apt update
sudo apt install curl dbus-daemon xvfb xauth openssl libgtk-3-0t64 libnss3 libgbm1 libasound2t64 libcups2t64 libatk-bridge2.0-0t64 libxss1 fonts-liberation
```

Download the client and checksum into a new directory. Extract the archive after the checksum passes.

[Download version 0.5.66](https://cuefleet.com/downloads/linux/CueFleet-0.5.66-linux-x64.tar.gz) · [SHA-256 checksum](https://cuefleet.com/downloads/linux/CueFleet-0.5.66-linux-x64.tar.gz.sha256)

```bash
archive=CueFleet-0.5.66-linux-x64.tar.gz
base=https://cuefleet.com/downloads/linux
curl -fLO "$base/$archive" &&
  curl -fLO "$base/$archive.sha256" &&
  sha256sum -c "$archive.sha256" &&
  tar -xzf "$archive" &&
  cd CueFleet-Linux-x64
```

## 2. Choose how to connect

### Local access or SSH forwarding

Start the client from `CueFleet-Linux-x64` on your Linux machine.

```bash
sh ./start.sh
```

Open [http://127.0.0.1:19425/](http://127.0.0.1:19425/) in a browser on the same machine. If the client runs on a remote server, open a terminal on your own computer, run the following command, and then open the same URL.

```bash
ssh -N -L 19425:127.0.0.1:19425 user@server
```

Replace `user@server` with your SSH username and server address. With SSH forwarding, only the server's SSH port needs to be reachable. If port `19425` is in use, start with `sh ./start.sh --port 19426` and update the forwarding command and browser address accordingly.

### Direct access over a public IP (HTTP)

In an interactive terminal on your server, set a unique window password of at least 12 characters. The terminal hides it as you type. Then start CueFleet with the server's public IPv4 address, port, and idle lock timeout.

```bash
sh ./start.sh --set-password
sh ./start.sh --public-http 203.0.113.10 --port 19426 --idle-minutes 10
```

Replace `203.0.113.10` with the actual public IP. Allow the chosen TCP port in both your cloud firewall and the server firewall, ideally only from your own public IP. Open `http://YOUR_PUBLIC_IP:19426/`, unlock the window, and then sign in to CueFleet.

- The port can be `1024–65535` and defaults to `19425`.
- The idle lock can be set to `1–120` minutes and defaults to `10`. Enter the window password again to unlock it. The client keeps running in the background.
- To change the window password, stop the client and run `sh ./start.sh --set-password` again.

**Public HTTP is unencrypted. Someone on the network could intercept your window password or login session.** For private remote access, prefer SSH forwarding.

## 3. Sign in to Binance on a headless server

After signing in to CueFleet, open **Binance Accounts → Add Account**, accept the connection agreement, and open the official Binance sign-in window. On the server, open another terminal as the same Linux user, enter the client directory, and install and start the temporary sign-in viewer.

```bash
sudo apt install x11vnc
EVENTFOLO_NODE="$PWD/bin/node" sh ./scripts/linux-executor.sh login "${XDG_STATE_HOME:-$HOME/.local/state}/cuefleet/run"
```

On your own computer, open another terminal and forward the `login.sock` path printed by the viewer. Replace the example socket path and `user@server` with your actual values.

```bash
ssh -N -L 5901:/home/user/.local/state/cuefleet/run/login.sock user@server
```

Use a VNC client to connect to `127.0.0.1` on port `5901`. Complete sign-in and verification in the official Binance window. Once the account appears in WebUI, you can close the temporary viewer and its VNC tunnel. The Binance session is stored on the machine running CueFleet. Moving to another machine requires verification again.

## 4. Update the client

Download the new release from the website and extract it into a new directory. Stop the old client (`Ctrl+C` if running in the foreground), then start the new one. Keep the same Linux user, `XDG_STATE_HOME`, and launch options to reuse your window password and Binance connections. If `XDG_STATE_HOME` is unset, CueFleet stores its state in `~/.local/state/cuefleet`. Restarting briefly interrupts receipt of copy-trading signals.

[Download CueFleet](https://cuefleet.com/#download) · [Contact support](mailto:support@cuefleet.com)
