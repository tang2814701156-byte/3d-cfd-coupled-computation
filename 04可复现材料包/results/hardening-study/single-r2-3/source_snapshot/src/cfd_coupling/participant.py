"""preCICE 3.x participant; rollback restores physical time and control state."""
from __future__ import annotations

import argparse
import copy
import csv
import json
import os
from pathlib import Path
import time

import numpy as np

from .model import Controller, PipeModel
from .transport import MixingVolume


def stamp(path: Path, seq: int, target: float, ns: int) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(f"{seq} {target:.17g} {ns}\n", encoding="ascii")
    os.replace(tmp, path)


def main() -> None:
    import precice  # Docker-only dependency; model tests do not require libprecice.

    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, type=Path)
    args = parser.parse_args()
    case = json.loads(args.case.read_text(encoding="utf-8"))
    model = PipeModel(**case["pipe"])
    thermal = MixingVolume(**case["transport"]) if "transport" in case else None
    controller = Controller(case["control"]["events"], case["control"]["period_s"])
    root = args.case.resolve().parent
    trace = root / "traces"
    trace.mkdir(exist_ok=True)
    participant = precice.Participant("Fluid1DLeft", str(root / "precice-config.xml"), 0, 1)
    mesh = "Fluid1DLeft-Mesh"
    vertices = participant.set_mesh_vertices(mesh, [[0.0, 0.0, model.length]])
    state_mesh = "State1D"
    state_vertices = participant.set_mesh_vertices(state_mesh, [[0., 0., model.length]]) if thermal else None
    if participant.requires_initial_data():
        participant.write_data(mesh, "Velocity", vertices, [[0., 0., model.velocity]])
        if thermal:
            participant.write_data(state_mesh, "FlowTemperature", state_vertices, [thermal.temperature_k])
            participant.write_data(state_mesh, "Alpha", state_vertices, [thermal.alpha])
    participant.initialize()
    t, seq, window, checkpoint = 0.0, 0, 0, None
    pending, pending_events = [], []
    rows, events, exchanges = [], [], []
    start_ns = time.monotonic_ns()
    timing = {key: 0. for key in ["read_pressure_s", "model_and_control_s", "write_and_stamp_s", "advance_wait_s", "finalize_s"]}
    last_status = 0.
    status_path = os.environ.get("CFD_STATUS_PATH")
    # Persist only committed windows. A killed participant retains an auditable
    # prefix, never a speculative iteration that was subsequently rolled back.
    journal = (root / "accepted_windows.jsonl").open("w", encoding="utf-8", buffering=1)
    def publish_status(force=False):
        nonlocal last_status
        now = time.monotonic()
        if status_path and rows and (force or now-last_status >= .5):
            target = Path(status_path)
            payload = {"case": case["name"], "state": "completed" if force else "running",
                       "accepted_windows": window, "end_time_s": case["coupling"]["end_time_s"],
                       "wall_seconds": (time.monotonic_ns()-start_ns)/1e9,
                       "latest": rows[-1], "timing": timing}
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(temporary, target)
            last_status = now
    try:
        while participant.is_coupling_ongoing():
            if participant.requires_writing_checkpoint():
                checkpoint = (t, copy.deepcopy(model), controller.cursor, copy.deepcopy(thermal))
                pending, pending_events = [], []
            stage = time.perf_counter()
            pending_events.extend(controller.apply(t, model))
            dt = min(case["coupling"]["dt_1d_s"], participant.get_max_time_step_size())
            dt = controller.limit_dt(t, dt)
            timing["model_and_control_s"] += time.perf_counter()-stage
            stage = time.perf_counter()
            pressure = float(participant.read_data(mesh, "Pressure", vertices, dt)[0]) * model.rho
            usable_ns = time.monotonic_ns()
            timing["read_pressure_s"] += time.perf_counter()-stage
            reverse = trace / "reverse.stamp"
            if reverse.exists():
                rseq, source_t, sent = reverse.read_text().split()
                exchanges.append({"direction": "3d_to_1d", "seq": int(rseq),
                                  "target_s": float(source_t), "sent_ns": int(sent),
                                  "usable_ns": usable_ns, "read_physical_s": t + dt})
            stage = time.perf_counter()
            result = model.advance(dt, pressure)
            transport_balance = thermal.advance(result["mass_kg"], model.rho) if thermal else {}
            if not np.isfinite(model.velocity):
                raise FloatingPointError("Non-finite pipe velocity")
            timing["model_and_control_s"] += time.perf_counter()-stage
            stage = time.perf_counter()
            seq += 1
            sent_ns = time.monotonic_ns()
            stamp(trace / "forward.stamp", seq, t + dt, sent_ns)
            participant.write_data(mesh, "Velocity", vertices, [[0., 0., model.velocity]])
            if thermal:
                participant.write_data(state_mesh, "FlowTemperature", state_vertices, [thermal.temperature_k])
                participant.write_data(state_mesh, "Alpha", state_vertices, [thermal.alpha])
            timing["write_and_stamp_s"] += time.perf_counter()-stage
            stage = time.perf_counter()
            participant.advance(dt)
            timing["advance_wait_s"] += time.perf_counter()-stage
            t += dt
            pending.append({"time_s": t, "step_start_s": t - dt, "window": window, "dt_s": dt,
                            "velocity_m_s": model.velocity, "mdot_kg_s": model.rho * model.area * model.velocity,
                            "back_pressure_pa": pressure, "opening": model.opening,
                            "temperature_k": thermal.temperature_k if thermal else case["interface"]["temperature_k"],
                            "phase_fraction": thermal.alpha if thermal else 1.0,
                            "integrated_outflow_kg": result["mass_kg"],
                            **{k: v for k, v in result.items() if k not in ["mass_kg", "acceleration"]},
                            **transport_balance})
            if participant.requires_reading_checkpoint():
                if checkpoint is None:
                    raise RuntimeError("Missing checkpoint")
                t, model, controller.cursor, thermal = copy.deepcopy(checkpoint)
                pending, pending_events = [], []
            elif participant.is_time_window_complete():
                journal.write(json.dumps({"window": window, "rows": pending, "events": pending_events}) + "\n")
                journal.flush()
                rows.extend(pending)
                events.extend(pending_events)
                pending, pending_events = [], []
                window += 1
                publish_status()
    finally:
        journal.close()
        stage = time.perf_counter()
        participant.finalize()
        timing["finalize_s"] += time.perf_counter()-stage
    if not rows:
        raise RuntimeError("No accepted coupling windows")
    publish_status(force=True)
    for name, data in [("pipe.csv", rows), ("control_events.csv", events), ("reverse_latency.csv", exchanges)]:
        if data:
            with (root / name).open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=list(data[0]))
                writer.writeheader()
                writer.writerows(data)
    # Uniform incompressible velocity; pressure gradient follows unsteady momentum balance.
    x = np.linspace(0., model.length, 101)
    valve_drop = model.valve_resistance * (model.opening ** -2 - 1) * model.velocity if model.opening > 0 else 0.
    pressure = np.linspace(model.supply_pressure - valve_drop, rows[-1]["back_pressure_pa"], len(x))
    np.savetxt(root / "pipe_final.csv", np.column_stack([x, pressure, np.full_like(x, model.velocity)]),
               delimiter=",", header="x_m,p_pa,velocity_m_s", comments="")
    (root / "participant_summary.json").write_text(json.dumps({
        "accepted_windows": window, "accepted_substeps": len(rows), "write_attempts": seq,
        "physical_end_s": t, "wall_seconds": (time.monotonic_ns() - start_ns) / 1e9,
        "temperature_phase_mode": "equal_property_two_phase_transport" if thermal else "metadata_only_single_phase_isothermal",
        "model": "uniform incompressible pipe inertia with quasi-steady Poiseuille friction",
        "timing_seconds": timing,
        "timing_scope": "all trials; advance includes remote CFD solve and synchronization, not isolated network overhead; excludes initialization",
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

