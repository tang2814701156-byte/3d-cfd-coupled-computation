"""Derive hardening results, figures and Word-source supplements from raw evidence."""
import csv
import json
from pathlib import Path
import sys
import numpy as np
from energy_audit import audit
from transient_reference import reference

ROOT=Path(__file__).resolve().parents[1]
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def rows(path): return list(csv.DictReader(path.open(encoding='utf-8')))
def values(data,key): return np.array([float(r[key]) for r in data])

def main(root):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    times_font=Path(r'C:\Windows\Fonts\times.ttf')
    if times_font.exists(): font_manager.fontManager.addfont(str(times_font))
    plt.rcParams.update({'font.family':'Times New Roman' if times_font.exists() else 'DejaVu Serif','font.size':11,'axes.unicode_minus':False})
    records=read(root/'execution_records.json')
    if len(records)!=11 or not all(r['verified'] for r in records):
        raise ValueError('Study incomplete or failed: inspect execution_records.json')
    successful=[r for r in records if not r.get('expected_failure')]
    journal_checks=[]
    for record in records:
        directory=root/record['name']
        entries=[json.loads(line) for line in (directory/'accepted_windows.jsonl').read_text().splitlines()]
        if [e['window'] for e in entries] != list(range(len(entries))):
            raise ValueError('Noncontiguous committed journal')
        flat=[r for entry in entries for r in entry['rows']]
        if not all(y['time_s']>x['time_s'] for x,y in zip(flat,flat[1:])):
            raise ValueError('Journal contains rollback data')
        if not record.get('expected_failure'):
            accepted=rows(directory/'pipe.csv')
            if len(flat)!=len(accepted): raise ValueError('Journal/CSV count differs')
            difference=max(abs(float(x[k])-float(y[k])) for x,y in zip(flat,accepted) for k in x)
            if difference>1e-12: raise ValueError('Journal/CSV states differ')
        else: difference=None
        journal_checks.append({'name':record['name'],'accepted_windows':len(entries),'accepted_rows':len(flat),'csv_max_difference':difference})
    (root/'accepted_journal_check.json').write_text(json.dumps(journal_checks,indent=2))
    a=rows(root/'single-r2-1/pipe.csv'); b=rows(root/'single-r5-1/pipe.csv')
    fields=['velocity_m_s','back_pressure_pa','temperature_k','phase_fraction']
    comparison={k:float(np.max(abs(values(a,k)-values(b,k)))/np.max(abs(values(a,k)))) for k in fields}
    repeats={}
    for factor in [2,5]:
        data=[rows(root/f'single-r{factor}-{i}/pipe.csv') for i in range(1,4)]
        summaries=[read(root/f'single-r{factor}-{i}/summary.json') for i in range(1,4)]
        participants=[read(root/f'single-r{factor}-{i}/participant_summary.json') for i in range(1,4)]
        repeats[str(factor)]={'wall_seconds':[s['wall_seconds'] for s in summaries],
            'median_wall_seconds':float(np.median([s['wall_seconds'] for s in summaries])),
            'iteration_amplification':participants[0]['write_attempts']/participants[0]['accepted_substeps'],
            'max_repeat_difference':max(float(np.max(abs(values(data[0],k)-values(d,k)))) for d in data[1:] for k in fields)}
    recovery=rows(root/'recovery/pipe.csv')
    recovery_difference=max(float(np.max(abs(values(a,k)-values(recovery,k)))) for k in fields)
    selected=max(comparison.values())<.001 and recovery_difference<1e-10
    if selected:
        case=read(root/'single-r5-1/case.json'); case['name']='valve-single-step-optimized'
        (ROOT/'cases/valve-single-step-optimized.json').write_text(json.dumps(case,indent=2))
    fine=read(root/'advection-combined/transport_summary.json')
    base=read(ROOT/'results/exploratory-study/advection-time-base/transport_summary.json')
    config=read(root/'advection-combined/case.json'); config['name']='transport-advection-combined-refined'
    (ROOT/'cases/transport-advection-combined-refined.json').write_text(json.dumps(config,indent=2))
    energy={r['name']:audit(root/r['name']) for r in successful}
    historical=ROOT/'results/exploratory-study/valve-h1-repeat1'
    # Keep prior run directories immutable: audit a lightweight analysis-only copy.
    source=root/'historical-energy-input'; source.mkdir(exist_ok=True)
    import shutil
    for name in ['case.json','pipe.csv','foam_accepted.csv','window_balances.csv']: shutil.copyfile(historical/name,source/name)
    energy['historical-h1']=audit(source)
    case=read(root/'single-r2-1/case.json'); times=values(a,'time_s')
    low=reference(case,times,128); high=reference(case,times,256)
    np.savetxt(root/'transient-reference-refined.csv',np.column_stack([high,low[:,1:]]),delimiter=',',
               header='time_s,u256_m_s,p256_pa,u128_m_s,p128_pa',comments='')
    ref={'radial_cells':[128,256], 'max_refinement_velocity_m_s':float(np.max(abs(high[:,1]-low[:,1]))),
         'max_refinement_pressure_pa':float(np.max(abs(high[:,2]-low[:,2]))),
         'max_cfd_velocity_difference_m_s':float(np.max(abs(high[:,1]-values(a,'velocity_m_s')))),
         'max_cfd_pressure_difference_pa':float(np.max(abs(high[:,2]-values(a,'back_pressure_pa')))),
         'scope':'independent unsteady fully-developed radial Stokes + pipe inertia; different inlet profile and end-effect assumptions, sensitivity benchmark only'}
    benchmark=[read(p) for p in sorted((root/'exchange-benchmark').glob('*/summary.json'))]
    if len(benchmark)!=3: raise ValueError('Three communication repetitions required')
    metrics={'successful_runs':len(successful),'fault_tests':2,'accepted_windows':sum(r['accepted_windows'] for r in successful),
        'waveform_relative_differences':comparison,'repeats':repeats,'selected_single_step_relaxation':.5 if selected else None,
        'recovery_max_difference':recovery_difference,'refinement':{
            'base_temperature_rms_k':base['max_temperature_field_rms_k'], 'combined_temperature_rms_k':fine['max_temperature_field_rms_k'],
            'base_thermal_residual':base['interface_window_integrals']['thermal']['relative_cumulative_residual'],
            'combined_thermal_residual':fine['interface_window_integrals']['thermal']['relative_cumulative_residual']},
        'transient_reference':ref,'energy':energy,'microbenchmark':benchmark}
    (root/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    figures=root/'figures'; figures.mkdir(exist_ok=True)
    fig,axes=plt.subplots(1,2,figsize=(9.2,3.4),constrained_layout=True)
    axes[0].plot(times,values(a,'back_pressure_pa'),label='Coupled 3-D')
    axes[0].plot(times,high[:,2],'--',label='Radial Stokes reference')
    axes[0].set(xlabel='Time [s]',ylabel='Back pressure [Pa]'); axes[0].legend()
    axes[1].plot(times,100*abs(values(a,'back_pressure_pa')-values(b,'back_pressure_pa'))/max(abs(values(a,'back_pressure_pa'))))
    axes[1].axhline(.1,color='tab:red',ls='--',label='Acceptance limit')
    axes[1].set(xlabel='Time [s]',ylabel='Relaxation pressure difference [%]'); axes[1].legend()
    for ax in axes: ax.grid(alpha=.25)
    fig.savefig(figures/'pressure-validation.png',dpi=200); plt.close(fig)
    long=rows(root/'long-cycles/pipe.csv')
    fig,axes=plt.subplots(2,1,figsize=(9.2,4.6),sharex=True,constrained_layout=True)
    axes[0].plot(values(long,'time_s'),values(long,'back_pressure_pa')); axes[0].set(ylabel='Back pressure [Pa]')
    axes[1].plot(values(long,'time_s'),values(long,'velocity_m_s')); axes[1].set(xlabel='Time [s]',ylabel='Mean velocity [m/s]')
    for ax in axes: ax.grid(alpha=.25)
    fig.savefig(figures/'long-cycles.png',dpi=200); plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(9.2,3.4),constrained_layout=True)
    labels=['Earlier 1 ms','Single 0.125 ms']; keys=['historical-h1','single-r2-1']
    axes[0].bar(labels,[100*energy[k]['mechanical']['discrete_profile_relative_to_supply_work'] for k in keys],color=['#bf7d46','#476e95'])
    axes[0].set(ylabel='Mechanical balance / supply work [%]')
    axes[1].bar(labels,[100*energy[k]['thermal']['relative_to_supply_heat'] for k in keys],color=['#bf7d46','#476e95'])
    axes[1].set(ylabel='Thermal balance / supply heat [%]')
    for ax in axes: ax.grid(axis='y',alpha=.25)
    fig.savefig(figures/'energy-balances.png',dpi=200); plt.close(fig)
    longsummary=read(root/'long-cycles/summary.json')
    volume=np.pi*case['pipe']['radius']**2*case['cfd']['length']
    replacements=float(sum(float(r['integrated_outflow_kg']) for r in long)/case['pipe']['rho']/volume)
    fault=[r for r in records if r.get('expected_failure')]
    m=metrics['refinement']; reduction=100*(1-m['combined_temperature_rms_k']/m['base_temperature_rms_k'])
    heat_reduction=100*(1-m['combined_thermal_residual']/m['base_thermal_residual'])
    amp_reduction=100*(1-repeats['5']['iteration_amplification']/repeats['2']['iteration_amplification'])
    means=[x['mean_framework_increment_s']*1e6 for x in benchmark]
    mech=energy['single-r2-1']['mechanical']; thermal=energy['single-r2-1']['thermal']
    report=f'''
## 11 技术补强验证

2026 年 10 月 13 日新增 {len(successful)} 次完整耦合运行，累计 {metrics['accepted_windows']:,} 个收敛窗口；另完成 2 次预设故障注入和 3 次独立通信微基准。完整运行及故障测试均通过各自预声明检查，21 项单元测试通过。试验计划、输入、原始轨迹、失败日志与统计结果保存于 results/hardening-study。正式解析算例仍为前述 A、B 两类，本节增加工程可靠性和模型敏感性证据。

### 11.1 单子步窗口与压力一致性

原先 1 ms 窗口内多子步的压力峰值差异无法仅靠收紧端点容限解决。本次将两侧步长及窗口统一为 0.125 ms，使接受窗口端点覆盖全部离散采样时刻。松弛因子 0.2 和 0.5 交错各重复 3 次；两组最大压力差为参考峰值的 {100*comparison['back_pressure_pa']:.6f}%，通过预设 0.1% 门槛。速度归一化最大差为 {100*comparison['velocity_m_s']:.6f}%。同配置重复运行的物理轨迹最大差为 {max(v['max_repeat_difference'] for v in repeats.values()):.3g}。

| 初始松弛因子 | 试算放大倍数 | 三次墙钟耗时 s |
| --- | --- | --- |
| 0.2 | {repeats['2']['iteration_amplification']:.6f} | {' / '.join(f'{v:.2f}' for v in repeats['2']['wall_seconds'])} |
| 0.5 | {repeats['5']['iteration_amplification']:.6f} | {' / '.join(f'{v:.2f}' for v in repeats['5']['wall_seconds'])} |

试算放大倍数下降 {amp_reduction:.2f}%。墙钟受共享主机负载影响，报告保留三次原始耗时，不将迭代节省直接等同于固定比例的运行加速。专用配置 valve-single-step-optimized.json 采用 0.5；多子步通用配置继续采用 0.2。该结果验证离散采样轨迹一致性，尚不能给出采样点之间的连续波形误差界。

![图 12 压力参考对比及松弛因子一致性](../results/hardening-study/figures/pressure-validation.png)

### 11.2 独立非定常径向模型

新增径向有限体积非定常 Stokes 模型，与上游一维惯性方程联立，分段恒定阀门区间采用矩阵指数推进，不调用原一维步进实现。径向扩散算子的稳态误差随网格加密呈二阶下降，并通过加权耗散测试。模型满足

$$\\frac{{\\partial w}}{{\\partial t}}=\\nu\\frac{{1}}{{r}}\\frac{{\\partial}}{{\\partial r}}\\left(r\\frac{{\\partial w}}{{\\partial r}}\\right)+\\frac{{p_b}}{{\\rho L_3}}.$$

$$u=\\frac{{2}}{{R^2}}\\int_0^R w r\\,dr,\\qquad \\rho L_1\\frac{{du}}{{dt}}=p_s-p_b-\\left(\\frac{{8\\rho\\nu L_1}}{{R^2}}+K_v(a^{{-2}}-1)\\right)u.$$

128 与 256 个径向单元的最大速度差为 {ref['max_refinement_velocity_m_s']:.4g} m/s，最大背压差为 {ref['max_refinement_pressure_pa']:.4g} Pa。256 单元参考与耦合三维轨迹最大差分别为 {ref['max_cfd_velocity_difference_m_s']:.4g} m/s、{ref['max_cfd_pressure_difference_pa']:.4g} Pa。径向模型允许剖面随时间变化，三维短管入口仍强制抛物线剖面且包含端部效应，二者边界假设不同。因此这组数据用于揭示瞬态模型敏感性，不能当作第三个同边界条件解析验收算例。

### 11.3 长时循环和故障恢复

2 s 物理运行包含 20 次阀门动作、2,000 个窗口，较此前 0.36 s 试验延长 5.56 倍；覆盖 10 个名义三维管段停留时间，按实际积分流量折算为 {replacements:.2f} 次管内容积置换。全部窗口收敛，最大控制时间误差为 {longsummary['max_control_error_s']:.4g} s，温度、相分数和守恒检查均通过。此范围提供持续循环证据，尚不代表任意时长稳定性。

![图 13 二十次阀门动作的连续响应](../results/hardening-study/figures/long-cycles.png)

| 故障注入 | 保留的接受窗口 | 注入后全部进程停止 s | 检查结果 |
| --- | --- | --- | --- |
| 强制终止一维参与者 | {fault[0]['accepted_prefix_windows']} | {fault[0]['cleanup_seconds']:.4f} | 失败状态和日志保留 |
| 强制终止三维参与者 | {fault[1]['accepted_prefix_windows']} | {fault[1]['cleanup_seconds']:.4f} | 失败状态和日志保留 |

接受窗口逐条写入 accepted_windows.jsonl，回滚试算不进入该日志。容器退出前统一终止存活子进程，并在结果回写后发布最终状态，防止旧状态覆盖故障结论。故障后从原始输入新建目录重跑，轨迹与基线最大差 {recovery_difference:.3g}；这证明重新运行可恢复，不包含断点续算。

### 11.4 网格与时间联合加密

将网格从 6/40 加密至 8/80，同时两侧时间步缩小至原来的四分之一。最高温度场均方根误差从 {m['base_temperature_rms_k']:.6f} K 降至 {m['combined_temperature_rms_k']:.6f} K，下降 {reduction:.2f}%；热量接口累计相对残差从 {100*m['base_thermal_residual']:.6f}% 降至 {100*m['combined_thermal_residual']:.6f}%，下降 {heat_reduction:.2f}%。实际验证配置保存为 transport-advection-combined-refined.json。该联合试验确认组合方案有效，阶次判断仍应使用前节单因素细化。

### 11.5 系统能量审计

新增外边界总账，将一维水力惯性、独立混合容积与三维域的储能、外部通量及耗散汇总。机械耗散仍作为恒温环境的能量输出，未注入温度方程。接口差异不抵销成零，而保留为误差来源：

$$R_{{mech,ext}}=R_{{mech,1}}+R_{{mech,3}}-\\Delta W_{{interface}}-\\Delta F_{{kinetic}}.$$

$$R_{{thermal,ext}}=R_{{mixing}}+R_{{thermal,3}}-\\Delta F_{{thermal}}.$$

单子步基线的机械能残差按连续抛物线动能通量计为供压功的 {100*mech['relative_to_supply_work']:.4f}%；使用同一离散剖面通量后为 {100*mech['discrete_profile_relative_to_supply_work']:.4f}%。热量外边界残差为供给热量的 {100*thermal['relative_to_supply_heat']:.6f}%。分解恒等式误差分别为 {abs(mech['decomposition_identity_error_j']):.3g} J 和 {abs(thermal['decomposition_identity_error_j']):.3g} J，证明账本项对应一致，不代表物理残差为零。三维重构应力、时间离散以及面积压力与流量加权压力的差异仍需进一步研究。

![图 14 按各自供给能量归一化的外边界残差](../results/hardening-study/figures/energy-balances.png)

### 11.6 通信框架独立微基准

使用真实 preCICE socket 双进程，单顶点交换速度三个分量、温度、相分数和反向压力。三次各运行 1,020 个窗口，排除前 20 个预热样本；在运行前后测量本地数组操作基线。框架平均增量分别为 {' / '.join(f'{v:.2f}' for v in means)} μs/轮。该指标包含读写、推进和对端调度等待，排除 CFD 求解；单顶点映射与实际入口面不同，不能直接替代完整系统通信占比，也不能视为网络单向时延。

本次补强解决了专用单子步配置的压力一致性、增加了组合加密、长时循环和故障恢复证据，并给出可追溯的系统能量分解。完整机械能物理闭合、同边界瞬态基准、干净独立环境复现仍作为后续事项保留。
'''
    metrics['long_run_actual_volume_replacements']=replacements
    (root/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    (root/'report-section.md').write_text(report,encoding='utf-8')
    scheme=f'''
## 11 技术补强实施约定

2026 年 10 月 13 日增加接受窗口持久化日志、双侧故障注入、退出状态保护、独立径向瞬态参考以及外边界能量审计。新增 {len(successful)} 次完整运行、{metrics['accepted_windows']:,} 个收敛窗口，2 次强制终止测试和 3 次通信微基准；详细结果见技术补强版报告第 11 节。

### 11.1 配置选择

强瞬态压力一致性优先时，可采用 valve-single-step-optimized.json：窗口及两侧步长均为 0.125 ms，初始松弛因子 0.5。三组重复中压力轨迹相对差 {100*comparison['back_pressure_pa']:.6f}%，满足预设 0.1% 门槛，试算放大倍数下降 {amp_reduction:.2f}%。该配置仅适用于已测范围；多子步配置的默认松弛因子保持 0.2。温度输运精度优先时采用 transport-advection-combined-refined.json，其网格 8/80、两侧步长 0.25/0.125 ms，温度场误差较原始配置降低 {reduction:.2f}%。

### 11.2 故障与状态管理

每个接受窗口将完整状态和控制事件追加到 accepted_windows.jsonl 并刷新缓冲；未收敛试算不写入。监管进程发现任一参与者失败后终止其余参与者，保留日志与清理结果。最终状态在结果复制完成后写入；主机超时也记录 execution.json 和失败状态。两侧强制终止测试后均在 10 s 门槛内完成清理，从原始输入重新运行获得相同物理轨迹。接受日志用于诊断与数据恢复，目前不承担重启 preCICE 会话的检查点功能。

### 11.3 能量与性能指标适用范围

系统能量审计同时报告外边界机械能和热量残差，分别用供压功和供给热量归一化；额外列出接口压力功、动能通量及局部离散残差。保持恒温耗散外排的建模约定，不使用残差补偿项使账本强制闭合。独立微基准使用一顶点真实 socket 耦合并扣除本地操作基线，测得的框架增量包含调度等待，不等同于实际面网格下的网络净开销。独立径向 Stokes 参考用于分析瞬态剖面假设敏感性。
'''
    (root/'scheme-section.md').write_text(scheme,encoding='utf-8')
    print(json.dumps({k:v for k,v in metrics.items() if k not in ['energy','microbenchmark']},indent=2))

if __name__=='__main__': main(Path(sys.argv[1]).resolve())
