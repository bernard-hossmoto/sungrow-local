"""The access rules, as a table: configuration, client, headers -> expected status."""
import unittest

from tests.util import sl, headers, basic

OWN = "192.168.1.10"          # this machine's LAN address in the tests
LAN = "192.168.1.20"          # another device in the LAN
PUBLIC = "8.8.8.8"
GOOD = basic("owner", "correct horse")
BAD = basic("owner", "wrong horse!")
HOST = "192.168.1.10:8787"


class FakeAccess(object):
    def verify(self, token):
        return token == "valid-token"


def gate(mode, **extra):
    cfg = dict(sl.DEFAULTS)
    if mode in ("login", "login+lan"):
        cfg["basic_auth"] = "owner:correct horse"
    if mode == "login+lan":
        cfg["lan_without_login"] = True
    cfg.update(extra)
    access = FakeAccess() if cfg.get("cloudflare_access") else None
    return sl.Gate(cfg, access, own={OWN}, hostname="dash")


# mode, client address, request headers, expected status
TABLE = [
    # no login: local addresses only, never through a proxy
    ("open", "127.0.0.1", {}, 200),
    ("open", LAN, {}, 200),
    ("open", OWN, {}, 200),
    ("open", "100.101.1.2", {}, 200),                 # carrier-grade NAT, e.g. Tailscale
    ("open", "fd00::5", {}, 200),
    ("open", PUBLIC, {}, 403),                        # port forward or public host
    ("open", "::ffff:" + PUBLIC, {}, 403),
    ("open", "127.0.0.1", {"X_Forwarded_For": PUBLIC}, 403),
    ("open", "127.0.0.1", {"X_Real_IP": PUBLIC}, 403),
    ("open", "127.0.0.1", {"Forwarded": "for=" + PUBLIC}, 403),
    ("open", "127.0.0.1", {"CF_Connecting_IP": PUBLIC}, 403),
    ("open", "127.0.0.1", {"Via": "1.1 proxy"}, 403),
    # login
    ("login", "127.0.0.1", {}, 401),
    ("login", LAN, {}, 401),
    ("login", LAN, {"Authorization": BAD}, 401),
    ("login", LAN, {"Authorization": GOOD}, 200),
    ("login", PUBLIC, {"Authorization": GOOD}, 200),
    ("login", "127.0.0.1", {"Authorization": GOOD, "X_Forwarded_For": PUBLIC}, 200),
    ("login", LAN, {"Authorization": "Basic \xff\xfe"}, 401),
    ("login", LAN, {"Authorization": "Bearer x"}, 401),
    ("login", LAN, {"Authorization": "Basic !!!"}, 401),
    # login, LAN devices without login
    ("login+lan", LAN, {}, 200),
    ("login+lan", "127.0.0.1", {}, 401),              # proxy on this machine via loopback
    ("login+lan", OWN, {}, 401),                      # proxy on this machine via its LAN address
    ("login+lan", PUBLIC, {}, 401),
    ("login+lan", LAN, {"X_Forwarded_For": PUBLIC}, 401),
    ("login+lan", LAN, {"Via": "1.1 proxy"}, 401),
    ("login+lan", OWN, {"Authorization": GOOD}, 200),
]


