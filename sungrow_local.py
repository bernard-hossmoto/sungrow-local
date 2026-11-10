#!/usr/bin/env python3
"""sungrow-local: a read-only local dashboard for Sungrow SH hybrid inverters.

Reads the inverter directly over Modbus TCP (WiNet-S dongle, no cloud), keeps a
small SQLite history and serves a web dashboard plus a JSON API.

    python3 sungrow_local.py                  # run with config.json
    python3 sungrow_local.py --check          # read the inverter once and print the values
    python3 sungrow_local.py --demo           # no inverter needed, simulated data
    python3 sungrow_local.py --hash-password  # create a hashed login for config.json

Standard library only, Python 3.8 or newer. The program never writes a register.
"""
import argparse, base64, difflib, getpass, hashlib, hmac, http.server, ipaddress, json, math, os
import random, socket, socketserver, sqlite3, struct, sys, threading, time, urllib.parse, urllib.request

__version__ = "0.2.1"

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
    "basic_auth": None,          # "user:password" or a hashed login, see README
    "lan_without_login": False,  # true: direct requests from other LAN devices skip basic_auth
    "cloudflare_access": None,   # {"team_domain": "...cloudflareaccess.com", "audience": "AUD tag"}
    "allowed_hosts": [],         # host names besides IP addresses, localhost and this machine's name
    "trusted_proxies": [],       # addresses or networks whose connections always count as proxied
}

READ_DEADLINE = 20.0             # seconds for one complete inverter reading
PBKDF2_ITERATIONS = 200000


def log(msg):
    sys.stderr.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    sys.stderr.flush()

# ---------------------------------------------------------------- configuration

def _num(lo=None, hi=None, integer=False):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, int if integer else (int, float)):
            return "must be " + ("a whole number" if integer else "a number")
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            return "must be between %s and %s" % (lo, hi)
    return check


def _text(maxlen=200, forbidden=""):
    def check(v):
        if not isinstance(v, str) or not v.strip():
            return "must be a non-empty string"
        if len(v) > maxlen:
            return "must be at most %d characters" % maxlen
        if any(c in v for c in forbidden):
            return "must not contain any of " + " ".join(forbidden)
    return check


def _bool(v):
    if not isinstance(v, bool):
        return "must be true or false (without quotes)"


def _language(v):
    if v not in ("en", "de"):
        return 'must be "en" or "de"'


def _text_list(v):
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        return "must be a list of strings"


def _networks(v):
    if not isinstance(v, list):
        return "must be a list of addresses or networks"
    for x in v:
        try:
            ipaddress.ip_network(x, strict=False)
        except (TypeError, ValueError):
            return "%r is not an address or network" % (x,)


def _basic_auth(v):
    if v is None:
        return None
    if isinstance(v, str):
        user, sep, pw = v.partition(":")
        if not sep or not user:
            return 'must look like "user:password"'
        if len(pw) < 8:
            return "the password must have at least 8 characters"
        return None
    if isinstance(v, dict):
        if set(v) != {"user", "pbkdf2_sha256"} or not isinstance(v["user"], str) or not v["user"]:
            return 'the hashed form is {"user": "...", "pbkdf2_sha256": "..."}, see --hash-password'
        try:
            it, salt, digest = v["pbkdf2_sha256"].split("$")
            if int(it) < 10000 or not bytes.fromhex(salt) or len(bytes.fromhex(digest)) != 32:
                raise ValueError
        except (AttributeError, ValueError):
            return "pbkdf2_sha256 is not a value created by --hash-password"
        return None
    return 'must be null, "user:password" or a hashed login'


def _cloudflare_access(v):
    if v is None:
        return None
    if not isinstance(v, dict) or set(v) - {"team_domain", "audience"}:
        return "must be null or {\"team_domain\": ..., \"audience\": ...}"
    if not isinstance(v.get("team_domain"), str) or not v["team_domain"].strip():
        return "needs team_domain"
    aud = v.get("audience")
    if not (isinstance(aud, str) and aud) and not (isinstance(aud, list) and aud and
                                                   all(isinstance(a, str) and a for a in aud)):
        return "needs audience (the AUD tag, or a list of AUD tags)"


