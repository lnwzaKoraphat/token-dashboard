import json
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import server  # noqa: E402

SCHEMA = """
create table sessions (id text primary key, source text, display_name text, title text, started_at real);
create table session_model_usage (session_id text, model text, billing_provider text, api_call_count integer,
  input_tokens integer, output_tokens integer, cache_read_tokens integer, cache_write_tokens integer,
  reasoning_tokens integer, estimated_cost_usd real, first_seen real, last_seen real);
create table messages (id integer primary key, session_id text, content text, timestamp real, token_count integer);
"""


def bkk(y, m, d, hh=0, mm=0, ss=0):
    from datetime import datetime
    return datetime(y, m, d, hh, mm, ss, tzinfo=server.TZ).timestamp()


def make_profile(base, name, usage=(), messages=(), sessions=()):
    os.makedirs(os.path.join(base, name), exist_ok=True)
    con = sqlite3.connect(os.path.join(base, name, "state.db"))
    con.executescript(SCHEMA)
    con.executemany("insert into sessions values (?,?,?,?,?)", sessions)
    con.executemany("insert into session_model_usage values (?,?,?,?,?,?,?,?,?,?,?,?)", usage)
    con.executemany("insert into messages (session_id, content, timestamp, token_count) values (?,?,?,?)", messages)
    con.commit()
    con.close()


NOW = bkk(2026, 10, 22, 12, 0)


def row(sid, model, calls, i, o, cr, cw, rs, cost, last=NOW - 100):
    return (sid, model, "x", calls, i, o, cr, cw, rs, cost, last - 50, last)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        make_profile(self.base, "sol", usage=[row("s-sol-1", "claude-opus-5-5[1m]", 3, 100, 50, 1000, 10, 5, 1.5),
                                              row("s-sol-2", "claude-sonnet-5-5", 2, 20, 10, 0, 0, 0, 0.25)],
                     sessions=[("s-sol-1", "local", "Bot Chat", "งานหนึ่ง", 1)])
        make_profile(self.base, "flash", usage=[row("s-fl-1", "claude-sonnet-5-5[1m]", 4, 200, 100, 5000, 20, 0, 2.0)])
        make_profile(self.base, "astra", usage=[row("s-as-1", "openai/gpt-6-astra", 5, 3000, 300, 0, 0, 7, 4.0)])
        make_profile(self.base, "luna", usage=[row("s-lu-1", "openai/gpt-6.1-sol", 6, 4000, 400, 0, 0, 0, 3.0),
                                               row("s-lu-2", "mystery-model", 1, 1, 1, 0, 0, 0, 0.5)])

    def tearDown(self):
        self.tmp.cleanup()


class TestAC01Totals(Fixture):
    def test_ac01_family_totals_equal_fixture_sums(self):
        d = server.build_usage(self.base, now=NOW)
        c, g, a = d["totals"]["claude"], d["totals"]["gpt"], d["totals"]["all"]
        self.assertEqual((c["input"], c["output"], c["cache_read"], c["cache_write"], c["reasoning"], c["calls"]),
                         (320, 160, 6000, 30, 5, 9))
        self.assertAlmostEqual(c["cost"], 3.75)
        self.assertEqual((g["input"], g["output"], g["reasoning"], g["calls"]), (7000, 700, 7, 11))
        self.assertAlmostEqual(g["cost"], 7.0)
        self.assertEqual(a["input"], 320 + 7000 + 1)  # "other" counts only in all
        self.assertAlmostEqual(a["cost"], 3.75 + 7.0 + 0.5)

    def test_ac01_classification(self):
        self.assertEqual([server.family_of(m) for m in ("claude-opus-5-5[1m]", "Claude-X", "openai/gpt-6", "gpt-4o", "mystery", "", None)],
                         ["claude", "claude", "gpt", "gpt", "other", "other", "other"])
        d = server.build_usage(self.base, now=NOW)
        fam = {(b["bot"], b["model"]): b["family"] for b in d["by_bot"]}
        self.assertEqual(fam[("sol", "claude-opus-5-5[1m]")], "claude")
        self.assertEqual(fam[("astra", "openai/gpt-6-astra")], "gpt")
        self.assertEqual(fam[("luna", "mystery-model")], "other")
        prof = {p["name"]: p for p in d["profiles"]}
        self.assertEqual((prof["sol"]["family"], prof["luna"]["family"]), ("claude", "gpt"))

    def test_ac01_top_sessions_sorted_with_labels(self):
        d = server.build_usage(self.base, now=NOW)
        top = d["top_sessions"]
        self.assertEqual(top[0]["session_id_short"], "s-fl-1")  # 5320 tokens, the biggest
        self.assertEqual([t["total_tokens"] for t in top], sorted((t["total_tokens"] for t in top), reverse=True))
        sol1 = [t for t in top if t["session_id_short"] == "s-sol-1"][0]
        self.assertEqual((sol1["title"], sol1["source"], sol1["total_tokens"]), ("งานหนึ่ง", "local", 1160))
        self.assertTrue(sol1["last_seen_iso"].endswith("+07:00"))
        self.assertLessEqual(len(top), 20)


