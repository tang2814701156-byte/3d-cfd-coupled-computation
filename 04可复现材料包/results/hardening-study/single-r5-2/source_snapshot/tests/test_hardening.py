import copy
import json
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from transient_reference import reference, radial_operator
from run_case import validate


class HardeningTests(unittest.TestCase):
    def test_radial_reference_steady_limit_converges(self):
        case = json.loads((ROOT/'cases/valve-transport.json').read_text())
        case['control']['events'] = []
        errors = []
        for n in [16,32,64]:
            result = reference(case,[20.],n)[0]
            errors.append(abs(result[1]-.1))
            self.assertLess(abs(result[2]-6.4), .03)
        self.assertLess(errors[1],errors[0]/3.9)
        self.assertLess(errors[2],errors[1]/3.9)

    def test_radial_diffusion_dissipates_weighted_energy(self):
        matrix, weights, _ = radial_operator(.005,1e-5,32)
        state = np.random.default_rng(3).normal(size=32)
        self.assertLess(np.dot(weights*state,matrix@state),0.)
        np.testing.assert_allclose(weights[:,None]*matrix,(weights[:,None]*matrix).T,atol=1e-12)

    def test_fault_specification_validation(self):
        case = json.loads((ROOT/'cases/valve-transport.json').read_text())
        for fault in [{'participant':'all','after_accepted_windows':20}, {'participant':'pipe','after_accepted_windows':0}]:
            case['fault_injection'] = fault
            with self.assertRaises(ValueError): validate(case)

if __name__ == '__main__': unittest.main()
