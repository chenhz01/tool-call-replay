# Alignment Audit (Rules 85-100 / 16 items) — tool-call-replay v0.1.1

| # | Check | Status | Evidence |
|---|-------|--------|----------|
| 1 | Safety/Ethics section | N/A | Not a security-research repo; no dual-use surface. Fails closed (exit 2) on unreadable/corrupt inputs; zero network by design |
| 2 | Privacy/dezero | PASS | No secrets/tokens/real names; no contact line needed; grep `(sk-\|ghp_\|api[_-]?key\s*=\s*['"][A-Za-z0-9])` → 0 hits |
| 3 | Copyright boundary | PASS | Anchor comparisons (auraoneai/tool-call-replay, yanqr213/tool-call-replay-harness, manuelsampedro1/agent-tool-call-replay) are structural restatements of public one-line descriptions, no >50-char copied text; MIT LICENSE present, "zhengming contributors" |
| 4 | Fact-check annotation | PASS | Quickstart ~2 s marked [Measured] with repro `python self_test.py`; per-step ≈0.5 s markers; behavioral claims qualitative |
| 5 | Confidence grading | PASS | Mechanics correctness [High ≥80%]; signature-binding coverage [Medium]; sequence-representativeness [Low]; visible in Confidence section |
| 6 | PLAN B built-in | PASS | "Minimal Fallback (PLAN B)": jq one-liner extracting tool name + arity per call for manual diffing |
| 7 | Timeout preset | PASS | Quickstart states "~2 s" total with per-step markers |
| 8 | Rule-conflict arbitration | PASS | "Design Trade-offs" opens with priority order: determinism > zero side-effect escape > diff precision > coverage of real agent runtimes |
| 9 | Version changelog | PASS | CHANGELOG.md v0.1.0 + v0.1.1; v0.1.1 lists the repr-comparison fix, detail-truncation fix, calls-validation fix, and test delta 52→58 |
| 10 | Exemption instruction | N/A | Session-level rule; static repo content not applicable |
| 11 | External-knowledge cutoff | PASS | No vendor-specific time-sensitive claims; anchor facts restated from the 2026-10 candidate pool snapshot |
| 12 | Assumption explicitness | PASS | "[Core Assumptions]" section with 4 items (pure tools, frozen snapshots, determinism-over-realism, TOOLS dict as contract) |
| 13 | Logic-check trio | PASS | self_test.py tiers: [A] functional (24), [B] exception/CLI paths (20), [C] extreme edges (14: empty script/150-deep nesting/100k-char arg/unicode/300-call timing/0.1+0.2 float/unserializable repr/truncation/summary-consistency). Final run: `python self_test.py` → `SUMMARY: PASS 58/58` |
| 14 | Socratic question | PASS | FAQ "When NOT to use this tool?" with 4 concrete anti-use-cases (pytest-harness needs, vendor trace formats, unsafe re-execution, live-session capture) |
| 15 | Pareto improvement | PASS | v0.1.1: test count 52→58 (+11.5%) plus 3 correctness fixes (repr comparison, detail truncation, calls validation); documented in CHANGELOG, suite re-run green |
| 16 | Ultimate fallback (≤60-word opener) | PASS | First paragraph = 59 words, contains what/who-needs-it judgment sentence |

Second-order effects (rule 16 bonus): PASS — "Limits & Second-order Effects" lists false-green masking of orchestration drift, repr-based comparison blindness, and unenforced type hints.

Scan evidence: `grep -rEn "(sk-\|ghp_\|api[_-]?key\s*=\s*['\"][A-Za-z0-9])" .` → 0 hits; `python self_test.py` → `SUMMARY: PASS 58/58`.
