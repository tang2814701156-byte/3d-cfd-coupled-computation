"""Sequential, predeclared exploration with input snapshots and retained failures."""
from __future__ import annotations
import argparse
import contextlib
import copy
import hashlib
import json
from pathlib import Path
from run_case import ROOT, run
from analyze import analyze
from verify_results import verify


def specifications():
    adv = json.loads((ROOT/'cases/transport-advection.json').read_text())
    for label, factor in [('base',1),('half',2),('quarter',4)]:
        case=copy.deepcopy(adv)
        case['coupling'].update(dt_1d_s=.001/factor, dt_3d_s=.0005/factor)
        yield 'advection-time-'+label, 'time_refinement', case
    case=copy.deepcopy(adv)
    case['cfd'].update(radial_cells_per_block=8, axial_cells=80)
    yield 'advection-space-fine', 'space_refinement', case
    valve=json.loads((ROOT/'cases/valve-transport.json').read_text())
    valve['cfd']['normalize_interface_area']=True
    valve['coupling'].update(window_s=.001, dt_1d_s=.00025,dt_3d_s=.000125)
    # Interleaved repetitions mitigate a simple time-order bias; serial execution
    # avoids competition between our own solver runs during timing comparisons.
    for repeat in range(1,4):
        for label,h in ([('h0125',.000125),('h1',.001)] if repeat!=2 else [('h1',.001),('h0125',.000125)]):
            case=copy.deepcopy(valve);case['coupling']['window_s']=h
            yield f'valve-{label}-repeat{repeat}', 'period_repeats', case
    for label,relaxation in [('05',.5),('08',.8)]:
        case=copy.deepcopy(valve);case['coupling']['initial_relaxation']=relaxation
        yield 'valve-relax'+label, 'relaxation', case
    case=copy.deepcopy(valve);case['coupling'].update(window_s=.005,dt_1d_s=.001)
    yield 'valve-ratio8', 'substep_ratio', case
    case=copy.deepcopy(valve);case['coupling']['window_s']=.00003125
    yield 'valve-short3125us', 'short_period', case
    case=copy.deepcopy(valve);case['coupling']['end_time_s']=.36
    case['control']['events']=[{'time_s':t,'opening':a} for t,a in [(.05,.4),(.08,1),(.17,.4),(.20,1),(.29,.4),(.32,1)]]
    yield 'valve-long', 'extended_control', case


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--only',nargs='+')
    args=parser.parse_args();root=args.output.resolve();root.mkdir(parents=True,exist_ok=True)
    specs=[(n,g,c) for n,g,c in specifications() if not args.only or n in args.only]
    plan=root/'experiment_plan.json'
    if not plan.exists():
        plan.write_text(json.dumps({'date':'2026-10-11','execution':'sequential',
          'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'comparisons':'time and space independently; three interleaved period repetitions; fixed grid for relaxation',
          'acceptance':'existing verify_results gates; exploratory failures retained; elapsed time is not hardware realtime',
          'specifications':[{'name':n,'group':g,'case':c} for n,g,c in specifications()]},indent=2),encoding='utf-8')
    records=[]
    for name,group,case in specs:
        target=root/name
        if target.exists(): raise FileExistsError(f'Fresh output required: {target}')
        print(f'RUN {name} ({group})',flush=True)
        record={'name':name,'group':group,'verified':False}
        try:
            run(case,target)
            with (target/'analysis.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
                report=analyze(target);verify(target)
            record.update(verified=True,wall_seconds=report['wall_seconds'],accepted_windows=report['accepted_windows'])
        except Exception as error:
            record['error']=str(error)
        records.append(record)
        (root/'execution_records.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        print(json.dumps(record),flush=True)


if __name__=='__main__': main()