class AccessTable(unittest.TestCase):
    def test_table(self):
        for mode, client, hdr, expected in TABLE:
            with self.subTest(mode=mode, client=client, headers=hdr):
                hdr = dict(hdr, Host=HOST)
                self.assertEqual(gate(mode).decide(client, headers(**hdr))[0], expected)

    def test_trusted_proxy_counts_as_proxied_without_headers(self):
        g = gate("open", trusted_proxies=["10.0.0.0/24"])
        self.assertEqual(g.decide("10.0.0.5", headers(Host=HOST))[0], 403)
        self.assertEqual(g.decide("10.0.1.5", headers(Host=HOST))[0], 200)
        g = gate("login+lan", trusted_proxies=["192.168.1.30"])
        self.assertEqual(g.decide("192.168.1.30", headers(Host=HOST))[0], 401)

    def test_cloudflare_access(self):
        ca = {"team_domain": "x.cloudflareaccess.com", "audience": "aud"}
        for mode in ("open", "login", "login+lan"):
            g = gate(mode, cloudflare_access=ca, allowed_hosts=["pv.example.org"])
            h = dict(Host="pv.example.org", CF_Connecting_IP=PUBLIC)
            self.assertEqual(g.decide("127.0.0.1", headers(Cf_Access_Jwt_Assertion="valid-token", **h))[0], 200)
            self.assertEqual(g.decide("127.0.0.1", headers(Cf_Access_Jwt_Assertion="forged", **h))[0],
                             403 if mode == "open" else 401)
            self.assertEqual(g.decide("127.0.0.1", headers(**h))[0], 403 if mode == "open" else 401)

    def test_hashed_login(self):
        import hashlib
        salt = b"0123456789abcdef"
        digest = hashlib.pbkdf2_hmac("sha256", b"correct horse", salt, 10000)
        g = gate("open", basic_auth={"user": "owner", "pbkdf2_sha256": "10000$%s$%s" % (salt.hex(), digest.hex())})
        self.assertEqual(g.decide(LAN, headers(Host=HOST, Authorization=GOOD))[0], 200)
        self.assertEqual(g.decide(LAN, headers(Host=HOST, Authorization=GOOD))[0], 200)      # cached
        self.assertEqual(g.decide(LAN, headers(Host=HOST, Authorization=BAD))[0], 401)
        self.assertEqual(g.decide(LAN, headers(Host=HOST, Authorization=basic("other", "correct horse")))[0], 401)

    def test_made_up_forwarding_headers_do_not_reset_the_counter(self):
        g = gate("login")
        codes = [g.decide(PUBLIC, headers(Host=HOST, Authorization=BAD, X_Real_IP="10.9.9.%d" % i,
                                          X_Forwarded_For="10.8.8.%d" % i))[0] for i in range(12)]
        self.assertEqual(codes[:10], [401] * 10)
        self.assertEqual(codes[10:], [429, 429])

    def test_trusted_proxy_counts_per_forwarded_client(self):
        g = gate("login", trusted_proxies=["10.0.0.5"])
        for _ in range(10):
            g.decide("10.0.0.5", headers(Host=HOST, Authorization=BAD, X_Forwarded_For="8.8.4.4"))
        self.assertEqual(g.decide("10.0.0.5", headers(Host=HOST, Authorization=GOOD, X_Forwarded_For="8.8.4.4"))[0], 429)
        self.assertEqual(g.decide("10.0.0.5", headers(Host=HOST, Authorization=GOOD, X_Forwarded_For="1.1.1.1"))[0], 200)
        self.assertEqual(g.client_key("10.0.0.5", headers(X_Forwarded_For="garbage<script>")), "10.0.0.5")

    def test_many_failures_from_everywhere_slow_all_logins_down(self):
        g = gate("login")
        self.assertEqual(g.decide(LAN, headers(Host=HOST, Authorization=GOOD))[0], 200)     # now cached
        for i in range(30):
            g.decide("8.8.%d.%d" % (i // 200, i % 200), headers(Host=HOST, Authorization=BAD))
        self.assertEqual(g.decide("9.9.9.9", headers(Host=HOST, Authorization=BAD))[0], 429)
        self.assertEqual(g.decide("9.9.9.9", headers(Host=HOST, Authorization=basic("owner", "x" * 9)))[0], 429)
        self.assertEqual(g.decide(LAN, headers(Host=HOST, Authorization=GOOD))[0], 200)     # known good login

    def test_lockout_after_ten_failures(self):
        g = gate("login")
        for _ in range(10):
            self.assertEqual(g.decide(PUBLIC, headers(Host=HOST, Authorization=BAD))[0], 401)
        self.assertEqual(g.decide(PUBLIC, headers(Host=HOST, Authorization=GOOD))[0], 429)
        self.assertEqual(g.decide(LAN, headers(Host=HOST, Authorization=GOOD))[0], 200)       # others still fine
        g.locked = {k: 0 for k in g.locked}                                                 # a minute later
        self.assertEqual(g.decide(PUBLIC, headers(Host=HOST, Authorization=GOOD))[0], 200)


class HostHeader(unittest.TestCase):
    ACCEPTED = ["192.168.1.10:8787", "192.168.1.10", "localhost:8787", "LOCALHOST", "[::1]:8787", "[fe80::1]",
                "dash", "dash:8787", "dash.local:8787", "pv.example.org", "PV.Example.Org.:443"]
    REFUSED = ["attacker.example", "attacker.example:8787", "dash.attacker.example", "192.168.1.10.nip.io",
               "localhost.attacker.example", "", "127.0.0.1:8787@evil.com", "192.168.1.10/x", "dash, evil"]

    def test_hosts(self):
        for mode in ("open", "login", "login+lan"):
            g = gate(mode, allowed_hosts=["pv.example.org"])
            for h in self.ACCEPTED:
                with self.subTest(mode=mode, host=h):
                    self.assertNotIn(g.decide(LAN, headers(Host=h, Authorization=GOOD))[0], (400, 421))
            for h in self.REFUSED:
                with self.subTest(mode=mode, host=h):
                    self.assertEqual(g.decide(LAN, headers(Host=h, Authorization=GOOD))[0], 421)

    def test_valid_token_still_needs_known_host(self):
        g = gate("open", cloudflare_access={"team_domain": "x", "audience": "y"})
        self.assertEqual(g.decide("127.0.0.1", headers(Host="pv.example.org",
                                                         Cf_Access_Jwt_Assertion="valid-token"))[0], 421)

    def test_missing_host(self):
        g = gate("open")
        self.assertEqual(g.decide(LAN, headers(), http10=True)[0], 200)
        self.assertEqual(g.decide(LAN, headers(), http10=False)[0], 400)


if __name__ == "__main__":
    unittest.main()
