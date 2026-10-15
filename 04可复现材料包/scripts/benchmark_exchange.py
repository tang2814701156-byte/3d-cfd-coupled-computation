"""No-CFD preCICE microbenchmark, five forward and one reverse doubles.

The one-vertex identity map is intentionally distinct from the production
surface mapping. Advance includes peer scheduling; no network-only claim.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np


def baseline(count):
    timings=[]
    data=np.array([[0.,0.,.1]])
    for _ in range(count):
        start=time.perf_counter()
        incoming=np.array([6.4]); velocity=data.copy(); temperature=np.array([300.]); alpha=np.array([.2])
        assert incoming[0]>0 and velocity.shape==(1,3) and temperature[0]>0 and alpha[0]>0
        timings.append(time.perf_counter()-start)
    return timings


def participant(root, side, count):
    import precice
    p=precice.Participant(side,str(root/'config.xml'),0,1)
    ids=p.set_mesh_vertices(side+'Mesh',[[0.,0.,0.]])
    p.initialize(); timings=[]
    while p.is_coupling_ongoing():
        start=time.perf_counter(); dt=min(.001,p.get_max_time_step_size())
        if side=='Left':
            p.read_data('LeftMesh','Pressure',ids,dt)
            p.write_data('LeftMesh','Velocity',ids,[[0.,0.,.1]])
            p.write_data('LeftMesh','Temperature',ids,[300.])
            p.write_data('LeftMesh','Alpha',ids,[.2])
        else:
            for field in ['Velocity','Temperature','Alpha']: p.read_data('RightMesh',field,ids,dt)
            p.write_data('RightMesh','Pressure',ids,[6.4])
        p.advance(dt); timings.append(time.perf_counter()-start)
    p.finalize()
    (root/(side+'.json')).write_text(json.dumps({'samples_s':timings,'count':len(timings)}))


def execute(root,count):
    root.mkdir(parents=True,exist_ok=False)
    forward=['Velocity','Temperature','Alpha']
    xml='<precice-configuration><log><sink filter="%Severity% &gt; warning" enabled="true" /></log><data:vector name="Velocity" />'
    xml+=''.join(f'<data:scalar name="{d}" />' for d in ['Temperature','Alpha','Pressure'])
    for side in ['Left','Right']:
        xml+=f'<mesh name="{side}Mesh" dimensions="3">'+''.join(f'<use-data name="{d}" />' for d in forward+['Pressure'])+'</mesh>'
    for side,other in [('Left','Right'),('Right','Left')]:
        xml+=f'<participant name="{side}"><provide-mesh name="{side}Mesh" /><receive-mesh name="{other}Mesh" from="{other}" />'
        for d in forward+['Pressure']:
            mode='write' if (side=='Left')==(d in forward) else 'read'
            xml+=f'<{mode}-data name="{d}" mesh="{side}Mesh" />'
        xml+=f'<mapping:nearest-neighbor direction="read" from="{other}Mesh" to="{side}Mesh" constraint="consistent" /></participant>'
    xml+=f'<m2n:sockets acceptor="Left" connector="Right" exchange-directory="{root}" /><coupling-scheme:serial-explicit><time-window-size value="0.001" /><max-time value="{count*.001}" /><participants first="Left" second="Right" />'
    for d in forward+['Pressure']:
        origin,destination=('Left','Right') if d in forward else ('Right','Left')
        xml+=f'<exchange data="{d}" mesh="{origin}Mesh" from="{origin}" to="{destination}" />'
    xml+='</coupling-scheme:serial-explicit></precice-configuration>'
    (root/'config.xml').write_text(xml)
    before=baseline(count)
    children=[]; logs=[]
    try:
        for side in ['Left','Right']:
            log=(root/(side+'.log')).open('w'); logs.append(log)
            children.append(subprocess.Popen([sys.executable,__file__,str(root),'--side',side,'--count',str(count)],cwd=root,stdout=log,stderr=subprocess.STDOUT))
        for child in children:
            if child.wait(timeout=60): raise RuntimeError('Microbenchmark failed; inspect participant logs')
    finally:
        for child in children:
            if child.poll() is None: child.kill(); child.wait()
        for log in logs: log.close()
    after=baseline(count)
    samples=json.loads((root/'Left.json').read_text())['samples_s'][20:]
    base=(before+after)[20:]
    result={'round_trips':len(samples),'warmup_excluded':20,
        'median_exchange_s':float(np.median(samples)),'p95_exchange_s':float(np.percentile(samples,95)),
        'mean_exchange_s':float(np.mean(samples)),'mean_local_baseline_s':float(np.mean(base)),
        'mean_framework_increment_s':float(np.mean(samples)-np.mean(base)),
        'scope':'one vertex, 5 forward + 1 reverse doubles; read/write/advance incl peer scheduling; excludes initialization/finalize; no CFD or production surface mapping'}
    (root/'summary.json').write_text(json.dumps(result,indent=2)); print(json.dumps(result),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('root',type=Path); parser.add_argument('--side'); parser.add_argument('--count',type=int,default=1020)
    args=parser.parse_args()
    if args.side: participant(args.root,args.side,args.count)
    else:
        for i in range(3): execute(args.root/f'repeat{i+1}',args.count)
