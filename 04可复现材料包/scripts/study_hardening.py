"""Reproducible hardening study; predeclared gates and retained fault evidence."""
import argparse
import contextlib
import copy
import json
from pathlib import Path
from run_case import ROOT, run
from analyze import analyze
from verify_results import verify


def specifications():
    valve = json.loads((ROOT/'cases/valve-transport.json').read_text())
    valve['cfd']['normalize_interface_area'] = True
    valve['coupling'].update(window_s=.000125, dt_1d_s=.000125, dt_3d_s=.000125)
    for repeat in range(1, 4):
        for factor in ([.2, .5] if repeat != 2 else [.5, .2]):
            case = copy.deepcopy(valve)
            case['coupling']['initial_relaxation'] = factor
            yield f'single-r{int(factor*10)}-{repeat}', 'single_step_waveform', case
    case = copy.deepcopy(valve)
    case['coupling'].update(end_time_s=2., window_s=.001, dt_1d_s=.001, dt_3d_s=.001)
    case['control']['events'] = [{'time_s':round(.05+i*.1, 6), 'opening':.4 if i%2 == 0 else 1.} for i in range(20)]
    yield 'long-cycles', 'long_run', case
    case = json.loads((ROOT/'cases/transport-advection.json').read_text())
    case['coupling'].update(dt_1d_s=.00025, dt_3d_s=.000125)
    case['cfd'].update(radial_cells_per_block=8, axial_cells=80)
    yield 'advection-combined', 'combined_refinement', case
    for participant in ['pipe', 'foam']:
        case = copy.deepcopy(valve)
        case['fault_injection'] = {'participant':participant, 'after_accepted_windows':20}
        yield 'kill-'+participant, 'fault_injection', case
    yield 'recovery', 'clean_rerun', copy.deepcopy(valve)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--only', nargs='+')
    args = parser.parse_args()
    root = args.output.resolve(); root.mkdir(parents=True, exist_ok=True)
    plan = root/'experiment_plan.json'
    if not plan.exists():
        plan.write_text(json.dumps({'date':'2026-10-13', 'execution':'sequential',
            'gates':{'waveform_max_difference_over_reference_max':.001,
                     'long_run':'all accepted windows converge; bounded phase; exact control clock',
                     'fault':'failed status; accepted journal retained; both children stop within 10s after injection',
                     'recovery':'fresh run from inputs; matches same-configuration reference; not checkpoint resume',
                     'refinement':'temperature RMS and thermal interface residual lower than original base'},
            'specifications':[{'name':n,'group':g,'case':c} for n,g,c in specifications()]},indent=2),encoding='utf-8')
    records_file = root/'execution_records.json'
    records = json.loads(records_file.read_text()) if records_file.exists() else []
    for name, group, case in specifications():
        if args.only and name not in args.only: continue
        target = root/name
        if target.exists(): raise FileExistsError(target)
        case['name'] = name
        print('RUN '+name, flush=True)
        record = {'name':name,'group':group,'verified':False}
        try:
            run(case,target)
            with (target/'analysis.log').open('w',encoding='utf-8') as log, contextlib.redirect_stdout(log):
                result = analyze(target); verify(target)
            record.update(verified=True,wall_seconds=result['wall_seconds'],accepted_windows=result['accepted_windows'])
        except Exception as exc:
            record['error'] = str(exc)
            if group == 'fault_injection' and (target/'fault_injection.json').exists():
                fault = json.loads((target/'fault_injection.json').read_text())
                cleanup = json.loads((target/'process_cleanup.json').read_text())
                status = json.loads((target/'status.json').read_text())
                delay = cleanup['cleanup_monotonic_s']-fault['injected_monotonic_s']
                journal = [json.loads(line) for line in (target/'accepted_windows.jsonl').read_text().splitlines()]
                record.update(cleanup_seconds=delay,accepted_prefix_windows=len(journal),
                    verified=cleanup['all_stopped'] and delay < 10 and status['state']=='failed' and len(journal)>0)
                record['expected_failure'] = True
        records.append(record)
        records_file.write_text(json.dumps(records,indent=2),encoding='utf-8')
        print(json.dumps(record),flush=True)


if __name__ == '__main__': main()
