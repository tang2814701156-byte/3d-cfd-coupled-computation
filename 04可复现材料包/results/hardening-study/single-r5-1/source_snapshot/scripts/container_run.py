"""Launch both real participants with bounded waits and failure propagation."""
from __future__ import annotations
import os
import json
import re
import shutil
from pathlib import Path
import subprocess
import sys
import time
import tempfile
import numpy as np


def initialize_fields(root: Path, case: dict) -> None:
    """Start with the analytic developed profile to separate startup from valve response."""
    foam = root / "fluid3d"
    subprocess.run(["postProcess", "-func", "writeCellCentres", "-time", "0"], cwd=foam,
                   env=dict(os.environ, PWD=str(foam)), check=True, timeout=90)
    s = (foam / "0/C").read_text()
    match = re.search(r"internalField\s+nonuniform\s+List<vector>\s+(\d+)\s*\((.*?)\)\s*;", s, re.S)
    if match is None:
        raise ValueError("Cannot read OpenFOAM cell centres")
    centers = np.fromstring(re.sub(r"[()]", " ", match[2]), sep=" ").reshape(-1, 3)
    if len(centers) != int(match[1]):
        raise ValueError("Cell count mismatch")
    pipe = case["pipe"]
    u = 2 * pipe["velocity"] * (1 - (centers[:, 0]**2 + centers[:, 1]**2) / pipe["radius"]**2)
    geometry_file = root / "mesh_geometry.json"
    if geometry_file.exists():
        u *= json.loads(geometry_file.read_text())["parabolic_profile_scale"]
    p = 8 * pipe["nu"] * pipe["velocity"] / pipe["radius"]**2 * (pipe["length"]+case["cfd"]["length"] - centers[:, 2])
    for field, kind, rows in [
        ("U", "vector", [f"(0 0 {v:.17g})" for v in u]),
        ("p", "scalar", [f"{v:.17g}" for v in p]),
    ]:
        path = foam / "0" / field
        s = path.read_text()
        internal = f"internalField nonuniform List<{kind}>\n{len(rows)}\n(\n" + "\n".join(rows) + "\n);"
        s = re.sub(r"internalField\s+uniform\s+[^;]+;", lambda m: internal, s, count=1)
        if field == "p":
            p_back = 8 * pipe["nu"] * pipe["velocity"] * case["cfd"]["length"] / pipe["radius"]**2
            s = s.replace("type            fixedFluxExtrapolatedPressure;", f"type fixedFluxExtrapolatedPressure;\n        value uniform {p_back};")
        path.write_text(s)
    if "transport" in case and case.get("scalar_cfd", {}).get("manufactured", False):
        for name, initial, gradient in [
            ("T", case["transport"]["temperature_k"], case["scalar_cfd"].get("temperature_gradient_k_m", 0.)),
            ("alpha", case["transport"]["alpha"], case["scalar_cfd"].get("alpha_gradient_per_m", 0.)),
        ]:
            path = foam / "0" / name
            values = initial + gradient*(centers[:, 2]-pipe["length"])
            internal = f"internalField nonuniform List<scalar>\n{len(values)}\n(\n" + "\n".join(f"{v:.17g}" for v in values) + "\n);"
            path.write_text(re.sub(r"internalField\s+uniform\s+[^;]+;", lambda m: internal, path.read_text(), count=1))