SCHEMA = {
    "inverter_host": _text(), "inverter_port": _num(1, 65535, True), "unit_id": _num(0, 247, True),
    "http_host": _text(), "http_port": _num(1, 65535, True),
    "poll_seconds": _num(1, 3600), "request_pause": _num(0, 5), "store_seconds": _num(10, 3600, True),
    "keep_days": _num(1, 36500, True), "database": _text(1000), "plant_name": _text(100),
    "peak_power_kw": _num(0.1, 1000), "feed_in_tariff": _num(0, 100), "currency": _text(8, "<>&\"'"),
    "language": _language, "basic_auth": _basic_auth, "lan_without_login": _bool,
    "cloudflare_access": _cloudflare_access, "allowed_hosts": _text_list, "trusted_proxies": _networks,
}


def check_config(cfg):
    """Return a list of problems, one string per bad key. Keys starting with _ are comments."""
    problems = []
    if "trust_cloudflare_access" in cfg:
        problems.append("trust_cloudflare_access was replaced by cloudflare_access "
                        "(team_domain and audience), see README")
    for key in cfg:
        if key.startswith("_") or key == "trust_cloudflare_access":
            continue
        if key not in SCHEMA:
            close = difflib.get_close_matches(key, SCHEMA, 1)
            problems.append("unknown setting %r%s" % (key, ", did you mean %r?" % close[0] if close else ""))
            continue
        err = SCHEMA[key](cfg[key])
        if err:
            problems.append("%s %s" % (key, err))
    return problems


def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except ValueError as e:
                sys.exit("%s is not valid JSON: %s" % (path, e))
        if not isinstance(data, dict):
            sys.exit("%s must contain one JSON object" % path)
        cfg.update(data)
    elif path and path != os.path.join(HERE, "config.json"):
        sys.exit("config file not found: %s" % path)
    problems = check_config(cfg)
    if problems:
        sys.exit("config problem%s in %s:\n  %s" % ("s" if len(problems) > 1 else "", path, "\n  ".join(problems)))
    cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
    cfg["poll_seconds"] = max(5, cfg["poll_seconds"])
    if cfg["basic_auth"] and path and os.path.exists(path) and os.stat(path).st_mode & 0o077:
        log("warning: %s holds a login and can be read by other users, consider chmod 600" % path)
    if not os.path.isabs(cfg["database"]):
        cfg["database"] = os.path.join(HERE, cfg["database"])
    return cfg

# ---------------------------------------------------------------- Modbus

class ModbusError(RuntimeError):
    """The inverter answered, but not with what was asked for."""


class ReadTimeout(Exception):
    """A complete reading took longer than READ_DEADLINE."""


class Implausible(ValueError):
    """A reading contains values that cannot be right."""


class Modbus(object):
    """Minimal Modbus TCP client for input registers (function 4).
    The WiNet-S accepts one connection at a time and drops it when requests come
    too quickly, so every reading uses one connection with a pause in between.
    The whole connection has one deadline, so a peer that answers slowly cannot
    keep the reader busy for ever."""

    def __init__(self, host, port, unit, pause, deadline=None):
        deadline = READ_DEADLINE if deadline is None else deadline
        self.end = time.monotonic() + deadline
        self.s = socket.create_connection((host, port), timeout=min(10.0, deadline))
        self.unit, self.pause, self.tid = unit, pause, 0

    def _left(self):
        left = self.end - time.monotonic()
        if left <= 0:
            raise ReadTimeout("reading took longer than %d s" % READ_DEADLINE)
        return min(10.0, left)

    def read(self, address, count):
        self.tid = self.tid % 65535 + 1
        pdu = struct.pack(">BHH", 4, address, count)
        self.s.settimeout(self._left())
        self.s.sendall(struct.pack(">HHHB", self.tid, 0, len(pdu) + 1, self.unit) + pdu)
        tid, proto, length, unit, func = struct.unpack(">HHHBB", self._exact(8))
        if tid != self.tid or proto != 0 or unit != self.unit:
            raise ModbusError("answer does not belong to the request (tid %d, protocol %d, unit %d)"
                              % (tid, proto, unit))
        if func == 0x84:
            if length != 3:
                raise ModbusError("malformed exception frame")
            raise ModbusError("Modbus exception %d at register %d" % (self._exact(1)[0], address))
        if func != 4:
            raise ModbusError("unexpected function code %d" % func)
        if length != 3 + 2 * count:
            raise ModbusError("unexpected length %d for %d registers" % (length, count))
        rest = self._exact(length - 2)
        if rest[0] != 2 * count:
            raise ModbusError("unexpected byte count %d" % rest[0])
        time.sleep(self.pause)
        return list(struct.unpack(">%dH" % count, rest[1:]))

    def _exact(self, n):
        buf = b""
        while len(buf) < n:
            self.s.settimeout(self._left())
            try:
                chunk = self.s.recv(n - len(buf))
            except socket.timeout:
                if time.monotonic() >= self.end - 0.05:
                    raise ReadTimeout("reading took longer than %d s" % READ_DEADLINE)
                raise
            if not chunk:
                raise ConnectionError("connection closed by inverter")
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


