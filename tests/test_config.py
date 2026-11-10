"""Configuration validation: every mistake stops the program with the name of the key."""
import json, os, tempfile, unittest
from unittest import mock

from tests.util import sl


def problems(**kw):
    cfg = dict(sl.DEFAULTS)
    cfg.update(kw)
    return sl.check_config(cfg)


class Validation(unittest.TestCase):
    def test_defaults_and_example_are_valid(self):
        self.assertEqual(problems(), [])
        with open(os.path.join(sl.HERE, "config.example.json"), encoding="utf-8") as f:
            self.assertEqual(problems(**json.load(f)), [])

    def test_mistakes_name_the_key(self):
        cases = [
            ({"basic_auth": ""}, "basic_auth"),
            ({"basic_auth": "secret"}, "basic_auth"),
            ({"basic_auth": "owner:short"}, "basic_auth"),
            ({"basic_auth": ":password123"}, "basic_auth"),
            ({"basic_auth": {"user": "x", "pbkdf2_sha256": "nonsense"}}, "basic_auth"),
            ({"lan_without_login": "false"}, "lan_without_login"),
            ({"feed_in_tariff": "0,08"}, "feed_in_tariff"),
            ({"http_port": "8787"}, "http_port"),
            ({"http_port": 70000}, "http_port"),
            ({"inverter_port": True}, "inverter_port"),
            ({"language": "fr"}, "language"),
            ({"currency": "<img src=x onerror=alert(1)>"}, "currency"),
            ({"currency": "€\""}, "currency"),
            ({"allowed_hosts": "pv.example.org"}, "allowed_hosts"),
            ({"trusted_proxies": ["not-an-address"]}, "trusted_proxies"),
            ({"cloudflare_access": {"team_domain": "x"}}, "cloudflare_access"),
            ({"cloudflare_access": {"team_domain": "x", "audience": []}}, "cloudflare_access"),
            ({"basicauth": "a:b"}, "basic_auth"),                 # typo, suggestion names the right key
            ({"lan_without_logins": True}, "lan_without_login"),
            ({"trust_cloudflare_access": True}, "cloudflare_access"),
        ]
        for kw, key in cases:
            with self.subTest(kw):
                p = problems(**kw)
                self.assertEqual(len(p), 1, p)
                self.assertIn(key, p[0])

    def test_good_values(self):
        self.assertEqual(problems(basic_auth="owner:correct horse", lan_without_login=True,
                                  allowed_hosts=["pv.example.org"], trusted_proxies=["10.0.0.0/8", "::1"],
                                  cloudflare_access={"team_domain": "t.cloudflareaccess.com",
                                                     "audience": ["a", "b"]},
                                  _comment="keys starting with _ are ignored"), [])

    def test_load_config_exits_with_the_problem(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w") as f:
                json.dump({"basic_auth": "secret"}, f)
            with self.assertRaises(SystemExit) as e:
                sl.load_config(path)
            self.assertIn("basic_auth", str(e.exception.code))
            with open(path, "w") as f:
                f.write("{not json")
            with self.assertRaises(SystemExit):
                sl.load_config(path)

    def test_readable_config_with_login_warns(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w") as f:
                json.dump({"basic_auth": "owner:correct horse"}, f)
            os.chmod(path, 0o644)
            with mock.patch.object(sl, "log") as log:
                sl.load_config(path)
            self.assertIn("chmod 600", log.call_args[0][0])
            os.chmod(path, 0o600)
            with mock.patch.object(sl, "log") as log:
                sl.load_config(path)
            log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
