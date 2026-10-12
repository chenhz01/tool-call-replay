# Changelog — tool-call-replay

## v0.1.1 — 2026-10-12

- Fixed: `_same_recorded` now compares the replayed result against the recorded
  value even when the replayed result is unserializable (compared via stored
  `repr`), so constant-`__repr__` object results no longer report false diffs.
- Fixed: result-diff report detail is truncated as a whole (previously the two
  embedded truncated dumps could still exceed the 200-char detail limit).
- Fixed: `replay()` validates that the snapshot has a `calls` list when called
  as a library function, not only via the CLI loader.
- Self-review round: test suite grew 52 → 58 cases (added `expected_error_but_ok`
  drift path, none-result recording, all-default-signature mock binding).

## v0.1.0 — 2026-10-11

- Initial cut (session-interrupted build): ToolRegistry + TOOLS-module loader,
  `record` (script → snapshot, no timestamps), `replay` in `mock` (signature
  check) and `verify` (re-execute + diff) modes, per-call status taxonomy,
  CLI with exit codes 0/1/2, demo_tools.py, 52 self-test cases.
