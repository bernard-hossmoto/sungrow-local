#!/usr/bin/env python3
"""sungrow-local: a read-only local dashboard for Sungrow SH hybrid inverters.

Reads the inverter directly over Modbus TCP (WiNet-S dongle, no cloud), keeps a
small SQLite history and serves a web dashboard plus a JSON API.

    python3 sungrow_local.py               # run with config.json
    python3 sungrow_local.py --check       # read the inverter once and print the values
    python3 sungrow_local.py --demo        # no inverter needed, simulated data

Standard library only, Python 3.8 or newer. The program never writes a register.
"""
import argparse, base64, hashlib, hmac, http.server, ipaddress, json, math, os, random
import socket, socketserver, sqlite3, struct, sys, threading, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")

DEFAULTS = {
    "inverter_host": "192.168.1.100",
    "inverter_port": 502,
    "unit_id": 1,
    "http_host": "0.0.0.0",
    "http_port": 8787,
    "poll_seconds": 10,          # one full reading every n seconds (minimum 5)
    "request_pause": 0.35,       # pause between Modbus requests, the WiNet-S needs it
    "store_seconds": 60,         # one history row per minute
    "keep_days": 400,
    "database": "sungrow-local.db",
    "plant_name": "My PV system",
    "peak_power_kw": 10.0,
    "feed_in_tariff": 0.08,      # money per exported kWh, 0 hides the revenue
    "currency": "€",
    "language": "en",            # en or de
    "basic_auth": None,          # "user:password" to require a login
    "lan_without_login": False,  # true: direct requests from the LAN skip basic_auth
    "cloudflare_access": None,   # {"team_domain": "...cloudflareaccess.com", "audience": "AUD tag"}
}

# ---------------------------------------------------------------- configuration

def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    elif path and path != os.path.join(HERE, "config.json"):
        sys.exit("config file not found: %s" % path)
    cfg["poll_seconds"] = max(5, int(cfg["poll_seconds"]))
    if "trust_cloudflare_access" in cfg:
        sys.exit("trust_cloudflare_access was replaced by cloudflare_access "
                 "(team_domain and audience), see README")
    ca = cfg.get("cloudflare_access")
    if ca and not (isinstance(ca, dict) and ca.get("team_domain") and ca.get("audience")):
        sys.exit("cloudflare_access needs team_domain and audience, see README")
    if not os.path.isabs(cfg["database"]):
        cfg["database"] = os.path.join(HERE, cfg["database"])
    return cfg

# ---------------------------------------------------------------- Modbus

class Modbus(object):
    """Minimal Modbus TCP client for input registers (function 4).
    The WiNet-S accepts one connection at a time and drops it when requests come
    too quickly, so every reading uses one connection with a pause in between."""

    def __init__(self, host, port, unit, pause):
        self.s = socket.create_connection((host, port), timeout=10)
        self.unit, self.pause, self.tid = unit, pause, 0

    def read(self, address, count):
        self.tid = (self.tid + 1) % 65535
        pdu = struct.pack(">BHH", 4, address, count)
        self.s.sendall(struct.pack(">HHHB", self.tid, 0, len(pdu) + 1, self.unit) + pdu)
        head = self._exact(8)
        length = struct.unpack(">H", head[4:6])[0]
        rest = self._exact(length - 2)
        if head[7] & 0x80:
            raise RuntimeError("Modbus exception %d at register %d" % (rest[0], address))
        raw = rest[1:1 + rest[0]]
        time.sleep(self.pause)
        return [struct.unpack(">H", raw[i:i + 2])[0] for i in range(0, len(raw), 2)]

    def _exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise RuntimeError("connection closed by inverter")
            buf += chunk
        return buf

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


def u32(w, i):
    return w[i] | (w[i + 1] << 16)          # Sungrow: low word first


def s32(w, i):
    v = u32(w, i)
    return v - (1 << 32) if v >= (1 << 31) else v


def s16(v):
    return v - 65536 if v > 32767 else v


