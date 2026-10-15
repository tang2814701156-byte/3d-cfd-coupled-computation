"""Make the serial extruded pipe's discrete inlet area match its 1D area."""
from __future__ import annotations
import json
import math
from pathlib import Path
import re
import numpy as np


def list_body(text: str):
    match = re.search(r"\n\s*(\d+)\s*\n\s*\((.*)\)\s*(?://[^\n]*\s*)?$", text, re.S)
    if match is None:
        raise ValueError("Expected an ASCII OpenFOAM list")
    return match


def normalize_area(foam: Path, radius: float) -> dict:
    mesh = foam / "constant/polyMesh"
    point_path = mesh / "points"
    text = point_path.read_text()
    match = list_body(text)
    points = np.fromstring(re.sub(r"[()]", " ", match[2]), sep=" ").reshape(-1, 3)
    if len(points) != int(match[1]):
        raise ValueError("Point count mismatch")
    faces_text = list_body((mesh / "faces").read_text())[2]
    faces = [list(map(int, m[2].split())) for m in re.finditer(r"(\d+)\s*\(([^()]*)\)", faces_text)]
    patch = re.search(r"\binlet\s*\{([^}]+)\}", (mesh / "boundary").read_text())
    if patch is None:
        raise ValueError("Missing inlet patch")
    count = int(re.search(r"nFaces\s+(\d+)", patch[1])[1])
    start = int(re.search(r"startFace\s+(\d+)", patch[1])[1])
    area = 0.
    for face in faces[start:start+count]:
        polygon = points[face]
        vector = .5*np.sum(np.cross(polygon, np.roll(polygon, -1, axis=0)), axis=0)
        if np.linalg.norm(vector[:2]) > abs(vector[2])*1e-9:
            raise ValueError("Area normalization requires a z-normal inlet")
        area += abs(vector[2])
    target = math.pi*radius**2
    if not math.isfinite(area) or area <= 0 or not .8 < area/target < 1.2:
        raise ValueError("Unexpected inlet geometry")
    scale = math.sqrt(target/area)
    points[:, :2] *= scale
    quadrature = []
    for face in faces[start:start+count]:
        polygon = points[face, :2]
        next_point = np.roll(polygon, -1, axis=0)
        cross = polygon[:, 0]*next_point[:, 1]-next_point[:, 0]*polygon[:, 1]
        center = np.sum((polygon+next_point)*cross[:, None], axis=0)/(3*np.sum(cross))
        quadrature.append((abs(np.sum(cross))*.5, 2*(1-float(center@center)/radius**2)))
    mean_profile = sum(a*f for a, f in quadrature)/target
    if mean_profile <= 0:
        raise ValueError("Nonpositive initial profile")
    body = "\n" + "\n".join("(" + " ".join(f"{v:.17g}" for v in row) + ")" for row in points) + "\n"
    point_path.write_text(text[:match.start(2)]+body+text[match.end(2):])
    result = {"original_inlet_area_m2": area, "target_inlet_area_m2": target,
              "corrected_inlet_area_m2": area*scale**2, "radial_scale": scale,
              "parabolic_profile_scale": 1/mean_profile,
              "discrete_beta": sum(a*(f/mean_profile)**2 for a, f in quadrature)/target,
              "discrete_gamma": sum(a*(f/mean_profile)**3 for a, f in quadrature)/target,
              "scope": "uniform x/y scaling of the extruded polygonal mesh; radius is area-equivalent"}
    (foam.parent / "mesh_geometry.json").write_text(json.dumps(result, indent=2))
    return result
