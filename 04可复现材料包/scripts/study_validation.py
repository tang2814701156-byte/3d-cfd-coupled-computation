"""Run geometry, source-free analytic transport and exchange-period verification."""
from __future__ import annotations
import argparse
import contextlib
import copy
import json
from pathlib import Path
from run_case import ROOT, run
from analyze import analyze
from verify_results import verify
from transport_analysis import write_csv


def specifications():
    def load(name):
        return json.loads((ROOT / "cases" / name).read_text())
    steady = load("pipe-steady-water.json")
    steady["cfd"]["normalize_interface_area"] = True
    yield "steady", steady
    fine = copy.deepcopy(steady)
    fine["cfd"].update(radial_cells_per_block=12, axial_cells=80)
    yield "steady-fine", fine
    mms = load("transport-mms.json")
    mms["cfd"]["normalize_interface_area"] = True
    yield "mms-area", mms
    physical = load("transport-advection.json")
    yield "advection", physical
    fine = copy.deepcopy(physical)
    fine["cfd"].update(radial_cells_per_block=8, axial_cells=80)
    fine["coupling"].update(dt_1d_s=.0005, dt_3d_s=.00025)
    yield "advection-fine", fine
    valve = load("valve-transport.json")
    valve["cfd"]["normalize_interface_area"] = True
    valve["coupling"].update(dt_1d_s=.00025, dt_3d_s=.000125)
    for h in [.0000625, .000125, .001, .005, .01]:
        case = copy.deepcopy(valve)
        case["coupling"]["window_s"] = h
        yield f"valve-{h:g}", case


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", nargs="+")
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    results = []
    for name, case in specifications():
        if args.only and name not in args.only:
            continue
        target = root / name
        if target.exists():
            raise FileExistsError(f"Use fresh run directories: {target}")
        print(f"Running {name}", flush=True)
        run(case, target)
        with (target / "analysis.log").open("w") as output, contextlib.redirect_stdout(output):
            report = analyze(target)
            verify(target)
        results.append({"name": name, "wall_seconds": report["wall_seconds"],
                        "accepted_windows": report["accepted_windows"], "verified": True})
        print(json.dumps(results[-1]), flush=True)
    # Include prior completed subsets without rerunning or modifying their raw results.
    all_runs = []
    for path in sorted(root.glob("*/summary.json")):
        report = json.loads(path.read_text())
        all_runs.append({"name": path.parent.name, "wall_seconds": report["wall_seconds"],
                         "accepted_windows": report["accepted_windows"],
                         "window_s": report["window_s"],
                         "velocity_error": report["steady_poiseuille_reference"]["relative_final_velocity_error"],
                         "forward_p95_ms": report["latency"]["1d_to_3d"]["p95_ms"],
                         "reverse_p95_ms": report["latency"]["3d_to_1d"]["p95_ms"]})
    write_csv(root / "runs.csv", all_runs)
    (root / "study_summary.json").write_text(json.dumps({"runs": len(all_runs),
        "accepted_windows": sum(r["accepted_windows"] for r in all_runs),
        "scope": "local verification; analytic Poiseuille and source-free scalar characteristics; single-run frequency scan"}, indent=2))


if __name__ == "__main__":
    main()