def read_inverter(cfg):
    """One complete reading. Addresses are the ones sent on the wire, which is the
    number in the Sungrow documentation minus one. See docs/registers.md."""
    m = Modbus(cfg["inverter_host"], cfg["inverter_port"], cfg["unit_id"], cfg["request_pause"])
    try:
        a = m.read(5016, 2)      # PV power, W
        b = m.read(5213, 2)      # battery power, W, negative = charging
        c = m.read(5600, 2)      # meter power, W, positive = import
        d = m.read(13000, 30)    # daily and total energy, battery state
        e = m.read(13033, 14)    # import, charge, export
    finally:
        m.close()
    return {
        "pv": u32(a, 0), "battery": s32(b, 0), "grid": s32(c, 0),
        "soc": d[22] / 10.0, "battery_voltage": d[19] / 10.0,
        "battery_temp": s16(d[24]) / 10.0, "battery_health": d[23] / 10.0,
        "battery_capacity": e[5] / 10.0,
        "today": {"pv": d[1] / 10.0, "direct": d[16] / 10.0, "discharged": d[25] / 10.0,
                  "imported": e[2] / 10.0, "charged": e[6] / 10.0, "exported": e[11] / 10.0},
        "total": {"pv": u32(d, 2) / 10.0, "direct": u32(d, 17) / 10.0,
                  "discharged": u32(d, 26) / 10.0, "imported": u32(e, 3) / 10.0,
                  "charged": u32(e, 7) / 10.0, "exported": u32(e, 12) / 10.0},
    }

# ---------------------------------------------------------------- demo inverter

