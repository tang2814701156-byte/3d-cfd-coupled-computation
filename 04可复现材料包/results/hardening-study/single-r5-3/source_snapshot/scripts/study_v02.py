"""Local numerical validation: two analytic cases, refinement and repeated frequency study."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import numpy as np
from run_case import ROOT, run
from analyze import analyze, read_csv
from transport_analysis import write_csv
from verify_results import verify


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--repeats",type=int,default=3)
    args=parser.parse_args()
    if args.repeats<1: raise ValueError("Repeats must be positive")
    root=args.output.resolve()
    if root.exists(): raise FileExistsError(root)
    root.mkdir(parents=True)
    results=[]
    def execute(case,name,category):
        target=root/name
        print(f"Running {name}",flush=True)
        run(case,target)
        report=analyze(target)
        verify(target)
        results.append({"name":name,"category":category,"wall_seconds":report["wall_seconds"],
                        "window_s":report["window_s"],"accepted_windows":report["accepted_windows"],
                        "velocity_error":report["steady_poiseuille_reference"]["relative_final_velocity_error"],
                        "temperature_field_rms_k":report.get("transport",{}).get("max_temperature_field_rms_k"),
                        "alpha_field_rms":report.get("transport",{}).get("max_alpha_field_rms")})
        write_csv(root/"runs.csv",results)
        return report,read_csv(target/"pipe.csv")
    steady=json.loads((ROOT/"cases/pipe-steady-water.json").read_text())
    execute(steady,"steady","steady_analytic")
    fine=copy.deepcopy(steady)
    fine["cfd"].update(radial_cells_per_block=12,axial_cells=80)
    execute(fine,"steady-fine","grid_refinement")
    mms=json.loads((ROOT/"cases/transport-mms.json").read_text())
    execute(mms,"mms","manufactured_analytic")
    for label,dt in [("half",.00025),("quarter",.000125)]:
        fine=copy.deepcopy(mms)
        fine["coupling"].update(dt_3d_s=dt,dt_1d_s=2*dt)
        execute(fine,"mms-time-"+label,"time_refinement")
    fine=copy.deepcopy(mms)
    fine["cfd"].update(radial_cells_per_block=8,axial_cells=80)
    execute(fine,"mms-grid-fine","grid_refinement")
    base=json.loads((ROOT/"cases/valve-transport.json").read_text())
    execute(base,"valve","physical_transient")
    base["coupling"].update(dt_1d_s=.00025,dt_3d_s=.000125)
    windows=[.00025,.001,.005,.01]
    frequency=[]
    reference=None
    fields=["velocity_m_s","back_pressure_pa","temperature_k","phase_fraction"]
    for i,h in enumerate(windows):
        for repetition in range(args.repeats):
            case=copy.deepcopy(base);case["coupling"]["window_s"]=h
            name=f"frequency-{i:02d}-repeat-{repetition:02d}"
            report,rows=execute(case,name,"frequency")
            t=np.array([float(r["time_s"]) for r in rows])
            history={field:np.array([float(r[field]) for r in rows]) for field in fields}
            if reference is None: reference=(t,history)
            rt,rh=reference
            mask=(rt>=t[0])&(rt<=t[-1])
            record={"name":name,"window_s":h,"frequency_hz":1/h,"repetition":repetition,
                "wall_seconds":report["wall_seconds"],"accepted_windows":report["accepted_windows"],
                "forward_p95_ms":report["latency"]["1d_to_3d"]["p95_ms"],
                "reverse_p95_ms":report["latency"]["3d_to_1d"]["p95_ms"],
                "control_error_s":report["max_control_error_s"],"passed":True}
            for field in fields:
                diff=np.interp(rt[mask],t,history[field])-rh[field][mask]
                record["normalized_rms_"+field]=float(np.sqrt(np.mean(diff**2))/max(np.ptp(rh[field][mask]),1e-12))
            frequency.append(record)
            write_csv(root/"frequency.csv",frequency)
    aggregated=[]
    for h in windows:
        group=[r for r in frequency if r["window_s"]==h]
        aggregated.append({"window_s":h,"frequency_hz":1/h,"repeats":len(group),
            "wall_median_s":float(np.median([r["wall_seconds"] for r in group])),
            "wall_min_s":min(r["wall_seconds"] for r in group),"wall_max_s":max(r["wall_seconds"] for r in group),
            **{"normalized_rms_"+f:float(np.median([r["normalized_rms_"+f] for r in group])) for f in fields}})
    write_csv(root/"frequency_aggregated.csv",aggregated)
    summary={"runs":len(results),"accepted_windows":sum(r["accepted_windows"] for r in results),
        "shortest_tested_stable_window_s":min(windows),"frequency_repeats":args.repeats,
        "scope":"tested lower bound only; no failure bracket and no universal minimum; accuracy relative to fine numerical window"}
    (root/"study_summary.json").write_text(json.dumps(summary,indent=2))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(11,4),constrained_layout=True)
    x=[r["frequency_hz"] for r in aggregated]
    for field in fields:
        axes[0].plot(x,[r["normalized_rms_"+field] for r in aggregated],"o-",label=field)
    med=np.array([r["wall_median_s"] for r in aggregated])
    axes[1].errorbar(x,med,yerr=[med-[r["wall_min_s"] for r in aggregated],[r["wall_max_s"] for r in aggregated]-med],fmt="o-")
    axes[0].set_ylabel("RMS / fine-reference signal range");axes[0].legend(fontsize=8)
    axes[1].set_ylabel("Wall time median and range [s]")
    for ax in axes: ax.set_xscale("log");ax.set_xlabel("Exchange frequency [Hz]");ax.grid(alpha=.25)
    fig.savefig(root/"frequency.png",dpi=160);plt.close(fig)
    print(json.dumps(summary,indent=2),flush=True)


if __name__=="__main__": main()
