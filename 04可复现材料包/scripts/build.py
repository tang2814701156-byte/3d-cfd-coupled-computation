"""Build the delivered OpenFOAM/preCICE solver image."""
from pathlib import Path
import argparse
import subprocess
import uuid
from prepare import ROOT, prepare

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--tag',default='cfd-coupling:local')
args=parser.parse_args()
prepare()
log_dir=ROOT/'results/build'
log_dir.mkdir(parents=True,exist_ok=True)
log=log_dir/(uuid.uuid4().hex[:12]+'.log')
with log.open('w',encoding='utf-8') as out:
    code=subprocess.call(['docker','build','--progress','plain','-t',args.tag,'-f','containers/Dockerfile','.'],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT)
print(f'Build exit code {code}; log: {log}')
raise SystemExit(code)
