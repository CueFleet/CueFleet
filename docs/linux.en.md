# CueFleet Linux WebUI Setup Guide

[简体中文](linux.md) · [Back to the project](../README.en.md)

For **Ubuntu 24.04 (x86-64)**. CueFleet runs on your Linux computer or server. You use it from a browser.

## 1. Run the setup wizard

[Download version 0.5.67](https://cuefleet.com/downloads/linux/CueFleet-0.5.67-linux-x64.tar.gz) · [SHA-256 checksum](https://cuefleet.com/downloads/linux/CueFleet-0.5.67-linux-x64.tar.gz.sha256)

Put the archive on the Linux machine where CueFleet will run. As a regular user, open a terminal in the directory containing the file.

```bash
tar -xzf CueFleet-0.5.67-linux-x64.tar.gz
cd CueFleet-Linux-x64
sh ./setup.sh
```

The wizard checks system dependencies, helps you choose how to connect and which port to use, and starts CueFleet. Keep this terminal open and save the restart command shown by the wizard. Linux may ask for your sudo password when installing dependencies or setting up the browser sandbox. Run `sh ./setup.sh --lang en` to use English.

## 2. Open the WebUI in a browser

- **On the Linux machine**. Open the local address shown by the wizard. The default is `http://127.0.0.1:19425/`.
- **From another computer**. Choose local or SSH access on the server. Open a terminal on your own computer, run the command below, and leave it open. On the same computer, open `http://127.0.0.1:19425/` in your browser.

```bash
ssh -N -L 19425:127.0.0.1:19425 user@server
```

Replace `user@server` with your SSH username and server address. If the wizard used a different port, update both port numbers and the browser address.

## 3. Connect a Binance account

Sign in to CueFleet. Open **Binance Accounts → Add Account**, accept the connection agreement, and open the official Binance sign-in window.

Use the temporary viewer to access the Binance window. On the Linux machine running CueFleet, open another terminal as the same user, enter the client directory, and run the following command.

```bash
sh ./start.sh --binance-login
```

- **Local Linux desktop**. Copy the printed `vncviewer` command into another terminal on the same computer. If you need the viewer, run `sudo apt install tigervnc-viewer` first.
- **Remote Linux server**. Copy the printed SSH command into a terminal on your own computer and replace `SERVER` with your SSH server address. In your VNC viewer, connect to `127.0.0.1` on port `5901`.

Complete sign-in in the official Binance window. Once the account appears in the WebUI, close the viewer and any VNC tunnel. The server needs no open VNC port.

## Advanced setup

### Set up a user on a root-only server

Sign in as root and run the following commands to create and switch to a regular user. Download and extract the package in the new user's home directory.

```bash
adduser cuefleet
usermod -aG sudo cuefleet
su - cuefleet
```

If the server uses SSH keys, add your public key for the new user and verify that you can sign in as `cuefleet@server` before using SSH forwarding.

### Connect directly to a public IP

Only public HTTP asks for the **public IPv4 address of the Linux server running CueFleet**. You can find it in your hosting dashboard. CueFleet checks this address against the address your browser uses to open WebUI. Local access and SSH forwarding skip this field.

Set a window password and idle lock timeout, then allow the selected TCP port in the cloud and server firewalls. You can limit the firewall source to the public IP of the computer you connect from. Open the address shown by the wizard, unlock the window, and sign in to CueFleet.

**Public HTTP is unencrypted. Someone on the network could intercept the password or login session.** For private remote access, use SSH forwarding.

### Launch manually or change the password

Once the wizard has installed the dependencies, you can use the launch commands directly.

```bash
sh ./start.sh
sh ./start.sh --port 19426
```

The first command uses the default port. The second sets a custom port. The supported range is `1024–65535` and the default is `19425`. To set or change the window password, stop CueFleet, then run `sh ./start.sh --set-password`. The password must be at least 12 characters, and the terminal hides it as you type.

```bash
sh ./start.sh --public-http 203.0.113.10 --port 19426 --idle-minutes 10
```

Replace `203.0.113.10` with the public IPv4 address of the Linux server running CueFleet. The idle lock timeout can be `1–120` minutes and defaults to `10`. CueFleet keeps running while the window is locked.

### Download and verify from the server

Run the following commands in an empty directory. If `curl` is missing, run `sudo apt install curl` first.

```bash
archive=CueFleet-0.5.67-linux-x64.tar.gz
base=https://cuefleet.com/downloads/linux
curl -fLO "$base/$archive" &&
  curl -fLO "$base/$archive.sha256" &&
  sha256sum -c "$archive.sha256"
```

After the checksum passes, go back to step 1 to extract the archive and run the wizard.

### Update the client

Extract the new release to a new directory. Stop the old client (`Ctrl+C` if it is running in the foreground), then run `sh ./setup.sh` from the new directory. Keep the same Linux user, `XDG_STATE_HOME`, and launch options to reuse your window password and Binance connections. The default state directory is `~/.local/state/cuefleet`. Restarting briefly interrupts receipt of copy-trading signals.

[Download CueFleet](https://cuefleet.com/website/en.html#download) · [Contact support](mailto:support@cuefleet.com)
