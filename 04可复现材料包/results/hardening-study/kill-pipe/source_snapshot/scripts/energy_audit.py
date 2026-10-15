"""Assemble external-boundary ledgers without cancelling measured interface defects."""
import csv
import json
from pathlib import Path


def audit(root: Path):
    case=json.loads((root/'case.json').read_text())
    pipe=list(csv.DictReader((root/'pipe.csv').open()))
    foam=list(csv.DictReader((root/'foam_accepted.csv').open()))
    windows=list(csv.DictReader((root/'window_balances.csv').open()))
    total=lambda rows,key: sum(float(r[key]) for r in rows)
    rho=case['pipe']['rho']; supply=case['pipe']['supply_pressure']
    upstream_work=supply*total(pipe,'integrated_outflow_kg')/rho
    work1=total(windows,'pressure_work_1d_j'); work3=total(windows,'pressure_work_3d_j')
    kinetic1=total(windows,'kinetic_flux_1d_j'); kinetic3=total(windows,'kinetic_flux_3d_j')
    # The 1-D inertia model has equal inlet/outlet advective kinetic fluxes.
    # Use the documented parabolic-flux convention for this diagnostic.
    mechanical={
        'storage_j':total(pipe,'kinetic_change_j')+total(foam,'kinetic_storage_j'),
        'supply_pressure_work_j':upstream_work,
        'external_net_kinetic_flux_j':total(foam,'kinetic_boundary_j')+kinetic3-kinetic1,
        'outlet_pressure_work_j':total(foam,'pressure_boundary_j')+work3,
        'viscous_boundary_work_j':total(foam,'viscous_boundary_work_j'),
        'dissipation_export_j':total(pipe,'dissipation_j')+total(foam,'viscous_dissipation_j'),
        'local_discretization_residual_j':total(pipe,'mechanical_residual_j')+total(foam,'mechanical_residual_j'),
        'interface_pressure_work_defect_j':work1-work3,
        'interface_kinetic_flux_defect_j':kinetic1-kinetic3}
    mechanical['external_balance_residual_j']=(mechanical['storage_j']-upstream_work+
        mechanical['external_net_kinetic_flux_j']+mechanical['outlet_pressure_work_j']-
        mechanical['viscous_boundary_work_j']+mechanical['dissipation_export_j'])
    mechanical['decomposition_identity_error_j']=mechanical['external_balance_residual_j']-(
        mechanical['local_discretization_residual_j']-mechanical['interface_pressure_work_defect_j']-
        mechanical['interface_kinetic_flux_defect_j'])
    mechanical['relative_to_supply_work']=abs(mechanical['external_balance_residual_j'])/max(abs(upstream_work),1e-30)
    if 'kinetic_discrete_1d_j' in windows[0]:
        discrete_kinetic=total(windows,'kinetic_discrete_1d_j')
        mechanical['discrete_profile_external_residual_j']=mechanical['external_balance_residual_j']+kinetic1-discrete_kinetic
        mechanical['discrete_profile_relative_to_supply_work']=abs(mechanical['discrete_profile_external_residual_j'])/max(abs(upstream_work),1e-30)
    heat1=total(pipe,'thermal_out_j'); heat3=total(foam,'thermal_in_j')
    thermal={'storage_j':total(pipe,'thermal_storage_j')+total(foam,'thermal_storage_j'),
        'supply_heat_j':total(pipe,'thermal_in_j'),
        'outlet_heat_j':total(foam,'thermal_boundary_j')+heat3,
        'source_j':total(foam,'thermal_source_j'),
        'interface_heat_defect_j':heat1-heat3,
        'local_discretization_residual_j':total(windows,'mixing_thermal_residual_j')+total(foam,'thermal_residual_j')}
    thermal['external_balance_residual_j']=thermal['storage_j']-thermal['supply_heat_j']+thermal['outlet_heat_j']-thermal['source_j']
    thermal['decomposition_identity_error_j']=thermal['external_balance_residual_j']-(thermal['local_discretization_residual_j']-thermal['interface_heat_defect_j'])
    thermal['relative_to_supply_heat']=abs(thermal['external_balance_residual_j'])/max(abs(thermal['supply_heat_j']),1e-30)
    result={'mechanical':mechanical,'thermal':thermal,
        'total_external_residual_j':mechanical['external_balance_residual_j']+thermal['external_balance_residual_j'],
        'scope':'diagnostic assembly of hydraulic inertia + separate mixing volume + CFD; viscous losses exported to thermostat, not deposited into T; gradient-reconstructed CFD stress retains numerical defect; no full physical closure claim'}
    (root/'system_energy_audit.json').write_text(json.dumps(result,indent=2))
    return result
