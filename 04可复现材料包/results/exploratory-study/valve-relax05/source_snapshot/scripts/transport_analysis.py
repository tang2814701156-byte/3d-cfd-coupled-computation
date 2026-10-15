"""Accepted-window balances and manufactured-solution comparison from raw data."""
import csv
import json
import math
from pathlib import Path
import numpy as np


def accepted_trace(raw: list[dict]) -> list[dict]:
    """Discard trial suffixes when solver time rewinds; retain final converged trajectory."""
    accepted = []
    for row in raw:
        t = float(row["time_s"])
        while accepted and float(accepted[-1]["time_s"]) >= t-1e-12:
            accepted.pop()
        accepted.append(row)
    previous = 0.
    for row in accepted:
        if abs(float(row["time_s"])-previous-float(row["dt_s"])) > 1e-10:
            raise ValueError("CFD accepted trajectory has a gap or overlapping steps")
        previous = float(row["time_s"])
    return accepted


def write_csv(path: Path, rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def decompose_pressure_work(work_1d: float, foam: list[dict], area: float, rho: float) -> dict:
    """Separate area projection from the actual pressure/flow face-product ledger.

    Face pressure impulse is A*p_area*dt. Multiplying it by mdot/(rho*A)
    recovers p_area*Q*dt, without replacing the actual CFD pressure work.
    The temporal term also includes differences between participant trajectories.
    """
    actual = sum(float(r["inlet_pressure_work_j"]) for r in foam)
    projected = sum(float(r["inlet_pressure_impulse_kg_m_s"])*float(r["mdot_in_kg_s"])/(rho*area) for r in foam)
    return {"area_projected_3d_j": projected, "actual_3d_j": actual,
            "temporal_and_trajectory_difference_j": work_1d-projected,
            "spatial_pressure_flow_covariance_j": projected-actual,
            "total_difference_j": work_1d-actual}


def analyze_transport(root: Path, case: dict, pipe: list[dict]) -> dict:
    with (root / "traces/foam_transport.csv").open() as inp:
        raw = list(csv.DictReader(inp))
    foam = accepted_trace(raw)
    write_csv(root / "foam_accepted.csv", foam)
    if abs(float(foam[-1]["time_s"])-case["coupling"]["end_time_s"]) > 1e-10:
        raise ValueError("Incomplete accepted CFD trace")
    h = case["coupling"]["window_s"]
    energy_interface = "inlet_kinetic_flux_j" in foam[0] and "integral_velocity3_m3_s2" in pipe[0]
    geometry_file = root / "mesh_geometry.json"
    geometry = json.loads(geometry_file.read_text()) if geometry_file.exists() else None
    windows = []
    def total(rows, key):
        return sum(float(r.get(key, 0.)) for r in rows)
    for w in sorted({int(r["window"]) for r in pipe}):
        one = [r for r in pipe if int(r["window"]) == w]
        three = [r for r in foam if int(math.floor((float(r["time_s"])-1e-12)/h)) == w]
        if not three:
            raise ValueError("Missing CFD window")
        m1 = total(one,"integrated_outflow_kg")
        m3 = sum(float(r["mdot_in_kg_s"])*float(r["dt_s"]) for r in three)
        e1 = total(one,"thermal_out_j"); e3 = total(three,"thermal_in_j")
        a1 = total(one,"phase_out_kg"); a3 = total(three,"phase_in_kg")
        momentum1 = 4/3*case["pipe"]["rho"]*math.pi*case["pipe"]["radius"]**2*total(one,"integral_velocity2_m2_s")
        momentum3 = total(three,"inlet_momentum_kg_m_s")
        pressure1 = math.pi*case["pipe"]["radius"]**2*sum(float(r["back_pressure_pa"])*float(r["dt_s"]) for r in one)
        pressure3 = total(three,"inlet_pressure_impulse_kg_m_s")
        windows.append({"window":w, "end_time_s":float(one[-1]["time_s"]),
            "mass_1d_kg":m1,"mass_3d_kg":m3,"interface_mass_residual_kg":m1-m3,
            "thermal_1d_j":e1,"thermal_3d_j":e3,"interface_thermal_residual_j":e1-e3,
            "phase_1d_kg":a1,"phase_3d_kg":a3,"interface_phase_residual_kg":a1-a3,
            "momentum_1d_kg_m_s":momentum1,"momentum_3d_kg_m_s":momentum3,"interface_momentum_residual_kg_m_s":momentum1-momentum3,
            "pressure_impulse_1d_kg_m_s":pressure1,"pressure_impulse_3d_kg_m_s":pressure3,"interface_pressure_force_residual_kg_m_s":pressure1-pressure3,
            "cfd_mass_residual_kg":total(three,"mass_boundary_kg"),
            "cfd_thermal_storage_j":total(three,"thermal_storage_j"),
            "cfd_thermal_boundary_j":total(three,"thermal_boundary_j"),
            "cfd_thermal_source_j":total(three,"thermal_source_j"),
            "cfd_thermal_residual_j":total(three,"thermal_residual_j"),
            "cfd_phase_storage_kg":total(three,"phase_storage_kg"),
            "cfd_phase_boundary_kg":total(three,"phase_boundary_kg"),
            "cfd_phase_source_kg":total(three,"phase_source_kg"),
            "cfd_phase_residual_kg":total(three,"phase_residual_kg"),
            "cfd_momentum_residual_kg_m_s":total(three,"momentum_residual_kg_m_s"),
            "cfd_kinetic_storage_j":total(three,"kinetic_storage_j"),
            "cfd_kinetic_boundary_j":total(three,"kinetic_boundary_j"),
            "cfd_pressure_boundary_j":total(three,"pressure_boundary_j"),
            "cfd_viscous_boundary_work_j":total(three,"viscous_boundary_work_j"),
            "cfd_viscous_dissipation_j":total(three,"viscous_dissipation_j"),
            "cfd_mechanical_residual_j":total(three,"mechanical_residual_j"),
            "cfd_total_energy_residual_j":total(three,"total_energy_residual_j"),
            "pipe_momentum_residual_kg_m_s":total(one,"momentum_residual_kg_m_s"),
            "pipe_mechanical_residual_j":total(one,"mechanical_residual_j"),
            "mixing_thermal_residual_j":total(one,"thermal_storage_j")-total(one,"thermal_in_j")+e1,
            "mixing_phase_residual_kg":total(one,"phase_storage_kg")-total(one,"phase_in_kg")+a1})
        if energy_interface:
            kinetic1 = case["pipe"]["rho"]*math.pi*case["pipe"]["radius"]**2*total(one,"integral_velocity3_m3_s2")
            kinetic3 = total(three,"inlet_kinetic_flux_j")
            work1 = sum(float(r["back_pressure_pa"])*float(r["integrated_outflow_kg"])/case["pipe"]["rho"] for r in one)
            work3 = total(three,"inlet_pressure_work_j")
            decomposition = decompose_pressure_work(work1, three, math.pi*case["pipe"]["radius"]**2, case["pipe"]["rho"])
            windows[-1].update({"pressure_work_"+key: value for key, value in decomposition.items()})
            for quantity, left, right in [("kinetic_flux",kinetic1,kinetic3), ("pressure_work",work1,work3),
                                          ("total_energy_flux",e1+kinetic1+work1,e3+kinetic3+work3)]:
                windows[-1].update({quantity+"_1d_j":left, quantity+"_3d_j":right,
                                    "interface_"+quantity+"_residual_j":left-right})
        if geometry:
            discrete_momentum = momentum1*geometry["discrete_beta"]/(4/3)
            windows[-1].update(momentum_discrete_1d_kg_m_s=discrete_momentum,
                              interface_momentum_discrete_residual_kg_m_s=discrete_momentum-momentum3)
            if energy_interface:
                discrete_kinetic = kinetic1*geometry["discrete_gamma"]/2
                windows[-1].update(kinetic_discrete_1d_j=discrete_kinetic,
                                  interface_kinetic_discrete_residual_j=discrete_kinetic-kinetic3)
    write_csv(root / "window_balances.csv", windows)
    budgets = {}
    for qty, denominator in [("mass","mass_1d_kg"),("thermal","thermal_1d_j"),("phase","phase_1d_kg")]:
        residual = total(windows,f"interface_{qty}_residual_"+ ("j" if qty=="thermal" else "kg"))
        scale = sum(abs(float(r[denominator])) for r in windows)
        budgets[qty] = {"cumulative_residual":residual,"relative_cumulative_residual":abs(residual)/max(scale,1e-14)}
    for qty, denominator, key in [("momentum","momentum_1d_kg_m_s","interface_momentum_residual_kg_m_s"),
                                 ("pressure_force","pressure_impulse_1d_kg_m_s","interface_pressure_force_residual_kg_m_s")]:
        residual = total(windows,key)
        budgets[qty] = {"cumulative_residual":residual,"relative_cumulative_residual":abs(residual)/max(sum(abs(r[denominator]) for r in windows),1e-14)}
    if energy_interface:
        for qty in ["kinetic_flux", "pressure_work", "total_energy_flux"]:
            residual = total(windows, "interface_"+qty+"_residual_j")
            budgets[qty] = {"cumulative_residual":residual,
                "relative_cumulative_residual":abs(residual)/max(sum(abs(r[qty+"_1d_j"]) for r in windows),1e-14)}
    if geometry:
        for qty, suffix in [("momentum_discrete", "kg_m_s"), ("kinetic_discrete", "j")]:
            if qty == "kinetic_discrete" and not energy_interface:
                continue
            residual = total(windows, "interface_"+qty+"_residual_"+suffix)
            budgets[qty] = {"cumulative_residual": residual, "relative_cumulative_residual":abs(residual)/max(sum(abs(r[qty+"_1d_"+suffix]) for r in windows), 1e-14)}
    for qty in budgets:
        suffix = "kg_m_s" if qty in ["momentum","momentum_discrete","pressure_force"] else ("kg" if qty in ["mass","phase"] else "j")
        key = "interface_"+qty+"_residual_"+suffix
        denominator = "pressure_impulse_1d_kg_m_s" if qty == "pressure_force" else qty+"_1d_"+suffix
        residuals = [abs(r[key]) for r in windows]
        scale = sum(abs(r[denominator]) for r in windows)
        budgets[qty].update(max_abs_window_residual=max(residuals), sum_abs_window_residual=sum(residuals),
                           relative_l1_window_residual=sum(residuals)/max(scale,1e-14))
    times = np.array([float(r["time_s"]) for r in foam])
    pt = np.array([0.]+[float(r["time_s"]) for r in pipe])
    mix = case["transport"]
    interface = {}
    for field, key, initial in [("temperature_k","T_in_k",mix["temperature_k"]),("phase_fraction","alpha_in",mix["alpha"])]:
        reference = np.interp(times,pt,[initial]+[float(r[field]) for r in pipe])
        delta = np.array([float(r[key]) for r in foam])-reference
        interface[field] = {"rms":float(np.sqrt(np.mean(delta**2))),"max_abs":float(np.max(np.abs(delta)))}
    mms = bool(case.get("scalar_cfd",{}).get("manufactured",False))
    advection = bool(case.get("scalar_cfd",{}).get("analytic_advection",False))
    result = {"manufactured_solution":mms,"accepted_cfd_steps":len(foam),"trial_cfd_steps":len(raw),
        "analytic_advection": advection,
        "discrete_profile_geometry": geometry,
        "interface":interface,"interface_window_integrals":budgets,
        "max_cfd_thermal_residual_j":max(abs(float(r["thermal_residual_j"])) for r in foam),
        "max_cfd_phase_residual_kg":max(abs(float(r["phase_residual_kg"])) for r in foam),
        "cumulative_cfd_thermal_residual_j":total(foam,"thermal_residual_j"),
        "cumulative_cfd_phase_residual_kg":total(foam,"phase_residual_kg"),
        "cumulative_cfd_momentum_residual_kg_m_s":total(foam,"momentum_residual_kg_m_s"),
        "cumulative_cfd_mechanical_residual_j":total(foam,"mechanical_residual_j"),
        "cumulative_cfd_total_energy_residual_j":total(foam,"total_energy_residual_j"),
        "max_pipe_momentum_residual_kg_m_s":max(abs(float(r["momentum_residual_kg_m_s"])) for r in pipe),
        "max_pipe_mechanical_residual_j":max(abs(float(r["mechanical_residual_j"])) for r in pipe),
        "alpha_min":min(float(r["alpha_min"]) for r in foam),"alpha_max":max(float(r["alpha_max"]) for r in foam),
        "scope":"thermal sensible energy; equal-property phases; signed boundary flux includes diffusion; mechanical energy separate; CFD momentum uses reconstructed stress diagnostic"}
    if mms or advection:
        result["max_temperature_field_rms_k"] = max(float(r["temperature_rms_k"]) for r in foam)
        result["max_alpha_field_rms"] = max(float(r["alpha_rms"]) for r in foam)
        tau = mix["volume_m3"]/(math.pi*case["pipe"]["radius"]**2*case["pipe"]["velocity"])
        t1 = np.array([float(r["time_s"]) for r in pipe])
        for field, initial, target in [("temperature_k",mix["temperature_k"],mix["supply_temperature_k"]),
                                       ("phase_fraction",mix["alpha"],mix["supply_alpha"])]:
            exact = target+(initial-target)*np.exp(-t1/tau)
            result["max_1d_"+field+"_error"] = float(np.max(np.abs(np.array([float(r[field]) for r in pipe])-exact)))
    if energy_interface:
        scale = max(sum(abs(r["pressure_work_1d_j"]) for r in windows), 1e-14)
        terms = {key: total(windows,"pressure_work_"+key) for key in decomposition}
        result["pressure_work_decomposition"] = {**terms,
            "normalization_j": scale,
            "signed_temporal_percent": 100*terms["temporal_and_trajectory_difference_j"]/scale,
            "signed_spatial_percent": 100*terms["spatial_pressure_flow_covariance_j"]/scale,
            "signed_total_percent": 100*terms["total_difference_j"]/scale,
            "closure_error_j": terms["total_difference_j"]-terms["temporal_and_trajectory_difference_j"]-terms["spatial_pressure_flow_covariance_j"],
            "scope": "signed additive diagnostic; actual face-product pressure work remains the conservation metric"}
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2,1,figsize=(9,6),sharex=True,constrained_layout=True)
    for ax,field,key,label in [(axes[0],"temperature_k","T_in_k","Temperature [K]"),(axes[1],"phase_fraction","alpha_in","Phase A volume fraction")]:
        ax.plot(pt[1:],[float(r[field]) for r in pipe],label="1D interface")
        ax.plot(times,[float(r[key]) for r in foam],"--",label="3D inlet")
        if mms or advection:
            initial,target=(mix["temperature_k"],mix["supply_temperature_k"]) if field=="temperature_k" else (mix["alpha"],mix["supply_alpha"])
            ax.plot(times,target+(initial-target)*np.exp(-times/tau),":",label="Analytic nominal-flow benchmark")
        ax.set_ylabel(label);ax.grid(alpha=.25);ax.legend()
    axes[-1].set_xlabel("Physical time [s]");fig.savefig(root / "transport.png",dpi=160);plt.close(fig)
    if mms or advection:
        fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True, constrained_layout=True)
        for ax, key, label in [(axes[0], "temperature_rms_k", "Temperature field RMS [K]"),
                               (axes[1], "alpha_rms", "Phase A field RMS")]:
            ax.plot(times, [float(r[key]) for r in foam]); ax.set_ylabel(label); ax.grid(alpha=.25)
        axes[-1].set_xlabel("Physical time [s]")
        fig.savefig(root / "analytic-field-error.png", dpi=160); plt.close(fig)
    (root/"transport_summary.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result
