import copy
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"),str(ROOT/"scripts")]
from cfd_coupling.model import PipeModel
from cfd_coupling.transport import MixingVolume
from transport_analysis import accepted_trace


class TransportTests(unittest.TestCase):
    def test_variable_flow_analytic_and_balances(self):
        volume = MixingVolume(0.5)
        balances = [volume.advance(m,2.) for m in [0.03,0.1,0.07]]
        decay = math.exp(-0.2/(2*0.5))
        self.assertAlmostEqual(volume.temperature_k,320-20*decay)
        self.assertAlmostEqual(volume.alpha,0.8-0.6*decay)
        for b in balances:
            self.assertAlmostEqual(b["thermal_storage_j"],b["thermal_in_j"]-b["thermal_out_j"])
            self.assertAlmostEqual(b["phase_storage_kg"],b["phase_in_kg"]-b["phase_out_kg"])

    def test_zero_flow_and_rollback(self):
        volume = MixingVolume(0.5)
        initial = copy.deepcopy(volume)
        zero = volume.advance(0,1)
        self.assertEqual(volume,initial)
        self.assertEqual(zero["thermal_storage_j"],0)
        checkpoint = copy.deepcopy(volume)
        volume.advance(.01,1)
        replay = copy.deepcopy(checkpoint)
        replay.advance(.01,1)
        self.assertEqual(volume,replay)

    def test_invalid_fraction_and_reverse_flow(self):
        with self.assertRaises(ValueError): MixingVolume(.5,alpha=1.1)
        with self.assertRaises(ValueError): MixingVolume(.5).advance(-.1,1)

    def test_pipe_impulse_and_mechanical_energy(self):
        pipe = PipeModel(1.,10.,5.,20.,12.8,velocity=.1)
        for opening in [1.,.4,1.]:
            pipe.opening=opening
            balance=pipe.advance(.003,6.4)
            self.assertLess(abs(balance["momentum_residual_kg_m_s"]),1e-11)
            self.assertLess(abs(balance["mechanical_residual_j"]),1e-11)
            self.assertGreaterEqual(balance["dissipation_j"],0)

    def test_trial_rewind_discards_suffix(self):
        raw = [{"time_s":t,"dt_s":.001,"value":v} for t,v in [(.001,1),(.002,1),(.001,2),(.002,2),(.003,2)]]
        accepted=accepted_trace(raw)
        self.assertEqual([r["value"] for r in accepted],[2,2,2])
        with self.assertRaises(ValueError): accepted_trace([{"time_s":.002,"dt_s":.001}])


if __name__ == "__main__": unittest.main()
