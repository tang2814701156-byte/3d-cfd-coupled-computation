import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cfd_coupling.model import Controller, PipeModel


class ModelTests(unittest.TestCase):
    def pipe(self):
        return PipeModel(1., 10., 5., 20., 12.8)

    def test_steady_solution(self):
        model = self.pipe()
        expected = (12.8 - 6.4) / 64.
        model.advance(10., 6.4)
        self.assertAlmostEqual(model.velocity, expected, places=12)

    def test_nonmatching_substeps_preserve_solution_and_integral(self):
        one, many = self.pipe(), self.pipe()
        mass = one.advance(0.1, 6.4)["mass_kg"]
        parts = sum(many.advance(dt, 6.4)["mass_kg"] for dt in [0.017, 0.043, 0.04])
        self.assertAlmostEqual(one.velocity, many.velocity, places=14)
        self.assertAlmostEqual(mass, parts, places=12)

    def test_back_pressure_changes_flow(self):
        low, high = self.pipe(), self.pipe()
        low.advance(0.1, 3.)
        high.advance(0.1, 9.)
        self.assertGreater(low.velocity, high.velocity)

    def test_valve_reduces_flow(self):
        opened, restricted = self.pipe(), self.pipe()
        restricted.opening = 0.4
        opened.advance(0.1, 6.4)
        restricted.advance(0.1, 6.4)
        self.assertGreater(opened.velocity, restricted.velocity)

    def test_event_truncates_step_and_replays_after_rollback(self):
        model = self.pipe()
        controller = Controller([{"time_s": 0.005, "opening": 0.4}], 0.001)
        self.assertAlmostEqual(controller.limit_dt(0.003, 0.003), 0.002)
        checkpoint = copy.deepcopy((model, controller))
        first = controller.apply(0.005, model)
        restored_model, restored_controller = copy.deepcopy(checkpoint)
        replay = restored_controller.apply(0.005, restored_model)
        self.assertEqual(first, replay)
        self.assertEqual(first[0]["error_s"], 0.)
        self.assertEqual(controller.apply(0.006, model), [])

    def test_control_clock_is_enforced(self):
        with self.assertRaises(ValueError):
            Controller([{"time_s": 0.0055, "opening": 0.4}], 0.001)

    def test_nonfinite_boundary_rejected(self):
        with self.assertRaises(ValueError):
            self.pipe().advance(0.1, math.nan)


if __name__ == "__main__":
    unittest.main()
