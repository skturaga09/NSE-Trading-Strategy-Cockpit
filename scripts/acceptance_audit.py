"""Phase 15 requirements audit: every requirement row of every docs/phase-N-report.md, joined to the latest test run.

Inputs: the phase reports, the verbose engine unittest log, the dashboard test log and the vitest log
(docs/phase-15-evidence/*-baseline.txt). Output: a markdown table on stdout, one row per requirement, with
a GAP column. Read-only; it runs no tests itself.
Usage: python3 scripts/acceptance_audit.py [verbose-unittest-log] > docs/phase-15-evidence/requirements-matrix.md
"""
import re
import sys
from pathlib import Path

DOCS = Path("docs")
EV = DOCS / "phase-15-evidence"
STATUS_RE = re.compile(r"^(DONE|PARTIAL|NOT DONE)")
TEST_RE = re.compile(r"`(test_[A-Za-z0-9_]+)(…|\.\.\.)?")
FILE_RE = re.compile(r"`((?:engine|dashboard|config|scripts|tests)/[^`\s]+|[A-Za-z_]+\.(?:py|tsx?|yaml))`")


CLASSES: dict[str, list[str]] = {}  # test class name -> its test methods
MODULES: dict[str, list[str]] = {}  # test module name -> its test methods


def engine_results(log: Path = EV / "engine-suite-baseline.txt") -> dict[str, str]:
    """test method name -> ok / FAIL / ERROR, from the verbose unittest log."""
    out: dict[str, str] = {}
    text = log.read_text()
    for m in re.finditer(r"^(test_\w+) \(([\w.]+)\)", text, re.M):
        out.setdefault(m.group(1), "ok")
        CLASSES.setdefault(m.group(2).split(".")[-2], []).append(m.group(1))
        MODULES.setdefault(m.group(2).split(".")[-3], []).append(m.group(1))
    for m in re.finditer(r"^(FAIL|ERROR): (test_\w+) ", text, re.M):
        out[m.group(2)] = m.group(1)
    return out


