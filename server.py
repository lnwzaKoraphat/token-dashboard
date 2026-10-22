#!/usr/bin/env python3
"""Token Dashboard - read-only localhost page for Hermes bot token usage. Stdlib only (Python 3.11+)."""
import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BOTS = ("astra", "sol", "flash", "luna")
TZ = timezone(timedelta(hours=7))  # Asia/Bangkok, no DST
TZ_OFFSET = 7 * 3600
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
FIELDS = ("input", "output", "cache_read", "cache_write", "reasoning", "calls", "cost")


def default_base():
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "hermes", "profiles")


def family_of(model):
    m = (model or "").lower()
    if "claude" in m:
        return "claude"
    if "gpt" in m or "openai/" in m:
        return "gpt"
    return "other"


def zero():
    return {k: 0 for k in FIELDS}


def add(a, b):
    for k in FIELDS:
        a[k] += b[k] or 0


def open_ro(path):
    """Read-only connection (mode=ro). Retries once on a busy/locked database."""
    uri = "file:" + path.replace("\\", "/").replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    last = sqlite3.DatabaseError("unable to open database")
    for attempt in range(2):
        con = None
        try:
            con = sqlite3.connect(uri, uri=True, timeout=1.0)
            con.execute("select 1 from sqlite_master limit 1")
            return con
        except sqlite3.DatabaseError as e:
            last = e
            if con is not None:
                con.close()
            if attempt == 0 and ("locked" in str(e).lower() or "busy" in str(e).lower()):
                time.sleep(0.3)
                continue
            break
    raise last


def bucket_keys(bucket, days, now):
    """Return (labels, key->index, first_key) where key is the integer bucket id in UTC+7."""
    unit = 3600 if bucket == "hour" else 86400
    n = min(days, 7) * 24 if bucket == "hour" else days
    last = int((now + TZ_OFFSET) // unit)
    keys = list(range(last - n + 1, last + 1))
    labels = []
    for k in keys:
        t = datetime.fromtimestamp(k * unit - TZ_OFFSET, TZ)
        labels.append(t.strftime("%Y-%m-%d %H:00") if bucket == "hour" else t.strftime("%Y-%m-%d"))
    return labels, {k: i for i, k in enumerate(keys)}, keys[0], unit


def read_profile(name, base, bucket, days, now, nbuckets_ctx):
    """Collect one profile. Raises on unavailable DB (caller records it)."""
    path = os.path.join(base, name, "state.db")
    if not os.path.exists(path):
        raise FileNotFoundError("ไม่พบไฟล์ state.db")
    con = open_ro(path)
    try:
        rows = con.execute(
            "select u.session_id, u.model, u.api_call_count, u.input_tokens, u.output_tokens, u.cache_read_tokens,"
            " u.cache_write_tokens, u.reasoning_tokens, u.estimated_cost_usd, u.last_seen,"
            " s.source, coalesce(nullif(s.title,''), s.display_name) from session_model_usage u"
            " left join sessions s on s.id = u.session_id").fetchall()
        labels, index, first_key, unit = nbuckets_ctx
        counts = [0] * len(labels)
        cutoff = first_key * unit - TZ_OFFSET
        for key, tok in con.execute(
                "select cast((timestamp + ?) / ? as integer) as b,"
                " sum(coalesce(token_count, length(coalesce(content,'')) / 4)) from messages"
                " where timestamp >= ? group by b", (TZ_OFFSET, unit, cutoff)):
            if key in index:
                counts[index[key]] += int(tok or 0)
        return rows, counts
    finally:
        con.close()


def build_usage(base, bucket="day", days=7, now=None):
    now = time.time() if now is None else now
    bucket = bucket if bucket in ("day", "hour") else "day"
    days = max(1, min(int(days), 90))
    ctx = bucket_keys(bucket, days, now)
    out = {
        "generated_at": datetime.fromtimestamp(now, TZ).isoformat(timespec="seconds"),
        "profiles": [], "totals": {"claude": zero(), "gpt": zero(), "all": zero()},
        "by_bot": [], "series": {"bucket": bucket, "labels": ctx[0], "bots": {}}, "top_sessions": [],
    }
    sessions = []
    for name in BOTS:
        try:
            rows, counts = read_profile(name, base, bucket, days, now, ctx)
        except Exception as e:  # unavailable profile must never crash the response
            out["profiles"].append({"name": name, "family": "other", "model": "", "available": False, "error": str(e)[:200]})
            out["series"]["bots"][name] = [0] * len(ctx[0])
            continue
        per_model = {}
        for (sid, model, calls, i, o, cr, cw, rs, cost, last, source, title) in rows:
            vals = {"input": i, "output": o, "cache_read": cr, "cache_write": cw, "reasoning": rs, "calls": calls, "cost": cost or 0.0}
            vals = {k: (v or 0) for k, v in vals.items()}
            fam = family_of(model)
            m = per_model.setdefault(model or "-", zero())
            add(m, vals)
            if fam in ("claude", "gpt"):
                add(out["totals"][fam], vals)
            add(out["totals"]["all"], vals)
            sessions.append({
                "bot": name, "session_id_short": (sid or "")[:8], "source": source or "", "title": title or "",
                "model": model or "", "total_tokens": vals["input"] + vals["output"] + vals["cache_read"] + vals["cache_write"],
                "cost": vals["cost"], "last_seen_iso": datetime.fromtimestamp(last, TZ).isoformat(timespec="seconds") if last else "",
            })
        main = max(per_model, key=lambda k: per_model[k]["input"] + per_model[k]["output"], default="")
        out["profiles"].append({"name": name, "family": family_of(main), "model": main if main != "-" else "", "available": True})
        for model, vals in per_model.items():
            out["by_bot"].append(dict({"bot": name, "model": model, "family": family_of(model)}, **vals))
        out["series"]["bots"][name] = counts
    sessions.sort(key=lambda s: s["total_tokens"], reverse=True)
    out["top_sessions"] = sessions[:20]
    return out


class Handler(BaseHTTPRequestHandler):
    base = default_base()
    server_version = "TokenDashboard/1.0"

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            try:
                with open(os.path.join(STATIC_DIR, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                return self._send(500, b"index.html missing", "text/plain")
        if u.path == "/api/usage":
            q = parse_qs(u.query)
            try:
                days = int(q.get("days", ["7"])[0])
            except ValueError:
                days = 7
            data = build_usage(self.base, q.get("bucket", ["day"])[0], days)
            return self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        self._send(404, b"not found", "text/plain")

    do_PUT = do_DELETE = do_PATCH = do_POST

    def log_message(self, format, *args):
        pass


def make_server(port=8787, base=None):
    handler = type("H", (Handler,), {"base": base or default_base()})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)  # loopback only


def main():
    ap = argparse.ArgumentParser(description="Token Dashboard (localhost, read-only)")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--base", default=None, help="profiles directory (default: %%LOCALAPPDATA%%/hermes/profiles)")
    a = ap.parse_args()
    srv = make_server(a.port, a.base)
    print("Token Dashboard: http://127.0.0.1:%d" % srv.server_address[1])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
