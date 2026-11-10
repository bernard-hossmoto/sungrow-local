"""The real web server: methods, headers, robustness."""
import http.client, socket, threading, time, unittest

from tests.util import sl, RunningServer, basic


def request(port, method, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        c.request(method, path, headers=headers or {})
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        c.close()


class Open(unittest.TestCase):
    def setUp(self):
        self.s = RunningServer()
        self.p = self.s.port

    def tearDown(self):
        self.s.close()

    def test_pages_and_api(self):
        for path in ("/", "/index.html", "/app.js", "/api/now", "/api/day", "/api/days", "/api/config"):
            with self.subTest(path):
                self.assertEqual(request(self.p, "GET", path)[0], 200)

    def test_security_headers(self):
        for path in ("/", "/app.js", "/api/now", "/nothing-here"):
            status, h, _ = request(self.p, "GET", path)
            with self.subTest(path):
                self.assertEqual(h.get("X-Content-Type-Options"), "nosniff")
                self.assertIn("frame-ancestors 'none'", h.get("Content-Security-Policy", ""))
                self.assertEqual(h.get("Referrer-Policy"), "no-referrer")
                self.assertEqual(h.get("Server"), "sungrow-local")

    def test_unknown_host_is_refused(self):
        for method in ("GET", "HEAD"):
            for path in ("/", "/api/now", "/app.js"):
                with self.subTest(method=method, path=path):
                    self.assertEqual(request(self.p, method, path, {"Host": "attacker.example:8787"})[0], 421)

    def test_head_follows_the_same_rules(self):
        self.assertEqual(request(self.p, "HEAD", "/", {"X-Forwarded-For": "8.8.8.8"})[0], 403)
        status, h, body = request(self.p, "HEAD", "/")
        self.assertEqual((status, body), (200, b""))

    def test_other_methods_after_the_check(self):
        self.assertEqual(request(self.p, "POST", "/")[0], 501)
        self.assertEqual(request(self.p, "OPTIONS", "/")[0], 501)
        self.assertEqual(request(self.p, "POST", "/", {"Host": "attacker.example"})[0], 421)

    def test_large_and_bad_offset(self):
        for q in ("99999999999999999999999", "-5", "abc", "1&offset=2", "%31"):
            with self.subTest(q):
                self.assertEqual(request(self.p, "GET", "/api/day?offset=" + q)[0], 200)

    def test_path_traversal(self):
        for path in ("/../sungrow_local.py", "/..%2f..%2fconfig.json", "/%2e%2e/sungrow_local.py",
                     "/web/../../sungrow_local.py", "//etc/passwd", "/tests/"):
            with self.subTest(path):
                self.assertEqual(request(self.p, "GET", path)[0], 404)

    def test_idle_connection_is_closed(self):
        s = socket.create_connection(("127.0.0.1", self.p))
        s.sendall(b"GET / HTTP/1.1\r\n")
        s.settimeout(30)
        began = time.time()
        self.assertEqual(s.recv(100), b"")          # the server gives up and closes
        self.assertLess(time.time() - began, 10)
        s.close()


class SlowSenders(unittest.TestCase):
    def setUp(self):
        self.s = RunningServer()             # request deadline 2 s in the tests

    def tearDown(self):
        self.s.close()

    def test_dripping_request_is_closed_at_the_deadline(self):
        c = socket.create_connection(("127.0.0.1", self.s.port))
        c.settimeout(10)
        began = time.time()
        closed = False
        try:
            c.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n")
            for _ in range(20):
                c.sendall(b"X")
                time.sleep(0.4)
        except OSError:
            closed = True
        if not closed:
            closed = c.recv(100) == b""
        c.close()
        self.assertTrue(closed)
        self.assertLess(time.time() - began, 6)

    def test_one_client_cannot_take_every_slot(self):
        try:
            probe = socket.socket()
            probe.bind(("127.0.0.2", 0))
            probe.close()
        except OSError:
            self.skipTest("no second loopback address on this system")
        slow = []
        for _ in range(40):
            c = socket.create_connection(("127.0.0.1", self.s.port))
            c.sendall(b"GET / HTTP/1.1\r\n")
            slow.append(c)
        time.sleep(0.3)
        other = socket.create_connection(("127.0.0.1", self.s.port), source_address=("127.0.0.2", 0))
        other.sendall(b"GET /api/now HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        other.settimeout(5)
        self.assertTrue(other.recv(100).startswith(b"HTTP/1.0 200"))
        other.close()
        for c in slow:
            c.close()


class Login(unittest.TestCase):
    def setUp(self):
        self.s = RunningServer(basic_auth="owner:correct horse")
        self.p = self.s.port

    def tearDown(self):
        self.s.close()

    def test_get_and_head_need_the_login(self):
        for method in ("GET", "HEAD"):
            with self.subTest(method):
                self.assertEqual(request(self.p, method, "/index.html")[0], 401)
                self.assertEqual(request(self.p, method, "/index.html",
                                         {"Authorization": basic("owner", "correct horse")})[0], 200)

    def test_non_ascii_authorization(self):
        c = socket.create_connection(("127.0.0.1", self.p))
        c.sendall(b"GET /api/now HTTP/1.0\r\nAuthorization: Basic \xff\xfe\r\n\r\n")
        self.assertTrue(c.recv(100).startswith(b"HTTP/1.0 401"))
        c.close()


class ConnectionLimit(unittest.TestCase):
    def test_idle_connections_do_not_exhaust_the_server(self):
        s = RunningServer()
        try:
            before = threading.active_count()
            idle = []
            for _ in range(80):
                c = socket.create_connection(("127.0.0.1", s.port))
                c.sendall(b"GET / HTTP/1.1\r\n")
                idle.append(c)
            time.sleep(1)
            self.assertLessEqual(threading.active_count() - before, s.server.max_connections + 2)
            time.sleep(3)                           # the idle ones time out
            self.assertEqual(request(s.port, "GET", "/api/now")[0], 200)
            for c in idle:
                c.close()
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
