"""Run the submitted project inside its supplied image, with no host Python."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
CASES = {'steady':'submission-steady.json', 'advection':'transport-advection.json',
         'valve':'valve-single-step-optimized.json', 'refined':'transport-advection-combined-refined.json'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',default='valve',help='steady / advection / valve / refined, or a path under cases/')
    parser.add_argument('--output-name')
    parser.add_argument('--study',choices=['validation','exploratory','hardening'])
    parser.add_argument('--tests',action='store_true')
    args=parser.parse_args()
    os.environ['CFD_RUN_IN_CONTAINER']='1'
    if args.tests:
        raise SystemExit(subprocess.call([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=ROOT))
    output=args.output_name or f'{args.study or Path(args.case).stem}-{uuid.uuid4().hex[:12]}'
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}',output) or output in ('.','..'):
        parser.error('Output name must contain ASCII letters, digits, _, - or .')
    target=ROOT/'results'/output
    if target.exists(): parser.error('Output already exists; choose a fresh name')
    if args.study:
        script={'validation':'study_validation.py','exploratory':'study_exploratory.py','hardening':'study_hardening.py'}[args.study]
        raise SystemExit(subprocess.call([sys.executable,str(ROOT/'scripts'/script),'--output',str(target)],cwd=ROOT))
    case_path=(ROOT/'cases'/CASES[args.case]) if args.case in CASES else (ROOT/args.case).resolve()
    if not case_path.resolve().is_relative_to((ROOT/'cases').resolve()): parser.error('Case must be inside cases/')
    case=json.loads(case_path.read_text(encoding='utf-8'))
    from run_case import run
    from analyze import analyze
    from verify_results import verify
    print(f'Running {case["name"]}; output: {target}',flush=True)
    run(case,target)
    with (target/'analysis.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
        report=analyze(target)
        verify(target)
    print(f'Completed and checked: {report["accepted_windows"]} converged windows',flush=True)
    print(f'Results: results/{output}',flush=True)


if __name__=='__main__': main()
