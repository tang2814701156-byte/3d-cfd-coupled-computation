"""Build the real OpenFOAM/preCICE image with a persistent build log."""
from pathlib import Path
import subprocess
import time
from prepare import ROOT, prepare
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--reuse-base", action="store_true", help="Use existing v0.1 image for local incremental build")
args = parser.parse_args()
if not args.reuse_base:
    prepare()
log_dir = ROOT / "results/build"
log_dir.mkdir(parents=True, exist_ok=True)
log = log_dir / (time.strftime("%Y%m%d-%H%M%S") + ".log")
with log.open("w", encoding="utf-8") as out:
    code = 0
    if not args.reuse_base:
        code = subprocess.call(["docker", "build", "--progress", "plain", "-t", "cfd-coupling:0.1",
                                "-f", "containers/Dockerfile", "."], cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
    if code == 0:
        code = subprocess.call(["docker", "build", "--progress", "plain", "-t", "cfd-coupling:0.3",
                                "-f", "containers/Dockerfile.v03", "."], cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
print(f"Build exit code {code}; log: {log}")
raise SystemExit(code)
