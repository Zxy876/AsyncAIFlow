from __future__ import annotations

import argparse
import json
from pathlib import Path

from worker import process_raw_scan


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process a raw OBJ/PLY scan into a web-ready GLB using pymeshlab"
    )
    parser.add_argument("input", help="path to input .obj/.ply/.stl mesh")
    parser.add_argument(
        "--output",
        help="path to output .glb (default: <input_stem>.web.glb in same folder)",
        default="",
    )
    parser.add_argument("--target-faces", type=int, default=20000)
    parser.add_argument("--min-diameter-pct", type=float, default=3.0)

    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else input_path.with_name(f"{input_path.stem}.web.glb")
    )

    payload = {
        "scan": {
            "rawModelPath": str(input_path),
            "outputGlbPath": str(output_path),
            "targetFaces": args.target_faces,
            "isolatedPieceMinDiameterPct": args.min_diameter_pct,
        }
    }

    result = process_raw_scan(json.dumps(payload, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
