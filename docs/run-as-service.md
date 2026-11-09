# Starting sungrow-local automatically

Put the project in a fixed place first, for example `/opt/sungrow-local` on Linux or
`~/sungrow-local` on a Mac, with your `config.json` next to `sungrow_local.py`.

## Linux and Raspberry Pi (systemd)

1. Copy [`contrib/sungrow-local.service`](../contrib/sungrow-local.service) to
   `/etc/systemd/system/` and adjust `User` and the paths if needed.
2. Start it and enable it at boot:
   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable --now sungrow-local
   systemctl status sungrow-local
   ```
3. Logs: `journalctl -u sungrow-local -f`

## macOS (launchd)

1. Copy [`contrib/sungrow-local.plist`](../contrib/sungrow-local.plist) to
   `~/Library/LaunchAgents/`, replace `YOURNAME` with your user name and check the paths.
2. Load it:
   ```sh
   launchctl load -w ~/Library/LaunchAgents/sungrow-local.plist
   ```
3. Restart after a change: `launchctl unload` and `launchctl load -w` with the same file.
   The log goes to `sungrow-local.log` in the project folder.

A launch agent runs while the user is logged in. On a Mac that serves as a small home
server, turn on automatic login for that user.

## Updating

Stop the service, replace the files (or `git pull`), start it again. The database and your
`config.json` stay untouched.
