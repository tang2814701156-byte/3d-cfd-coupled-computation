"""Rebuild v0.3 comparison tables and figures from saved, verified runs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from analyze import read_csv
from transport_analysis import write_csv
from verify_results import verify


def summarize(root: Path):
    reports = {}
    for path in sorted(root.glob("*/summary.json")):
        verify(path.parent)
        reports[path.parent.name] = json.loads(path.read_text())
    required = {"steady", "steady-fine", "advection", "advection-fine", "mms-area"}
    if not required.issubset(reports):
        raise ValueError("Missing mandatory verification cases: " + str(required-reports.keys()))
    names = sorted([n for n in reports if n.startswith("valve-")], key=lambda n: reports[n]["window_s"])
    if len(names) < 2:
        raise ValueError("Need multiple valve exchange periods")
    ref_rows = read_csv(root / names[0] / "pipe.csv")
    reference_time = np.array([float(r["time_s"]) for r in ref_rows])
    fields = ["velocity_m_s", "back_pressure_pa", "temperature_k", "phase_fraction"]
    frequency = []
    timing = []
    for name in names:
        report = reports[name]
        rows = read_csv(root / name / "pipe.csv")
        t = np.array([float(r["time_s"]) for r in rows])
        mask = (reference_time >= t[0]) & (reference_time <= t[-1])
        record = {"name": name, "window_s": report["window_s"], "frequency_hz": 1/report["window_s"],
                  "wall_seconds": report["wall_seconds"], "accepted_windows": report["accepted_windows"],
                  "trial_work_amplification": report["trial_work_amplification"],
                  "forward_p95_ms": report["latency"]["1d_to_3d"]["p95_ms"],
                  "reverse_p95_ms": report["latency"]["3d_to_1d"]["p95_ms"]}
        for field in fields:
            reference = np.array([float(r[field]) for r in ref_rows])
            candidate = np.array([float(r[field]) for r in rows])
            diff = np.interp(reference_time[mask], t, candidate)-reference[mask]
            record["normalized_rms_"+field] = float(np.sqrt(np.mean(diff**2))/max(np.ptp(reference), 1e-12))
            if field == "back_pressure_pa":
                away = np.ones(np.count_nonzero(mask), dtype=bool)
                case = json.loads((root / name / "case.json").read_text())
                for event in case["control"]["events"]:
                    away &= abs(reference_time[mask]-event["time_s"]) > .001
                record["normalized_pressure_rms_excluding_event_1ms"] = float(np.sqrt(np.mean(diff[away]**2))/max(np.ptp(reference), 1e-12))
        frequency.append(record)
        participant = json.loads((root / name / "participant_summary.json").read_text())
        measured = participant["timing_seconds"]
        timing.append({"name": name, **measured, "participant_wall_s": participant["wall_seconds"],
                       "unassigned_s": participant["wall_seconds"]-sum(measured.values())})
    write_csv(root / "frequency.csv", frequency)
    write_csv(root / "timing.csv", timing)
    metrics = {"runs": len(reports), "accepted_windows": sum(r["accepted_windows"] for r in reports.values()),
               "shortest_tested_stable_window_s": reports[names[0]]["window_s"],
               "frequency_reference": names[0], "scope": "single run per period; actual substeps also shorten when H is smaller than configured maxima",
               "cases": {name: {"steady": r["steady_poiseuille_reference"], "transport": r.get("transport"),
                                  "latency": r["latency"], "wall_seconds": r["wall_seconds"]} for name, r in reports.items()}}
    (root / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (root / "study_summary.json").write_text(json.dumps({k:v for k,v in metrics.items() if k != "cases"}, indent=2))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    x = [r["frequency_hz"] for r in frequency]
    for field in fields:
        axes[0].plot(x, [100*r["normalized_rms_"+field] for r in frequency], "o-", label=field)
    axes[0].set_ylabel("RMS / reference signal range [%]"); axes[0].legend(fontsize=8)
    axes[1].plot(x, [r["wall_seconds"] for r in frequency], "o-")
    axes[1].set_ylabel("Wall time [s], one run per point")
    for ax in axes: ax.set_xscale("log"); ax.set_xlabel("Exchange frequency [Hz]"); ax.grid(alpha=.25)
    fig.savefig(root / "frequency.png", dpi=160); plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    for name, label in [("advection", "6x40, dt=0.5 ms"), ("advection-fine", "8x80, dt=0.25 ms")]:
        rows = read_csv(root / name / "foam_accepted.csv")
        t = [float(r["time_s"]) for r in rows]
        axes[0].plot(t, [float(r["temperature_rms_k"]) for r in rows], label=label)
        axes[1].plot(t, [float(r["alpha_rms"]) for r in rows], label=label)
    axes[0].set_ylabel("Temperature field RMS [K]"); axes[1].set_ylabel("Phase A field RMS")
    for ax in axes: ax.set_xlabel("Physical time [s]"); ax.grid(alpha=.25); ax.legend(fontsize=8)
    fig.savefig(root / "advection-refinement.png", dpi=160); plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for name in names:
        rows = read_csv(root / name / "pipe.csv")
        t = np.array([float(r["time_s"]) for r in rows])
        p = np.array([float(r["back_pressure_pa"]) for r in rows])
        label = f"H={reports[name]['window_s']*1000:g} ms"
        axes[0].plot(t*1000, p, label=label)
        axes[1].plot(t*1000, p, ".-", markersize=3, label=label)
    axes[1].set_xlim(49.8, 50.6)
    for ax in axes: ax.set_xlabel("Physical time [ms]"); ax.set_ylabel("Back pressure [Pa]"); ax.grid(alpha=.25)
    axes[0].legend(fontsize=8)
    fig.savefig(root / "pressure-event-comparison.png", dpi=160); plt.close(fig)
    source = Path(__file__).resolve().parent
    inputs = list(root.glob("*/summary.json"))+list(root.glob("*/pipe.csv"))
    (root / "analysis_manifest.json").write_text(json.dumps({
        "script_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                          [Path(__file__), source/"analyze.py", source/"transport_analysis.py", source/"verify_results.py"]},
        "input_sha256": {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}, indent=2))
    print(json.dumps({k:v for k,v in metrics.items() if k != "cases"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    summarize(parser.parse_args().directory.resolve())
