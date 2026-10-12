#!/usr/bin/env python3
"""tool-call-replay: record agent tool-call sequences, replay them deterministically.

Single-process, zero-network. A "script" is a JSON list of tool calls executed
against a registry of pure-Python callables. `record` produces a snapshot with
results (and errors); `replay` either mocks the tools (signature check only) or
re-executes them (`verify`) and reports per-call side-effect diffs.
"""
import argparse
import importlib.util
import inspect
import json
import sys

SNAPSHOT_VERSION = 1
DETAIL_LIMIT = 200


# ---------------------------------------------------------------- registry

class ToolRegistry:
    """Name -> callable mapping for tools exposed to the recorded script."""

    def __init__(self):
        self._tools = {}

    def register(self, name=None):
        def deco(fn):
            if not callable(fn):
                raise TypeError("register expects a callable")
            self._tools[name or fn.__name__] = fn
            return fn
        return deco

    def register_function(self, name, fn):
        if not callable(fn):
            raise TypeError("tool %r is not callable" % (name,))
        self._tools[name] = fn

    def get(self, name):
        return self._tools.get(name)

    def names(self):
        return sorted(self._tools)


def load_tools_module(path):
    """Import a .py file and return its TOOLS dict ({name: callable})."""
    spec = importlib.util.spec_from_file_location("tcr_tools_mod", path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load tools module from %s" % path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001
        raise ValueError("tools module raised on import: %s: %s"
                         % (type(e).__name__, e))
    tools = getattr(mod, "TOOLS", None)
    if tools is None:
        raise ValueError("tools module %s has no TOOLS dict" % path)
    if not isinstance(tools, dict):
        raise ValueError("TOOLS must be a dict of name -> callable")
    for name, fn in tools.items():
        if not callable(fn):
            raise ValueError("tool %r is not callable" % (name,))
    return tools


# ---------------------------------------------------------------- script / snapshot

def load_script(path):
    """Load and validate a script file -> list of call dicts."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return parse_script_text(text)


def parse_script_text(text):
    if not text.strip():
        raise ValueError("empty script: no calls")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError("invalid script JSON: %s" % e)
    if isinstance(data, dict) and "calls" in data:
        data = data["calls"]
    if not isinstance(data, list):
        raise ValueError("script must be a list of calls")
    for i, call in enumerate(data):
        if not isinstance(call, dict) or "name" not in call:
            raise ValueError("call %d: expected object with a 'name' field" % i)
        if "args" in call and not isinstance(call["args"], list):
            raise ValueError("call %d: 'args' must be a list" % i)
        if "kwargs" in call and not isinstance(call["kwargs"], dict):
            raise ValueError("call %d: 'kwargs' must be an object" % i)
    return data


def _jsonable(x):
    """Return (ok, stored): JSON value if serializable, else repr string."""
    try:
        json.dumps(x)
        return True, x
    except (TypeError, ValueError):
        return False, repr(x)


def record(calls, registry):
    """Execute calls in order; return a snapshot dict."""
    entries = []
    for i, call in enumerate(calls):
        name = call["name"]
        args = list(call.get("args", []))
        kwargs = dict(call.get("kwargs", {}))
        fn = registry.get(name)
        if fn is None:
            raise ValueError("call %d: unknown tool %r (have: %s)"
                             % (i, name, ", ".join(registry.names()) or "none"))
        entry = {"index": i, "name": name, "args": args, "kwargs": kwargs}
        try:
            result = fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            ok, err = _jsonable("%s: %s" % (type(e).__name__, e))
            entry.update({"ok": False, "error": err})
        else:
            ok, stored = _jsonable(result)
            entry.update({"ok": True, "result": stored})
            if not ok:
                entry["result_repr"] = True
        entries.append(entry)
    return {"format_version": SNAPSHOT_VERSION,
            "recorded_with": "tool-call-replay",
            "calls": entries}


def save_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)


# ---------------------------------------------------------------- replay

def _load_snapshot(path):
    with open(path, "r", encoding="utf-8") as f:
        try:
            snap = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError("invalid snapshot JSON: %s" % e)
    if not isinstance(snap, dict) or not isinstance(snap.get("calls"), list):
        raise ValueError("snapshot must be an object with a 'calls' list")
    return snap


def _binds(fn, args, kwargs):
    """True if args/kwargs can bind to fn's signature."""
    try:
        inspect.signature(fn).bind(*args, **kwargs)
        return True, None
    except TypeError as e:
        return False, str(e)


def _same_recorded(actual_ok, actual, recorded_entry):
    """Compare an executed outcome against a recorded outcome."""
    if recorded_entry.get("ok", True):
        if not actual_ok:
            return False, "unexpected_error"
        exp = recorded_entry.get("result")
        _, act = _jsonable(actual)
        if exp == act:
            return True, "match"
        return False, "result_diff"
    else:
        if actual_ok:
            return False, "expected_error_but_ok"
        err = "%s: %s" % (type(actual).__name__, actual)
        if recorded_entry.get("error") == err:
            return True, "match"
        return False, "error_diff"


def _trunc(s):
    return s if len(s) <= DETAIL_LIMIT else s[:DETAIL_LIMIT - 3] + "..."


def replay(snap, registry, mode="verify"):
    """Replay snapshot calls; return a report dict.

    mode "mock": never execute; only check the tool exists and the recorded
    args/kwargs still bind to its signature.
    mode "verify": actually execute each call and diff results vs recorded.
    """
    if mode not in ("mock", "verify"):
        raise ValueError("mode must be 'mock' or 'verify'")
    if not isinstance(snap, dict) or not isinstance(snap.get("calls"), list):
        raise ValueError("snapshot must be an object with a 'calls' list")
    calls = []
    summary = {"total": 0, "match": 0, "missing_tool": 0,
               "signature_error": 0, "diff": 0}
    for entry in snap["calls"]:
        summary["total"] += 1
        name = entry.get("name")
        args = entry.get("args", [])
        kwargs = entry.get("kwargs", {})
        out = {"index": entry.get("index"), "name": name}
        fn = registry.get(name)
        if fn is None:
            out.update(status="missing_tool", detail="tool %r not registered" % (name,))
            summary["missing_tool"] += 1
            calls.append(out)
            continue
        if mode == "mock":
            ok, err = _binds(fn, args, kwargs)
            if ok:
                out.update(status="match", detail="signature binds")
                summary["match"] += 1
            else:
                out.update(status="signature_error", detail=_trunc(err or ""))
                summary["signature_error"] += 1
            calls.append(out)
            continue
        try:
            result = fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            same, status = _same_recorded(False, e, entry)
            out.update(status=status, detail=_trunc("%s: %s" % (type(e).__name__, e)))
            if same:
                summary["match"] += 1
            else:
                summary["diff"] += 1
            calls.append(out)
            continue
        same, status = _same_recorded(True, result, entry)
        if same:
            out.update(status="match", detail="result identical")
            summary["match"] += 1
        else:
            detail = ""
            if status == "result_diff":
                detail = _trunc("recorded=%s current=%s" % (
                    json.dumps(entry.get("result"), default=repr),
                    json.dumps(result, default=repr)))
            elif status == "expected_error_but_ok":
                detail = "recorded an error; current call succeeded"
            out.update(status=status, detail=detail)
            summary["diff"] += 1
        calls.append(out)
    return {"format_version": SNAPSHOT_VERSION, "mode": mode,
            "summary": summary, "calls": calls}


# ---------------------------------------------------------------- CLI

def cmd_record(args):
    tools = load_tools_module(args.tools)
    registry = ToolRegistry()
    for name, fn in tools.items():
        registry.register_function(name, fn)
    calls = load_script(args.script)
    snap = record(calls, registry)
    save_json(snap, args.output)
    n_err = sum(1 for c in snap["calls"] if not c.get("ok"))
    print("snapshot written: %d calls (%d errors) -> %s"
          % (len(snap["calls"]), n_err, args.output))
    return 0


def cmd_replay(args):
    tools = load_tools_module(args.tools)
    registry = ToolRegistry()
    for name, fn in tools.items():
        registry.register_function(name, fn)
    snap = _load_snapshot(args.snapshot)
    rep = replay(snap, registry, mode=args.mode)
    if args.report:
        save_json(rep, args.report)
    s = rep["summary"]
    print("replay[%s]: total=%d match=%d diff=%d missing_tool=%d signature_error=%d"
          % (rep["mode"], s["total"], s["match"], s["diff"],
             s["missing_tool"], s["signature_error"]))
    for c in rep["calls"]:
        if c["status"] != "match":
            print("  #%s %s -> %s %s" % (c["index"], c["name"], c["status"],
                                         c.get("detail", "")))
    bad = s["diff"] + s["missing_tool"] + s["signature_error"]
    return 1 if bad else 0


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="tool-call-replay",
        description="Record agent tool-call sequences and replay them deterministically.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="execute a call script and snapshot results")
    r.add_argument("--script", required=True, help="script JSON (list of calls)")
    r.add_argument("--tools", required=True, help="Python file exposing a TOOLS dict")
    r.add_argument("-o", "--output", required=True)
    r.set_defaults(fn=cmd_record)

    pl = sub.add_parser("replay", help="replay a snapshot against current tools")
    pl.add_argument("snapshot")
    pl.add_argument("--tools", required=True)
    pl.add_argument("--mode", choices=["mock", "verify"], default="verify")
    pl.add_argument("--report", help="write full JSON report to this path")
    pl.set_defaults(fn=cmd_replay)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