class TestAC02ReadOnly(Fixture):
    def test_ac02_connection_is_read_only(self):
        con = server.open_ro(os.path.join(self.base, "sol", "state.db"))
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("insert into messages (session_id, content, timestamp) values ('x','y',1)")
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("create table t (a)")
        con.close()

    def test_ac02_database_unchanged_by_requests(self):
        p = os.path.join(self.base, "sol", "state.db")
        before = (os.path.getsize(p), os.path.getmtime(p))
        server.build_usage(self.base, now=NOW)
        self.assertEqual(before, (os.path.getsize(p), os.path.getmtime(p)))

    def test_ac02_binds_loopback_only_and_has_no_write_endpoints(self):
        srv = server.make_server(0, self.base)
        self.addCleanup(srv.server_close)
        self.assertEqual(srv.server_address[0], "127.0.0.1")
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        # reachable on loopback, JSON shape ok
        with urllib.request.urlopen("http://127.0.0.1:%d/api/usage?bucket=hour&days=1" % port) as r:
            self.assertEqual(r.status, 200)
            body = json.load(r)
        self.assertEqual(set(body), {"generated_at", "profiles", "totals", "by_bot", "window5h", "series", "top_sessions"})
        self.assertEqual(body["series"]["bucket"], "hour")
        # not listening on other interfaces
        for host in {socket.gethostbyname(socket.gethostname())} - {"127.0.0.1"}:
            s = socket.socket()
            s.settimeout(1)
            self.assertNotEqual(s.connect_ex((host, port)), 0)
            s.close()
        # unknown paths 404; writes rejected
        for method, path in (("GET", "/nope"), ("GET", "/api/other"), ("POST", "/api/usage"), ("DELETE", "/")):
            req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method, data=b"" if method == "POST" else None)
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req)
            self.assertEqual(cm.exception.code, 404, method + path)


class TestAC03Unavailable(Fixture):
    def test_ac03_missing_profile_is_unavailable_others_render(self):
        os.remove(os.path.join(self.base, "astra", "state.db"))
        d = server.build_usage(self.base, now=NOW)
        prof = {p["name"]: p for p in d["profiles"]}
        self.assertFalse(prof["astra"]["available"])
        self.assertIn("error", prof["astra"])
        self.assertTrue(all(prof[n]["available"] for n in ("sol", "flash", "luna")))
        self.assertEqual(d["totals"]["gpt"]["input"], 4001 - 1)  # luna only
        self.assertEqual(d["totals"]["claude"]["calls"], 9)
        self.assertEqual(d["series"]["bots"]["astra"], [0] * 7)

    def test_ac03_locked_profile_is_unavailable_and_http_200(self):
        locker = sqlite3.connect(os.path.join(self.base, "flash", "state.db"), isolation_level=None)
        locker.execute("begin exclusive")  # rollback-journal DB: readers get SQLITE_BUSY
        try:
            srv = server.make_server(0, self.base)
            self.addCleanup(srv.server_close)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.shutdown)
            with urllib.request.urlopen("http://127.0.0.1:%d/api/usage" % srv.server_address[1], timeout=15) as r:
                self.assertEqual(r.status, 200)
                d = json.load(r)
        finally:
            locker.execute("rollback")
            locker.close()
        prof = {p["name"]: p for p in d["profiles"]}
        self.assertFalse(prof["flash"]["available"])
        self.assertIn("lock", prof["flash"]["error"].lower())
        self.assertTrue(prof["sol"]["available"] and prof["astra"]["available"] and prof["luna"]["available"])
        self.assertEqual(d["totals"]["claude"]["calls"], 5)  # sol only

    def test_ac03_corrupt_file_does_not_crash(self):
        with open(os.path.join(self.base, "luna", "state.db"), "wb") as f:
            f.write(b"this is not a database" * 50)
        d = server.build_usage(self.base, now=NOW)
        self.assertFalse({p["name"]: p for p in d["profiles"]}["luna"]["available"])


