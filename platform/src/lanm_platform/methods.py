"""Small versioned method registry. Draft code is checked outside the web process.

Generated numerical methods use a deliberately restricted Python subset. This is
not a general-purpose Python hosting service. Wider scientific packages can be
added as reviewed built-in tools without changing stored project evidence.
"""
from __future__ import annotations
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
from . import economics

BUILTIN = economics.METHOD_ID
_ID = re.compile(r"^[a-z][a-z0-9_-]{2,64}$")
_IMPORTS = {"math", "statistics"}
_CALLS = {"abs", "min", "max", "sum", "len", "range", "enumerate", "zip", "round", "float", "int", "bool", "str", "dict", "list", "tuple", "sorted", "all", "any", "isinstance", "ValueError"}
_FORBIDDEN = (ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom, ast.Global, ast.Nonlocal, ast.With, ast.AsyncWith, ast.Delete)

def _json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)

def validate_source(code):
    if len(code.encode()) > 64000:
        raise ValueError("Method source exceeds the 64 KB limit")
    tree = ast.parse(code)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    if "calculate" not in names:
        raise ValueError("A method must define calculate(inputs)")
    for n in ast.walk(tree):
        if isinstance(n, _FORBIDDEN):
            raise ValueError(f"Unsupported numerical-method construct: {type(n).__name__}")
        if isinstance(n, (ast.Name, ast.arg)) and (getattr(n, "id", getattr(n, "arg", "")).startswith("_")):
            raise ValueError("Private names are not permitted in numerical methods")
        if isinstance(n, ast.Attribute) and n.attr.startswith("_"):
            raise ValueError("Private attributes are not permitted")
        if isinstance(n, ast.Import):
            if any(a.name not in _IMPORTS for a in n.names):
                raise ValueError("Only math and statistics imports are available")
        if isinstance(n, ast.ImportFrom) and (n.module not in _IMPORTS or n.level or any(a.name.startswith("_") or a.name == "*" for a in n.names)):
            raise ValueError("Only named math/statistics imports are available")
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id not in _CALLS | names | {"sqrt", "exp", "log", "log10", "ceil", "floor", "isfinite", "mean", "median", "stdev"}:
            raise ValueError(f"Call {n.func.id!r} is not available in a numerical method")
        if isinstance(n, ast.Constant) and isinstance(n.value, (str, bytes)) and len(n.value) > 10000:
            raise ValueError("Oversized literal")
    return tree

def execute_source(code, inputs, timeout=8):
    validate_source(code)
    payload = json.dumps({"code": code, "inputs": inputs}, allow_nan=False)
    result = subprocess.run([sys.executable, "-I", "-S", str(Path(__file__).with_name("method_worker.py"))], input=payload, text=True,
                            capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise ValueError((result.stderr or result.stdout or "Method execution failed")[-3000:])
    if len(result.stdout) > 1_000_000:
        raise ValueError("Method output exceeds 1 MB")
    output = json.loads(result.stdout)
    if not isinstance(output, dict):
        raise ValueError("calculate(inputs) must return a JSON object")
    return output

def _matches(actual, expected, tolerance):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _matches(actual[k], v, tolerance) for k,v in expected.items())
    if isinstance(expected, (int,float)) and not isinstance(expected,bool):
        return isinstance(actual,(int,float)) and abs(actual-expected) <= tolerance * max(1,abs(expected))
    return actual == expected

