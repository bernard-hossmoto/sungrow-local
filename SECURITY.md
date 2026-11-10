# Security

## Reporting a problem

Please do not open a public issue for security problems. Use GitHub's private
vulnerability reporting instead: **Security** tab, **Report a vulnerability**. It is
switched on for this repository.

## How sungrow-local is built

- **Read-only towards the inverter.** It only sends Modbus function code 4 (read input
  registers). It never writes a register and cannot change a setting. Answers from the
  dongle are checked (transaction, unit, function code, length), a whole reading has a
  deadline, and implausible values are not stored.
- **No HTTPS of its own.** The built-in web server speaks plain HTTP and is meant for the
  home network. For access from outside put it behind a VPN, a reverse proxy with HTTPS or
  Cloudflare Access.
- **Standard library only.** No third-party packages, nothing to keep patched besides
  Python itself.
- **Tests** for the access rules, the token verifier, the Modbus client and the web server
  run on every push (Python 3.8 and the current release).

## Threat model

- **Trusted:** the owner, `config.json`, the machine sungrow-local runs on.
- **Not trusted:** every device in the LAN that has no login, everything that arrives
  through a proxy or tunnel, web pages that a browser in the LAN opens, and the answers of
  the WiNet-S dongle.
- **Out of scope:** the Modbus port itself, the dongle's web interface and its firmware
  (see below), the security of your router, your reverse proxy and your VPN.

## What sungrow-local does not protect

sungrow-local needs Modbus TCP on port 502 of the WiNet-S. That port has no login.
**Everything that can reach it can read the inverter and should be assumed able to write
settings**, no matter what sungrow-local does. The dongle's own web interface stays
reachable as well, and older dongle firmware has published vulnerabilities. How to shield
the dongle: [docs/block-cloud.md, Lock down the WiNet-S](docs/block-cloud.md#lock-down-the-winet-s).

## How requests are checked

Every request, whatever the method, passes one check before it is handled. In this order:

0. **Host name.** The `Host` header must be an IP address, `localhost`, this machine's own
   name (also with `.local`) or a name listed in `allowed_hosts`. Otherwise the answer is
   421. This stops DNS rebinding, where a web page opened in your home network re-points
   its own name to your dashboard and reads it through your browser.
1. **Cloudflare Access.** If `cloudflare_access` is set and the request carries a
   `Cf-Access-Jwt-Assertion` token, the token is verified (RS256 signature against the
   team's public keys from `https://<team_domain>/cdn-cgi/access/certs`, audience,
   issuer, expiry). A valid token lets the request in.
2. **No login configured.** Only direct requests from local addresses (loopback, private,
   link-local, carrier-grade NAT as used by some VPNs) are allowed. Refused with 403:
   requests that came through a proxy or tunnel (`X-Forwarded-For`, `X-Real-IP`,
   `Forwarded`, `CF-Connecting-IP` or `Via` present, or the connection comes from an
   address in `trusted_proxies`), and requests from public addresses (port forward, host
   with a public address).
3. **`lan_without_login`.** With `basic_auth` set, a direct request from *another* device
   in the LAN is allowed without login. Requests from this machine itself (loopback or one
   of its own addresses), through a proxy or from `trusted_proxies` never count as LAN.
4. **Login.** Otherwise a valid `basic_auth` login is required, compared in constant time
   (or checked against a PBKDF2 hash). Failed logins are logged. Ten failures within five
   minutes block that client for a minute (429). A forwarded client address counts only
   when the connection comes from this machine or from `trusted_proxies`. Thirty failures
   within a minute from all clients together block every login that is not already known
   to be good, for a minute.

What these rules cannot see: a proxy that adds none of the forwarding headers and connects
from another machine in the LAN looks like a direct request from that machine. Put such a
proxy into `trusted_proxies`. The same applies to containers with user-mode networking or
any source NAT in front of sungrow-local, where every client appears with one private
address: do not use `lan_without_login` there.

Every response carries `Content-Security-Policy`, `X-Content-Type-Options`,
`X-Frame-Options` and `Referrer-Policy` headers. The server does not reveal its Python
version, a request must be complete within 15 seconds (however slowly it is sent), and at
most 32 connections are handled at the same time, at most 8 from one address.

## Fixed in this repository

- **Login bypass behind a local reverse proxy** (fixed 2026-11-09). The first version
  exempted all private addresses including loopback from the login by default, so a
  reverse proxy on the same machine let every visitor in. `lan_without_login` is now off by
  default and never applies to loopback or proxied requests.
- **Unverified Cloudflare Access header** (fixed 2026-11-09). The first version trusted the
  presence of the Access header without checking its signature. The option
  `trust_cloudflare_access` was replaced by `cloudflare_access`, which verifies the token.

Found in an external security review on 2026-11-10, fixed in version 0.2.0:

- **DNS rebinding** (medium). No `Host` check, so a web page opened in the LAN could read
  the API through the visitor's browser. Fixed by rule 0.
- **Proxy detection relied on optional headers** (medium). Without forwarding headers a
  proxied request looked direct; without a login a port forward exposed the dashboard, and
  `lan_without_login` skipped the login behind a proxy on the same machine that connected
  through its LAN address. Fixed by rules 2 and 3 and `trusted_proxies`.
- **HEAD requests skipped the check** (low). The check now runs for every method.
- **Stale or malformed inverter data reported as current** (medium). Reading deadline,
  validated Modbus frames, plausibility checks, `age` in `/api/now` and `stale` after
  three missed readings.
- **Key fetch back-off did not work** (low to medium, only with `cloudflare_access`).
  After a failed fetch every request with an unknown key id started a new fetch under a
  lock. Now one attempt per minute, without holding the lock.
- **No socket timeout and no connection limit** (low to medium). Idle connections held a
  thread each without a login.
- **Unhandled exceptions from request input** (low). A non-ASCII `Authorization` header
  or a huge `offset` raised and wrote tracebacks to the log.
- **Hardening:** configuration checked at start, optional hashed password, logging and
  lockout for failed logins, security headers, escaped currency symbol, short error codes
  in the API, sandboxed systemd unit with its own user, documentation on shielding the
  Modbus port.

Found in a follow-up review of 0.2.0 on 2026-11-10, fixed in version 0.2.1:

- **Lockout bypass with made-up forwarding headers** (low to medium). The lockout key
  included `X-Real-IP` and similar headers from any client, so a new value per request
  gave a fresh counter. Forwarded addresses now count only from this machine or
  `trusted_proxies`, and a global limit bounds failed logins (and the PBKDF2 load).
- **Slowly sending clients** (low). The 15 second timeout applied per read, so 32 clients
  sending one byte every few seconds held every slot. The request now has one deadline,
  and one address gets at most 8 of the 32 connections.
- `Host` values with `@`, `/`, spaces or commas are refused.
