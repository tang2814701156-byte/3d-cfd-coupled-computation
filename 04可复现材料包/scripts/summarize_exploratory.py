"""Verify exploratory runs and build source-backed tables, figures and Word sections."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import numpy as np
from verify_results import verify
from transport_analysis import write_csv
from confirm_exploratory import signal_errors


def read_rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))


def summarize(root):
    plan=json.loads((root/'experiment_plan.json').read_text())
    declared={x['name']:x['group'] for x in plan['specifications']}
    reports={};records=[]
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not (folder/'case.json').exists(): continue
        if not (folder/'summary.json').exists():
            records.append({'name':folder.name,'verified':False,'reason':'no summary; inspect retained logs'})
            continue
        verify(folder)
        d=json.loads((folder/'summary.json').read_text());reports[folder.name]=d
        case=json.loads((folder/'case.json').read_text());tr=d['transport'];balances=tr['interface_window_integrals']
        records.append({'name':folder.name,'verified':True,'group':declared.get(folder.name,'confirmation'),
            'window_ms':1000*d['window_s'],'dt_1d_ms':1000*case['coupling']['dt_1d_s'],
            'dt_3d_ms':1000*case['coupling']['dt_3d_s'],'radial_cells':case['cfd']['radial_cells_per_block'],
            'axial_cells':case['cfd']['axial_cells'],'relaxation':case['coupling'].get('initial_relaxation',.2),
            'relative_tolerance':case['coupling']['relative_tolerance'],
            'physical_time_s':d['physical_end_s'],'wall_s':d['wall_seconds'],
            'accepted_windows':d['accepted_windows'],'work_amplification':d['trial_work_amplification'],
            'temperature_rms_k':tr.get('max_temperature_field_rms_k'),
            'alpha_rms':tr.get('max_alpha_field_rms'),
            'heat_residual_percent':100*balances['thermal']['relative_cumulative_residual'],
            'mass_residual_percent':100*balances['mass']['relative_cumulative_residual'],
            'pressure_work_percent':100*balances['pressure_work']['relative_cumulative_residual'],
            'pressure_temporal_signed_percent':tr['pressure_work_decomposition']['signed_temporal_percent'],
            'pressure_spatial_signed_percent':tr['pressure_work_decomposition']['signed_spatial_percent'],
            'control_error_s':d['max_control_error_s'],'control_events':d['control_events'],
            'forward_p95_ms':d['latency']['1d_to_3d']['p95_ms'],
            'reverse_p95_ms':d['latency']['3d_to_1d']['p95_ms']})
        dec=tr['pressure_work_decomposition']
        assert abs(dec['closure_error_j']) < 1e-15
        assert math.isclose(dec['total_difference_j'],balances['pressure_work']['cumulative_residual'],abs_tol=1e-15)
    valid=[x for x in records if x['verified']]
    if len(valid)!=len(records):
        (root/'retained_failures.json').write_text(json.dumps([r for r in records if not r['verified']],indent=2))
    write_csv(root/'metrics.csv',valid)
    byname={x['name']:x for x in valid}
    repeat_stats={}
    for label in ['h0125','h1']:
        rows=[x for x in valid if x['name'].startswith('valve-'+label+'-repeat')]
        wall=[x['wall_s'] for x in rows]
        repeat_stats[label]={'n':len(rows),'median_wall_s':statistics.median(wall),
          'min_wall_s':min(wall),'max_wall_s':max(wall),'mean_wall_s':statistics.mean(wall),
          'sample_sd_s':statistics.stdev(wall) if len(wall)>1 else None,
          'mean_work_amplification':statistics.mean(x['work_amplification'] for x in rows)}
    # Same-period replicas should give the same accepted physical trajectory.
    reproducibility={}
    for label in ['h0125','h1']:
        paths=sorted(root.glob('valve-'+label+'-repeat*/pipe.csv'))
        reference=read_rows(paths[0]);difference={}
        for field in ['time_s','velocity_m_s','back_pressure_pa','temperature_k','phase_fraction']:
            a=np.array([float(r[field]) for r in reference])
            difference[field]=max(float(np.max(np.abs(np.array([float(r[field]) for r in read_rows(p)])-a))) for p in paths)
        reproducibility[label]=difference
    metrics={'runs':len(valid),'accepted_windows':sum(x['accepted_windows'] for x in valid),
        'failures':[r for r in records if not r['verified']], 'repeat_statistics':repeat_stats,
        'same_configuration_max_absolute_differences':reproducibility,'records':valid,
        'scope':'same-machine exploration; sequential solver runs; three period repetitions; relaxation screens initially single runs; no independent-machine reproduction'}
    confirmation=None
    if (root/'confirmation_plan.json').exists():
        selection=json.loads((root/'confirmation_plan.json').read_text())['selected_screen']
        selected=[x for x in valid if x['name']==selection or x['name'].startswith(selection+'-confirm')]
        assert len(selected)==3
        confirmation={'screen':selection,'relaxation':selected[0]['relaxation'],'n':3,
          'relative_tolerance':selected[0]['relative_tolerance'],
          'median_wall_s':statistics.median(x['wall_s'] for x in selected),
          'min_wall_s':min(x['wall_s'] for x in selected),'max_wall_s':max(x['wall_s'] for x in selected),
          'mean_work_amplification':statistics.mean(x['work_amplification'] for x in selected),
          'signal_errors':{x['name']:signal_errors(root,'valve-h1-repeat1',x['name']) for x in selected}}
        metrics['relaxation_confirmation']=confirmation
    (root/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    times_font=Path(r'C:\Windows\Fonts\times.ttf')
    if times_font.exists(): font_manager.fontManager.addfont(str(times_font))
    plt.rcParams.update({'font.family':'Times New Roman' if times_font.exists() else 'DejaVu Serif','font.size':12,'axes.labelsize':13,'legend.fontsize':10})
    blue='#476e95';orange='#bf7d46'
    names=['advection-time-base','advection-time-half','advection-time-quarter']
    dt=[byname[n]['dt_3d_ms'] for n in names]
    fig,axes=plt.subplots(1,2,figsize=(9.4,3.7),constrained_layout=True)
    axes[0].plot(dt,[byname[n]['temperature_rms_k'] for n in names],'o-',color=blue,label='6 / 40 grid')
    axes[0].plot([.5],[byname['advection-space-fine']['temperature_rms_k']],'s',color=orange,label='8 / 80 grid')
    axes[0].set_ylabel('Maximum temperature field RMS [K]');axes[0].legend()
    axes[1].plot(dt,[byname[n]['heat_residual_percent'] for n in names],'o-',color=blue,label='Sensible heat')
    axes[1].plot(dt,[byname[n]['pressure_work_percent'] for n in names],'s--',color=orange,label='Pressure work')
    axes[1].set_ylabel('Cumulative interface residual [%]');axes[1].legend()
    for ax in axes:ax.set_xlabel('3D time step [ms]');ax.grid(alpha=.25);ax.set_xlim(.1,.525)
    fig.savefig(root/'time-space.png',dpi=220);plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(9.4,3.7),constrained_layout=True)
    for i,label in enumerate(['h0125','h1']):
        rows=[r for r in valid if r['name'].startswith('valve-'+label+'-repeat')]
        axes[0].plot([i-.08,i,i+.08],[r['wall_s'] for r in rows],'o',color=blue)
        axes[0].plot([i-.19,i+.19],[repeat_stats[label]['median_wall_s']]*2,'-',color=orange)
    axes[0].set_xticks([0,1],['0.125','1']);axes[0].set_ylabel('Complete run wall time [s]')
    axes[0].set_xlabel('Exchange period [ms], 3 runs each');axes[0].set_ylim(0,1.12*max(r['wall_s'] for r in valid if r['group']=='period_repeats'))
    relaxation=[.2,.5,.8]
    amp=[repeat_stats['h1']['mean_work_amplification'],byname['valve-relax05']['work_amplification'],byname['valve-relax08']['work_amplification']]
    axes[1].bar(range(3),amp,color=blue,width=.55)
    axes[1].set_xticks(range(3),['0.2','0.5','0.8']);axes[1].set_xlabel('Aitken initial relaxation, screening runs')
    axes[1].set_ylabel('Trial / accepted 1D substeps')
    for ax in axes:ax.grid(axis='y',alpha=.25)
    fig.savefig(root/'repeat-relaxation.png',dpi=220);plt.close(fig)

    chosen=['advection-time-base','advection-time-quarter','advection-space-fine','valve-h1-repeat1']
    fig,ax=plt.subplots(figsize=(8.7,3.8),constrained_layout=True)
    y=np.arange(4);h=.32
    ax.barh(y-h/2,[byname[n]['pressure_temporal_signed_percent'] for n in chosen],h,color=blue,label='Time / participant trajectories')
    ax.barh(y+h/2,[byname[n]['pressure_spatial_signed_percent'] for n in chosen],h,color=orange,label='Spatial pressure-flow covariance')
    ax.set_yticks(y,['Advection base','Advection quarter step','Advection finer grid','Valve, 1 ms period']);ax.invert_yaxis()
    ax.axvline(0,color='#444444',linewidth=.8);ax.set_xlabel('Signed contribution / absolute 1D work [%]')
    ax.grid(axis='x',alpha=.25);ax.legend(loc='lower right',bbox_to_anchor=(1,1.01),ncol=2)
    fig.savefig(root/'pressure-work-decomposition.png',dpi=220);plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(9.4,3.7),constrained_layout=True)
    long=read_rows(root/'valve-long/pipe.csv');t=[1000*float(x['time_s']) for x in long]
    axes[0].plot(t,[float(x['velocity_m_s']) for x in long],color=blue);axes[0].set_ylabel('Mean velocity [m/s]')
    axes[1].plot(t,[float(x['back_pressure_pa']) for x in long],color=orange);axes[1].set_ylabel('Back pressure [Pa]')
    for ax in axes:ax.set_xlabel('Physical time [ms]');ax.grid(alpha=.25)
    fig.savefig(root/'extended-control.png',dpi=220);plt.close(fig)

    base=byname[names[0]];half=byname[names[1]];quarter=byname[names[2]];fine=byname['advection-space-fine']
    short=byname['valve-short3125us'];long=byname['valve-long'];ratio=byname['valve-ratio8']
    prefix='../results/'+root.name+'/'
    parts=['\n## 10 探索试验与优化结果\n',
      '2026-10-11 补充一轮预先列明配置的探索试验。所有求解顺序运行，使用同一 v0.3 容器镜像；输入、实际源码快照、原始轨迹和校验结果独立保存。该轮共 '+str(len(valid))+' 次通过验证的运行、'+str(metrics['accepted_windows'])+' 个收敛窗口。两个正式解析算例仍为第 3、4 节的水力与无源项输运；本节用于补强误差来源、重复性、迭代效率和已测试稳定范围。',
      '\n### 10.1 分别细化时间与空间\n',
      '固定交换窗口 $H=5$ ms，时间研究保持 6/40 网格，每次将一维和三维步长同时减半；空间研究保持原时间步长，仅将网格改为 8/80。三维最大场误差及显热接口累计相对残差如下。',
      '\n| 网格 | 一维步长 ms | 三维步长 ms | 最大温度场 RMS K | 最大相分数场 RMS | 显热累计残差 |\n| --- | --- | --- | --- | --- | --- |']
    for x in [base,half,quarter,fine]:parts.append(f"| {x['radial_cells']}/{x['axial_cells']} | {x['dt_1d_ms']:g} | {x['dt_3d_ms']:g} | {x['temperature_rms_k']:.6f} | {x['alpha_rms']:.8f} | {x['heat_residual_percent']:.6f}% |")
    parts += [f"\n只减小时间步至四分之一，场误差降低 {100*(1-quarter['temperature_rms_k']/base['temperature_rms_k']):.2f}%；只加密网格，场误差降低 {100*(1-fine['temperature_rms_k']/base['temperature_rms_k']):.2f}%。本组配置下，场误差改善主要由空间细化贡献；显热累计残差随时间步减半近似减半。空间仅两档，不能据此确定空间收敛阶。",
      f'\n![图 8 独立时间细化与空间细化的误差及守恒结果]({prefix}time-space.png)',
      '\n### 10.2 交换周期的重复性与松弛参数探索\n',
      '固定 6/40 网格、一维最大步长 0.25 ms、三维 0.125 ms、物理时长 0.12 s，交错执行 0.125 ms 与 1 ms 两档窗口，每档三次。表中范围为实测最小至最大值，不是置信区间。',
      '\n| 交换周期 | 次数 | 完整耗时中位数 s | 实测耗时范围 s | 试算与接受子步比均值 |\n| --- | --- | --- | --- | --- |']
    for label,h in [('h0125',.125),('h1',1)]:
        x=repeat_stats[label];parts.append(f"| {h:g} ms | {x['n']} | {x['median_wall_s']:.3f} | {x['min_wall_s']:.3f} 至 {x['max_wall_s']:.3f} | {x['mean_work_amplification']:.3f} |")
    parts += ['\n同配置重复的接受轨迹差值保存于 `metrics.json`，墙钟时间受负载和进程启动影响。0.125 ms 窗口会截短实际一维子步，两档比较仍包含有效时间离散变化。不能将时间差全部归因于通信频率。',
      '\n初始 Aitken 松弛因子开放为配置项，默认保持 0.2，合法范围为 $(0,1]$。固定 1 ms 窗口，筛选 0.5、0.8 两档；下表为同网格同误差容限的结果。',
      '\n| 初始松弛因子 | 本表运行次数 | 试算与接受子步比 | 完整耗时 s | 显热累计残差 |\n| --- | --- | --- | --- | --- |',
      f"| 0.2 | 3 | {repeat_stats['h1']['mean_work_amplification']:.3f} | 中位数 {repeat_stats['h1']['median_wall_s']:.3f} | {byname['valve-h1-repeat1']['heat_residual_percent']:.6f}% |"]
    for n,a in [('valve-relax05',.5),('valve-relax08',.8)]:
        x=byname[n];parts.append(f"| {a:g} | 1 | {x['work_amplification']:.3f} | {x['wall_s']:.3f} | {x['heat_residual_percent']:.6f}% |")
    parts += [f'\n![图 9 完整运行耗时的重复散点及松弛参数的试算成本]({prefix}repeat-relaxation.png)',
      '\n松弛筛选的试算次数可以直接用于判断迭代工作量；单次墙钟耗时不能建立普适加速比。候选参数需在确认重复试验及其他工况中继续评价。',
      '\n### 10.3 压力功残差的可加分解\n',
      '保留三维实际面压力与面流量乘积的积分作为压力功守恒指标。新增同一三维轨迹上的面积平均压力投影，仅用于识别差异来源。定义',
      '\n'+r'$$W_A=\sum_j \bar p_{A,j}Q_j\Delta t_j,\qquad W_3=\sum_j\sum_i p_{i,j}Q_{i,j}\Delta t_j.$$',
      '\n$$W_1-W_3=(W_1-W_A)+(W_A-W_3).$$',
      '\n第一项包含时间积分及两个参与者轨迹差异，第二项是压力与流量空间分布的协方差投影差异。归一化采用各窗口一维压力功绝对值之和，分项保留符号。该恒等分解不改变实际残差，也不代表完整系统能量闭合。',
      '\n| 工况 | 时间与轨迹项 | 空间投影项 | 有符号总残差 |\n| --- | --- | --- | --- |']
    for n,label in zip(chosen,['无源项基础','无源项四分之一时间步','无源项加密网格','阀门 1 ms']):
        x=byname[n];parts.append(f"| {label} | {x['pressure_temporal_signed_percent']:.6f}% | {x['pressure_spatial_signed_percent']:.6f}% | {reports[n]['transport']['pressure_work_decomposition']['signed_total_percent']:.6f}% |")
    parts += [f'\n![图 10 压力功残差中时间轨迹项与空间投影项的有符号贡献]({prefix}pressure-work-decomposition.png)',
      '\n仅减小时间步没有使压力功残差单调下降；本组证据显示空间投影项占主要部分，加密网格可降低该项。下一步应构造兼顾压力力与压力功的多矩接口模型，不能直接把面积平均压力替换为流量加权压力而忽略动量一致性。',
      '\n### 10.4 步长比例 更短窗口及延长控制试验\n',
      f"内部步长比例探索采用一维 1 ms、三维 0.125 ms、交换窗口 5 ms；完成 {ratio['accepted_windows']} 个收敛窗口，显热累计残差 {ratio['heat_residual_percent']:.6f}%。该例说明 8 倍内部步长差在声明工况下可以运行，仍需按误差与成本选择比例。",
      f"\n窗口缩短至 31.25 μs 后完成 {short['accepted_windows']} 个收敛窗口、0.12 s 物理过程，完整耗时 {short['wall_s']:.3f} s。该结果将最短已测试稳定周期从 62.5 μs 扩展至 31.25 μs；尚无失败下界，不称普适最小周期。",
      f"\n延长试验运行 0.36 s，安排三组关闭与恢复、共 {long['control_events']} 个控制事件，完成 {long['accepted_windows']} 个收敛窗口；最大控制注入误差 {long['control_error_s']:.3g} s，显热累计残差 {long['heat_residual_percent']:.6f}%。它扩展了连续控制覆盖，但 0.36 s 仍不能代替工业长时稳定性及异常恢复验收。",
      f'\n![图 11 延长试验中三次阀门关闭与恢复的流量和压力响应]({prefix}extended-control.png)',
      '\n### 10.5 已落实的改进与仍待验证的能力\n',
      '代码新增初始松弛参数及输入校验、可复跑的顺序探索脚本、压力功分项诊断与相应测试。18 项单元测试通过。建议在当前基准下优先用网格细化改善物理场精度，用时间细化降低显热接口积分误差，并分别审查实际压力功和投影分项。完整系统能量闭合、阀门瞬态独立物理基准、通信净开销、独立环境复现及演示视频仍需完成。',
      f'\n数据入口：[预先声明的配置]({prefix}experiment_plan.json)、[逐次指标]({prefix}metrics.csv)、[完整分析]({prefix}metrics.json)、[分析与输入哈希]({prefix}analysis_manifest.json)。']
    if confirmation:
        baseline=repeat_stats['h1'];x=confirmation
        max_diff=max(v['normalized_max'] for case in x['signal_errors'].values() for v in case.values())
        text=f"\n对四个状态最大差均低于默认轨迹极差 0.1% 的候选做两次追加确认，含筛选运行共三次。初始松弛因子 {x['relaxation']:g}、相对收敛容限 ${x['relative_tolerance']:g}$ 的平均试算比为 {x['mean_work_amplification']:.3f}，较默认降低 {100*(1-x['mean_work_amplification']/baseline['mean_work_amplification']):.2f}%；耗时中位数 {x['median_wall_s']:.3f} s，实测范围 {x['min_wall_s']:.3f} 至 {x['max_wall_s']:.3f} s，较默认中位数降低 {100*(1-x['median_wall_s']/baseline['median_wall_s']):.2f}%。四个状态的最大归一化差不超过 {100*max_diff:.6f}%。该指标评价与默认耦合轨迹的一致性，不替代物理解析验证。可复跑配置保存于 `cases/valve-transport-optimized.json`；默认配置仍保留，适用范围须进一步扩展。\n"
        position=parts.index('\n### 10.3 压力功残差的可加分解\n')
        parts.insert(position,text)
    if (root/'adaptive_screen_plan.json').exists():
        adaptive=json.loads((root/'adaptive_screen_plan.json').read_text())
        peak=max(v['back_pressure_pa']['normalized_max'] for v in adaptive['rejected_original_screens'].values())
        position=parts.index('\n### 10.3 压力功残差的可加分解\n')
        parts.insert(position,f"\n原始 0.5 与 0.8 松弛筛选的压力最大归一化差达到 {100*peak:.6f}%，超过预先采用的 0.1% 一致性门槛，因此未直接选为优化配置。随后在保持比较门槛不变的条件下，声明追加 0.5 松弛、相对收敛容限 $10^{{-5}}$ 的试验，用更严格的迭代检查压力差异。")
        if not confirmation:
            adaptive_result=json.loads((root/'adaptive_screen_result.json').read_text())
            x=byname[adaptive_result['name']]
            err=adaptive_result['signal_errors']['back_pressure_pa']
            parts.insert(position+1,f"\n追加试验通过基础收敛与守恒检查，但压力最大差仍为 {err['max_abs']:.6f} Pa、归一化 {100*err['normalized_max']:.6f}%，未满足 0.1% 的候选门槛。试算比为 {x['work_amplification']:.3f}，完整耗时 {x['wall_s']:.3f} s；降低迭代成本不足以证明轨迹一致，故保留默认 0.2 松弛，不发布该候选。最大差出现在阀门恢复后的窗口内部，应进一步检查全窗口压力波形的一致性；仅加强当前窗口收敛容限未消除差异。")
    parts.append('\n已经保存两组通过验证的精度改进配置：`cases/transport-advection-spatial-refined.json` 用于优先改善场精度，`cases/transport-advection-time-refined.json` 用于改善显热接口积分误差。两者分别细化空间和时间，尚未试验 8/80 网格与四分之一时间步的组合。')
    (root/'report-section.md').write_text('\n'.join(parts),encoding='utf-8')
    scheme='''\n## 10 探索试验支持的配置与诊断扩展\n
2026-10-11 补充探索试验，将时间与空间细化分别评价，并对交换周期做同机交错重复。初始 Aitken 松弛因子可通过 `coupling.initial_relaxation` 配置，默认 0.2，合法范围为 $(0,1]$。具体配置和适用范围见配套验证报告第 10 节。\n
压力力仍使用面积平均接口压力，三维实际压力功仍按面压力与面流量的乘积积分。新增面积平均压力投影的功积分，采用 $W_1-W_3=(W_1-W_A)+(W_A-W_3)$ 分离时间轨迹与空间投影差异。两个参与者的实际账本继续保留；投影诊断不替代守恒验收。\n
在已测试工况下，网格细化对物理标量场 RMS 的改善大于单独时间细化；缩短时间步主要改善显热接口累计残差。窗口稳定范围补测至 31.25 μs，延长控制试验覆盖 0.36 s 和六次阀门事件。以上结论以本机、等物性同速两相、圆管几何及已声明离散为限。\n'''
    (root/'scheme-section.md').write_text(scheme,encoding='utf-8')
    inputs=[p for name in reports for p in [root/name/'summary.json',root/name/'pipe.csv',root/name/'case.json']]
    (root/'analysis_manifest.json').write_text(json.dumps({'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'inputs_sha256':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        'figures':['time-space.png','repeat-relaxation.png','pressure-work-decomposition.png','extended-control.png']},indent=2))
    print(json.dumps({k:v for k,v in metrics.items() if k!='records'},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path)
    summarize(parser.parse_args().directory.resolve())
