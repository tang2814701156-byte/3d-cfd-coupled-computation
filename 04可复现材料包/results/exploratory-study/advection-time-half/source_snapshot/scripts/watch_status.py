"""Read accepted-window live status without opening a desktop application."""
import argparse
import json
from pathlib import Path
import time

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    previous = None
    try:
        while True:
            try:
                data = json.loads((args.directory / "status.json").read_text())
                if data["state"] == "failed":
                    raise SystemExit("Run failed: " + data.get("error", "see logs"))
                row = data["latest"]
                if row["time_s"] != previous:
                    print(f"t={row['time_s']:.6f}/{data['end_time_s']} s | "
                          f"mdot={row['mdot_kg_s']:.6g} kg/s | p={row['back_pressure_pa']:.6g} Pa | "
                          f"T={row['temperature_k']:.5f} K | alpha={row['phase_fraction']:.6f} | "
                          f"opening={row['opening']:.3f} | windows={data['accepted_windows']}", flush=True)
                    previous = row["time_s"]
                if data["state"] == "completed":
                    break
            except (FileNotFoundError, json.JSONDecodeError, PermissionError):
                pass
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
