#!/usr/bin/env python3
"""List IfcSpace names with their (x, y) centroid in world coordinates.

Use this to find real map-frame coordinates for named rooms/areas instead
of guessing, when building a config/waypoints.yaml for send_goal.

Usage:
    ros2 run go2_bim_nav list_spaces --input model.ifc
"""
import argparse
import sys

try:
    import ifcopenshell
    import ifcopenshell.geom
except ImportError:
    print("ifcopenshell is required. See the README - recent ifcopenshell releases "
          "don't ship Python 3.8 wheels, so this likely needs a separate venv with "
          "a newer Python rather than the ROS2/Foxy system Python.",
          file=sys.stderr)
    raise

from go2_bim_nav.ifc_to_map import make_geom_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to the .ifc file")
    args = parser.parse_args()

    model = ifcopenshell.open(args.input)
    settings = make_geom_settings()

    print(f"{'Name':30s}  {'x (m)':>8s}  {'y (m)':>8s}")
    skipped = 0
    for space in model.by_type("IfcSpace"):
        try:
            shape = ifcopenshell.geom.create_shape(settings, space)
        except RuntimeError:
            skipped += 1
            continue
        verts = shape.geometry.verts
        xs = verts[0::3]
        ys = verts[1::3]
        if not xs:
            continue
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        name = space.Name or space.LongName or f"Space#{space.id()}"
        print(f"{name:30s}  {cx:8.2f}  {cy:8.2f}")

    if skipped:
        print(f"\nnote: skipped {skipped} IfcSpace element(s) with no usable geometry",
              file=sys.stderr)


if __name__ == "__main__":
    main()
