"""Modbus client against a fake inverter, plausibility checks and stale data."""
import socket, struct, threading, time, unittest
from unittest import mock

from tests.util import sl, config


class FakeInverter(object):
    """Answers Modbus TCP requests. `mode` changes how it answers."""

    def __init__(self, mode="ok"):
        self.mode = mode
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def regs(self, address, count):
        if address == 13000:
            r = [0] * 30
            r[1], r[22], r[19], r[24], r[23] = 259, 503, 2150, 106, 1000
            return r
        return [1234, 0] + [0] * (count - 2) if count >= 2 else [0] * count

    def serve(self):
        try:
            c, _ = self.sock.accept()
        except OSError:
            return
        with c:
            try:
                while True:
                    req = b""
                    while len(req) < 12:
                        chunk = c.recv(12 - len(req))
                        if not chunk:
                            return
                        req += chunk
                    tid, _, _, unit, func, address, count = struct.unpack(">HHHBBHH", req)
                    data = struct.pack(">%dH" % count, *self.regs(address, count))
                    m = self.mode
                    if m == "exception":
                        c.sendall(struct.pack(">HHHBBB", tid, 0, 3, unit, 0x84, 2))
                        continue
                    if m == "wrong tid":
                        tid += 1
                    if m == "wrong unit":
                        unit += 1
                    if m == "wrong function":
                        func = 3
                    body = struct.pack(">BB", func, len(data)) + data
                    if m == "wrong byte count":
                        body = struct.pack(">BB", func, len(data) - 2) + data[:-2]
                    frame = struct.pack(">HHHB", tid, 0, len(body) + 1, unit) + body
                    if m == "short length":
                        frame = struct.pack(">HHHB", tid, 0, 2, unit) + struct.pack(">B", func)
                    if m == "drip":
                        for b in frame:
                            c.sendall(bytes([b]))
                            time.sleep(0.3)
                        continue
                    c.sendall(frame)
            except OSError:
                return

    def close(self):
        self.sock.close()


def read(mode, deadline=sl.READ_DEADLINE):
    f = FakeInverter(mode)
    try:
        cfg = config(inverter_host="127.0.0.1", inverter_port=f.port, request_pause=0)
        with mock.patch.object(sl, "READ_DEADLINE", deadline):
            return sl.read_inverter(cfg)
    finally:
        f.close()


class Client(unittest.TestCase):
    def test_correct_reading(self):
        w = read("ok")
        self.assertEqual(w["pv"], 1234)
        self.assertEqual(w["soc"], 50.3)
        self.assertEqual(w["today"]["pv"], 25.9)

    def test_bad_frames_raise(self):
        for mode in ("exception", "wrong tid", "wrong unit", "wrong function", "wrong byte count", "short length"):
            with self.subTest(mode):
                with self.assertRaises(sl.ModbusError):
                    read(mode)

    def test_slow_peer_hits_the_deadline(self):
        began = time.time()
        with self.assertRaises(sl.ReadTimeout):
            read("drip", deadline=1.5)
        self.assertLess(time.time() - began, 4)

    def test_refused_connection(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        with self.assertRaises(OSError) as e:
            sl.read_inverter(config(inverter_host="127.0.0.1", inverter_port=port))
        self.assertEqual(sl.error_code(e.exception), "unreachable")


def reading(**kw):
    w = {"pv": 3000, "battery": -1000, "grid": -500, "soc": 55.0, "battery_voltage": 210.0,
         "battery_temp": 20.0, "battery_health": 100.0, "battery_capacity": 15.0,
         "today": dict.fromkeys(("pv", "direct", "discharged", "imported", "charged", "exported"), 1.0),
         "total": dict.fromkeys(("pv", "direct", "discharged", "imported", "charged", "exported"), 100.0)}
    w.update(kw)
    return w


class Plausibility(unittest.TestCase):
    def test_good_reading_passes(self):
        sl.check_plausible(reading(), config())

    def test_bad_readings_are_rejected(self):
        for kw in ({"pv": 4000000000}, {"pv": -1}, {"soc": 6553.5}, {"battery": 300000}, {"grid": -300000},
                   {"battery_temp": 3276.7}, {"today": dict(reading()["today"], pv=-1.0)}):
            with self.subTest(kw):
                with self.assertRaises(sl.Implausible):
                    sl.check_plausible(reading(**kw), config())


class StoreSpy(object):
    def __init__(self):
        self.samples = []

    def sample(self, *a):
        self.samples.append(a)

    def day_row(self, *a):
        self.samples.append(a)


class Collecting(unittest.TestCase):
    def test_implausible_reading_is_not_stored(self):
        store = StoreSpy()
        c = sl.Collector(config(), store, lambda: reading(soc=6553.5))
        with mock.patch.object(sl, "log"):
            c.once(0.0)
        self.assertEqual(store.samples, [])
        self.assertEqual(c.now()["error"], "implausible")

    def test_old_reading_turns_stale(self):
        c = sl.Collector(config(), StoreSpy(), reading)
        c.once(0.0)
        self.assertTrue(c.now()["ok"])
        c.last_ok -= 120
        now = c.now()
        self.assertFalse(now["ok"])
        self.assertEqual(now["error"], "stale")
        self.assertGreaterEqual(now["age"], 120)

    def test_errors_are_short_codes(self):
        def fail():
            raise ConnectionRefusedError("[Errno 111] Connection refused to 192.168.1.100")
        c = sl.Collector(config(), StoreSpy(), fail)
        with mock.patch.object(sl, "log") as log:
            c.once(0.0)
            c.once(0.0)
        self.assertEqual(c.now()["error"], "unreachable")
        self.assertEqual(log.call_count, 1)              # logged once, not on every poll


if __name__ == "__main__":
    unittest.main()
