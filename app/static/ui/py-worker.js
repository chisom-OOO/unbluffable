// Coding rounds (decision log 26): the candidate's Python runs here, in a Web Worker with
// Pyodide, never on the server. The page sends { id, code, fn, cases } and gets back each
// case's return value as exact text (ints and fractions as written, floats as repr), or the
// error. The page terminates this worker if a run takes too long.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.js");

const HARNESS = `
import json
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
    ns = {"__name__": "__candidate__"}
    try:
        exec(code, ns)
    except BaseException as e:
        return json.dumps({"compile_error": type(e).__name__ + ": " + str(e)[:300]})
    f = ns.get(fn)
    if not callable(f):
        return json.dumps({"compile_error": "Define " + fn + "(...) as in the signature."})
    out = []
    for args in json.loads(cases_json):
        try:
            out.append({"ok": True, "value": _ub_value(f(*args))})
        except BaseException as e:
            out.append({"ok": False, "error": type(e).__name__ + ": " + str(e)[:200]})
    return json.dumps({"results": out})
`;

const ready = loadPyodide().then((py) => { py.runPython(HARNESS); return py; });
ready.then(() => postMessage({ ready: true }), (e) => postMessage({ failed: String(e) }));

onmessage = async ({ data }) => {
  const py = await ready;
  try {
    const run = py.globals.get("_ub_run");
    postMessage({ id: data.id, ...JSON.parse(run(data.code, data.fn, JSON.stringify(data.cases))) });
  } catch (e) {
    postMessage({ id: data.id, compile_error: String(e).slice(0, 300) });
  }
};
