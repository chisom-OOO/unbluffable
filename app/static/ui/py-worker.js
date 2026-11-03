// Coding rounds (decision log 26): the candidate's Python runs here, in a Web Worker with
// Pyodide, never on the server. The page sends { id, code, fn, cases } and gets back each
// case's return value as exact text (ints and fractions as written, floats as repr), or the
// error, and what the code printed (the console's Output tab). The page terminates this
// worker if a run takes too long.
//
// Decision log 42: importScripts has no integrity option, so pyodide.js is fetched, checked
// against its SHA-384 and only then run (from a blob of the checked bytes). Its WASM and
// packages, which Pyodide loads itself from INDEX, are not checked here.
const INDEX = "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/";
const PYODIDE_SHA384 = "tVslJOEkg7nVRW3Y3/ReGX0NnonNrbcmt1R5qFbQXQdGa2chRkoJYHAjAsv3zoTq";

async function checkedPyodide() {
  const response = await fetch(INDEX + "pyodide.js", { credentials: "omit" });
  if (!response.ok) throw new Error("Python could not be downloaded.");
  const bytes = await response.arrayBuffer();
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-384", bytes));
  if (btoa(String.fromCharCode(...digest)) !== PYODIDE_SHA384) throw new Error("Python failed its integrity check.");
  const url = URL.createObjectURL(new Blob([bytes], { type: "text/javascript" }));
  try { importScripts(url); } finally { URL.revokeObjectURL(url); }
  return loadPyodide({ indexURL: INDEX });
}

const HARNESS = `
import io
import json
import sys
from fractions import Fraction

def _ub_plain(v):
    if isinstance(v, (list, tuple)):
        return [_ub_plain(x) for x in v]
    if isinstance(v, (bool, int, str)) or v is None:
        return v
    if isinstance(v, Fraction) and v.denominator == 1:
        return int(v)
    raise TypeError("not a plain value")

def _ub_value(v):
    if isinstance(v, (list, tuple)):  # a list answer: canonical JSON, compared exactly
        try:
            return json.dumps(_ub_plain(v), separators=(",", ":"))[:4000]
        except TypeError:
            return repr(v)[:200]
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, Fraction):
        return str(v)
    return repr(v)[:200]

def _ub_run(code, fn, cases_json):
    printed, real = io.StringIO(), sys.stdout
    sys.stdout = printed
    try:
        return _ub_cases(code, fn, cases_json, printed)
    finally:
        sys.stdout = real

def _ub_cases(code, fn, cases_json, printed):
    shown = lambda: printed.getvalue()[-4000:]
    ns = {"__name__": "__candidate__"}
    try:
        exec(code, ns)
    except BaseException as e:
        return json.dumps({"compile_error": type(e).__name__ + ": " + str(e)[:300], "stdout": shown()})
    f = ns.get(fn)
    if not callable(f):
        return json.dumps({"compile_error": "Define " + fn + "(...) as in the signature.", "stdout": shown()})
    out = []
    for args in json.loads(cases_json):
        try:
            out.append({"ok": True, "value": _ub_value(f(*args))})
        except BaseException as e:
            out.append({"ok": False, "error": type(e).__name__ + ": " + str(e)[:200]})
    return json.dumps({"results": out, "stdout": shown()})

# Class specs ("implement the component"): build the class with each test's init arguments,
# replay its calls, and return the list of return values (None for a call that returns nothing).
def _ub_run_class(code, cls, cases_json):
    printed, real = io.StringIO(), sys.stdout
    sys.stdout = printed
    try:
        ns = {"__name__": "__candidate__"}
        try:
            exec(code, ns)
        except BaseException as e:
            return json.dumps({"compile_error": type(e).__name__ + ": " + str(e)[:300], "stdout": printed.getvalue()[-4000:]})
        C = ns.get(cls)
        if not isinstance(C, type):
            return json.dumps({"compile_error": "Define class " + cls + " as in the starter.", "stdout": printed.getvalue()[-4000:]})
        out = []
        for case in json.loads(cases_json):
            try:
                obj = C(*case["init"])
                values = []
                for name, args in case["ops"]:
                    r = getattr(obj, name)(*args)
                    values.append(None if r is None else _ub_value(r))
                out.append({"ok": True, "values": values})
            except BaseException as e:
                out.append({"ok": False, "error": type(e).__name__ + ": " + str(e)[:200]})
        return json.dumps({"results": out, "stdout": printed.getvalue()[-4000:]})
    finally:
        sys.stdout = real

# Part 2 (decision log 29): build one large input with the forge's own generator source, then
# time only the candidate's function on it.
def _ub_scale(code, fn, generator, config_json, keys_json, seed, n):
    import time
    printed, real = io.StringIO(), sys.stdout
    sys.stdout = printed
    try:
        gen_ns = {}
        exec(generator, gen_ns)
        params = gen_ns["generate"](json.loads(config_json), seed, n)
        args = [params[k] for k in json.loads(keys_json)]
        ns = {"__name__": "__candidate__"}
        try:
            exec(code, ns)
        except BaseException as e:
            return json.dumps({"compile_error": type(e).__name__ + ": " + str(e)[:300]})
        f = ns.get(fn)
        if not callable(f):
            return json.dumps({"compile_error": "Define " + fn + "(...) as in the signature."})
        began = time.perf_counter()
        try:
            value = f(*args)
        except BaseException as e:
            return json.dumps({"ok": False, "error": type(e).__name__ + ": " + str(e)[:200]})
        ms = (time.perf_counter() - began) * 1000
        return json.dumps({"ok": True, "value": _ub_value(value), "ms": round(ms, 1)})
    finally:
        sys.stdout = real
`;

const ready = checkedPyodide().then((py) => { py.runPython(HARNESS); return py; });
ready.then(() => postMessage({ ready: true }), (e) => postMessage({ failed: String(e) }));

onmessage = async ({ data }) => {
  const py = await ready;
  if (data.scale) {
    try {
      const s = data.scale;
      const out = py.globals.get("_ub_scale")(data.code, data.fn, s.generator, JSON.stringify(s.config), JSON.stringify(s.keys), s.seed, s.n);
      postMessage({ id: data.id, scale: JSON.parse(out) });
    } catch (e) {
      postMessage({ id: data.id, scale: { ok: false, error: String(e).slice(0, 300) } });
    }
    return;
  }
  try {
    if (data.cls) {
      postMessage({ id: data.id, ...JSON.parse(py.globals.get("_ub_run_class")(data.code, data.cls, JSON.stringify(data.cases))) });
      return;
    }
    const run = py.globals.get("_ub_run");
    postMessage({ id: data.id, ...JSON.parse(run(data.code, data.fn, JSON.stringify(data.cases))) });
  } catch (e) {
    postMessage({ id: data.id, compile_error: String(e).slice(0, 300) });
  }
};