class TestAC04Buckets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = self.tmp.name
        msgs = [
            ("a", "x", bkk(2026, 10, 21, 23, 59, 59), 10),   # day 21, hour 23
            ("a", "x", bkk(2026, 10, 22, 0, 0, 0), 20),      # day 22, hour 00
            ("a", "x", bkk(2026, 10, 22, 0, 30, 0), 5),      # day 22, hour 00
            ("a", "x" * 40, bkk(2026, 10, 22, 7, 0, 0), None),  # NULL token_count -> len//4 = 10
            ("a", "x", bkk(2026, 10, 14, 12, 0, 0), 999),    # outside a 7-day window
        ]
        make_profile(self.base, "sol", messages=msgs)
        for n in ("astra", "flash", "luna"):
            make_profile(self.base, n)

    def test_ac04_day_buckets_use_utc7_around_midnight(self):
        d = server.build_usage(self.base, "day", 7, now=bkk(2026, 10, 22, 12, 0))
        s = d["series"]
        self.assertEqual(s["labels"][-2:], ["2026-10-21", "2026-10-22"])
        self.assertEqual(len(s["labels"]), 7)
        self.assertEqual(s["bots"]["sol"][-2:], [10, 35])  # 23:59:59 stays on the 21st; 00:00 starts the 22nd
        self.assertEqual(sum(s["bots"]["sol"]), 45, "old message excluded")

    def test_ac04_hour_buckets_and_null_token_fallback(self):
        d = server.build_usage(self.base, "hour", 1, now=bkk(2026, 10, 22, 12, 0))
        s = d["series"]
        self.assertEqual(len(s["labels"]), 24)
        self.assertEqual(s["labels"][-1], "2026-10-22 12:00")
        by = dict(zip(s["labels"], s["bots"]["sol"]))
        self.assertEqual(by["2026-10-21 23:00"], 10)
        self.assertEqual(by["2026-10-22 00:00"], 25)
        self.assertEqual(by["2026-10-22 07:00"], 10, "NULL token_count -> len(content)//4")

    def test_ac04_utc_midnight_is_not_a_bucket_boundary(self):
        # 2026-10-21 17:00 UTC == 2026-10-22 00:00 Bangkok; 16:59:59 UTC belongs to the 21st
        from datetime import datetime, timezone
        os.remove(os.path.join(self.base, "luna", "state.db"))
        make_profile(self.base, "luna", messages=[("b", "x", datetime(2026, 10, 21, 16, 59, 59, tzinfo=timezone.utc).timestamp(), 7),
                                                  ("b", "x", datetime(2026, 10, 21, 17, 0, 0, tzinfo=timezone.utc).timestamp(), 3)])
        d = server.build_usage(self.base, "day", 3, now=bkk(2026, 10, 22, 12, 0))
        self.assertEqual(d["series"]["bots"]["luna"], [0, 7, 3])

    def test_ac04_bad_params_fall_back(self):
        d = server.build_usage(self.base, "weeks", 9999, now=bkk(2026, 10, 22, 12, 0))
        self.assertEqual((d["series"]["bucket"], len(d["series"]["labels"])), ("day", 90))