def solve(root: Path) -> None:
    env = os.environ.copy()
    env["CFD_TRACE_DIR"] = str(root / "traces")
    env["CFD_STATUS_PATH"] = os.environ.get("CFD_STATUS_PATH", str(root / "status.json"))
    case = json.loads((root / "case.json").read_text())
    env["CFD_RADIUS"] = str(case["pipe"]["radius"])
    (root / "environment.json").write_text(json.dumps({
        "python": sys.version, "openfoam": env.get("WM_PROJECT_VERSION"),
        "precice": subprocess.check_output(["precice-version"], text=True).strip(),
        "pip_freeze": subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True).splitlines(),
        "cpu_count": os.cpu_count(), "platform": sys.platform, "storage_mode": "container_local_workdir",
        "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
        "debian_packages": subprocess.check_output(["dpkg-query", "-W", "-f=${Package}=${Version}\n"], text=True).splitlines(),
    }, indent=2))
    env["PWD"] = str(root / "fluid3d")
    subprocess.run(["blockMesh"], cwd=root / "fluid3d", env=env, check=True, timeout=60)
    if case["cfd"].get("normalize_interface_area", False):
        from mesh_geometry import normalize_area
        normalize_area(root / "fluid3d", case["pipe"]["radius"])
    initialize_fields(root, case)
    logs, processes = [], []
    try:
        for name, cmd, directory in [
            ("pipe.log", [sys.executable, "-m", "cfd_coupling.participant", "--case", str(root / "case.json")], root),
            ("foam.log", ["/opt/cfd/coupledTransportFoam.bin" if "transport" in case else "pimpleFoam"], root / "fluid3d"),
        ]:
            log = (root / name).open("w")
            logs.append(log)
            child_env = dict(env, PWD=str(directory))
            processes.append(subprocess.Popen(cmd, cwd=directory, env=child_env, stdout=log, stderr=subprocess.STDOUT))
        deadline = time.monotonic() + case.get("runtime", {}).get("participant_timeout_s", 840)
        fault = case.get("fault_injection")
        injected = False
        while any(p.poll() is None for p in processes):
            journal = root / "accepted_windows.jsonl"
            if fault and not injected and journal.exists():
                accepted = len(journal.read_text().splitlines())
                if accepted >= fault["after_accepted_windows"]:
                    index = {"pipe": 0, "foam": 1}[fault["participant"]]
                    processes[index].kill()
                    injected = True
                    (root / "fault_injection.json").write_text(json.dumps({
                        "participant": fault["participant"], "accepted_windows": accepted,
                        "injected_monotonic_s": time.monotonic(), "signal": "SIGKILL"}))
            failed = [p for p in processes if p.poll() not in (None, 0)]
            if failed:
                raise RuntimeError(f"Participant failed: {[p.returncode for p in failed]}")
            if time.monotonic() > deadline:
                raise TimeoutError("Participant timeout")
            time.sleep(0.1)
        if any(p.returncode for p in processes):
            raise RuntimeError("Nonzero participant exit status")
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        for log in logs:
            log.close()
        (root / "process_cleanup.json").write_text(json.dumps({
            "all_stopped": all(p.poll() is not None for p in processes),
            "return_codes": [p.returncode for p in processes],
            "cleanup_monotonic_s": time.monotonic()}))
    subprocess.run(["postProcess", "-latestTime", "-func", "sampleDict"], cwd=root / "fluid3d", env=env, check=True, timeout=90)
    (root / "fluid3d" / "case.foam").touch()
    print("Both coupling participants completed successfully.")


def main(target: Path) -> None:
    # Linux-local solver files avoid Windows bind-mount metadata overhead.
    # Copy the complete result back, including diagnostic files on failures.
    # Scratch is copied back in full; no explicit filesystem deletion is used.
    directory = tempfile.mkdtemp(prefix="cfd-v04-")
    if directory:
        root = Path(directory) / "case"
        shutil.copytree(target, root, ignore=shutil.ignore_patterns("container.log"))
        config = root / "precice-config.xml"
        config.write_text(config.read_text().replace(str(target), str(root)))
        failure = None
        try:
            os.environ["CFD_STATUS_PATH"] = str(target / "status.json")
            solve(root)
        except Exception as exc:
            failure = str(exc)
            raise
        finally:
            shutil.copytree(root, target, dirs_exist_ok=True)
            status = target / "status.json"
            payload = json.loads(status.read_text()) if status.exists() else {}
            payload.update(state="failed" if failure else "completed")
            if failure:
                payload["error"] = failure
            status.write_text(json.dumps(payload))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
