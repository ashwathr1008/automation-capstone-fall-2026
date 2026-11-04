"""Isolated-process runner for the registry's restricted numerical Python subset."""
import builtins
import json
import math
import statistics
import sys

def limited_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "math": return math
    if name == "statistics": return statistics
    raise ImportError("Only math and statistics are available")

def main():
    payload=json.load(sys.stdin)
    allowed="abs min max sum len range enumerate zip round float int bool str dict list tuple sorted all any isinstance ValueError".split()
    safe={name:getattr(builtins,name) for name in allowed}
    safe["__import__"]=limited_import
    namespace={"__builtins__":safe}
    exec(compile(payload["code"],"<numerical-method>","exec"),namespace,namespace)
    result=namespace["calculate"](payload["inputs"])
    print(json.dumps(result,allow_nan=False))

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}",file=sys.stderr)
        sys.exit(1)