class TestSessionLimit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = self.tmp.name

    def _profile(self, name, model, sessions, messages):
        make_profile(self.base, name, usage=[row("s-new", model, 1, 1, 1, 0, 0, 0, 0.1)], sessions=sessions)
        con = sqlite3.connect(os.path.join(self.base, name, "state.db"))
        con.execute("alter table messages add column active integer")
        con.executemany("insert into messages (session_id, content, timestamp, token_count, active) values (?,?,?,?,?)", messages)
        con.commit()
        con.close()

    def test_session_limit_uses_latest_session_active_messages_and_model_window(self):
        self._profile("sol", "claude-opus-5-5[1m]",
                      [("s-old", "local", "Bot Chat", "old", 100.0), ("s-new", "local", "Bot Chat", "new", 200.0)],
                      [("s-old", "x" * 4000, 1, None, 1),               # older session: ignored
                       ("s-new", "x" * 4000, 2, None, 1),               # 1000
                       ("s-new", "y" * 2000, 3, None, 1),               # 500
                       ("s-new", "z" * 80000, 4, None, 0),              # compacted away: ignored
                       ("s-new", "w" * 400, 5, None, None)])            # active NULL -> counted? (treated as active)
        for n in ("astra", "flash", "luna"):
            make_profile(self.base, n)
        d = server.build_usage(self.base, now=NOW)
        sl = [b for b in d["by_bot"] if b["bot"] == "sol"][0]["session_limit"]
        self.assertEqual(sl["session_id_short"], "s-new")
        self.assertEqual(sl["used_est"], 1000 + 500 + 100)
        self.assertEqual((sl["limit"], sl["basis"]), (1_000_000, "estimate"))
        self.assertAlmostEqual(sl["pct"], 0.2)

    def test_context_limit_rules_and_pct_bands(self):
        self.assertEqual(server.context_limit("claude-sonnet-5-5[1m]"), 1_000_000)
        self.assertEqual(server.context_limit("openai/gpt-6.1-sol"), 400_000)
        self.assertEqual(server.context_limit("claude-haiku"), 200_000)
        self.assertEqual(server.context_limit(None), 200_000)
        self._profile("luna", "openai/gpt-6.1-sol", [("s-new", "local", "Bot Chat", "n", 1.0)], [("s-new", "x" * 1_400_000, 1, None, 1)])
        for n in ("astra", "sol", "flash"):
            make_profile(self.base, n)
        sl = [b for b in server.build_usage(self.base, now=NOW)["by_bot"] if b["bot"] == "luna"][0]["session_limit"]
        self.assertEqual((sl["used_est"], sl["limit"], sl["pct"]), (350_000, 400_000, 87.5))
        # profile without sessions -> session_limit is None, response still fine
        d = server.build_usage(self.base, now=NOW)
        self.assertEqual(len(d["profiles"]), 4)


