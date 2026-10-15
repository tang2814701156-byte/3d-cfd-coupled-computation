// Extension to GPL-licensed OpenFOAM pimpleFoam; equal-property scalar transport.
volScalarField T(IOobject("T", runTime.timeName(), mesh, IOobject::MUST_READ, IOobject::AUTO_WRITE), mesh);
volScalarField alpha(IOobject("alpha", runTime.timeName(), mesh, IOobject::MUST_READ, IOobject::AUTO_WRITE), mesh);
IOdictionary props(IOobject("couplingTransport", runTime.constant(), mesh, IOobject::MUST_READ, IOobject::NO_WRITE));
dimensionedScalar DT("DT", dimViscosity, props.get<scalar>("thermalDiffusivity"));
dimensionedScalar DA("DA", dimViscosity, props.get<scalar>("phaseDiffusivity"));
const scalar rhoLedger = props.get<scalar>("rho");
const scalar cpLedger = props.get<scalar>("cp");
const scalar trefLedger = props.get<scalar>("referenceTemperature");
const bool manufactured = props.get<bool>("manufactured");
const bool analyticAdvection = props.lookupOrDefault<bool>("analyticAdvection", false);
const scalar referenceRadius = props.lookupOrDefault<scalar>("referenceRadius", 1);
const scalar referenceVelocity = props.lookupOrDefault<scalar>("referenceVelocity", 1);
const scalar tau = props.get<scalar>("tau");
const scalar tInitial = props.get<scalar>("initialTemperature");
const scalar tSupply = props.get<scalar>("supplyTemperature");
const scalar aInitial = props.get<scalar>("initialAlpha");
const scalar aSupply = props.get<scalar>("supplyAlpha");
const scalar gt = props.get<scalar>("temperatureGradient");
const scalar ga = props.get<scalar>("alphaGradient");
const scalar inletPosition = props.get<scalar>("inletPosition");
// Allocate old fields before preCICE registers checkpoints.
T.oldTime(); alpha.oldTime();
std::ofstream ledger("../traces/foam_transport.csv");
ledger.precision(17);
ledger << "time_s,dt_s,volume_m3,mass_boundary_kg,thermal_storage_j,thermal_boundary_j,thermal_source_j,thermal_residual_j,phase_storage_kg,phase_boundary_kg,phase_source_kg,phase_residual_kg,temperature_rms_k,alpha_rms,T_in_k,alpha_in,mdot_in_kg_s,thermal_in_j,phase_in_kg,momentum_storage_kg_m_s,momentum_boundary_kg_m_s,pressure_impulse_kg_m_s,viscous_impulse_kg_m_s,momentum_residual_kg_m_s,alpha_min,alpha_max,inlet_momentum_kg_m_s,inlet_pressure_impulse_kg_m_s,kinetic_storage_j,kinetic_boundary_j,pressure_boundary_j,viscous_boundary_work_j,viscous_dissipation_j,mechanical_residual_j,total_energy_residual_j,inlet_kinetic_flux_j,inlet_pressure_work_j\n";
