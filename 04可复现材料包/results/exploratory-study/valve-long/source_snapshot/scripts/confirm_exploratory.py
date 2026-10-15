"""Confirm the lowest-work verified relaxation screen with two additional runs."""
import argparse
import contextlib
import copy
import json
from pathlib import Path
import numpy as np
from run_case import run
from analyze import analyze
from verify_results import verify


def signal_errors(root, reference, candidate):
    import csv
    def rows(name):
        with (root/name/'pipe.csv').open() as stream: return list(csv.DictReader(stream))
    a,b=rows(reference),rows(candidate)
    ta=np.array([float(r['time_s']) for r in a]);tb=np.array([float(r['time_s']) for r in b])
    mask=(ta>=tb[0])&(ta<=tb[-1]);result={}
    for field in ['velocity_m_s','back_pressure_pa','temperature_k','phase_fraction']:
        values=np.array([float(r[field]) for r in a]);test=np.array([float(r[field]) for r in b])
        delta=np.interp(ta[mask],tb,test)-values[mask]
        result[field]={'max_abs':float(np.max(abs(delta))),
          'normalized_max':float(np.max(abs(delta))/max(float(np.ptp(values)),1e-12)),
          'normalized_rms':float(np.sqrt(np.mean(delta**2))/max(float(np.ptp(values)),1e-12))}
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path)
    root=parser.parse_args().directory.resolve()
    reference='valve-h1-repeat1'
    baseline=json.loads((root/reference/'summary.json').read_text())
    candidates=[]
    for name in ['valve-relax05','valve-relax08']:
        verify(root/name)
        d=json.loads((root/name/'summary.json').read_text())
        errors=signal_errors(root,reference,name)
        if all(v['normalized_max']<.001 for v in errors.values()):
            candidates.append((d['trial_work_amplification'],name,errors))
    if not candidates: raise ValueError('No relaxation candidate meets the declared trajectory-comparison gate')
    amp,name,errors=min(candidates)
    if amp>=baseline['trial_work_amplification']: raise ValueError('No candidate reduces trial work')
    case=json.loads((root/name/'case.json').read_text())
    plan={'selected_screen':name,'selection':'lowest trial work among verified screens with maximum difference < 0.1% of reference signal range in all four states',
          'reference':reference,'comparison_errors':errors,'additional_repetitions':2,'case':case}
    (root/'confirmation_plan.json').write_text(json.dumps(plan,indent=2))
    records=[]
    for repeat in [2,3]:
        target=root/(name+f'-confirm{repeat}')
        if target.exists(): raise FileExistsError(str(target))
        print('CONFIRM '+target.name,flush=True)
        run(copy.deepcopy(case),target)
        with (target/'analysis.log').open('w') as log,contextlib.redirect_stdout(log):
            d=analyze(target);verify(target)
        difference=signal_errors(root,reference,target.name)
        assert all(v['normalized_max']<.001 for v in difference.values())
        records.append({'name':target.name,'wall_seconds':d['wall_seconds'],
                        'work_amplification':d['trial_work_amplification'],'signal_errors':difference})
        (root/'confirmation_results.json').write_text(json.dumps(records,indent=2))
        print(json.dumps(records[-1]),flush=True)


if __name__=='__main__': main()
