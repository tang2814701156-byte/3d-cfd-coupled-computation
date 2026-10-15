"""Incompressible uniform-flow pipe with inertia and Poiseuille friction (SI)."""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass
class PipeModel:
    rho: float
    nu: float
    radius: float
    length: float
    supply_pressure: float
    velocity: float = 0.0
    opening: float = 1.0
    valve_resistance: float = 64.0  # Pa / (m/s), multiplied by (1/a^2 - 1).

    def __post_init__(self) -> None:
        values = [self.rho, self.nu, self.radius, self.length]
        if any(not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("Density, viscosity and geometry must be positive and finite")
        if not 0 <= self.opening <= 1 or self.valve_resistance < 0:
            raise ValueError("Invalid valve parameters")
        if any(not math.isfinite(v) for v in [self.supply_pressure, self.velocity, self.valve_resistance]):
            raise ValueError("Pressure, velocity and resistance must be finite")

    @property
    def area(self) -> float:
        return math.pi * self.radius ** 2

    @property
    def friction(self) -> float:
        return 8 * self.rho * self.nu * self.length / self.radius ** 2

    def advance(self, dt: float, back_pressure: float) -> dict[str, float]:
        if dt <= 0 or not math.isfinite(dt) or not math.isfinite(back_pressure):
            raise ValueError("Invalid time step or pressure")
        old = self.velocity
        if self.opening == 0:
            self.velocity = 0.0  # Ideal completely shut valve boundary.
            impulse = -self.rho*self.area*self.length*old
            kinetic = -0.5*self.rho*self.area*self.length*old**2
            return {"mass_kg": 0.0, "acceleration": -old/dt,
                    "momentum_change_kg_m_s": impulse, "net_impulse_kg_m_s": impulse,
                    "momentum_residual_kg_m_s": 0., "kinetic_change_j": kinetic,
                    "pressure_work_j": 0., "dissipation_j": -kinetic,
                    "mechanical_residual_j": 0., "integral_velocity2_m2_s": 0., "integral_velocity3_m3_s2": 0.}
        resistance = self.friction + self.valve_resistance * (self.opening ** -2 - 1)
        rate = resistance / (self.rho * self.length)
        target = (self.supply_pressure - back_pressure) / resistance
        decay = math.exp(-rate * dt)
        integral_u = target * dt + (old - target) * (-math.expm1(-rate * dt)) / rate
        integral_u2 = (target**2*dt + 2*target*(old-target)*(-math.expm1(-rate*dt))/rate
                       + (old-target)**2*(-math.expm1(-2*rate*dt))/(2*rate))
        integral_u3 = target**3*dt + sum(
            math.comb(3, k)*target**(3-k)*(old-target)**k*(-math.expm1(-k*rate*dt))/(k*rate)
            for k in range(1, 4))
        self.velocity = target + (old - target) * decay
        acceleration = (self.velocity - old) / dt
        impulse = self.rho*self.area*self.length*(self.velocity-old)
        force_impulse = self.area*((self.supply_pressure-back_pressure)*dt-resistance*integral_u)
        kinetic = 0.5*self.rho*self.area*self.length*(self.velocity**2-old**2)
        pressure_work = self.area*(self.supply_pressure-back_pressure)*integral_u
        dissipation = self.area*resistance*integral_u2
        return {"mass_kg": self.rho * self.area * integral_u, "acceleration": acceleration,
                "momentum_change_kg_m_s": impulse, "net_impulse_kg_m_s": force_impulse,
                "momentum_residual_kg_m_s": impulse-force_impulse,
                "kinetic_change_j": kinetic, "pressure_work_j": pressure_work,
                "dissipation_j": dissipation, "mechanical_residual_j": kinetic-pressure_work+dissipation,
                "integral_velocity2_m2_s": integral_u2, "integral_velocity3_m3_s2": integral_u3}


class Controller:
    """Apply scheduled valve commands at exact solver-time boundaries."""

    def __init__(self, events: list[dict], period: float):
        if period <= 0 or not math.isfinite(period):
            raise ValueError("Control period must be positive")
        self.period = period
        self.events = sorted(events, key=lambda e: e["time_s"])
        for event in self.events:
            t, a = event["time_s"], event["opening"]
            if not math.isfinite(t) or t < 0 or not 0 <= a <= 1:
                raise ValueError("Invalid control event")
            if abs(t / period - round(t / period)) > 1e-8:
                raise ValueError("Control events must lie on the declared control clock")
        if len({e["time_s"] for e in self.events}) != len(self.events):
            raise ValueError("Duplicate control event time")
        self.cursor = 0

    def apply(self, time: float, model: PipeModel) -> list[dict]:
        applied = []
        while self.cursor < len(self.events) and self.events[self.cursor]["time_s"] <= time + 1e-12:
            event = self.events[self.cursor]
            model.opening = event["opening"]
            applied.append({"scheduled_s": event["time_s"], "applied_s": time,
                            "error_s": time - event["time_s"], "opening": model.opening})
            self.cursor += 1
        return applied

    def limit_dt(self, time: float, dt: float) -> float:
        if self.cursor < len(self.events):
            gap = self.events[self.cursor]["time_s"] - time
            if gap > 1e-12:
                dt = min(dt, gap)
        return dt