class Registry:
    def __init__(self, data_dir):
        self.root = Path(data_dir) / "methods"
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "drafts").mkdir(exist_ok=True)
        (self.root / "versions").mkdir(exist_ok=True)

    def _draft(self, method_id):
        if not _ID.fullmatch(method_id):
            raise ValueError("Method ID must contain only lowercase letters, numbers, underscores or hyphens")
        return self.root / "drafts" / method_id

    def create_draft(self, method_id, manifest, code):
        path = self._draft(method_id)
        validate_source(code)
        required = ("name", "description", "boundary", "assumptions", "inputs", "references", "reference_cases")
        if any(k not in manifest for k in required):
            raise ValueError("Manifest requires name, description, boundary, assumptions, inputs, references and reference_cases")
        if not isinstance(manifest["inputs"], dict) or not isinstance(manifest["reference_cases"], list):
            raise ValueError("inputs must be an object; reference_cases must be a list")
        path.mkdir(parents=True, exist_ok=True)
        _json(path / "manifest.json", {**manifest, "id": method_id, "status": "draft", "created_at": time.time()})
        (path / "method.py").write_text(code, encoding="utf-8")
        (path / "checks.json").unlink(missing_ok=True)
        return self.get(method_id)

    def get(self, method_id):
        if method_id in {BUILTIN,"separation-unit-v1"}:
            manifest=economics.manifest()
            return {**manifest,"status":"built-in","inputs":manifest["input_schema"],
                    "validation":"Numerical checks; not industrial scale validation", "source":Path(economics.__file__).read_text(encoding="utf-8")}
        if "@" in method_id:
            base, version = method_id.split("@",1)
            self._draft(base)
            if not re.fullmatch(r"[a-f0-9]{12}",version):
                raise ValueError("Invalid version")
            path = self.root / "versions" / (base + "@" + version)
        else:
            path = self._draft(method_id)
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        code = (path / "method.py").read_text(encoding="utf-8")
        digest = hashlib.sha256((json.dumps({k:v for k,v in manifest.items() if k not in {"status","created_at","version","registered_at","checks"}},sort_keys=True)+code).encode()).hexdigest()
        checks = json.loads((path / "checks.json").read_text()) if (path / "checks.json").exists() else None
        return {**manifest,"id":method_id,"source":code,"digest":digest,"checks":checks,"path":str(path)}

    def list(self):
        rows = [self.get(BUILTIN)]
        for directory in [self.root / "drafts",self.root / "versions"]:
            for path in sorted(directory.iterdir()):
                if path.is_dir() and (path / "manifest.json").exists():
                    try:
                        rows.append(self.get(path.name))
                    except (ValueError,OSError):
                        continue
        return [{k:v for k,v in row.items() if k not in {"source","path"}} for row in rows]

    def check(self, method_id):
        if "@" in method_id or method_id == BUILTIN:
            raise ValueError("Checks are run against draft methods; registered versions are immutable")
        method = self.get(method_id)
        cases = method.get("reference_cases",[])
        if not cases:
            raise ValueError("At least one reference case with independently stated expected outputs is required")
        results=[]
        for case in cases:
            if not case.get("basis") or "inputs" not in case or "expected" not in case or not case["expected"]:
                raise ValueError("Each reference case needs inputs, nonempty expected outputs and a basis")
            try:
                actual=execute_source(method["source"],case["inputs"])
                passed=_matches(actual,case["expected"],float(case.get("relative_tolerance",1e-7)))
                results.append({"name":case.get("name","Reference case"),"passed":passed,"expected":case["expected"],"actual":actual,"basis":case["basis"]})
            except Exception as exc:
                results.append({"name":case.get("name","Reference case"),"passed":False,"error":str(exc)})
        report={"passed":all(c["passed"] for c in results),"cases":results,"digest":method["digest"],"checked_at":time.time(),"qualification":"Numerical agreement with declared references; this does not validate the scientific assumptions."}
        _json(self._draft(method_id)/"checks.json",report)
        return report

    def register(self, method_id):
        method=self.get(method_id)
        checks=method.get("checks")
        if not checks or not checks.get("passed") or checks.get("digest") != method["digest"]:
            raise ValueError("Run passing reference checks against the current draft before registering")
        version=method["digest"][:12]
        destination=self.root/"versions"/(method_id+"@"+version)
        if not destination.exists():
            destination.mkdir()
            source=self._draft(method_id)
            manifest=json.loads((source/"manifest.json").read_text())
            _json(destination/"manifest.json",{**manifest,"status":"registered","version":version,"registered_at":time.time()})
            (destination/"method.py").write_text(method["source"],encoding="utf-8")
            _json(destination/"checks.json",checks)
        return self.get(destination.name)

    def run(self, method_id, inputs):
        if "@" not in method_id:
            raise ValueError("Analysis requires an explicitly registered method version")
        method=self.get(method_id)
        checks=method.get("checks") or {}
        if method["digest"][:12] != method.get("version") or checks.get("digest") != method["digest"] or not checks.get("passed"):
            raise ValueError("Registered method content no longer matches its checked version; restore it or register a new draft")
        if not isinstance(inputs,dict) or set(inputs)-set(method["inputs"]):
            raise ValueError("Inputs must use the method's declared parameter names")
        for key,spec in method["inputs"].items():
            if key not in inputs and isinstance(spec,dict) and "default" in spec:
                inputs[key]=spec["default"]
            if key not in inputs:
                raise ValueError(f"Required method input: {key}")
            if isinstance(spec,dict):
                value=inputs[key]
                kind=spec.get("type","number")
                valid={"number":lambda:isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value),
                       "integer":lambda:isinstance(value,int) and not isinstance(value,bool),
                       "string":lambda:isinstance(value,str),"boolean":lambda:isinstance(value,bool),
                       "array":lambda:isinstance(value,list),"object":lambda:isinstance(value,dict)}
                if kind not in valid or not valid[kind](): raise ValueError(f"{key} must have declared type {kind}")
                if kind in {"number","integer"}:
                    if "minimum" in spec and value<spec["minimum"]: raise ValueError(f"{key} is below its declared minimum")
                    if "maximum" in spec and value>spec["maximum"]: raise ValueError(f"{key} is above its declared maximum")
        return {"method_id":method_id,"method_version":method["version"],"inputs":inputs,"outputs":execute_source(method["source"],inputs),"boundary":method["boundary"],"assumptions":method["assumptions"],"qualification":"Registered numerical method; scientific validity remains conditional on its documented assumptions."}
