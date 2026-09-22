"""python_eval sandbox child. Reads {code, root, allowed} JSON on stdin; prints one JSON line.

Isolation: launched with -I -S; audit hook denies open() outside the corpus, all sockets, subprocess,
os.system/exec; resource limits on CPU and address space; the exec namespace has no open/import builtins.
"""
import json, sys, math, statistics, csv, io, resource

def main():
    req = json.loads(sys.stdin.read()); root = req["root"].rstrip("/") + "/"; allowed = {root + a for a in req["allowed"]}
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5)); resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    except Exception: pass
    DENY = ("socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.fork", "os.spawn", "shutil.", "ctypes.", "os.remove", "os.rename", "os.unlink", "os.rmdir", "os.mkdir", "os.chmod")
    def hook(event, args):
        if event == "open":
            path = str(args[0]) if args and args[0] is not None else ""
            mode = str(args[1]) if len(args) > 1 and args[1] else "r"
            if path not in allowed or any(c in mode for c in "wa+x"):
                raise PermissionError(f"sandbox: open denied for {path!r}")
        if event.startswith(DENY):
            raise PermissionError(f"sandbox: {event} denied")
    sys.addaudithook(hook)
    def _read(rel):
        p = root + rel
        if p not in allowed: raise PermissionError(f"{rel} is not a permitted corpus file")
        with open(p, encoding="utf-8") as f: return f.read()
    def csv_rows(rel): return list(csv.DictReader(io.StringIO(_read(rel))))
    def json_load(rel): return json.loads(_read(rel))
    safe = {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
            for k in ("abs", "all", "any", "dict", "enumerate", "float", "int", "len", "list", "max", "min", "range", "round", "set", "sorted", "str", "sum", "tuple", "zip", "bool", "isinstance")}
    out = io.StringIO()
    env = {"__builtins__": safe, "csv_rows": csv_rows, "json_load": json_load, "read_text": _read,
           "mean": statistics.mean, "median": statistics.median, "stdev": statistics.stdev, "math": math, "result": None,
           "print": lambda *a, **k: print(*a, file=out, **k)}
    try:
        exec(req["code"], env)  # noqa: S102
        res = env.get("result")
        try: json.dumps(res)
        except Exception: res = repr(res)
        print(json.dumps({"status": "ok", "result": res, "stdout": out.getvalue()[:8000]}))
    except BaseException as e:  # noqa: BLE001
        print(json.dumps({"status": "error", "error": repr(e)[:500], "stdout": out.getvalue()[:8000]}))

if __name__ == "__main__":
    main()
