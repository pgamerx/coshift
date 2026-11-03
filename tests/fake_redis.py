"""A tiny in-memory stand-in for Upstash's REST /pipeline endpoint, enough for board.py. Used by tests/test-redis.py."""
import json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB, LOCK = {}, threading.Lock()


def run(cmd):
    op, a = cmd[0].upper(), [str(x) for x in cmd[1:]]
    if op == "GET":
        return DB.get(a[0])
    if op == "SET":
        if "NX" in a[2:] and a[0] in DB:
            return None
        DB[a[0]] = a[1]
        return "OK"
    if op == "DEL":
        return sum(DB.pop(k, None) is not None for k in a)
    if op == "MGET":
        return [DB.get(k) for k in a]
    if op == "INCR":
        DB[a[0]] = str(int(DB.get(a[0], 0)) + 1)
        return int(DB[a[0]])
    if op == "EVAL":  # board.py's only script: delete the lock if it's still ours
        return DB.pop(a[2]) and 1 if DB.get(a[2]) == a[3] else 0
    if op == "EXPIRE":
        return 1
    if op in ("SADD", "SREM", "SMEMBERS"):
        s = DB.setdefault(a[0], set())
        if op == "SMEMBERS":
            return sorted(s)
        n = len(s)
        (s.update if op == "SADD" else s.difference_update)(a[1:])
        return abs(len(s) - n)
    if op in ("LPUSH", "RPUSH"):
        lst = DB.setdefault(a[0], [])
        for x in a[1:]:
            lst.insert(0, x) if op == "LPUSH" else lst.append(x)
        return len(lst)
    if op in ("LRANGE", "LTRIM"):
        lst, i, j = DB.get(a[0], []), int(a[1]), int(a[2])
        n = len(lst)
        i, j = max(0, i + n if i < 0 else i), (j + n if j < 0 else j)
        if op == "LRANGE":
            return lst[i:j + 1]
        DB[a[0]] = lst[i:j + 1]
        return "OK"
    if op == "LREM":
        lst = DB.get(a[0], [])
        DB[a[0]] = [x for x in lst if x != a[2]]
        return len(lst) - len(DB[a[0]])
    if op in ("HSET", "HGETALL", "HDEL"):
        h = DB.setdefault(a[0], {})
        if op == "HSET":
            h.update(zip(a[1::2], a[2::2]))
            return 1
        if op == "HDEL":
            return sum(h.pop(k, None) is not None for k in a[1:])
        return [x for kv in h.items() for x in kv]
    if op in ("ZADD", "ZREM", "ZRANGEBYSCORE", "ZREMRANGEBYSCORE"):
        z = DB.setdefault(a[0], {})
        if op == "ZADD":
            z[a[2]] = float(a[1])
            return 1
        if op == "ZREM":
            return sum(z.pop(k, None) is not None for k in a[1:])
        lo, hi = float(a[1]), float("inf") if a[2] == "+inf" else float(a[2])
        hit = sorted((k for k, v in z.items() if lo <= v <= hi), key=z.get)
        if op == "ZREMRANGEBYSCORE":
            for k in hit:
                del z[k]
            return len(hit)
        return hit
    raise ValueError(f"fake redis: {op} not supported")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        cmds = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        out = []
        with LOCK:
            for c in cmds:
                try:
                    out.append({"result": run(c)})
                except Exception as e:  # noqa: BLE001
                    out.append({"error": str(e)})
        body = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}"
