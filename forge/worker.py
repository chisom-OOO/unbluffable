"""Trusted child harness. No forge/app imports; isolated Python stdlib only."""
import ast
import builtins
import functools
import itertools
import json
import math
import os
import random
import re
import sys
import types
from fractions import Fraction

_JOB = None


class PolicyError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def limits(memory_mb, seconds):
    global _JOB
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                        ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                        ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ("read", "write", "other", "read_bytes", "write_bytes", "other_bytes")]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        _JOB = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x100 | 0x2000 | 0x2
        info.basic.process_time = math.ceil(seconds) * 10000000
        info.process_memory = memory_mb * 1024 * 1024
        if not _JOB or not kernel.SetInformationJobObject(_JOB, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise RuntimeError("resource_limit")
        if not kernel.AssignProcessToJobObject(_JOB, kernel.GetCurrentProcess()):
            raise RuntimeError("resource_limit")
    else:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (math.ceil(seconds),) * 2)


FORBIDDEN = {"open", "eval", "exec", "compile", "getattr", "setattr", "delattr", "globals",
             "locals", "vars", "dir", "type", "object", "super", "input", "help", "breakpoint"}
MODULES = {"math", "fractions", "random", "itertools", "functools"}


def inspect_code(code, mode):
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.Global, ast.Nonlocal)):
            raise PolicyError("forbidden_syntax")
        if isinstance(node, ast.Name) and (node.id.startswith("__") or node.id in FORBIDDEN):
            raise PolicyError("forbidden_name")
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            raise PolicyError("forbidden_attribute_mutation")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in FORBIDDEN):
            raise PolicyError("forbidden_attribute")
        if mode == "sample" and isinstance(node, ast.Attribute) and node.attr in {"seed", "Random"}:
            raise PolicyError("simulator_reseed")
        if isinstance(node, ast.FunctionDef) and node.decorator_list:
            raise PolicyError("decorators_forbidden")
        if isinstance(node, ast.Import):
            if any(alias.name not in MODULES for alias in node.names):
                raise PolicyError("forbidden_import")
        if mode == "sample" and isinstance(node, ast.ImportFrom) and node.module == "random":
            if any(alias.name in {"Random", "seed"} for alias in node.names):
                raise PolicyError("simulator_reseed")
        if isinstance(node, ast.ImportFrom):
            if node.level or node.module not in MODULES or any(a.name.startswith("_") or a.name == "*" for a in node.names):
                raise PolicyError("forbidden_import")
        if isinstance(node, ast.alias) and node.asname and (node.asname.startswith("__") or node.asname in FORBIDDEN):
            raise PolicyError("forbidden_name")
    return tree


def exact(value):
    if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
        raise TypeError("solver_not_exact")
    value = Fraction(value)
    if len(str(value)) > 4096:
        raise PolicyError("numeric_output_too_large")
    return str(value)


