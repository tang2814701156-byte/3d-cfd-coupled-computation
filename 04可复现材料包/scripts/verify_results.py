"""Verify completed real runs against declared v0.1 numerical/software gates."""
from __future__ import annotations
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def verify(root: Path) -> None:
    report = json.loads((root / "summary.json").read_text())
    case = json.loads((root / "case.json").read_text())
    rows = list(csv.DictReader((root / "pipe.csv").open()))
    times = [float(r["time_s"]) for r in rows]
    assert rows and all(math.isfinite(float(v)) for r in rows for v in r.values()), "Non-finite accepted state"
    assert all(b > a for a, b in zip(times, times[1:])), "Accepted physical times must increase"
    assert abs(times[-1] - case["coupling"]["end_time_s"]) < 1e-10
    foam = (root / "foam.log").read_text()
    assert "Reached end at:" in foam, "OpenFOAM did not reach coupling end"
    assert foam.count("All converged") == report["accepted_windows"], "Unconverged coupling window"
    assert report["mass_mapping"]["max_abs_volume_flow_residual_m3_s"] < 1e-10
    for direction in ["1d_to_3d", "3d_to_1d"]:
        assert report["latency"][direction]["samples"] > 0
    events = case["control"]["events"]
    if events:
        assert report["control_events"] == len(events)
        assert report["max_control_error_s"] < 1e-12
        u = [float(r["velocity_m_s"]) for r in rows]
        p = [float(r["back_pressure_pa"]) for r in rows]
        assert max(u) - min(u) > 0.01, "Missing flow response"
        assert max(p) - min(p) > 1., "Missing pressure response"
    else:
        # Initial numerical gate, not a competition acceptance threshold.
        assert report["steady_poiseuille_reference"]["relative_final_velocity_error"] < 0.03
    if "transport" in report:
        tr = report["transport"]
        assert "Solving for T" in foam and "Solving for alpha" in foam
        assert tr["accepted_cfd_steps"] > 0
        assert tr["interface"]["temperature_k"]["max_abs"] < 1e-8
        assert tr["interface"]["phase_fraction"]["max_abs"] < 1e-10
        assert tr["alpha_min"] >= -1e-8 and tr["alpha_max"] <= 1+1e-8
        assert tr["max_pipe_momentum_residual_kg_m_s"] < 1e-9
        assert tr["max_pipe_mechanical_residual_j"] < 1e-9
        assert tr["max_cfd_thermal_residual_j"] < 1e-3
        assert tr["max_cfd_phase_residual_kg"] < 1e-8
        for quantity in ["mass","thermal","phase"]:
            assert tr["interface_window_integrals"][quantity]["relative_cumulative_residual"] < .01
        if tr["manufactured_solution"]:
            assert tr["max_temperature_field_rms_k"] < .1
            assert tr["max_alpha_field_rms"] < .003
        elif tr.get("analytic_advection"):
            # Predeclared 5% input-amplitude gates for the physical advection case.
            assert tr["max_temperature_field_rms_k"] < 1.
            assert tr["max_alpha_field_rms"] < .03
        else:
            assert float(rows[-1]["temperature_k"])-float(rows[0]["temperature_k"]) > 1.
            assert float(rows[-1]["phase_fraction"])-float(rows[0]["phase_fraction"]) > .01
    manifest = json.loads((root / "source_manifest.json").read_text())
    for name, expected in manifest.get("code_sha256", {}).items():
        archived = root / "source_snapshot" / name
        path = archived if (root / "source_snapshot").exists() else ROOT / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, f"Source fingerprint mismatch: {name}"
    print(f"Verified {root.name}: {len(rows)} accepted substeps, {report['accepted_windows']} converged windows")


if __name__ == "__main__":
    for name in sys.argv[1:]:
        verify(Path(name).resolve())
