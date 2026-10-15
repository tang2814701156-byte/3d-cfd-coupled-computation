"""Equal-property, no-slip two-phase mixing volume in SI units."""
from dataclasses import dataclass
import math


@dataclass
class MixingVolume:
    volume_m3: float
    temperature_k: float = 300.0
    alpha: float = 0.2  # phase A volume fraction; equals mass fraction for equal density
    supply_temperature_k: float = 320.0
    supply_alpha: float = 0.8
    cp_j_kg_k: float = 1000.0
    reference_temperature_k: float = 300.0

    def __post_init__(self):
        if any(not math.isfinite(v) for v in self.__dict__.values()):
            raise ValueError("Non-finite mixing parameters")
        if self.volume_m3 <= 0 or self.cp_j_kg_k <= 0:
            raise ValueError("Volume and heat capacity must be positive")
        if min(self.temperature_k, self.supply_temperature_k) <= 0:
            raise ValueError("Temperature must be positive Kelvin")
        if not 0 <= self.alpha <= 1 or not 0 <= self.supply_alpha <= 1:
            raise ValueError("Phase fraction outside [0,1]")

    def advance(self, mass_kg: float, rho: float) -> dict:
        if mass_kg < 0 or rho <= 0:
            raise ValueError("Mixing model requires forward flow and positive density")
        old_t, old_a = self.temperature_k, self.alpha
        fraction = -math.expm1(-mass_kg / (rho * self.volume_m3))
        self.temperature_k += (self.supply_temperature_k-old_t)*fraction
        self.alpha += (self.supply_alpha-old_a)*fraction
        delta_e = rho*self.volume_m3*self.cp_j_kg_k*(self.temperature_k-old_t)
        delta_a = rho*self.volume_m3*(self.alpha-old_a)
        incoming_e = mass_kg*self.cp_j_kg_k*(self.supply_temperature_k-self.reference_temperature_k)
        incoming_a = mass_kg*self.supply_alpha
        return {"thermal_storage_j": delta_e, "phase_storage_kg": delta_a,
                "thermal_in_j": incoming_e, "thermal_out_j": incoming_e-delta_e,
                "phase_in_kg": incoming_a, "phase_out_kg": incoming_a-delta_a}