class DemoInverter(object):
    """Simulated plant for trying the dashboard without hardware."""

    def __init__(self, cfg):
        self.kw = float(cfg["peak_power_kw"])
        self.cap = 10.0
        self.soc = 35.0
        self.day = time.strftime("%Y-%m-%d")
        self.today = dict.fromkeys(("pv", "direct", "discharged", "imported", "charged", "exported"), 0.0)
        self.total = {"pv": 4180.0, "direct": 1120.0, "discharged": 980.0,
                      "imported": 1460.0, "charged": 1050.0, "exported": 1890.0}
        self.last = None

    @staticmethod
    def sun(t, kw, seed=0):
        lt = time.localtime(t)
        h = lt.tm_hour + lt.tm_min / 60.0
        doy = lt.tm_yday
        length = 12 + 3.8 * math.cos((doy - 172) / 365.0 * 2 * math.pi)
        rise = 12.6 - length / 2
        x = (h - rise) / length
        if x <= 0 or x >= 1:
            return 0.0
        season = 0.72 + 0.28 * math.cos((doy - 172) / 365.0 * 2 * math.pi)
        rnd = random.Random(int(t // 600) + seed)
        clouds = 1.0 - 0.45 * max(0.0, math.sin(t / 2300.0)) * rnd.random()
        return kw * 1000 * 0.82 * season * math.sin(math.pi * x) ** 1.4 * clouds

    @staticmethod
    def load(t):
        lt = time.localtime(t)
        h = lt.tm_hour + lt.tm_min / 60.0
        base = 230 + 110 * math.sin(t / 900.0) ** 2
        if 6.5 < h < 7.2 or 18.2 < h < 19.2:
            base += 1400
        if 12.0 < h < 12.5:
            base += 2000
        return base

    def step(self, t):
        if time.strftime("%Y-%m-%d", time.localtime(t)) != self.day:
            self.day = time.strftime("%Y-%m-%d", time.localtime(t))
            self.today = dict.fromkeys(self.today, 0.0)
        dt = 10.0 if self.last is None else max(1.0, min(600.0, t - self.last))
        self.last = t
        pv, house = self.sun(t, self.kw), self.load(t)
        surplus = pv - house
        if surplus > 0:
            charge = min(surplus, 5000.0, (100 - self.soc) / 100 * self.cap * 1000 * 3600 / dt)
            battery, grid = -charge, -(surplus - charge)
        else:
            discharge = min(-surplus, 5000.0, (self.soc - 5) / 100 * self.cap * 1000 * 3600 / dt)
            battery, grid = discharge, -surplus - discharge
        self.soc = max(5.0, min(100.0, self.soc - battery * dt / 3600 / (self.cap * 1000) * 100))
        kwh = lambda w: max(0.0, w) * dt / 3600000.0
        inc = {"pv": kwh(pv), "direct": kwh(min(pv, house)), "charged": kwh(-battery),
               "discharged": kwh(battery), "imported": kwh(grid), "exported": kwh(-grid)}
        for k, v in inc.items():
            self.today[k] += v
            self.total[k] += v
        return pv, battery, grid

    def read(self):
        pv, battery, grid = self.step(time.time())
        r1 = lambda d: {k: round(v, 1) for k, v in d.items()}
        return {"pv": int(pv), "battery": int(battery), "grid": int(grid),
                "soc": round(self.soc, 1), "battery_voltage": round(204.0 + self.soc * 0.2, 1),
                "battery_temp": 21.5, "battery_health": 100.0, "battery_capacity": self.cap,
                "today": r1(self.today), "total": r1(self.total)}

    def backfill(self, store, days=75):
        """Fill history so that the period views have something to show."""
        now = time.time()
        start = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
        rnd = random.Random(7)
        for back in range(days, 0, -1):
            t0 = start - back * 86400
            day = time.strftime("%Y-%m-%d", time.localtime(t0 + 43200))
            pv = sum(self.sun(t0 + m * 600, self.kw, seed=back) for m in range(144)) * 600 / 3600000
            use = sum(self.load(t0 + m * 600) for m in range(144)) * 600 / 3600000 * rnd.uniform(.9, 1.15)
            direct = min(pv, use) * 0.3
            charged = min(pv - direct, self.cap * 0.9)
            exported = max(0.0, pv - direct - charged)
            discharged = min(charged * 0.92, use - direct)
            imported = max(0.0, use - direct - discharged)
            store.day_row(day, pv, direct, charged, discharged, imported, exported)
        self.last = start
        self.soc = 30.0
        t = start
        while t < now - 60:
            pv, battery, grid = self.step(t)
            store.sample(int(t), pv, battery, grid, self.soc)
            t += 60
        self.last = None

# ---------------------------------------------------------------- storage

class Store(object):
    def __init__(self, path, keep_days):
        self.path, self.keep = path, keep_days
        self.lock = threading.Lock()
        v = self._db()
        v.execute("""CREATE TABLE IF NOT EXISTS samples (ts INTEGER PRIMARY KEY,
            pv INTEGER, battery INTEGER, grid INTEGER, house INTEGER, soc REAL)""")
        v.execute("""CREATE TABLE IF NOT EXISTS days (day TEXT PRIMARY KEY, pv REAL,
            direct REAL, charged REAL, discharged REAL, imported REAL, exported REAL)""")
        v.commit()
        v.close()

    def _db(self):
        v = sqlite3.connect(self.path, timeout=8)
        v.execute("PRAGMA journal_mode=WAL")
        return v

    def sample(self, ts, pv, battery, grid, soc):
        with self.lock:
            v = self._db()
            v.execute("INSERT OR REPLACE INTO samples VALUES (?,?,?,?,?,?)",
                      (ts, int(pv), int(battery), int(grid), int(max(0, pv + battery + grid)), soc))
            v.execute("DELETE FROM samples WHERE ts < ?", (int(time.time()) - self.keep * 86400,))
            v.commit()
            v.close()

    def day_row(self, day, pv, direct, charged, discharged, imported, exported):
        with self.lock:
            v = self._db()
            v.execute("INSERT OR REPLACE INTO days VALUES (?,?,?,?,?,?,?)",
                      (day, round(pv, 2), round(direct, 2), round(charged, 2),
                       round(discharged, 2), round(imported, 2), round(exported, 2)))
            v.commit()
            v.close()

    def day_curve(self, offset=0, step=5):
        lt = time.localtime()
        start = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))) - offset * 86400
        v = self._db()
        try:
            rows = v.execute("SELECT ts, pv, house FROM samples WHERE ts >= ? AND ts < ? ORDER BY ts",
                             (start, start + 86400)).fetchall()
        finally:
            v.close()
        buckets = {}
        for ts, pv, house in rows:
            b = buckets.setdefault(int((ts - start) / 60 / step), [0, 0, 0])
            b[0] += pv or 0
            b[1] += house or 0
            b[2] += 1
        return [[k * step, int(b[0] / b[2]), int(b[1] / b[2])] for k, b in sorted(buckets.items())]

    def days(self):
        v = self._db()
        try:
            return [list(r) for r in v.execute(
                "SELECT day, pv, direct, charged, discharged, imported, exported FROM days ORDER BY day")]
        finally:
            v.close()

# ---------------------------------------------------------------- collector

