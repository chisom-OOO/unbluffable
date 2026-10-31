// Coding rounds (decision log 26): the candidate's Python runs here, in a Web Worker with
// Pyodide, never on the server. The page sends { id, code, fn, cases } and gets back each
// case's return value as exact text (ints and fractions as written, floats as repr), or the
// error, and what the code printed (the console's Output tab). The page terminates this
// worker if a run takes too long.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.js");

const HARNESS = `
import io
import json
import sys
from fractions import Fraction

def _ub_value(v):
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

const ready = loadPyodide().then((py) => { py.runPython(HARNESS); return py; });
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
    const run = py.globals.get("_ub_run");
    postMessage({ id: data.id, ...JSON.parse(run(data.code, data.fn, JSON.stringify(data.cases))) });
  } catch (e) {
    postMessage({ id: data.id, compile_error: String(e).slice(0, 300) });
  }
};
