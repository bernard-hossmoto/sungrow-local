# Security

## Reporting a problem

Please do not open a public issue for security problems. Use GitHub's private
vulnerability reporting instead: **Security** tab, **Report a vulnerability**.

## How sungrow-local is built

- **Read-only towards the inverter.** It only sends Modbus function code 4 (read input
  registers). It never writes a register and cannot change a setting.
- **No HTTPS of its own.** The built-in web server speaks plain HTTP and is meant for the
  home network. For access from outside put it behind a VPN, a reverse proxy with HTTPS or
  Cloudflare Access.
- **Standard library only.** No third-party packages, nothing to keep patched besides
  Python itself.

## How requests are checked

In this order:

1. If `cloudflare_access` is set and the request carries a `Cf-Access-Jwt-Assertion`
   token, the token is verified (RS256 signature against the team's public keys from
   `https://<team_domain>/cdn-cgi/access/certs`, audience, issuer, expiry). A valid token
   lets the request in.
2. Without `basic_auth`, direct requests are allowed. Requests that came through a proxy or
   tunnel (`X-Forwarded-For`, `X-Real-IP`, `Forwarded` or `CF-Connecting-IP` present) are
   refused with 403.
3. With `basic_auth` and `lan_without_login`, a direct request from another private
   address is allowed. Loopback and proxied requests never count as LAN.
4. Otherwise a valid login is required (compared in constant time), or the answer is 401.

## Fixed in this repository

- **Login bypass behind a local reverse proxy** (fixed 2026-11-09). The first version
  exempted all private addresses including loopback from the login by default, so a
  reverse proxy on the same machine let every visitor in. `lan_without_login` is now off by
  default and never applies to loopback or proxied requests.
- **Unverified Cloudflare Access header** (fixed 2026-11-09). The first version trusted the
  presence of the Access header without checking its signature. The option
  `trust_cloudflare_access` was replaced by `cloudflare_access`, which verifies the token.
