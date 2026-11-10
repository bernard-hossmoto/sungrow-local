"""Helpers shared by the tests."""
import base64, email.message, hashlib, json, os, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sungrow_local as sl                      # noqa: E402
from tests import keys                          # noqa: E402

TEAM = "example.cloudflareaccess.com"
AUD = "a" * 64


def headers(**kw):
    """Request headers like http.server builds them. Keyword names use _ for -."""
    m = email.message.Message()
    for k, v in kw.items():
        if v is not None:
            m[k.replace("_", "-")] = v
    return m


def basic(user, password):
    return "Basic " + base64.b64encode(("%s:%s" % (user, password)).encode("utf-8")).decode("ascii")


def b64(data):
    raw = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def sign(header, payload, n=keys.N1, d=keys.D1):
    """RS256 token signed with a test key, built by hand like Cloudflare does."""
    h64, p64 = b64(header), b64(payload)
    size = (n.bit_length() + 7) // 8
    t = sl.SHA256_DIGEST_INFO + hashlib.sha256((h64 + "." + p64).encode("ascii")).digest()
    em = b"\x00\x01" + b"\xff" * (size - len(t) - 3) + b"\x00" + t
    sig = pow(int.from_bytes(em, "big"), d, n).to_bytes(size, "big")
    return h64 + "." + p64 + "." + b64(sig)


def claims(**kw):
    now = time.time()
    c = {"aud": [AUD], "iss": "https://" + TEAM, "exp": now + 600, "nbf": now - 10, "email": "owner@example.org"}
    c.update(kw)
    return {k: v for k, v in c.items() if v is not None}


def verifier(fetch=None):
    v = sl.AccessVerifier(TEAM, AUD)
    v.fetch_keys = fetch or (lambda: {"k1": (keys.N1, keys.E)})
    return v


def config(**kw):
    cfg = dict(sl.DEFAULTS)
    cfg.update(kw)
    return cfg


class FakeCollector(object):
    def __init__(self, state=None):
        self.state = state or {"ok": True, "pv": 1}

    def now(self):
        return dict(self.state)


class RunningServer(object):
    """A real sungrow-local web server on a free port, with a temporary database."""

    def __init__(self, **kw):
        self.dir = tempfile.TemporaryDirectory()
        self.cfg = config(database=os.path.join(self.dir.name, "t.db"), http_host="127.0.0.1", **kw)
        self.store = sl.Store(self.cfg["database"], self.cfg["keep_days"])
        gate = sl.Gate(self.cfg, own=set(), hostname="testhost")
        handler = sl.make_handler(self.cfg, self.store, FakeCollector(), gate)
        handler.timeout = 2                       # the real value is 15 s, the tests need not wait that long
        self.server = sl.Server(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.dir.cleanup()
