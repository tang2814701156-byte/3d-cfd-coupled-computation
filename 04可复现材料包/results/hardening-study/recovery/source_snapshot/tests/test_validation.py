import copy
import contextlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from mesh_geometry import normalize_area
from run_case import validate, configuration
from transport_analysis import decompose_pressure_work
from cfd_coupling.model import PipeModel


class ValidationTests(unittest.TestCase):
    def test_relaxation_configuration_and_invalid_values(self):
        case = json.loads((ROOT / "cases/transport-advection.json").read_text())
        for value in [0, -1, 1.01, float('nan'), float('inf')]:
            case["coupling"]["initial_relaxation"] = value
            with self.assertRaises(ValueError): validate(case)
        case["coupling"]["initial_relaxation"] = .5
        validate(case)
        self.assertIn('<initial-relaxation value="0.5"', configuration(case, '/tmp/test'))

    def test_pressure_work_projection_separates_face_covariance(self):
        # Two equal-area faces: p=(2,4), Q=(1,3), dt=.5, rho=10.
        # Actual work is 7 J, area-mean projected work is 6 J.
        row = {"inlet_pressure_work_j": 7., "inlet_pressure_impulse_kg_m_s": 3., "mdot_in_kg_s": 40.}
        terms = decompose_pressure_work(6.2, [row], area=2., rho=10.)
        self.assertAlmostEqual(terms['area_projected_3d_j'], 6.)
        self.assertAlmostEqual(terms['temporal_and_trajectory_difference_j'], .2)
        self.assertAlmostEqual(terms['spatial_pressure_flow_covariance_j'], -1.)
        self.assertAlmostEqual(terms['total_difference_j'], -.8)

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
        archive = ROOT / "delete" / "unit-test-fixtures"
        archive.mkdir(parents=True, exist_ok=True)
        with contextlib.nullcontext(tempfile.mkdtemp(prefix="mesh-", dir=archive)) as directory:
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