class TestWindow5h(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = self.tmp.name
        self.app_now = bkk(2026, 10, 22, 15, 30)

    def _msgs(self, name, items, cost=4.0, sid="s1", model=None):
        """items: [(timestamp, content_len)] -> profile db with one session."""
        model = model or ("claude-sonnet-5-5[1m]" if name in ("sol", "flash") else "openai/gpt-6")
        make_profile(self.base, name, usage=[row(sid, model, 1, 1, 1, 0, 0, 0, cost)],
                     messages=[(sid, "x" * n, ts, None) for ts, n in items])

    def _fill(self, skip=()):
        for n in ("astra", "sol", "flash", "luna"):
            if n not in skip and not os.path.exists(os.path.join(self.base, n)):
                make_profile(self.base, n)

    def test_window_start_reset_and_boundary_5h(self):
        # 09:00 starts window 1 (ends 14:00); a message at exactly 14:00 starts window 2 (ends 19:00)
        self._msgs("sol", [(bkk(2026, 10, 22, 9, 0), 400), (bkk(2026, 10, 22, 9, 30), 400), (bkk(2026, 10, 22, 13, 59, 59), 400),
                           (bkk(2026, 10, 22, 14, 0, 0), 800), (bkk(2026, 10, 22, 15, 0), 1200)])
        self._fill()
        w = server.build_usage(self.base, now=self.app_now)["window5h"]
        c = w["claude"]
        self.assertFalse(c["idle"])
        self.assertEqual(c["start_iso"], "2026-10-22T14:00:00+07:00")
        self.assertEqual(c["reset_iso"], "2026-10-22T19:00:00+07:00")
        self.assertEqual(c["minutes_left"], 210)
        self.assertEqual(c["used_tokens_est"], 800 // 4 + 1200 // 4)
        self.assertEqual(c["limit"], 2_000_000)
        self.assertAlmostEqual(c["pct"], round(500 / 2_000_000 * 100, 1))
        # one second before the boundary we are still in window 1 (resets 14:00)
        w1 = server.build_usage(self.base, now=bkk(2026, 10, 22, 13, 59, 59))["window5h"]["claude"]
        self.assertEqual((w1["start_iso"], w1["reset_iso"], w1["used_tokens_est"]), ("2026-10-22T09:00:00+07:00", "2026-10-22T14:00:00+07:00", 300))
        self.assertEqual(w1["minutes_left"], 1)

    def test_window_idle_when_latest_window_ended(self):
        self._msgs("sol", [(bkk(2026, 10, 22, 6, 0), 400), (bkk(2026, 10, 22, 10, 59), 400)])
        self._fill()
        d = server.build_usage(self.base, now=bkk(2026, 10, 22, 11, 0, 0))  # window 06:00-11:00 ended exactly now
        c = d["window5h"]["claude"]
        self.assertTrue(c["idle"])
        self.assertEqual((c["start_iso"], c["reset_iso"], c["used_tokens_est"], c["pct"]), ("", "", 0, 0.0))
        self.assertTrue(d["window5h"]["bots"]["sol"]["idle"])
        self.assertTrue(d["window5h"]["gpt"]["idle"])  # no gpt messages at all

    def test_window_ignores_messages_older_than_24h_and_in_the_future(self):
        self._msgs("luna", [(self.app_now - 25 * 3600, 4000), (self.app_now - 3600, 400), (self.app_now + 600, 4000)])
        self._fill()
        g = server.build_usage(self.base, now=self.app_now)["window5h"]["gpt"]
        self.assertEqual((g["used_tokens_est"], g["minutes_left"]), (100, 240))
        self.assertEqual(g["start_iso"], "2026-10-22T14:30:00+07:00")

    def test_window_family_merge_cost_proration_and_limits_file(self):
        t0 = bkk(2026, 10, 22, 13, 0)
        # sol: session total 800 chars, only 400 inside the window (other 400 is 30 h old) -> half of $4
        self._msgs("sol", [(t0, 400), (t0 - 30 * 3600, 400)], cost=4.0, sid="sa")
        self._msgs("flash", [(t0 + 600, 800)], cost=1.0, sid="sb")
        self._fill()
        lim = os.path.join(self.base, "limits.json")
        with open(lim, "w") as f:
            json.dump({"claude": {"tokens_5h": 1000}, "gpt": {"tokens_5h": 5}}, f)
        d = server.build_usage(self.base, now=self.app_now, limits=server.load_limits(lim))["window5h"]
        c = d["claude"]
        self.assertEqual(c["used_tokens_est"], 100 + 200)
        self.assertAlmostEqual(c["cost_est"], 2.0 + 1.0)
        self.assertEqual((c["limit"], c["pct"]), (1000, 30.0))
        self.assertEqual(d["bots"]["sol"]["used_tokens_est"], 100)
        self.assertAlmostEqual(d["bots"]["sol"]["cost_est"], 2.0)
        self.assertEqual(d["bots"]["flash"]["limit"], 1000)
        self.assertEqual(d["gpt"]["limit"], 5)

    def test_load_limits_defaults_and_bad_files(self):
        self.assertEqual(server.load_limits(os.path.join(self.base, "missing.json")), server.LIMITS_DEFAULT)
        bad = os.path.join(self.base, "bad.json")
        for text in ("not json", "[]", '{"claude": {"tokens_5h": -5}, "gpt": {"tokens_5h": "x"}}', '{"claude": 7}'):
            with open(bad, "w") as f:
                f.write(text)
            self.assertEqual(server.load_limits(bad), server.LIMITS_DEFAULT, text)
        with open(bad, "w") as f:
            f.write('{"gpt": {"tokens_5h": 123456}}')
        got = server.load_limits(bad)
        self.assertEqual((got["gpt"]["tokens_5h"], got["claude"]["tokens_5h"]), (123456, 2_000_000))
        with open(os.path.join(os.path.dirname(server.__file__), "limits.example.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), server.LIMITS_DEFAULT)


if __name__ == "__main__":
    unittest.main()
