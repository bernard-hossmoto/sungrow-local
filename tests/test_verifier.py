"""Cloudflare Access token verification and the key refresh behaviour."""
import hashlib, hmac, threading, time, unittest
from unittest import mock

from tests.util import sl, keys, sign, claims, verifier, b64, AUD, TEAM

HEAD = {"alg": "RS256", "kid": "k1", "typ": "JWT"}


class Tokens(unittest.TestCase):
    def setUp(self):
        self.v = verifier()

    def test_valid(self):
        self.assertTrue(self.v.verify(sign(HEAD, claims())))
        self.assertTrue(self.v.verify(sign(HEAD, claims(aud=AUD))))                 # aud as a string
        self.assertTrue(self.v.verify(sign(HEAD, claims(aud=["other", AUD]))))

    def test_audience_list_in_config(self):
        v = sl.AccessVerifier(TEAM, ["x", AUD])
        v.fetch_keys = lambda: {"k1": (keys.N1, keys.E)}
        self.assertTrue(v.verify(sign(HEAD, claims())))

    def test_refused(self):
        good = sign(HEAD, claims())
        h64, p64, s64 = good.split(".")
        hs256_sig = b64(hmac.new(str(keys.N1).encode(), (h64 + "." + p64).encode(), hashlib.sha256).digest())
        cases = {
            "other key": sign(HEAD, claims(), keys.N2, keys.D2),
            "tampered payload": h64 + "." + b64(claims(email="evil@example.org")) + "." + s64,
            "alg none": b64({"alg": "none", "kid": "k1"}) + "." + p64 + ".",
            "alg HS256": b64({"alg": "HS256", "kid": "k1"}) + "." + p64 + "." + hs256_sig,
            "unknown kid": sign(dict(HEAD, kid="k9"), claims()),
            "missing kid": sign({"alg": "RS256"}, claims()),
            "wrong aud": sign(HEAD, claims(aud=["b" * 64])),
            "missing aud": sign(HEAD, claims(aud=None)),
            "wrong iss": sign(HEAD, claims(iss="https://evil.cloudflareaccess.com")),
            "missing iss": sign(HEAD, claims(iss=None)),
            "expired": sign(HEAD, claims(exp=time.time() - 120)),
            "missing exp": sign(HEAD, claims(exp=None)),
            "future nbf": sign(HEAD, claims(nbf=time.time() + 600)),
            "exp not a number": sign(HEAD, claims(exp="tomorrow")),
            "zero signature": h64 + "." + p64 + "." + b64(b"\x00" * 256),
            "signature 1": h64 + "." + p64 + "." + b64((1).to_bytes(256, "big")),
            "short signature": h64 + "." + p64 + "." + b64(b"\x01"),
            "two segments": h64 + "." + p64,
            "four segments": good + ".x",
            "garbage": "not a token",
            "empty": "",
        }
        for name, token in cases.items():
            with self.subTest(name):
                self.assertFalse(self.v.verify(token))


class KeyRefresh(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(sl, "log")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_failed_fetch_is_retried_only_once_a_minute(self):
        calls = []

        def down():
            calls.append(1)
            raise OSError("no network")
        v = verifier(down)
        for i in range(50):
            self.assertFalse(v.verify(sign(dict(HEAD, kid="random%d" % i), claims())))
        self.assertEqual(len(calls), 1)
        v.next_try = 0                       # a minute later
        v.verify(sign(HEAD, claims()))
        self.assertEqual(len(calls), 2)

    def test_unknown_kid_refreshes_at_most_once_a_minute(self):
        calls = []

        def fetch():
            calls.append(1)
            return {"k1": (keys.N1, keys.E)}
        v = verifier(fetch)
        self.assertTrue(v.verify(sign(HEAD, claims())))
        for i in range(20):
            v.verify(sign(dict(HEAD, kid="new%d" % i), claims()))
        self.assertEqual(len(calls), 1)
        v.last_try -= 61
        v.verify(sign(dict(HEAD, kid="new"), claims()))
        self.assertEqual(len(calls), 2)

    def test_hourly_refresh_and_old_keys_survive_a_failure(self):
        state = {"up": True, "calls": 0}

        def fetch():
            state["calls"] += 1
            if not state["up"]:
                raise OSError("down")
            return {"k1": (keys.N1, keys.E)}
        v = verifier(fetch)
        self.assertTrue(v.verify(sign(HEAD, claims())))
        state["up"] = False
        v.loaded -= 3601
        self.assertTrue(v.verify(sign(HEAD, claims())))      # fetch fails, old key still used
        self.assertEqual(state["calls"], 2)
        self.assertTrue(v.verify(sign(HEAD, claims())))
        self.assertEqual(state["calls"], 2)                   # no new attempt within the minute

    def test_slow_fetch_does_not_block_known_keys(self):
        v = verifier()
        self.assertTrue(v.verify(sign(HEAD, claims())))
        release = threading.Event()

        def slow():
            release.wait(5)
            return {"k1": (keys.N1, keys.E)}
        v.fetch_keys = slow
        v.last_try -= 61
        t = threading.Thread(target=v.verify, args=(sign(dict(HEAD, kid="k9"), claims()),))
        t.start()
        time.sleep(0.2)
        began = time.time()
        self.assertTrue(v.verify(sign(HEAD, claims())))
        self.assertLess(time.time() - began, 1.0)
        release.set()
        t.join()


if __name__ == "__main__":
    unittest.main()
