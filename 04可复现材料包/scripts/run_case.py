"""Create a fresh run directory, start the container, and keep logs/results."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get("CFD_IMAGE_REF", "cfd-coupling:local")


def validate(case: dict) -> None:
    fault = case.get("fault_injection")
    if fault and (fault.get("participant") not in ("pipe", "foam") or
                  not isinstance(fault.get("after_accepted_windows"), int) or fault["after_accepted_windows"] < 1):
        raise ValueError("Fault injection requires participant pipe/foam and a positive accepted-window count")
    scale = case["pipe"]["radius"]/5
    if not math.isclose(case["pipe"]["length"],20*scale) or not math.isclose(case["cfd"]["length"],20*scale):
        raise ValueError("Round-pipe mesh supports both lengths = 4 * radius")
    c = case["coupling"]
    relaxation = c.get("initial_relaxation", .2)
    if not isinstance(relaxation, (int, float)) or not math.isfinite(relaxation) or not 0 < relaxation <= 1:
        raise ValueError("initial_relaxation must be finite and in (0, 1]")
    for key in ["end_time_s", "window_s", "dt_1d_s", "dt_3d_s", "relative_tolerance"]:
        if not math.isfinite(c[key]) or c[key] <= 0:
            raise ValueError(f"Invalid {key}")
    if not isinstance(c["max_iterations"], int) or c["max_iterations"] < 2:
        raise ValueError("max_iterations must be an integer >= 2")
    for key in ["radial_cells_per_block", "axial_cells"]:
        if not isinstance(case["cfd"][key], int) or case["cfd"][key] < 2:
            raise ValueError(f"Invalid mesh count: {key}")
    if c["window_s"] > c["end_time_s"]:
        raise ValueError("Exchange window exceeds simulation duration")
    for event in case["control"]["events"]:
        if not 0 <= event["time_s"] < c["end_time_s"]:
            raise ValueError("Event outside simulation")
        # An initial version uses globally aligned control events.
        if abs(event["time_s"] / c["window_s"] - round(event["time_s"] / c["window_s"])) > 1e-8:
            raise ValueError("Control events must align with exchange window boundaries")
    sys.path.insert(0, str(ROOT / "src"))
    from cfd_coupling.model import Controller, PipeModel
    PipeModel(**case["pipe"])
    Controller(case["control"]["events"], case["control"]["period_s"])
    if "transport" in case:
        from cfd_coupling.transport import MixingVolume
        MixingVolume(**case["transport"])
        if case["pipe"].get("velocity", 0) <= 0:
            raise ValueError("Transport cases require positive initial forward flow")
        scalar = case.get("scalar_cfd", {})
        if scalar.get("analytic_advection", False):
            if scalar.get("manufactured", False) or case["control"]["events"]:
                raise ValueError("Analytic advection requires no sources and no valve events")
            expected = case["pipe"]["supply_pressure"]*case["pipe"]["radius"]**2/(8*case["pipe"]["rho"]*case["pipe"]["nu"]*(case["pipe"]["length"]+case["cfd"]["length"]))
            if not math.isclose(case["pipe"]["velocity"], expected, rel_tol=1e-10) or case["pipe"].get("opening", 1.) != 1.:
                raise ValueError("Analytic advection requires the nominal steady Poiseuille initial flow")
        for key in ["thermal_diffusivity_m2_s", "phase_diffusivity_m2_s"]:
            if scalar.get(key, 0.) != 0.:
                raise ValueError("Current one-way scalar interface supports pure advection; diffusivity must be zero")


def configuration(case: dict, exchange_directory: str) -> str:
    c, radius = case["coupling"], case["pipe"]["radius"]
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<precice-configuration experimental="true">
  <log><sink filter="%Severity% &gt; debug and %Rank% = 0" enabled="true" /></log>
  <profiling mode="fundamental" synchronize="false" />
  <data:vector name="Velocity" />
  <data:scalar name="Pressure" />
  <mesh name="Fluid1DLeft-Mesh" dimensions="3">
    <use-data name="Velocity" /><use-data name="Pressure" />
  </mesh>
  <mesh name="Fluid3DRight-Mesh" dimensions="3">
    <use-data name="Velocity" /><use-data name="Pressure" />
  </mesh>
  <participant name="Fluid1DLeft">
    <provide-mesh name="Fluid1DLeft-Mesh" />
    <receive-mesh name="Fluid3DRight-Mesh" from="Fluid3DRight" />
    <write-data name="Velocity" mesh="Fluid1DLeft-Mesh" />
    <read-data name="Pressure" mesh="Fluid1DLeft-Mesh" />
    <mapping:axial-geometric-multiscale direction="read" multiscale-dimension="1d-3d"
      multiscale-cross-section="circle" multiscale-type="collect" multiscale-radius="{radius}"
      multiscale-axis="z" from="Fluid3DRight-Mesh" to="Fluid1DLeft-Mesh" constraint="consistent" />
  </participant>
  <participant name="Fluid3DRight">
    <provide-mesh name="Fluid3DRight-Mesh" />
    <receive-mesh name="Fluid1DLeft-Mesh" from="Fluid1DLeft" />
    <read-data name="Velocity" mesh="Fluid3DRight-Mesh" />
    <write-data name="Pressure" mesh="Fluid3DRight-Mesh" />
    <mapping:axial-geometric-multiscale direction="read" multiscale-dimension="1d-3d"
      multiscale-cross-section="circle" multiscale-type="spread" multiscale-cross-section-profile="parabolic"
      multiscale-radius="{radius}" multiscale-axis="z" from="Fluid1DLeft-Mesh"
      to="Fluid3DRight-Mesh" constraint="consistent" />
  </participant>
  <m2n:sockets acceptor="Fluid1DLeft" connector="Fluid3DRight" exchange-directory="{exchange_directory}" />
  <coupling-scheme:serial-implicit>
    <time-window-size value="{c['window_s']}" />
    <max-time value="{c['end_time_s']}" />
    <participants first="Fluid1DLeft" second="Fluid3DRight" />
    <exchange data="Velocity" mesh="Fluid1DLeft-Mesh" from="Fluid1DLeft" to="Fluid3DRight" initialize="yes" substeps="true" />
    <exchange data="Pressure" mesh="Fluid3DRight-Mesh" from="Fluid3DRight" to="Fluid1DLeft" initialize="yes" substeps="true" />
    <max-iterations value="{c['max_iterations']}" />
    <relative-convergence-measure limit="{c['relative_tolerance']}" data="Pressure" mesh="Fluid3DRight-Mesh" />
    <acceleration:aitken>
      <data mesh="Fluid3DRight-Mesh" name="Pressure" />
      <initial-relaxation value="{c.get('initial_relaxation', .2)}" />
    </acceleration:aitken>
  </coupling-scheme:serial-implicit>
</precice-configuration>
'''
    if "transport" in case:
        xml = xml.replace('  <mesh name="Fluid1DLeft-Mesh"', '''  <data:scalar name="FlowTemperature" />
  <data:scalar name="Alpha" />
  <mesh name="State1D" dimensions="3"><use-data name="FlowTemperature" /><use-data name="Alpha" /></mesh>
  <mesh name="State3D" dimensions="3"><use-data name="FlowTemperature" /><use-data name="Alpha" /></mesh>
  <mesh name="Fluid1DLeft-Mesh"''')
        xml = xml.replace('  <participant name="Fluid1DLeft">', '''  <participant name="Fluid1DLeft">
    <provide-mesh name="State1D" />
    <write-data name="FlowTemperature" mesh="State1D" /><write-data name="Alpha" mesh="State1D" />''')
        xml = xml.replace('  <participant name="Fluid3DRight">', '''  <participant name="Fluid3DRight">
    <provide-mesh name="State3D" /><receive-mesh name="State1D" from="Fluid1DLeft" />
    <read-data name="FlowTemperature" mesh="State3D" /><read-data name="Alpha" mesh="State3D" />
    <mapping:nearest-neighbor direction="read" from="State1D" to="State3D" constraint="consistent" />''')
        xml = xml.replace('    <max-iterations', '''    <exchange data="FlowTemperature" mesh="State1D" from="Fluid1DLeft" to="Fluid3DRight" initialize="yes" substeps="true" />
    <exchange data="Alpha" mesh="State1D" from="Fluid1DLeft" to="Fluid3DRight" initialize="yes" substeps="true" />
    <max-iterations''')
    return xml


def prepare_transport(case: dict, foam: Path) -> None:
    mix, scalar = case["transport"], case.get("scalar_cfd", {})
    manufactured = scalar.get("manufactured", False)
    for name, dimensions, initial, gradient in [
        ("T", "[0 0 0 1 0 0 0]", mix["temperature_k"], scalar.get("temperature_gradient_k_m", 0.)),
        ("alpha", "[0 0 0 0 0 0 0]", mix["alpha"], scalar.get("alpha_gradient_per_m", 0.)),
    ]:
        outlet = f"fixedGradient; gradient uniform {gradient}" if manufactured else "zeroGradient"
        (foam / "0" / name).write_text(f'''FoamFile {{ version 2.0; format ascii; class volScalarField; object {name}; }}
dimensions {dimensions};
internalField uniform {initial};
boundaryField {{
 inlet {{ type fixedValue; value uniform {initial}; }}
 outlet {{ type {outlet}; }}
 fixedWalls {{ type zeroGradient; }}
}}
''', encoding="utf-8")
    props = {"thermalDiffusivity": scalar.get("thermal_diffusivity_m2_s", 0.),
             "phaseDiffusivity": scalar.get("phase_diffusivity_m2_s", 0.),
             "inletPosition": case["pipe"]["length"],
             "rho": case["pipe"]["rho"], "cp": mix["cp_j_kg_k"],
             "referenceTemperature": mix["reference_temperature_k"],
             "manufactured": "true" if manufactured else "false",
             "analyticAdvection": "true" if scalar.get("analytic_advection", False) else "false",
             "referenceRadius": case["pipe"]["radius"], "referenceVelocity": case["pipe"]["velocity"],
             "tau": mix["volume_m3"]/(math.pi*case["pipe"]["radius"]**2*case["pipe"]["velocity"]),
             "initialTemperature": mix["temperature_k"], "supplyTemperature": mix["supply_temperature_k"],
             "initialAlpha": mix["alpha"], "supplyAlpha": mix["supply_alpha"],
             "temperatureGradient": scalar.get("temperature_gradient_k_m", 0.),
             "alphaGradient": scalar.get("alpha_gradient_per_m", 0.)}
    (foam / "constant/couplingTransport").write_text(
        "FoamFile { version 2.0; format ascii; class dictionary; object couplingTransport; }\n"
        + "\n".join(f"{k} {v};" for k,v in props.items()), encoding="utf-8")
    adapter = foam / "system/preciceDict"
    content = adapter.read_text()
    content = content.replace("  Interface1", '''  StateInterface
  {
    mesh State3D; patches (inlet);
    readData (FlowTemperature Alpha); writeData ();
  };
  Interface1''')
    adapter.write_text(content, encoding="utf-8")
    schemes = foam / "system/fvSchemes"
    content = schemes.read_text().replace("    div(phi,U)", "    div(phi,T) Gauss upwind;\n    div(phi,alpha) Gauss upwind;\n    div(phi,U)")
    schemes.write_text(content + "\nfluxRequired { default no; T; alpha; }\n", encoding="utf-8")
    solution = foam / "system/fvSolution"
    solution.write_text(solution.read_text().replace('    p\n', '''    "(T|alpha)"
    { solver PBiCGStab; preconditioner DILU; tolerance 1e-11; relTol 0; }
    p
''', 1), encoding="utf-8")


def prepare_case(case: dict, target: Path) -> None:
    validate(case)
    relative = target.relative_to(ROOT).as_posix()
    if target.exists():
        raise FileExistsError(f"Run directory already exists: {target}")
    target.mkdir(parents=True)
    (target / "traces").mkdir()
    archive = next((ROOT / "third_party").glob("tutorials-*.zip"))
    part = "/partitioned-pipe-multiscale/fluid3d-right-openfoam/"
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            if part not in name or name.endswith("/"):
                continue
            rel = name.split(part, 1)[1]
            if not rel.startswith(("0/", "constant/", "system/")):
                continue
            out = target / "fluid3d" / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(source.read(name))
        for name in source.namelist():
            if name.count("/") == 1 and name.split("/")[-1].lower().startswith("license"):
                (target / "UPSTREAM-LICENSE").write_bytes(source.read(name))
    foam = target / "fluid3d"
    mesh = foam / "system/blockMeshDict"
    s = mesh.read_text(encoding="utf-8")
    s = re.sub(r"[xy]cells 10;", lambda m: m[0][:1] + f"cells {case['cfd']['radial_cells_per_block']};", s)
    s = s.replace("zcells 20;", f"zcells {case['cfd']['axial_cells']};")
    s += f"\nscale {case['pipe']['radius']/5:.17g};\n"
    mesh.write_text(s, encoding="utf-8")
    sample = foam / "system/sampleDict"
    sample.write_text(sample.read_text().replace("(0 0 20)",f"(0 0 {case['pipe']['length']})")
                      .replace("(0 0 40)",f"(0 0 {case['pipe']['length']+case['cfd']['length']})"),encoding="utf-8")
    # This inherited mesh has radius 5 and axial coordinates 20..40.
    p = foam / "0/p"
    p.write_text(p.read_text().replace("fixedFluxExtrapolatedPressure;;", "fixedFluxExtrapolatedPressure;"), encoding="utf-8")
    transport = foam / "constant/transportProperties"
    transport.write_text(transport.read_text().replace(" ] 10;", f" ] {case['pipe']['nu']};"), encoding="utf-8")
    control = foam / "system/controlDict"
    s = control.read_text()
    s = re.sub(r"endTime\s+5\.0;", f"endTime {case['coupling']['end_time_s']};", s)
    s = re.sub(r"deltaT\s+0\.01;", f"deltaT {case['coupling']['dt_3d_s']};", s)
    s = re.sub(r"writeInterval\s+0\.5;", f"writeInterval {case['coupling']['end_time_s']};", s)
    control.write_text(s, encoding="utf-8")
    if "transport" in case:
        prepare_transport(case, foam)
    (target / "case.json").write_text(json.dumps(case, indent=2), encoding="utf-8")
    (target / "precice-config.xml").write_text(configuration(case, "/work/" + relative), encoding="utf-8")
    (target / "source_manifest.json").write_text(json.dumps({
        "tutorial_archive": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "source_subdirectory": "partitioned-pipe-multiscale/fluid3d-right-openfoam",
        "modifications": "scripts/run_case.py:prepare_case", "image": IMAGE,
        "code_sha256": {str(p.relative_to(ROOT).as_posix()): hashlib.sha256(p.read_bytes()).hexdigest()
                        for folder in ["src", "scripts", "containers", "tests"]
                        for p in (ROOT / folder).rglob("*") if p.is_file() and (p.suffix in [".py", ".sh", ".H"] or p.name.startswith("Dockerfile"))},
    }, indent=2), encoding="utf-8")
    manifest = json.loads((target / "source_manifest.json").read_text())
    for name in manifest["code_sha256"]:
        saved = target / "source_snapshot" / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, saved)


def run(case: dict, target: Path, timeout: float = 900) -> None:
    prepare_case(case, target)
    if os.environ.get("CFD_RUN_IN_CONTAINER") == "1":
        # The portable launcher already entered the supplied solver image.
        # Running both participants here avoids Docker-in-Docker and host Python.
        from container_run import main as solve_in_container
        (target / "docker_image.json").write_text(json.dumps([{
            "Id": os.environ.get("CFD_IMAGE_ID", "unknown"), "RepoTags": [IMAGE],
            "source": "outer launcher image inspection"}], indent=2), encoding="utf-8")
        start = time.perf_counter()
        code = 1
        try:
            solve_in_container(target)
            code = 0
        finally:
            (target / "execution.json").write_text(json.dumps({
                "wall_seconds": time.perf_counter()-start, "exit_code": code,
                "timed_out": False, "scope": "inside supplied container; excludes outer container startup and image load",
            }, indent=2), encoding="utf-8")
        print(f"Completed {target}")
        return
    relative = target.relative_to(ROOT).as_posix()
    inspect = subprocess.check_output(["docker", "image", "inspect", IMAGE], text=True)
    (target / "docker_image.json").write_text(inspect, encoding="utf-8")
    args = ["docker", "run", "--rm", "--name", "cfd-" + target.name.lower().replace("_", "-"),
            "--mount", f"type=bind,source={ROOT},target=/work", IMAGE,
            "python", "/work/scripts/container_run.py", f"/work/{relative}"]
    start = time.perf_counter()
    timed_out = False
    with (target / "container.log").open("w", encoding="utf-8") as output:
        process = subprocess.Popen(args, stdout=output, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(["docker", "stop", args[4]], check=False, capture_output=True)
            code = process.wait(timeout=30)
    (target / "execution.json").write_text(json.dumps({
        "wall_seconds": time.perf_counter() - start, "exit_code": code, "timed_out": timed_out,
    }, indent=2), encoding="utf-8")
    if timed_out:
        (target / "status.json").write_text(json.dumps({"state": "failed", "error": "Host timeout", "timeout_s": timeout}))
        raise TimeoutError(f"Case exceeded {timeout}s; see {target / 'container.log'}")
    if code:
        raise RuntimeError(f"Coupled case failed ({code}); see {target / 'container.log'}")
    print(f"Completed {target}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("case", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--window", type=float)
    p.add_argument("--end-time", type=float)
    args = p.parse_args()
    case = json.loads(args.case.read_text(encoding="utf-8"))
    if args.window is not None:
        case["coupling"]["window_s"] = args.window
    if args.end_time is not None:
        case["coupling"]["end_time_s"] = args.end_time
    name = f"{case['name']}-{time.strftime('%Y%m%d-%H%M%S')}"
    target = (args.output or ROOT / "results" / name).resolve()
    run(case, target)
    sys.path.insert(0, str(ROOT / "scripts"))
    from analyze import analyze
    analyze(target)


if __name__ == "__main__":
    main()

