"""Read raw results; report the scope of each metric without upgrading it to validation."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import numpy as np


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def stats(samples: list[float]) -> dict:
    if not samples:
        return {"samples": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
    a = np.array(samples)
    return {"samples": len(a), "p50_ms": float(np.percentile(a, 50)),
            "p95_ms": float(np.percentile(a, 95)), "p99_ms": float(np.percentile(a,99)), "max_ms": float(a.max())}


def latency(root: Path) -> dict:
    forward, reverse = {}, {}
    p = root / "traces/foam_reads.csv"
    if p.exists():
        with p.open() as f:
            for row in csv.reader(f):
                seq, sent, usable = int(row[0]), int(row[2]), int(row[3])
                if usable < sent:
                    raise ValueError("Monotonic timestamp order violation")
                forward[seq] = min(forward.get(seq, float("inf")), (usable - sent) / 1e6)
    for row in read_csv(root / "reverse_latency.csv"):
        seq, sent, usable = int(row["seq"]), int(row["sent_ns"]), int(row["usable_ns"])
        if usable < sent:
            raise ValueError("Monotonic timestamp order violation")
        reverse[seq] = min(reverse.get(seq, float("inf")), (usable - sent) / 1e6)
    return {"1d_to_3d": stats(list(forward.values())), "3d_to_1d": stats(list(reverse.values())),
            "scope": "first receiver use per observed source sample; includes implicit trial iterations and stamp I/O; same-container CLOCK_MONOTONIC"}


def analyze(root: Path) -> dict:
    case = json.loads((root / "case.json").read_text())
    pipe = read_csv(root / "pipe.csv")
    if not pipe:
        raise ValueError("No accepted data")
    control = read_csv(root / "control_events.csv")
    boundary_path = root / "traces/foam_boundary.csv"
    boundary = np.loadtxt(boundary_path, delimiter=",", ndmin=2) if boundary_path.exists() else np.empty((0, 6))
    model = json.loads((root / "participant_summary.json").read_text())
    execution = json.loads((root / "execution.json").read_text())
    rho, nu, radius = [case["pipe"][k] for k in ["rho", "nu", "radius"]]
    length = case["pipe"]["length"] + case["cfd"]["length"]
    reference_u = case["pipe"]["supply_pressure"] * radius**2 / (8 * rho * nu * length)
    reference_pressure = case["pipe"]["supply_pressure"] * case["cfd"]["length"] / length
    final_u = float(pipe[-1]["velocity_m_s"])
    report = {
        "case": case["name"], "physical_end_s": model["physical_end_s"],
        "wall_seconds": execution["wall_seconds"], "window_s": case["coupling"]["window_s"],
        "accepted_windows": model["accepted_windows"], "accepted_1d_substeps": model["accepted_substeps"],
        "write_attempts_including_rollbacks": model["write_attempts"], "latency": latency(root),
        "control_events": len(control),
        "max_control_error_s": max([abs(float(e["error_s"])) for e in control], default=0.),
        "mass_mapping": {
            "samples_including_trials": len(boundary),
            "max_abs_volume_flow_residual_m3_s": float(np.max(np.abs(boundary[:, 5]))) if len(boundary) else None,
            "scope": "instantaneous discrete inlet profile normalization; not a full window or system mass/energy ledger",
        },
        "final_velocity_m_s": final_u,
        "steady_poiseuille_reference": {
            "velocity_m_s": reference_u,
            "relative_final_velocity_error": abs(final_u - reference_u) / abs(reference_u),
            "interface_pressure_pa": reference_pressure,
            "relative_final_pressure_error": abs(float(pipe[-1]["back_pressure_pa"]) - reference_pressure) / abs(reference_pressure),
            "applicable": not bool(case["control"]["events"]),
        },
        "physics_scope": "single-phase isothermal incompressible; no water hammer, heat equation or phase transport",
        "participant_timing_seconds": model.get("timing_seconds", {}),
        "participant_timing_scope": model.get("timing_scope", "not recorded"),
        "trial_work_amplification": model["write_attempts"]/model["accepted_substeps"],
        "wall_seconds_per_physical_second": execution["wall_seconds"]/model["physical_end_s"],
    }
    (root / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    if "transport" in case:
        from transport_analysis import analyze_transport
        report["transport"] = analyze_transport(root, case, pipe)
        report["physics_scope"] = "incompressible equal-property homogeneous two-phase scalar transport; sensible thermal energy"
        (root / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    t = np.array([float(r["time_s"]) for r in pipe])
    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True, constrained_layout=True)
    axes[0].plot(t, [float(r["velocity_m_s"]) for r in pipe], label="1D interface velocity")
    if not case["control"]["events"]:
        axes[0].axhline(reference_u, color="k", linestyle="--", label="Steady Poiseuille")
    axes[0].set_ylabel("Velocity [m/s]")
    axes[0].legend()
    axes[1].plot(t, [float(r["back_pressure_pa"]) for r in pipe], color="tab:orange")
    axes[1].set_ylabel("Back pressure [Pa]")
    starts = [float(r["step_start_s"]) for r in pipe] + [t[-1]]
    openings = [float(r["opening"]) for r in pipe] + [float(pipe[-1]["opening"])]
    axes[2].step(starts, openings, where="post", color="tab:green")
    axes[2].set_ylabel("Valve opening")
    axes[2].set_xlabel("Physical time [s]")
    for ax in axes:
        ax.grid(alpha=0.25)
        for event in control:
            ax.axvline(float(event["applied_s"]), color="gray", alpha=0.4, linestyle=":")
    fig.suptitle(case["name"])
    fig.savefig(root / "timeseries.png", dpi=160)
    plt.close(fig)
    samples = list((root / "fluid3d/postProcessing/sampleDict").glob("*/centerline_p.xy"))
    if samples:
        sample = max(samples, key=lambda p: float(p.parent.name))
        cfd = np.loadtxt(sample, ndmin=2)
        one = np.loadtxt(root / "pipe_final.csv", delimiter=",", skiprows=1, ndmin=2)
        fig, ax = plt.subplots(figsize=(9, 4), constrained_layout=True)
        ax.plot(one[:, 0], one[:, 1], label="1D")
        ax.plot(cfd[:, 0], cfd[:, 1] * rho, label="3D centreline")
        if not case["control"]["events"]:
            x = np.linspace(0, length, 101)
            ax.plot(x, case["pipe"]["supply_pressure"] * (1-x/length), "k--", label="Steady Poiseuille")
        ax.axvline(case["pipe"]["length"], color="gray", linestyle=":", label="Coupling interface")
        ax.set_xlabel("Axial coordinate [m]")
        ax.set_ylabel("Gauge pressure [Pa]")
        ax.legend()
        ax.grid(alpha=0.25)
        fig.savefig(root / "pressure-profile.png", dpi=160)
        plt.close(fig)
    def fmt(value):
        return "未取得样本" if value is None else f"{value:.6g}"
    forward, reverse = report["latency"]["1d_to_3d"], report["latency"]["3d_to_1d"]
    text = f'''# 运行报告：{case['name']}

## 运行结果

- 物理终止时间：{report['physical_end_s']:.6g} s。
- 交换窗口：{report['window_s']:.6g} s；一维最大子步 {case['coupling']['dt_1d_s']:.6g} s；三维最大子步 {case['coupling']['dt_3d_s']:.6g} s。
- 完整运行墙钟耗时：{report['wall_seconds']:.6g} s；接受 {report['accepted_windows']} 个窗口。
- 控制事件：{report['control_events']} 次；最大仿真时间注入误差 {report['max_control_error_s']:.6g} s。
- 正向延迟 p50 / p95 / max：{fmt(forward['p50_ms'])} / {fmt(forward['p95_ms'])} / {fmt(forward['max_ms'])} ms，{forward['samples']} 个源样本。
- 反向延迟 p50 / p95 / max：{fmt(reverse['p50_ms'])} / {fmt(reverse['p95_ms'])} / {fmt(reverse['max_ms'])} ms，{reverse['samples']} 个源样本。
- 瞬时离散入口体积流量映射最大残差：{fmt(report['mass_mapping']['max_abs_volume_flow_residual_m3_s'])} m³/s。

延迟按每个已观测源样本在接收侧第一次可用的时间统计，包含隐式试算和时间戳文件开销。同一容器的两个进程使用 CLOCK_MONOTONIC，原始时间戳保留于 traces/ 与 reverse_latency.csv。

## 验证范围

一维采用均匀不可压缩管道惯性及准稳态 Poiseuille 摩擦；三维为实际 OpenFOAM pimpleFoam 层流计算。温度与单相标记作为记录元数据。入口映射残差验证离散剖面的总流量，完整窗口及系统质量、动量、能量收支尚需扩展。

稳态 Poiseuille 参考速度为 {reference_u:.6g} m/s；本次末端速度 {final_u:.6g} m/s。{'稳态末端相对误差为 ' + format(report['steady_poiseuille_reference']['relative_final_velocity_error'], '.6g') + '，应结合收敛与网格研究使用。' if report['steady_poiseuille_reference']['applicable'] else '本算例存在控制瞬态，稳态解析值不用于判定瞬态波形准确性。'}

## 输出

![时序曲线](timeseries.png)

![末端轴向压力](pressure-profile.png)

- [量化摘要](summary.json)
- [接受步日志](pipe.csv)
- [一维进程日志](pipe.log)、[OpenFOAM 日志](foam.log)
- [固定输入](case.json)、[耦合配置](precice-config.xml)
- [上游来源](source_manifest.json)、[容器镜像信息](docker_image.json)
'''
    (root / "report.md").write_text(text, encoding="utf-8")
    if "transport" in case:
        text = text.replace("温度与单相标记作为记录元数据。入口映射残差验证离散剖面的总流量，完整窗口及系统质量、动量、能量收支尚需扩展。",
            "温度与相 A 体积分数通过 preCICE 传入三维入口，并实际求解输运方程。两相等密度、等热容、同速；热能采用显热参考状态。一维混合容积与管道机械能分别记账。三维动量残差采用重构面应力诊断，尚未构成完整总能量闭合。")
        tr = report["transport"]
        text += f'''\n## 温度、相分数与窗口收支\n
- 温度／相分数界面最大偏差：{tr['interface']['temperature_k']['max_abs']:.6g} K / {tr['interface']['phase_fraction']['max_abs']:.6g}。
- 质量／显热／相 A 窗口积分累计相对残差：{tr['interface_window_integrals']['mass']['relative_cumulative_residual']:.6g} / {tr['interface_window_integrals']['thermal']['relative_cumulative_residual']:.6g} / {tr['interface_window_integrals']['phase']['relative_cumulative_residual']:.6g}。
- 三维显热／相 A 单步收支最大残差：{tr['max_cfd_thermal_residual_j']:.6g} J / {tr['max_cfd_phase_residual_kg']:.6g} kg。
- 三维轴向动量累计诊断残差：{tr['cumulative_cfd_momentum_residual_kg_m_s']:.6g} kg·m/s。
- 接受三维步 {tr['accepted_cfd_steps']}，原始试算步 {tr['trial_cfd_steps']}；回滚时丢弃旧轨迹后缀。

{'本算例使用带明确源项的制造解验证温度与相分数输运。' if tr['manufactured_solution'] else ('本算例采用无源项对流特征线解析解，误差同时包含水力场、入口混合状态和标量离散误差。' if tr.get('analytic_advection') else '本算例没有制造源项，展示阀门反馈与温度、相分数的实际输运。')}

![温度与相分数](transport.png)

- [窗口账本](window_balances.csv)、[三维接受步](foam_accepted.csv)、[温度相分数摘要](transport_summary.json)。
'''
        (root / "report.md").write_text(text, encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    analyze(parser.parse_args().directory.resolve())