def derive(w, tariff):
    """Add house load and the energy balance for today and in total."""
    w["house"] = max(0, w["pv"] + w["battery"] + w["grid"])   # register 13007 is not reliable
    for part in ("today", "total"):
        p = w[part]
        p["consumption"] = round(p["direct"] + p["discharged"] + p["imported"], 1)
        p["autarky"] = round((1 - p["imported"] / p["consumption"]) * 100, 1) if p["consumption"] else None
        p["self_consumption"] = round((1 - p["exported"] / p["pv"]) * 100, 1) if p["pv"] else None
        p["revenue"] = round(p["exported"] * tariff, 2)
    return w


class Collector(threading.Thread):
    daemon = True

    def __init__(self, cfg, store, source):
        threading.Thread.__init__(self)
        self.cfg, self.store, self.source = cfg, store, source
        self.lock = threading.Lock()
        self.state = {"ok": False, "error": "no reading yet"}

    def now(self):
        with self.lock:
            return dict(self.state)

    def run(self):
        last_store = 0.0
        while True:
            began = time.time()
            try:
                w = derive(self.source(), float(self.cfg["feed_in_tariff"]))
                w.update(ok=True, error=None, time=time.strftime("%Y-%m-%dT%H:%M:%S"))
                if began - last_store >= self.cfg["store_seconds"]:
                    self.store.sample(int(began), w["pv"], w["battery"], w["grid"], w["soc"])
                    t = w["today"]
                    self.store.day_row(time.strftime("%Y-%m-%d"), t["pv"], t["direct"], t["charged"],
                                       t["discharged"], t["imported"], t["exported"])
                    last_store = began
                with self.lock:
                    self.state = w
            except Exception as e:
                with self.lock:
                    self.state["ok"] = False
                    self.state["error"] = "%s: %s" % (type(e).__name__, e)
                    self.state["time"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            time.sleep(max(1.0, self.cfg["poll_seconds"] - (time.time() - began)))

# ---------------------------------------------------------------- web

def is_lan(addr):
    """Private address of another device. Loopback does not count: a reverse proxy on the
    same machine would otherwise make every visitor look local."""
    try:
        ip = ipaddress.ip_address(addr)
        return ip.is_private and not ip.is_loopback
    except ValueError:
        return False

# ---------------------------------------------------------------- Cloudflare Access

SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def b64url(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class AccessVerifier(object):
    """Verifies the Cf-Access-Jwt-Assertion token that Cloudflare Access adds to every
    request it lets through: RS256 signature against the team's public keys, audience,
    issuer and expiry. Standard library only."""

    def __init__(self, team_domain, audience):
        self.team = team_domain.strip().replace("https://", "").rstrip("/")
        self.audience = set(audience if isinstance(audience, list) else [audience])
        self.keys, self.loaded = {}, 0.0
        self.lock = threading.Lock()

    def fetch_keys(self):
        url = "https://%s/cdn-cgi/access/certs" % self.team
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)
        return {k["kid"]: (int.from_bytes(b64url(k["n"]), "big"), int.from_bytes(b64url(k["e"]), "big"))
                for k in data.get("keys", []) if k.get("kty") == "RSA"}

    def key(self, kid):
        with self.lock:
            now = time.time()
            # refresh hourly, and for an unknown key id at most once a minute
            if now - self.loaded > 3600 or (kid not in self.keys and now - self.loaded > 60):
                try:
                    self.keys, self.loaded = self.fetch_keys(), now
                except Exception:
                    self.loaded = now - 3600 + 60   # retry in a minute, keep old keys
            return self.keys.get(kid)

    def verify(self, token):
        try:
            h64, p64, s64 = token.split(".")
            header, payload = json.loads(b64url(h64)), json.loads(b64url(p64))
            if header.get("alg") != "RS256":
                return False
            key = self.key(header.get("kid"))
            if not key:
                return False
            n, e = key
            size = (n.bit_length() + 7) // 8
            sig = b64url(s64)
            if len(sig) != size:
                return False
            em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(size, "big")
            t = SHA256_DIGEST_INFO + hashlib.sha256((h64 + "." + p64).encode("ascii")).digest()
            if not hmac.compare_digest(em, b"\x00\x01" + b"\xff" * (size - len(t) - 3) + b"\x00" + t):
                return False
            aud = payload.get("aud")
            if not self.audience & set(aud if isinstance(aud, list) else [aud]):
                return False
            if payload.get("iss") != "https://" + self.team:
                return False
            now = time.time()
            return payload.get("exp", 0) > now - 30 and payload.get("nbf", 0) < now + 30
        except Exception:
            return False


def make_handler(cfg, store, collector, access=None):
    public = {k: cfg[k] for k in ("plant_name", "peak_power_kw", "feed_in_tariff", "currency", "language")}

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            http.server.SimpleHTTPRequestHandler.__init__(self, *a, directory=WEB, **kw)

        def log_message(self, *a):
            pass

        def end_headers(self):
            if not self.path.startswith("/api"):
                self.send_header("Cache-Control", "no-cache")
            http.server.SimpleHTTPRequestHandler.end_headers(self)

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            if ctype.startswith("application/json"):
                self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def _proxied(self):
            return any(self.headers.get(h) for h in
                       ("CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP", "Forwarded"))

        def _allowed(self):
            """Rules, in this order:
            1. A valid Cloudflare Access token (if cloudflare_access is set): allowed.
            2. No basic_auth: direct requests are allowed, anything that came through a
               proxy or tunnel is refused, so a forgotten tunnel never exposes the dashboard.
            3. lan_without_login and a direct request from another device in the LAN: allowed.
            4. Otherwise a valid basic_auth login is required."""
            proxied = self._proxied()
            token = self.headers.get("Cf-Access-Jwt-Assertion")
            if access and token and access.verify(token):
                return True
            login = cfg.get("basic_auth")
            if not login:
                if not proxied:
                    return True
                self._send(403, b"Refused: request came through a proxy or tunnel and no login is configured.\n",
                           "text/plain; charset=utf-8")
                return False
            if cfg["lan_without_login"] and not proxied and is_lan(self.client_address[0]):
                return True
            expected = "Basic " + base64.b64encode(login.encode("utf-8")).decode("ascii")
            if hmac.compare_digest(self.headers.get("Authorization", ""), expected):
                return True
            self._send(401, b"", "text/plain", {"WWW-Authenticate": 'Basic realm="sungrow-local"'})
            return False

        def do_GET(self):
            if not self._allowed():
                return
            path, _, query = self.path.partition("?")
            args = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            if path == "/api/now":
                w = collector.now()
                return self._send(200 if w.get("ok") else 503, w)
            if path == "/api/day":
                try:
                    offset = max(0, int(args.get("offset", 0)))
                except ValueError:
                    offset = 0
                return self._send(200, {"step": 5, "points": store.day_curve(offset)})
            if path == "/api/days":
                return self._send(200, {"days": store.days()})
            if path == "/api/config":
                return self._send(200, public)
            if path == "/":
                self.path = "/index.html"
            return http.server.SimpleHTTPRequestHandler.do_GET(self)

    return Handler


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Local dashboard for Sungrow SH hybrid inverters")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--check", action="store_true", help="read the inverter once and print the values")
    ap.add_argument("--demo", action="store_true", help="simulated data, no inverter needed")
    args = ap.parse_args()
    cfg = load_config(args.config)

    if args.check:
        w = derive(read_inverter(cfg), float(cfg["feed_in_tariff"]))
        print(json.dumps(w, indent=2, ensure_ascii=False))
        return

    if args.demo:
        cfg["database"] = os.path.join(HERE, "demo-%d.db" % int(cfg["http_port"]))
        if os.path.exists(cfg["database"]):
            os.remove(cfg["database"])
    store = Store(cfg["database"], int(cfg["keep_days"]))
    if args.demo:
        demo = DemoInverter(cfg)
        demo.backfill(store)
        source = demo.read
    else:
        source = lambda: read_inverter(cfg)

    ca = cfg.get("cloudflare_access")
    access = AccessVerifier(ca["team_domain"], ca["audience"]) if ca else None
    collector = Collector(cfg, store, source)
    collector.start()
    print("sungrow-local on http://%s:%d/  (%s)" % (
        cfg["http_host"], cfg["http_port"], "demo mode" if args.demo else "inverter " + cfg["inverter_host"]))
    print("access: %s%s" % (
        "login required" + (", LAN without login" if cfg["lan_without_login"] else "") if cfg["basic_auth"]
        else "open for direct requests, proxied requests refused",
        ", Cloudflare Access for " + access.team if access else ""))
    Server((cfg["http_host"], int(cfg["http_port"])), make_handler(cfg, store, collector, access)).serve_forever()


if __name__ == "__main__":
    main()