def phase_rows(path: Path):
    lines = path.read_text().splitlines()
    in_section = False
    for line in lines:
        if re.match(r"^## \d+\. Requirement", line):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not (in_section and line.startswith("| ")) or line.startswith("|---") or line.startswith("| #"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        status_idx = next((i for i, c in enumerate(cells) if STATUS_RE.match(c)), None)
        if status_idx is None:
            continue
        yield cells[0], " ".join(cells[1:status_idx]), cells[status_idx], " | ".join(cells[status_idx + 1:])


def classify(status: str, proof: str, results: dict[str, str], inherited: list[str] = ()) -> tuple[str, str, list[str]]:
    names = TEST_RE.findall(proof) + [(t, "") for t in inherited]
    names += [(t, "") for cls in re.findall(r"`?(\w+)\.\*`?", proof) for t in CLASSES.get(cls, [])]
    resolved, unresolved, failed = [], [], []
    for name, ellipsis in names:
        hits = [t for t in results if (t.startswith(name) if ellipsis else t == name)]
        if not hits:
            unresolved.append(name + (ellipsis or ""))
            continue
        resolved += hits
        failed += [t for t in hits if results[t] != "ok"]
    vitest = bool(re.search(r"\.test\.tsx?|`[^`]+ > [^`]+`|tooltip's ancestors", proof))  # vitest file or "describe > it" name
    if failed:
        result = "FAIL: " + ", ".join(failed)
    elif unresolved:
        result = "TEST NOT FOUND: " + ", ".join(unresolved)
    elif resolved or vitest:
        result = f"PASS ({len(set(resolved))} engine" + (" + vitest" if vitest else "") + ")"
    else:
        result = "NO TEST (evidence / run log only)"
    gap = []
    if not status.startswith("DONE"):
        gap.append(status.split(":")[0].split("(")[0].strip())
    if not result.startswith("PASS"):
        gap.append(result.split(":")[0].split("(")[0].strip())
    return result, ", ".join(gap), sorted(set(resolved))


# Rows whose report cites the proof only by prose ("property test", "§6", "header test"); each name was
# matched by hand against tests/engine_tests in Phase 15. "test_positioning" stands for that whole module.
HAND_RESOLVED = {
    ("1", "AT2"): ["test_get_latest_never_returns_future_data_property"],
    ("1", "5"): ["test_health_from_status_files"],
    ("2", "AT1"): ["test_no_duplicate_underlying_and_fno_derived_from_master"],
    ("2", "AT2"): ["test_no_duplicate_underlying_and_fno_derived_from_master"],
    ("2", "AT4"): ["test_banned_security_not_tradable"],
    ("2", "AT7"): ["test_token_reused_for_another_contract_resolves_by_date"],
    ("2", "1"): ["test_stale_constituents_flagged_then_blocked"],
    ("3", "AT5"): ["test_never_exceeds_limits_for_any_input_size_property", "test_allocator_never_exceeds_limits_with_option_tier"],
    ("3", "1c"): ["test_promote_ttl_demote_and_executor_ops"],
    ("3", "7"): ["test_report_then_compact_snapshots_losslessly"],
    ("4", "In"): ["test_pure_modules_do_no_io_and_read_no_clock"],
    ("4", "AT1–7"): ["test_positioning"],
    ("5", "AT1"): ["test_prefix_equals_batch_filtered_and_nothing_before_confirmed_ts"],
    ("6", "8"): ["test_phase4_event_becomes_a_setup_and_its_invalidation_ends_it"],
    ("6", "AT5"): ["test_mfe_mae_not_written_before_horizon_elapses_in_replay_time"],
    ("8", "AT4"): ["test_A_fresh_long_buildup_breakout", "test_B_fresh_short_buildup_breakdown",
                   "test_C_short_covering_momentum_is_labelled_and_exhaustion_checked",
                   "test_D_long_unwinding_continuation_needs_persistent_volume", "test_E_F_liquidity_sweep_reversals",
                   "test_G_exhaustion_is_an_observation_and_a_warning_never_an_entry"],
    ("10", "R4"): ["test_no_output_text_says_institution_except_the_disclaimer"],
    ("10", "D4"): [],  # vitest: components.test.tsx "tooltip portal inside [data-fo-engine]", see VITEST_ROWS
    ("12", "Val-6"): ["test_every_table_is_titled_with_its_dataset_stage_and_good_sessions"],
    # Phase 15 G-8: tests added for rows that had none
    ("1", "3f"): ["test_master_is_fetched_once_per_date_and_stored_gzipped_under_that_date"],
    ("4", "F3"): ["test_rvol_volume_oi_ratio_vwap_move_momentum_and_basis"],
    ("4", "F4"): ["test_rvol_volume_oi_ratio_vwap_move_momentum_and_basis"],
    ("4", "F5"): ["test_rvol_volume_oi_ratio_vwap_move_momentum_and_basis"],
    ("4", "F6"): ["test_rvol_volume_oi_ratio_vwap_move_momentum_and_basis", "test_abnormal_basis_flag_and_too_few_samples"],
    ("5", "R3"): ["test_every_detection_carries_type_level_times_source_and_config_version"],
    ("8", "SC4"): ["test_trend_from_latest_index_turn_and_breadth_share_above_vwap"],
    ("12", "Eng-3"): ["test_stop_gap_paper_exit_fills_beyond_the_stop_and_costs_are_date_effective",
                      "test_unverified_rate_or_no_rate_in_force_sets_unverified"],
}


def main(log: str | None = None) -> None:
    results = engine_results(Path(log)) if log else engine_results()
    print("| phase | # | requirement | status (report) | files cited | proving tests | latest result | GAP |")
    print("|---|---|---|---|---|---|---|---|")
    totals = {"rows": 0, "gap": 0}
    reports = sorted(DOCS.glob("phase-*-report.md"), key=lambda p: int(re.search(r"\d+", p.name).group()))
    for path in reports:
        phase = re.search(r"\d+", path.name).group()
        seen: dict[str, tuple[str, list[str]]] = {}  # row id -> (proof, resolved tests), for "see X" / "same test"
        prev: list[str] = []
        for rid, req, status, proof in phase_rows(path):
            ref = re.match(r"see (\S+)", proof)
            inherited: list[str] = []
            if ref and ref.group(1) in seen:
                inherited = list(seen[ref.group(1)][1])
                proof += f" (inherits row {ref.group(1)})"
            elif re.search(r"same tests?|tests named above|all tests above|all \w+ tests", proof, re.I):
                inherited = list(prev)
            for name in HAND_RESOLVED.get((phase, rid), []):
                inherited += MODULES.get(name, [name])
            result, gap, tests = classify(status, proof, results, inherited)
            seen[rid] = (proof, tests)
            prev = tests or prev
            files = sorted(set(FILE_RE.findall(proof)))
            totals["rows"] += 1
            totals["gap"] += bool(gap)
            clip = lambda s, n: (s[:n] + "…") if len(s) > n else s
            cell = lambda s: s.replace("|", "/").replace("\n", " ")
            print(f"| {phase} | {cell(rid)} | {cell(clip(req, 140))} | {cell(clip(status, 60))} | "
                  f"{cell(', '.join(files)) or '—'} | {cell(clip(', '.join(tests), 200)) or '—'} | {cell(result)} | {gap or '—'} |")
    print(f"\nRows: {totals['rows']}. Rows with a GAP: {totals['gap']}.", file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:])   # optional: path of a verbose unittest log (default: the Phase 15 baseline)
