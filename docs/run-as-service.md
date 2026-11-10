# Starting sungrow-local automatically

## Linux and Raspberry Pi (systemd)

The unit in [`contrib/sungrow-local.service`](../contrib/sungrow-local.service) runs the
dashboard under its own unprivileged user in a sandbox. Code, configuration and data live
apart, so the service can write its database but not its own code or the JavaScript it
serves.

| What | Where | Owner and mode |
|---|---|---|
| code | `/opt/sungrow-local` | root, not writable by the service |
| configuration | `/etc/sungrow-local/config.json` | `root:sungrow-local`, `640` |
| database | `/var/lib/sungrow-local` | created by systemd for the service |

1. Create the user and the folders, and put the code in place:
   ```sh
   sudo useradd --system --home-dir /var/lib/sungrow-local --shell /usr/sbin/nologin sungrow-local
   sudo git clone https://github.com/bernard-hossmoto/sungrow-local /opt/sungrow-local
   sudo install -d -m 750 -o root -g sungrow-local /etc/sungrow-local
   sudo install -m 640 -o root -g sungrow-local /opt/sungrow-local/config.example.json \
        /etc/sungrow-local/config.json
   ```
2. Edit `/etc/sungrow-local/config.json`. Set at least `inverter_host`, and the database
   path for this layout:
   ```json
   "database": "/var/lib/sungrow-local/sungrow-local.db"
   ```
   If only devices in your home network should reach the dashboard, set `http_host` to the
   machine's LAN address instead of `0.0.0.0`.
3. Install the unit, start it and enable it at boot:
   ```sh
   sudo cp /opt/sungrow-local/contrib/sungrow-local.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now sungrow-local
   systemctl status sungrow-local
   ```
4. Logs: `journalctl -u sungrow-local -f`. The program logs one line per event (failed
   logins, refused requests, lost inverter connection), not every request.
5. Optional: `systemd-analyze security sungrow-local` rates the sandbox. If your system is
   older and the unit does not start, remove the line systemd complains about in
   `journalctl`; `ProtectProc` and `ProtectClock` need systemd 247 or newer.

## macOS (launchd)

1. Copy [`contrib/sungrow-local.plist`](../contrib/sungrow-local.plist) to
   `~/Library/LaunchAgents/`, replace `YOURNAME` with your user name and check the paths.
2. Load it:
   ```sh
   launchctl load -w ~/Library/LaunchAgents/sungrow-local.plist
   ```
3. Restart after a change: `launchctl unload` and `launchctl load -w` with the same file.
   The log goes to `~/Library/Logs/sungrow-local.log` and is visible in the Console app.
4. If `config.json` holds a login: `chmod 600 config.json`. sungrow-local warns at start
   when other users could read it.

A launch agent runs while the user is logged in. On a Mac that serves as a small home
server, turn on automatic login for that user.

## Updating

Stop the service, update the code (`git pull`, or a release from the GitHub page), start
it again. The database and your `config.json` stay untouched.

**Updating to 0.2.0 or later:** the configuration is now checked at start, and the
program stops with a message naming the setting if something is wrong (for example a
password shorter than 8 characters, `"false"` in quotes, or a misspelled key). Requests
through a reverse proxy or Cloudflare need their host name in `allowed_hosts`. Existing
installations that keep code, config and database in one folder keep working; the new
systemd layout above is recommended, not required. To move to it, copy your
`config.json` to `/etc/sungrow-local/`, the database to `/var/lib/sungrow-local/` (owned
by `sungrow-local`) and set `database` as shown.
