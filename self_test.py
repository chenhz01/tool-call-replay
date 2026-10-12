#!/usr/bin/env python3
"""Self-test for tool-call-replay. Run: python self_test.py"""
import contextlib
import io
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tool_call_replay as tcr

TESTS = []


def t(fn):
    TESTS.append(fn)
    return fn


TD = None
HERE = os.path.dirname(os.path.abspath(__file__))
DEMO_TOOLS = os.path.join(HERE, "demo_tools.py")


def setup():
    global TD
    TD = tempfile.mkdtemp(prefix="tcr_test_")


def wp(name):
    return os.path.join(TD, name)


def wj(name, obj):
    p = wp(name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return p


def reg():
    tools = tcr.load_tools_module(DEMO_TOOLS)
    r = tcr.ToolRegistry()
    for n, f in tools.items():
        r.register_function(n, f)
    return r


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = tcr.main(argv)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 0
    return code, out.getvalue(), err.getvalue()


def calls(*lst):
    return list(lst)


def rec(c_list, r=None):
    return tcr.record(c_list, r if r is not None else reg())


# ---------------- [A] functional

@t
def a01_record_snapshot_shape():
    snap = rec(tcr.parse_script_text('[{"name":"add","args":[1,2]}]'))
    assert snap["format_version"] == 1 and snap["recorded_with"] == "tool-call-replay"
    assert len(snap["calls"]) == 1


@t
def a02_result_recorded():
    snap = rec([{"name": "add", "args": [2, 3]}])
    assert snap["calls"][0]["ok"] is True and snap["calls"][0]["result"] == 5


@t
def a03_kwargs_recorded():
    snap = rec([{"name": "bounded_scale", "args": [3], "kwargs": {"factor": 4}}])
    assert snap["calls"][0]["result"] == 12


@t
def a04_error_recorded():
    snap = rec([{"name": "fail"}])
    c = snap["calls"][0]
    assert c["ok"] is False and "ValueError: boom" in c["error"]


@t
def a05_mock_replay_all_match():
    snap = rec([{"name": "add", "args": [1, 2]}, {"name": "greet", "args": ["x"]}])
    rep = tcr.replay(snap, reg(), mode="mock")
    assert rep["summary"]["match"] == 2 and rep["summary"]["total"] == 2


@t
def a06_mock_signature_ok():
    rep = tcr.replay(rec([{"name": "bounded_scale", "args": [1], "kwargs": {"factor": 2}}]),
                     reg(), mode="mock")
    assert rep["calls"][0]["status"] == "match"


@t
def a07_verify_match():
    rep = tcr.replay(rec([{"name": "add", "args": [1, 2]}]), reg(), mode="verify")
    assert rep["calls"][0]["status"] == "match"


@t
def a08_verify_result_diff():
    snap = rec([{"name": "add", "args": [1, 2]}])
    snap["calls"][0]["result"] = 99
    rep = tcr.replay(snap, reg(), mode="verify")
    assert rep["calls"][0]["status"] == "result_diff" and rep["summary"]["diff"] == 1


@t
def a09_verify_error_diff():
    snap = rec([{"name": "fail"}])
    snap["calls"][0]["error"] = "ValueError: different"
    rep = tcr.replay(snap, reg(), mode="verify")
    assert rep["calls"][0]["status"] == "error_diff"


@t
def a10_verify_unexpected_error():
    snap = rec([{"name": "bounded_scale", "args": [1.0]}])
    snap["calls"][0]["result"] = 2.0
    # break the tool: bounded_scale with factor>100 raises; use kwargs drift instead
    # simulate drift by recording a wrong result while the tool raises
    snap2 = rec([{"name": "fail"}])
    snap2["calls"][0]["ok"] = True
    snap2["calls"][0]["result"] = None
    rep = tcr.replay(snap2, reg(), mode="verify")
    assert rep["calls"][0]["status"] == "unexpected_error"


@t
def a11_missing_tool():
    rep = tcr.replay(rec([{"name": "add", "args": [1, 1]}]), reg(), mode="mock")
    rep["calls"][0]["name"] = "ghost"
    rep2 = tcr.replay({"format_version": 1, "calls": rep["calls"]}, reg(), mode="mock")
    assert rep2["calls"][0]["status"] == "missing_tool"


@t
def a12_expected_error_but_ok():
    snap = rec([{"name": "fail"}])
    # tool drift: the same call now succeeds
    snap["calls"][0].update(name="add", args=[1, 2])
    rep = tcr.replay(snap, reg(), mode="verify")
    assert rep["calls"][0]["status"] == "expected_error_but_ok"


@t
def a13_recorded_error_matches():
    rep = tcr.replay(rec([{"name": "fail"}]), reg(), mode="verify")
    assert rep["calls"][0]["status"] == "match" and rep["summary"]["diff"] == 0


@t
def a14_deterministic_reports():
    snap = rec([{"name": "slugify", "args": ["Hello World!"]}])
    r1 = tcr.replay(snap, reg(), mode="verify")
    r2 = tcr.replay(snap, reg(), mode="verify")
    assert json.dumps(r1["calls"]) == json.dumps(r2["calls"])


@t
def a15_cli_record():
    script = wj("s.json", {"calls": [{"name": "greet", "args": ["world"]}]})
    code, out, _ = run_cli(["record", "--script", script, "--tools", DEMO_TOOLS,
                            "-o", wp("snap.json")])
    assert code == 0 and "snapshot written" in out


@t
def a16_cli_replay_ok_exit0():
    script = wj("s.json", [{"name": "greet", "args": ["world"]}])
    run_cli(["record", "--script", script, "--tools", DEMO_TOOLS, "-o", wp("snap.json")])
    code, out, _ = run_cli(["replay", wp("snap.json"), "--tools", DEMO_TOOLS,
                            "--mode", "verify"])
    assert code == 0 and "match=1" in out


@t
def a17_cli_replay_diff_exit1():
    script = wj("s.json", [{"name": "greet", "args": ["world"]}])
    run_cli(["record", "--script", script, "--tools", DEMO_TOOLS, "-o", wp("snap.json")])
    # tamper: make current tool disagree by pointing at a broken module
    broken = wp("broken_tools.py")
    with open(broken, "w", encoding="utf-8") as f:
        f.write('def greet(name):\n    return "CHANGED"\nTOOLS={"greet": greet}\n')
    code, out, _ = run_cli(["replay", wp("snap.json"), "--tools", broken,
                            "--mode", "verify"])
    assert code == 1 and "result_diff" in out


@t
def a18_cli_report_file():
    script = wj("s.json", [{"name": "fail"}])
    run_cli(["record", "--script", script, "--tools", DEMO_TOOLS, "-o", wp("snap.json")])
    code, _, _ = run_cli(["replay", wp("snap.json"), "--tools", DEMO_TOOLS,
                          "--report", wp("rep.json")])
    rep = json.load(open(wp("rep.json"), encoding="utf-8"))
    assert code == 0 and rep["summary"]["match"] == 1


@t
def a19_registry_decorator():
    r = tcr.ToolRegistry()

    @r.register("custom")
    def fn(x):
        return x

    @r.register()
    def auto(x):
        return x

    assert r.names() == ["auto", "custom"]


@t
def a20_load_tools_module():
    tools = tcr.load_tools_module(DEMO_TOOLS)
    assert set(tools) >= {"add", "greet", "slugify", "fail"}


@t
def a21_jsonl_script_wrapped():
    calls_l = tcr.parse_script_text('{"calls": [{"name": "add", "args": [1, 1]}]}')
    assert len(calls_l) == 1 and calls_l[0]["name"] == "add"


@t
def a22_unicode_args():
    snap = rec([{"name": "greet", "args": ["世界"]},
                {"name": "slugify", "args": [" Hello—World "]}])
    rep = tcr.replay(snap, reg(), mode="verify")
    assert rep["summary"]["match"] == 2
    assert "世界" in snap["calls"][0]["result"]


@t
def a23_mixed_scalars():
    snap = rec([{"name": "add", "args": [0.1, 0.2]},
                {"name": "greet", "args": [None]}])
    # greet(None) -> "hello, None!" is fine
    rep = tcr.replay(snap, reg(), mode="verify")
    assert rep["summary"]["match"] == 2


@t
def a24_snapshot_roundtrip_file():
    snap = rec([{"name": "add", "args": [7, 8]}])
    p = wp("rt.json")
    tcr.save_json(snap, p)
    loaded = tcr._load_snapshot(p)
    rep = tcr.replay(loaded, reg(), mode="verify")
    assert rep["summary"]["match"] == 1

# ---------------- [B] exception / CLI paths

@t
def b01_missing_script_exit2():
    code, _, err = run_cli(["record", "--script", wp("nope.json"),
                            "--tools", DEMO_TOOLS, "-o", wp("s.json")])
    assert code == 2 and "error" in err


@t
def b02_missing_tools_exit2():
    code, _, _ = run_cli(["record", "--script", wj("s.json", []),
                          "--tools", wp("nope.py"), "-o", wp("s.json")])
    assert code == 2


@t
def b03_malformed_script_json():
    raises_val = False
    try:
        tcr.parse_script_text("{bad")
    except ValueError:
        raises_val = True
    assert raises_val


@t
def b04_empty_script():
    try:
        tcr.parse_script_text("")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


@t
def b05_script_scalar_rejected():
    try:
        tcr.parse_script_text("42")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


@t
def b06_call_missing_name():
    try:
        tcr.parse_script_text('[{"args": [1]}]')
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


@t
def b07_args_not_list():
    try:
        tcr.parse_script_text('[{"name": "add", "args": 5}]')
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


@t
def b08_kwargs_not_dict():
    try:
        tcr.parse_script_text('[{"name": "add", "kwargs": [1]}]')
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


@t
def b09_record_unknown_tool():
    try:
        rec([{"name": "ghost"}])
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "unknown tool" in str(e)


@t
def b10_tools_module_no_TOOLS():
    p = wp("bad1.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    try:
        tcr.load_tools_module(p)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "TOOLS" in str(e)


@t
def b11_tools_not_callable():
    p = wp("bad2.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write("TOOLS = {'x': 42}\n")
    try:
        tcr.load_tools_module(p)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "not callable" in str(e)


@t
def b12_tools_import_crash():
    p = wp("bad3.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write("raise RuntimeError('nope')\nTOOLS = {}\n")
    try:
        tcr.load_tools_module(p)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "RuntimeError" in str(e)


@t
def b13_snapshot_missing_calls():
    try:
        tcr._load_snapshot(wj("snap.json", {"foo": 1}))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


@t
def b14_corrupt_snapshot_exit2():
    p = wp("snap.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{bad")
    code, _, _ = run_cli(["replay", p, "--tools", DEMO_TOOLS])
    assert code == 2


@t
def b15_bad_mode_rejected():
    code, _, _ = run_cli(["replay", wj("snap.json", {"calls": []}),
                          "--tools", DEMO_TOOLS, "--mode", "bogus"])
    assert code == 2  # argparse choices


@t
def b16_no_subcommand_exit2():
    code, _, _ = run_cli([])
    assert code == 2


@t
def b17_mock_signature_error():
    snap = rec([{"name": "add", "args": [1, 2]}])
    snap["calls"][0]["args"] = [1, 2, 3]  # too many args
    rep = tcr.replay(snap, reg(), mode="mock")
    assert rep["calls"][0]["status"] == "signature_error"
    assert rep["summary"]["signature_error"] == 1


@t
def b18_mock_unknown_kwarg():
    snap = {"format_version": 1, "calls": [
        {"index": 0, "name": "add", "args": [], "kwargs": {"zzz": 1}}]}
    rep = tcr.replay(snap, reg(), mode="mock")
    assert rep["calls"][0]["status"] == "signature_error"


@t
def b19_replay_calls_not_list():
    try:
        tcr.replay({"calls": "nope"}, reg())
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


@t
def b20_bad_mode_api():
    try:
        tcr.replay({"calls": []}, reg(), mode="warp")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

# ---------------- [C] extreme edges

@t
def c01_empty_calls_record_replay():
    snap = rec([])
    rep = tcr.replay(snap, reg(), mode="verify")
    assert rep["summary"]["total"] == 0


@t
def c02_deep_nested_args():
    deep = 0
    for _ in range(150):
        deep = [deep]
    s = json.dumps(deep)
    snap = rec([{"name": "greet", "args": [s]}])
    rep = tcr.replay(snap, reg(), mode="verify")
    assert rep["summary"]["match"] == 1 and len(s) > 300


@t
def c03_long_string_arg():
    big = "x" * 100000
    snap = rec([{"name": "greet", "args": [big]}])
    assert len(snap["calls"][0]["result"]) > 100000


@t
def c04_unicode_kwargs_and_results():
    snap = rec([{"name": "slugify", "args": ["Grüße_ünïcode-漢字"]}])
    rep = tcr.replay(snap, reg(), mode="verify")
    assert rep["summary"]["match"] == 1


@t
def c05_many_calls_timing():
    script = [{"name": "add", "args": [i, i]} for i in range(300)]
    t0 = time.time()
    snap = rec(script)
    rep = tcr.replay(snap, reg(), mode="verify")
    assert time.time() - t0 < 5.0 and rep["summary"]["match"] == 300


@t
def c06_float_precision_compare():
    snap = rec([{"name": "add", "args": [0.1, 0.2]}])
    assert snap["calls"][0]["result"] == 0.1 + 0.2
    rep = tcr.replay(snap, reg(), mode="verify")
    assert rep["summary"]["match"] == 1


@t
def c07_result_none_recorded():
    r = tcr.ToolRegistry()
    r.register_function("ret_none", lambda: None)
    snap = tcr.record([{"name": "ret_none", "args": []}], r)
    assert snap["calls"][0]["result"] is None
    rep = tcr.replay(snap, r, mode="verify")
    assert rep["summary"]["match"] == 1


@t
def c08_large_result():
    big = list(range(5000))
    snap = rec([{"name": "echo_list", "args": [big]}]) if "echo_list" in \
        reg().names() else rec([{"name": "slugify", "args": ["-" * 5000]}])
    assert len(json.dumps(snap["calls"][0])) > 4000


@t
def c09_unserializable_result_repr():
    p = wp("obj_tools.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write("class O:\n"
                "    def __repr__(self):\n"
                "        return 'O()'\n"
                "def make():\n"
                "    return O()\n"
                "TOOLS={'make': make}\n")
    tools = tcr.load_tools_module(p)
    r = tcr.ToolRegistry()
    r.register_function("make", tools["make"])
    snap = tcr.record([{"name": "make", "args": []}], r)
    c = snap["calls"][0]
    assert c["result_repr"] is True and isinstance(c["result"], str)
    rep = tcr.replay(snap, r, mode="verify")
    assert rep["summary"]["match"] == 1  # both sides repr'd identically


@t
def c10_detail_truncated():
    snap = rec([{"name": "slugify", "args": ["a" * 5000]}])
    snap["calls"][0]["result"] = "b" * 5000
    rep = tcr.replay(snap, reg(), mode="verify")
    d = rep["calls"][0]["detail"]
    assert len(d) <= tcr.DETAIL_LIMIT and d.endswith("...")


@t
def c11_report_serializable():
    snap = rec([{"name": "fail"}])
    rep = tcr.replay(snap, reg(), mode="verify")
    json.loads(json.dumps(rep))


@t
def c12_summary_counts_consistent():
    script = [{"name": "add", "args": [1, 2]}, {"name": "fail"}]
    snap = rec(script)
    snap["calls"][0]["result"] = -1  # force one diff
    rep = tcr.replay(snap, reg(), mode="verify")
    s = rep["summary"]
    assert s["total"] == s["match"] + s["diff"] + s["missing_tool"] + s["signature_error"]


@t
def c13_tampered_index_preserved():
    snap = rec([{"name": "add", "args": [1, 1]}])
    snap["calls"][0]["index"] = "idx-7"
    rep = tcr.replay(snap, reg(), mode="verify")
    assert rep["calls"][0]["index"] == "idx-7"


@t
def c14_args_default_empty():
    r = tcr.ToolRegistry()
    r.register_function("dflt", lambda x=1: x)
    snap = {"format_version": 1, "calls": [{"index": 0, "name": "dflt"}]}
    rep = tcr.replay(snap, r, mode="mock")
    assert rep["calls"][0]["status"] == "match"  # all-default signature binds


def raises_valueerror(fn, *a, **k):
    try:
        fn(*a, **k)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def main():
    setup()
    ok = 0
    fails = []
    for fn in TESTS:
        try:
            fn()
            ok += 1
        except Exception as e:  # noqa: BLE001
            fails.append((fn.__name__, repr(e)))
    for name, e in fails:
        print("FAIL %s: %s" % (name, e))
    total = len(TESTS)
    print("SUMMARY: %s %d/%d" % ("PASS" if not fails else "FAIL", ok, total))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