def execute(request):
    limits(request["memory_mb"], request["timeout_s"])
    mode = request["mode"]
    tree = inspect_code(request["code"], mode)
    draws = [0]
    def rng_object(seed):
        base = random.Random(seed)
        def wrap(name):
            def draw(*args, **kwargs):
                draws[0] += 1
                return getattr(base, name)(*args, **kwargs)
            return draw
        names = ("random", "randrange", "randint", "choice", "choices", "sample", "shuffle", "uniform",
                 "getrandbits", "triangular", "expovariate", "gammavariate", "betavariate", "gauss",
                 "normalvariate", "paretovariate", "weibullvariate")
        return types.SimpleNamespace(**{name: wrap(name) for name in names})
    rng = rng_object(request["seed"])
    safe_modules = {
        "math": types.SimpleNamespace(**{name: getattr(math, name) for name in dir(math) if not name.startswith("_")}),
        "fractions": types.SimpleNamespace(Fraction=Fraction),
        "itertools": types.SimpleNamespace(**{name: getattr(itertools, name) for name in (
            "product", "permutations", "combinations", "combinations_with_replacement", "accumulate",
            "chain", "islice", "repeat", "count", "cycle", "groupby", "zip_longest", "pairwise")}),
        "functools": types.SimpleNamespace(reduce=functools.reduce, partial=functools.partial),
        "random": types.SimpleNamespace(**vars(rng), Random=rng_object),
    }
    def importer(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name not in safe_modules:
            raise PolicyError("forbidden_import")
        module = safe_modules[name]
        for member in fromlist or ():
            if member.startswith("_") or not hasattr(module, member):
                raise PolicyError("forbidden_import")
        return module
    allowed = ("abs", "all", "any", "bool", "dict", "divmod", "enumerate", "float", "int", "len",
               "list", "max", "min", "pow", "range", "reversed", "round", "set", "sorted", "str",
               "sum", "tuple", "zip", "next", "iter", "map", "filter", "isinstance", "Exception", "ValueError", "ArithmeticError", "ZeroDivisionError")
    safe_builtins = {name: getattr(builtins, name) for name in allowed}
    safe_builtins["__import__"] = importer
    scope = {"__builtins__": safe_builtins}
    def audit(event, args):
        if (event == "open" or event.startswith(("socket.", "subprocess.", "ctypes.", "os.exec",
                                                "os.spawn", "os.system", "os.fork"))):
            raise PermissionError("forbidden_capability")
    sys.addaudithook(audit)
    compiled = compile(tree, "<generated>", "exec")
    def parameters(raw):
        if request.get("structured_params"):
            def freeze(value, depth=0):
                if depth > 20:
                    raise PolicyError("parameter_depth")
                if isinstance(value, dict):
                    return types.MappingProxyType({key: freeze(item, depth + 1) for key, item in value.items()})
                if isinstance(value, list):
                    return tuple(freeze(item, depth + 1) for item in value)
                if isinstance(value, float):
                    if not math.isfinite(value):
                        raise PolicyError("invalid_parameter")
                    return Fraction(str(value))
                if isinstance(value, str):
                    literal = value.strip()
                    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|[+-]?\d+\s*/\s*[+-]?\d+", literal):
                        exponent = re.search(r"[eE]([+-]?\d+)$", literal)
                        if len(literal) > 512 or (exponent and abs(int(exponent[1])) > 1000):
                            raise PolicyError("parameter_numeric_limit")
                        try:
                            return Fraction(*(int(part) for part in literal.split("/"))) if "/" in literal else Fraction(literal)
                        except (ValueError, ZeroDivisionError):
                            raise PolicyError("invalid_numeric_parameter") from None
                    return value
                if value is None or isinstance(value, (int, bool)):
                    return value
                raise PolicyError("invalid_parameter")
            if not isinstance(raw, dict):
                raise PolicyError("invalid_parameter")
            return freeze(raw)
        values = {key: Fraction(str(value)) for key, value in raw.items()}
        return types.MappingProxyType({key: int(value) if value.denominator == 1 else value for key, value in values.items()})
    if mode == "solve":
        def solve_one(raw_params):
            # Fresh generated globals at every point; no cross-variant state.
            local_scope = {"__builtins__": safe_builtins}
            exec(compiled, local_scope)
            raw = local_scope["solve"](parameters(raw_params))
            if draws[0]:
                raise PolicyError("random_solver")
            if isinstance(raw, dict):
                answer, steps = raw["answer"], raw.get("steps", {})
            else:
                answer, steps = raw, {}
            if not isinstance(steps, dict) or len(steps) > 64:
                raise PolicyError("invalid_steps")
            return {"answer": exact(answer), "steps": [{"name": str(k), "value": exact(v)} for k, v in steps.items()]}
        if "batch_params" in request:
            return {"results": [solve_one(params) for params in request["batch_params"]]}
        return solve_one(request["params"])
    params = parameters(request["params"])
    samples = request["trials"]
    total, squares = Fraction(0), Fraction(0)
    for _ in range(samples):
        before = draws[0]
        # Rebuild generated globals for every independent draw. Parameters and
        # shared module/RNG facades cannot be mutated by generated code.
        sample_scope = {"__builtins__": safe_builtins}
        exec(compiled, sample_scope)
        value = sample_scope["sample"](params, rng)
        if draws[0] == before:
            raise PolicyError("simulator_no_random_event")
        if isinstance(value, bool):
            value = int(value)
        if not isinstance(value, (int, float, Fraction)) or not math.isfinite(float(value)):
            raise PolicyError("invalid_sample")
        value = Fraction(str(value)) if isinstance(value, float) else Fraction(value)
        total += value
        squares += value * value
    mean = total / samples
    variance = (squares - total * total / samples) / (samples - 1)
    return {"mean": str(mean), "se": math.sqrt(float(variance / samples)), "trials": samples, "draws": draws[0]}


if __name__ == "__main__":
    try:
        result = execute(json.loads(sys.stdin.read(150001)))
        output = {"ok": True, "result": result}
    except BaseException as error:
        output = {"ok": False, "error": error.reason if isinstance(error, PolicyError) else type(error).__name__}
    sys.stdout.write(json.dumps(output))
