"""Build a local extension from the installed, GPL-licensed pimpleFoam source."""
from pathlib import Path
import os
import shutil
import subprocess

source = Path(os.environ["WM_PROJECT_DIR"]) / "applications/solvers/incompressible/pimpleFoam"
target = Path("/opt/cfd/coupledTransportFoam")
shutil.copytree(source, target, dirs_exist_ok=True)
for name in ["createTransport.H", "solveTransport.H"]:
    shutil.copyfile(Path("/opt/cfd/solver") / name, target / name)
code = (target / "pimpleFoam.C").read_text()
code = '#include <fstream>\n' + code
code = code.replace('    #include "createUfIfPresent.H"', '    #include "createTransport.H"\n    #include "createUfIfPresent.H"')
code = code.replace('        runTime.write();', '        #include "solveTransport.H"\n        runTime.write();')
(target / "pimpleFoam.C").write_text(code)
(target / "Make/files").write_text("pimpleFoam.C\n\nEXE = /opt/cfd/coupledTransportFoam.bin\n")
subprocess.run(["wmake"], cwd=target, check=True)
