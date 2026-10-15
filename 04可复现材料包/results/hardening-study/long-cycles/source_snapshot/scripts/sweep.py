"""Exchange-frequency study against a declared finer-window numerical reference."""
from __future__ import annotations
import argparse
import copy
import csv
import json
from pathlib import Path
import time
import numpy as np

from run_case import ROOT, run
from analyze import analyze, read_csv


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--case", type=Path, default=ROOT / "cases/valve-transient.json")
    p.add_argument("--windows", nargs="+", type=float, default=[0.001, 0.0025, 0.005, 0.01])
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    windows = sorted(set(args.windows))
    base = json.loads(args.case.read_text())
    root = (args.output or ROOT / "results" / ("sweep-" + time.strftime("%Y%m%d-%H%M%S"))).resolve()
    if root.exists():
        raise FileExistsError(root)
    reports, histories = [], []
    for i, h in enumerate(windows):
        case = copy.deepcopy(base)
        case["coupling"]["window_s"] = h
        target = root / f"window-{i:02d}"
        run(case, target)
        reports.append(analyze(target))
        rows = read_csv(target / "pipe.csv")
        histories.append((np.array([float(r["time_s"]) for r in rows]),
                          np.array([float(r["velocity_m_s"]) for r in rows])))
    ref_t, ref_u = histories[0]
    records = []
    for report, (t, u) in zip(reports, histories):
        # Compare on the fine-reference sampling grid, inside the common time interval.
        mask = (ref_t >= t[0]) & (ref_t <= t[-1])
        delta = np.interp(ref_t[mask], t, u) - ref_u[mask]
        rms = np.sqrt(np.mean(delta**2)) / max(np.max(np.abs(ref_u[mask])), 1e-12)
        records.append({"window_s": report["window_s"], "frequency_hz": 1 / report["window_s"],
                        "relative_rms_velocity_vs_fine": float(rms), "wall_seconds": report["wall_seconds"],
                        "forward_p95_ms": report["latency"]["1d_to_3d"]["p95_ms"],
                        "reverse_p95_ms": report["latency"]["3d_to_1d"]["p95_ms"],
                        "accepted_windows": report["accepted_windows"]})
    with (root / "sweep.csv").open("w", newline="") as out:
        w = csv.DictWriter(out, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    axes[0].plot([r["frequency_hz"] for r in records], [r["relative_rms_velocity_vs_fine"] for r in records], "o-")
    axes[0].set_ylabel("Velocity relative RMS vs fine window")
    axes[1].plot([r["frequency_hz"] for r in records], [r["wall_seconds"] for r in records], "o-")
    axes[1].set_ylabel("Wall time [s]")
    for ax in axes:
        ax.set_xlabel("Exchange frequency [Hz]")
        ax.grid(alpha=0.25)
    fig.savefig(root / "accuracy-efficiency.png", dpi=160)
    plt.close(fig)
    (root / "report.md").write_text(f'''# 交换频率扫描

最小窗口 {windows[0]:.6g} s 用作数值对照。该对照用于比较交换窗口敏感性，解析/实验验证需另行完成。保持物性、网格、控制动作及两侧最大内部时间步一致。

![频率与误差、耗时](accuracy-efficiency.png)

原始汇总：[sweep.csv](sweep.csv)。各子目录保留独立输入、日志和报告。墙钟耗时含容器启动、网格准备和后处理，不宜直接当作纯通信成本。
''', encoding="utf-8")
    print(f"Sweep report: {root / 'report.md'}")


if __name__ == "__main__":
    main()