def check_plausible(w, cfg):
    """Reject readings that cannot be right instead of storing them."""
    pv_max = max(2 * float(cfg["peak_power_kw"]), 30.0) * 1000
    bad = []
    if not 0 <= w["pv"] <= pv_max:
        bad.append("pv %s W" % w["pv"])
    if not 0 <= w["soc"] <= 100:
        bad.append("soc %s %%" % w["soc"])
    for k in ("battery", "grid"):
        if abs(w[k]) > 100000:
            bad.append("%s %s W" % (k, w[k]))
    if not -40 <= w["battery_temp"] <= 100:
        bad.append("battery_temp %s °C" % w["battery_temp"])
    for part in ("today", "total"):
        bad += ["%s.%s %s" % (part, k, v) for k, v in w[part].items() if v < 0]
    if bad:
        raise Implausible("implausible reading: " + ", ".join(bad))
    return w

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


def error_code(e):
    """Short, fixed error codes for the API. The full text only goes to the log."""
    if isinstance(e, Implausible):
        return "implausible"
    if isinstance(e, ModbusError):
        return "protocol"
    if isinstance(e, (ReadTimeout, socket.timeout)):
        return "timeout"
    if isinstance(e, OSError):
        return "unreachable"
    return "error"


class Collector(threading.Thread):
    daemon = True

    def __init__(self, cfg, store, source):
        threading.Thread.__init__(self)
        self.cfg, self.store, self.source = cfg, store, source
        self.lock = threading.Lock()
        self.state = {"ok": False, "error": "waiting"}
        self.last_ok = None
        self.stale_after = max(60.0, 3 * cfg["poll_seconds"])
        self.last_logged = None

    def now(self):
        with self.lock:
            s, last = dict(self.state), self.last_ok
        if last is not None:
            s["age"] = int(time.monotonic() - last)
            if s.get("ok") and s["age"] > self.stale_after:
                s["ok"], s["error"] = False, "stale"
        return s

    def once(self, last_store):
        began = time.time()
        try:
            w = derive(check_plausible(self.source(), self.cfg), float(self.cfg["feed_in_tariff"]))
            w.update(ok=True, error=None, time=time.strftime("%Y-%m-%dT%H:%M:%S"))
            if began - last_store >= self.cfg["store_seconds"]:
                self.store.sample(int(began), w["pv"], w["battery"], w["grid"], w["soc"])
                t = w["today"]
                self.store.day_row(time.strftime("%Y-%m-%d"), t["pv"], t["direct"], t["charged"],
                                   t["discharged"], t["imported"], t["exported"])
                last_store = began
            with self.lock:
                self.state, self.last_ok = w, time.monotonic()
            if self.last_logged:
                log("inverter readings are back")
                self.last_logged = None
        except Exception as e:
            text = "%s: %s" % (type(e).__name__, e)
            if text != self.last_logged:
                log("reading failed: " + text)
                self.last_logged = text
            with self.lock:
                self.state["ok"] = False
                self.state["error"] = error_code(e)
                self.state["time"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return began, last_store

    def run(self):
        last_store = 0.0
        while True:
            began, last_store = self.once(last_store)
            time.sleep(max(1.0, self.cfg["poll_seconds"] - (time.time() - began)))

# ---------------------------------------------------------------- Cloudflare Access

SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def b64url(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class AccessVerifier(object):
    """Verifies the Cf-Access-Jwt-Assertion token that Cloudflare Access adds to every
    request it lets through: RS256 signature against the team's public keys, audience,
    issuer and expiry. Standard library only."""

    RETRY = 60.0      # seconds after a failed key fetch, and between fetches for unknown key ids
    REFRESH = 3600.0  # regular refresh of the keys

    def __init__(self, team_domain, audience):
        self.team = team_domain.strip().replace("https://", "").rstrip("/")
        self.audience = set(audience if isinstance(audience, list) else [audience])
        self.keys, self.loaded, self.last_try, self.next_try = {}, 0.0, 0.0, 0.0
        self.fetching = False
        self.lock = threading.Lock()

    def fetch_keys(self):
        url = "https://%s/cdn-cgi/access/certs" % self.team
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read(65536))
        return {k["kid"]: (int.from_bytes(b64url(k["n"]), "big"), int.from_bytes(b64url(k["e"]), "big"))
                for k in data.get("keys", []) if k.get("kty") == "RSA"}

    def key(self, kid):
        """Key for kid. Refresh hourly, for an unknown kid at most once a minute, and wait
        a minute after a failed fetch. The lock is never held during the network call, so
        requests with known keys are not held up by a slow fetch."""
        now = time.time()
        with self.lock:
            due = now - self.loaded > self.REFRESH or (kid not in self.keys and now - self.last_try > self.RETRY)
            go = due and not self.fetching and now >= self.next_try
            if go:
                self.fetching, self.last_try = True, now
        if go:
            try:
                keys = self.fetch_keys()
                with self.lock:
                    self.keys, self.loaded, self.next_try = keys, time.time(), 0.0
            except Exception as e:
                with self.lock:
                    self.next_try = time.time() + self.RETRY      # keep the old keys
                log("cloudflare access: could not load keys from %s: %s" % (self.team, type(e).__name__))
            finally:
                with self.lock:
                    self.fetching = False
        with self.lock:
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

# ---------------------------------------------------------------- access rules

FORWARD_HEADERS = ("CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP", "Forwarded", "Via")


def parse_ip(addr):
    try:
        ip = ipaddress.ip_address(str(addr).split("%")[0])
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip


def is_local(addr):
    """Loopback, private, link-local or carrier-grade NAT (VPNs such as Tailscale)."""
    ip = parse_ip(addr)
    return ip is not None and not ip.is_global


def is_lan(addr):
    """Local address of another device. Loopback does not count: a reverse proxy on the
    same machine would otherwise make every visitor look local."""
    ip = parse_ip(addr)
    return ip is not None and not ip.is_global and not ip.is_loopback


def own_addresses(http_host=None):
    """Addresses of this machine, used so that a proxy on this machine never counts as LAN."""
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            found.add(info[4][0])
    except Exception:
        pass
    for family, target in ((socket.AF_INET, "192.0.2.1"), (socket.AF_INET6, "2001:db8::1")):
        try:
            s = socket.socket(family, socket.SOCK_DGRAM)
            try:
                s.connect((target, 9))           # sends nothing, only picks the outgoing address
                found.add(s.getsockname()[0])
            finally:
                s.close()
        except Exception:
            pass
    if http_host and http_host not in ("0.0.0.0", "::", ""):
        found.add(http_host)
    return {str(ip) for ip in map(parse_ip, found) if ip is not None and not ip.is_loopback}


def split_host(value):
    """Host part of a Host header, lower case, without port and brackets."""
    v = value.strip().lower()
    if any(c in v for c in "@/\\ \t,"):
        return ""                                # userinfo, paths or lists are never a valid Host
    if v.startswith("["):
        return v[1:v.find("]")] if "]" in v else v
    if v.count(":") == 1:
        v = v.rsplit(":", 1)[0]
    return v.rstrip(".")


class Gate(object):
    """Decides about every request before it is handled. See SECURITY.md for the rules."""

    def __init__(self, cfg, access=None, own=None, hostname=None):
        self.cfg, self.access = cfg, access
        self.login = cfg.get("basic_auth")
        name = (hostname or socket.gethostname()).lower().rstrip(".")
        short = name.split(".")[0]
        self.names = {"localhost", name, short, short + ".local"}
        self.names |= {h.lower().rstrip(".") for h in cfg.get("allowed_hosts") or []}
        self.proxies = [ipaddress.ip_network(n, strict=False) for n in cfg.get("trusted_proxies") or []]
        self.refresh_own = own is None
        self.own = set(own) if own is not None else own_addresses(cfg.get("http_host"))
        self.own_loaded, self.own_refreshing = time.time(), False
        self.lock = threading.Lock()
        self.ok_cache = {}          # sha256 of good Authorization headers
        self.failures = {}          # client key -> [timestamps of failed logins]
        self.locked = {}            # client key -> locked until
        self.recent = []            # times of failed logins from all clients
        self.all_locked = 0.0       # all logins without a cached good one are refused until then
        self.noted = {}             # log key -> last time logged

    # -- helpers

    def host_ok(self, host, http10):
        if host is None:
            return http10
        h = split_host(host)
        return parse_ip(h) is not None or h in self.names

    def proxied(self, client_ip, headers):
        if any(headers.get(h) for h in FORWARD_HEADERS):
            return True
        ip = parse_ip(client_ip)
        return ip is not None and any(ip in n for n in self.proxies)

    def _refresh_own(self):
        try:
            self.own = own_addresses(self.cfg.get("http_host")) | self.own
        finally:
            self.own_loaded, self.own_refreshing = time.time(), False

    def own_address(self, client_ip):
        if self.refresh_own and not self.own_refreshing and time.time() - self.own_loaded > 300:
            self.own_refreshing = True       # refresh in the background, keep the known ones
            threading.Thread(target=self._refresh_own, daemon=True).start()
        ip = parse_ip(client_ip)
        return ip is not None and str(ip) in self.own

    def speaks_for_others(self, client_ip):
        """Only a proxy on this machine or in trusted_proxies may name the real client."""
        ip = parse_ip(client_ip)
        if ip is None:
            return False
        return ip.is_loopback or str(ip) in self.own or any(ip in n for n in self.proxies)

    def client_key(self, client_ip, headers):
        """Key for the lockout and the log. The forwarded address counts only when the
        connection comes from a proxy that may speak for others, and only if it is one
        clean IP address, so a client cannot get a fresh counter by inventing headers."""
        if not self.speaks_for_others(client_ip):
            return str(client_ip)
        fwd = headers.get("CF-Connecting-IP") or headers.get("X-Real-IP") or \
            (headers.get("X-Forwarded-For") or "").split(",")[-1]
        fwd = (fwd or "").strip()[:45]
        ip = parse_ip(fwd) if fwd else None
        return "%s|%s" % (client_ip, ip) if ip is not None else str(client_ip)

    def cached(self, header):
        if not header:
            return False
        fp = hashlib.sha256(header.encode("latin-1", "replace")).digest()
        with self.lock:
            return fp in self.ok_cache

    def login_ok(self, header):
        if not header or not header.startswith("Basic "):
            return False
        raw_header = header.encode("latin-1", "replace")
        fp = hashlib.sha256(raw_header).digest()
        with self.lock:
            if fp in self.ok_cache:
                return True
        try:
            given = base64.b64decode(header[6:].strip(), validate=True)
        except (ValueError, TypeError):
            return False
        login = self.login
        if isinstance(login, str):
            ok = hmac.compare_digest(given, login.encode("utf-8"))
        else:
            user, _, pw = given.partition(b":")
            it, salt, digest = login["pbkdf2_sha256"].split("$")
            calc = hashlib.pbkdf2_hmac("sha256", pw, bytes.fromhex(salt), int(it))
            ok = hmac.compare_digest(user, login["user"].encode("utf-8")) & hmac.compare_digest(
                calc, bytes.fromhex(digest))
        if ok:
            with self.lock:
                if len(self.ok_cache) > 64:
                    self.ok_cache.clear()
                self.ok_cache[fp] = True
        return ok

    def is_locked(self, key):
        with self.lock:
            until = self.locked.get(key)
            if until and until > time.time():
                return True
            self.locked.pop(key, None)
            return False

    def failed(self, key):
        now = time.time()
        with self.lock:
            self.recent = [t for t in self.recent if t > now - 60] + [now]
            if len(self.recent) >= 30:              # many failures from everywhere: slow all down
                self.all_locked = now + 60
                self.recent = []
            hits = [t for t in self.failures.pop(key, []) if t > now - 300] + [now]
            self.failures[key] = hits
            while len(self.failures) > 1000:
                self.failures.pop(next(iter(self.failures)))
            if len(hits) >= 10:
                self.locked[key] = now + 60
                self.failures.pop(key, None)
                while len(self.locked) > 1000:
                    self.locked.pop(next(iter(self.locked)))

    def note(self, key, msg):
        """Log one line, at most one per key and 10 seconds."""
        now = time.time()
        with self.lock:
            if now - self.noted.get(key, 0) < 10:
                return
            self.noted[key] = now
            if len(self.noted) > 1000:
                self.noted.clear()
        log(msg)

    # -- the decision

    def decide(self, client_ip, headers, http10=False):
        """Return (status, reason). 200 means the request may be handled. In this order:
        0. The Host header must be an IP address, localhost, this machine's name or a name
           in allowed_hosts (protection against DNS rebinding).
        1. A valid Cloudflare Access token (if cloudflare_access is set) lets the request in.
        2. Without basic_auth only direct requests from local addresses are allowed. Anything
           that came through a proxy (forwarding header present, or the connection comes from
           a trusted_proxies address) or from a public address is refused.
        3. lan_without_login lets in direct requests from other devices in the LAN, never from
           this machine itself, loopback or a proxy.
        4. Otherwise a valid basic_auth login is required. Ten failures within five minutes
           block that client for a minute, thirty failures within a minute from all clients
           together block every login that is not already known to be good."""
        if not self.host_ok(headers.get("Host"), http10):
            return (400, "missing Host header") if headers.get("Host") is None else (421, "unknown host name")
        proxied = self.proxied(client_ip, headers)
        token = headers.get("Cf-Access-Jwt-Assertion")
        if self.access and token and self.access.verify(token):
            return 200, "cloudflare access"
        if not self.login:
            if proxied:
                return 403, "came through a proxy or tunnel and no login is configured"
            if not is_local(client_ip):
                return 403, "public address and no login is configured"
            return 200, "local request"
        if self.cfg.get("lan_without_login") and not proxied and is_lan(client_ip) \
                and not self.own_address(client_ip):
            return 200, "lan without login"
        key = self.client_key(client_ip, headers)
        auth = headers.get("Authorization")
        if self.is_locked(key) or (self.all_locked > time.time() and not self.cached(auth)):
            return 429, "too many failed logins"
        if self.login_ok(auth):
            return 200, "login"
        if auth:
            self.failed(key)
            return 401, "wrong login"
        return 401, "login required"

# ---------------------------------------------------------------- web

CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

DENY_TEXT = {
    400: b"Bad request: no Host header.\n",
    403: b"Refused: no login is configured and the request came from a public address or through a proxy.\n",
    421: b"Unknown host name. Add it to allowed_hosts in config.json if this is your dashboard.\n",
    429: b"Too many failed logins, try again in a minute.\n",
}


def make_handler(cfg, store, collector, gate):
    public = {k: cfg[k] for k in ("plant_name", "peak_power_kw", "feed_in_tariff", "currency", "language")}
    keep_days = int(cfg["keep_days"])

    class Handler(http.server.SimpleHTTPRequestHandler):
        server_version = "sungrow-local"
        sys_version = ""
        timeout = 15                    # seconds for a client to send its whole request

        def version_string(self):
            return self.server_version

        def setup(self):
            http.server.SimpleHTTPRequestHandler.setup(self)
            # one deadline for request line and headers together: a client that sends one
            # byte every few seconds would otherwise never hit the per-read timeout
            self.deadline = threading.Timer(self.timeout, self._expire)
            self.deadline.daemon = True
            self.deadline.start()

        def _expire(self):
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        def finish(self):
            self.deadline.cancel()
            http.server.SimpleHTTPRequestHandler.finish(self)

        def __init__(self, *a, **kw):
            http.server.SimpleHTTPRequestHandler.__init__(self, *a, directory=WEB, **kw)

        def log_message(self, *a):
            pass

        def end_headers(self):
            if not getattr(self, "path", "").startswith("/api"):
                self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
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
            if self.command != "HEAD":
                self.wfile.write(raw)

        # every request, whatever the method, passes through here before it is handled
        def parse_request(self):
            ok = http.server.SimpleHTTPRequestHandler.parse_request(self)
            self.deadline.cancel()          # the request is in, the deadline has done its job
            if not ok:
                return False
            client = self.client_address[0]
            try:
                status, reason = gate.decide(client, self.headers, self.request_version == "HTTP/1.0")
            except Exception as e:
                log("access check failed: %s" % type(e).__name__)
                status, reason = 500, "error"
            if status == 200:
                return True
            self.close_connection = True
            if status == 401:
                if reason == "wrong login":
                    gate.note("401" + client, "failed login from %s" % gate.client_key(client, self.headers))
                self._send(401, b"", "text/plain", {"WWW-Authenticate": 'Basic realm="sungrow-local"'})
            elif status == 429:
                gate.note("429" + client, "too many failed logins from %s, blocked for a minute"
                          % gate.client_key(client, self.headers))
                self._send(429, DENY_TEXT[429], "text/plain; charset=utf-8", {"Retry-After": "60"})
            else:
                if status in (403, 421):
                    gate.note("%d%s" % (status, client), "refused %s: %s" % (client, reason))
                self._send(status, DENY_TEXT.get(status, b"Error.\n"), "text/plain; charset=utf-8")
            return False

        def list_directory(self, path):
            self.send_error(404)

        def _handle(self):
            try:
                parts = urllib.parse.urlsplit(self.path)
                path, args = parts.path, urllib.parse.parse_qs(parts.query)
                if path == "/api/now":
                    w = collector.now()
                    return self._send(200 if w.get("ok") else 503, w)
                if path == "/api/day":
                    try:
                        offset = min(keep_days, max(0, int(args.get("offset", ["0"])[0])))
                    except ValueError:
                        offset = 0
                    return self._send(200, {"step": 5, "points": store.day_curve(offset)})
                if path == "/api/days":
                    return self._send(200, {"days": store.days()})
                if path == "/api/config":
                    return self._send(200, public)
                if path.startswith("/api/"):
                    return self._send(404, {"error": "not found"})
                if path == "/":
                    self.path = "/index.html"
                if self.command == "HEAD":
                    return http.server.SimpleHTTPRequestHandler.do_HEAD(self)
                return http.server.SimpleHTTPRequestHandler.do_GET(self)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                log("error %s while handling %s" % (type(e).__name__, self.path.split("?")[0][:100]))
                try:
                    self._send(500, b"Internal error.\n", "text/plain; charset=utf-8")
                except Exception:
                    pass

        do_GET = _handle
        do_HEAD = _handle

    return Handler


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16
    max_connections = 32
    per_client = 8                  # so that one device cannot take every slot

    def __init__(self, *a, **kw):
        self.slots = threading.BoundedSemaphore(self.max_connections)
        self.counts, self.count_lock = {}, threading.Lock()
        http.server.HTTPServer.__init__(self, *a, **kw)

    def _leave(self, addr):
        with self.count_lock:
            n = self.counts.get(addr, 1) - 1
            if n > 0:
                self.counts[addr] = n
            else:
                self.counts.pop(addr, None)

    def process_request(self, request, client_address):
        addr = client_address[0]
        with self.count_lock:
            busy = self.counts.get(addr, 0) >= self.per_client
            if not busy:
                self.counts[addr] = self.counts.get(addr, 0) + 1
        if busy:
            self.shutdown_request(request)       # this client already has its share
            return
        if not self.slots.acquire(blocking=False):
            self._leave(addr)
            self.shutdown_request(request)       # all slots busy: close at once
            return
        try:
            socketserver.ThreadingMixIn.process_request(self, request, client_address)
        except Exception:
            self.slots.release()
            self._leave(addr)
            raise

    def process_request_thread(self, request, client_address):
        try:
            socketserver.ThreadingMixIn.process_request_thread(self, request, client_address)
        finally:
            self.slots.release()
            self._leave(client_address[0])

    def handle_error(self, request, client_address):
        e = sys.exc_info()[1]
        if not isinstance(e, (ConnectionError, socket.timeout)):
            log("connection from %s ended with %s" % (client_address[0], type(e).__name__))

# ---------------------------------------------------------------- main

def hash_password():
    user = input("user name: ").strip()
    pw = getpass.getpass("password (at least 8 characters): ")
    if len(pw) < 8 or not user:
        sys.exit("user name missing or password too short")
    if getpass.getpass("again: ") != pw:
        sys.exit("the passwords do not match")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    value = {"user": user, "pbkdf2_sha256": "%d$%s$%s" % (PBKDF2_ITERATIONS, salt.hex(), digest.hex())}
    print('put this into config.json:\n\n  "basic_auth": %s\n' % json.dumps(value))


def main():
    ap = argparse.ArgumentParser(description="Local dashboard for Sungrow SH hybrid inverters")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--check", action="store_true", help="read the inverter once and print the values")
    ap.add_argument("--demo", action="store_true", help="simulated data, no inverter needed")
    ap.add_argument("--hash-password", action="store_true", help="create a hashed login for config.json")
    args = ap.parse_args()
    if args.hash_password:
        return hash_password()
    cfg = load_config(args.config)

    if args.check:
        w = read_inverter(cfg)
        try:
            check_plausible(w, cfg)
        except Implausible as e:
            log("warning: %s" % e)
        print(json.dumps(derive(w, float(cfg["feed_in_tariff"])), indent=2, ensure_ascii=False))
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
    if access:
        threading.Thread(target=access.key, args=(None,), daemon=True).start()   # load the keys early
    gate = Gate(cfg, access)
    collector = Collector(cfg, store, source)
    collector.start()
    print("sungrow-local %s on http://%s:%d/  (%s)" % (__version__,
        cfg["http_host"], cfg["http_port"], "demo mode" if args.demo else "inverter " + cfg["inverter_host"]))
    print("access: %s%s" % (
        "login required" + (", LAN devices without login" if cfg["lan_without_login"] else "") if cfg["basic_auth"]
        else "no login, local addresses only, proxied requests refused",
        ", Cloudflare Access for " + access.team if access else ""))
    wildcard = cfg["http_host"] in ("0.0.0.0", "::")
    if not cfg["basic_auth"] and wildcard:
        print("note: without a login every device in your network that reaches port %d can read the "
              "dashboard" % cfg["http_port"])
    bound = parse_ip(cfg["http_host"])
    loopback = cfg["http_host"] == "localhost" or (bound is not None and bound.is_loopback)
    if cfg["basic_auth"] and not loopback:
        print("note: the login travels unencrypted over plain HTTP, put HTTPS in front for access from outside")
    if (access or cfg["trusted_proxies"]) and not cfg["allowed_hosts"]:
        print("note: requests through a proxy or Cloudflare carry your public host name, "
              "add it to allowed_hosts")
    sys.stdout.flush()
    Server((cfg["http_host"], int(cfg["http_port"])), make_handler(cfg, store, collector, gate)).serve_forever()


if __name__ == "__main__":
    main()
