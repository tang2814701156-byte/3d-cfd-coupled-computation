import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from mesh_geometry import normalize_area
from run_case import validate
from cfd_coupling.model import PipeModel


class ValidationTests(unittest.TestCase):
    def test_cubic_velocity_integral_against_quadrature(self):
        import numpy as np
        model = PipeModel(1000., 1e-5, .005, .02, 12.8, velocity=.1, opening=.4)
        rate = (model.friction+model.valve_resistance*(model.opening**-2-1))/(model.rho*model.length)
        target = (model.supply_pressure-6.4)/(rate*model.rho*model.length)
        nodes, weights = np.polynomial.legendre.leggauss(16)
        dt = .01
        expected = dt/2*np.dot(weights, (target+(.1-target)*np.exp(-rate*(nodes+1)*dt/2))**3)
        self.assertAlmostEqual(model.advance(dt, 6.4)["integral_velocity3_m3_s2"], expected, places=16)

    def test_polygon_area_correction_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            foam = Path(directory) / "fluid3d"
            mesh = foam / "constant/polyMesh"
            mesh.mkdir(parents=True)
            (mesh / "points").write_text("FoamFile { format ascii; }\n4\n(\n(-1 -1 0)\n(1 -1 0)\n(1 1 0)\n(-1 1 0)\n)\n// end\n")
            (mesh / "faces").write_text("FoamFile { format ascii; }\n1\n(4(0 1 2 3))\n")
            (mesh / "boundary").write_text("inlet { nFaces 1; startFace 0; }")
            result = normalize_area(foam, math.sqrt(4.1/math.pi))
            self.assertAlmostEqual(result["corrected_inlet_area_m2"], 4.1)
            self.assertAlmostEqual(normalize_area(foam, math.sqrt(4.1/math.pi))["radial_scale"], 1.)

    def test_reject_nonfinite_physics(self):
        for field in ["velocity", "supply_pressure", "valve_resistance"]:
            args = dict(rho=1000., nu=1e-5, radius=.005, length=.02, supply_pressure=12.8)
            args[field] = float("nan")
            with self.assertRaises(ValueError):
                PipeModel(**args)

    def test_advection_reference_rejects_incompatible_case(self):
        case = json.loads((ROOT / "cases/transport-mms.json").read_text())
        case["scalar_cfd"]["analytic_advection"] = True
        with self.assertRaises(ValueError): validate(case)
        case["scalar_cfd"]["manufactured"] = False
        validate(case)
        bad = copy.deepcopy(case)
        bad["pipe"]["velocity"] = .2
        with self.assertRaises(ValueError): validate(bad)
        bad = copy.deepcopy(case)
        bad["cfd"]["axial_cells"] = 0
        with self.assertRaises(ValueError): validate(bad)


if __name__ == "__main__":
    unittest.main()
