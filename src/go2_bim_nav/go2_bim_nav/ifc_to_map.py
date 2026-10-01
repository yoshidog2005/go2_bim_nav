#!/usr/bin/env python3
"""Convert an IFC/BIM model into a ROS 2 map_server occupancy grid.

The output (.pgm + .yaml) is treated as ground truth by the static costmap
layer. Only permanent, structural elements are rasterised here - anything
not baked in (people, boxes, furniture that gets moved, closed doors) is
left for the live lidar-based obstacle layer to catch at runtime instead.

Door footprints are cleared to free space by default (see --no-clear-doors)
since many real IFC files don't cleanly model a wall's opening at each
door, which otherwise leaves doorways rendered as solid, unbroken wall.

Usage:
    ros2 run go2_bim_nav ifc_to_map \\
        --input model.ifc --output maps/bim_map \\
        --resolution 0.05 --storey "Level 1"
"""
import argparse
import sys

import numpy as np
from PIL import Image, ImageDraw

try:
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element
except ImportError:
    print(
        "ifcopenshell is required. See the README - recent ifcopenshell releases "
        "don't ship Python 3.8 wheels, so this likely needs a separate venv with "
        "a newer Python rather than the ROS2/Foxy system Python.",
        file=sys.stderr,
    )
    raise

# Deliberately excluded by default: IfcSlab, IfcCovering, IfcRoof. These
# represent floors/ceilings/roofs - a horizontal plane, not a vertical
# barrier. Projected straight to 2D they would blank out the entire room's
# footprint, not just the walls. If you want partial slabs (e.g. parapets,
# raised plant decks) included, add "IfcSlab" to --include-types and filter
# further by PredefinedType yourself.
#
# IfcDoor is excluded from the obstacle list itself, on purpose: whether a
# door counts as an obstacle depends on whether it's open or shut right
# now, which the BIM doesn't know. Leaving it out and letting the live
# lidar mark a closed door as an obstacle is simpler and self-correcting.
#
# Separately, door FOOTPRINTS are still cleared to free space by default
# (see door_bounding_boxes / --no-clear-doors) - not because doors are
# obstacles, but because IfcOpenShell only cuts a door-shaped hole in a
# wall if the source file correctly relates the wall to an IfcOpeningElement
# via IfcRelVoidsElement. Plenty of real-world IFC files don't - this is a
# documented, recurring category of bug/data-quality gap (see IfcOpenShell
# issue #2237), not something a settings flag here fixes - so a wall can
# render as solid straight across a doorway. Clearing each door's own
# footprint afterwards guards against that regardless of root cause.
DEFAULT_INCLUDE_TYPES = [
    "IfcWall",
    "IfcWallStandardCase",
    "IfcColumn",
    "IfcCurtainWall",
    "IfcRailing",
    "IfcStairFlight",
    "IfcPlate",
]

FREE = 254
OCCUPIED = 0


def get_storey_name(element):
    storey = ifcopenshell.util.element.get_container(element)
    return getattr(storey, "Name", None) if storey else None


def make_geom_settings():
    settings = ifcopenshell.geom.settings()
    try:
        # ifcopenshell < 0.7 style
        settings.set(settings.USE_WORLD_COORDS, True)
    except Exception:
        # ifcopenshell >= 0.7 style (string-keyed settings)
        settings.set("use-world-coords", True)
    return settings


def project_triangles(model, include_types, storey_name=None):
    """Yield one [(x, y), (x, y), (x, y)] triangle (world metres) at a time
    for every matching element's triangulated mesh."""
    settings = make_geom_settings()

    elements = []
    for ifc_type in include_types:
        elements.extend(model.by_type(ifc_type))

    skipped = 0
    for element in elements:
        if storey_name is not None:
            if get_storey_name(element) != storey_name:
                continue
        try:
            shape = ifcopenshell.geom.create_shape(settings, element)
        except RuntimeError:
            skipped += 1
            continue  # element has no representation geometry - skip it

        verts = shape.geometry.verts
        faces = shape.geometry.faces
        points = [(verts[i], verts[i + 1]) for i in range(0, len(verts), 3)]

        for i in range(0, len(faces), 3):
            a, b, c = faces[i], faces[i + 1], faces[i + 2]
            yield [points[a], points[b], points[c]]

    if skipped:
        print(f"note: skipped {skipped} element(s) with no usable geometry",
              file=sys.stderr)


def door_bounding_boxes(model, storey_name=None, padding=0.05):
    """Yield a padded (min_x, min_y, max_x, max_y) world-space bounding box
    for every IfcDoor. Used to force each door's own footprint to free
    space after walls are rasterised, regardless of whether the source
    wall's opening/void was modeled cleanly."""
    settings = make_geom_settings()

    doors = list(model.by_type("IfcDoor"))
    try:
        doors += list(model.by_type("IfcDoorStandardCase"))  # older IFC2X3-style schemas
    except Exception:
        pass

    skipped = 0
    for door in doors:
        if storey_name is not None and get_storey_name(door) != storey_name:
            continue
        try:
            shape = ifcopenshell.geom.create_shape(settings, door)
        except RuntimeError:
            skipped += 1
            continue

        verts = shape.geometry.verts
        xs = verts[0::3]
        ys = verts[1::3]
        if not xs:
            continue
        yield (min(xs) - padding, min(ys) - padding, max(xs) + padding, max(ys) + padding)

    if skipped:
        print(f"note: skipped {skipped} door(s) with no usable geometry",
              file=sys.stderr)


def rasterise(triangles, resolution, padding, clear_boxes=None):
    triangles = list(triangles)
    if not triangles:
        raise ValueError(
            "No matching geometry found - check --include-types and --storey"
        )

    xs = [p[0] for tri in triangles for p in tri]
    ys = [p[1] for tri in triangles for p in tri]
    min_x, max_x = min(xs) - padding, max(xs) + padding
    min_y, max_y = min(ys) - padding, max(ys) + padding

    width_px = int(np.ceil((max_x - min_x) / resolution))
    height_px = int(np.ceil((max_y - min_y) / resolution))

    img = Image.new("L", (width_px, height_px), color=FREE)
    draw = ImageDraw.Draw(img)

    for tri in triangles:
        pixel_tri = []
        for (x, y) in tri:
            px = (x - min_x) / resolution
            py = (max_y - y) / resolution  # image row 0 == max_y (map_server convention)
            pixel_tri.append((px, py))
        draw.polygon(pixel_tri, fill=OCCUPIED)

    # Force door footprints to free space. Runs AFTER walls specifically so
    # it can clear pixels a wall just marked occupied - see the note above
    # DEFAULT_INCLUDE_TYPES for why this is necessary even with doors
    # excluded from the obstacle list.
    for (bx0, by0, bx1, by1) in (clear_boxes or []):
        px0 = (bx0 - min_x) / resolution
        px1 = (bx1 - min_x) / resolution
        py0 = (max_y - by1) / resolution  # world max_y of the box -> top edge (smaller row)
        py1 = (max_y - by0) / resolution  # world min_y of the box -> bottom edge (larger row)
        draw.rectangle([px0, py0, px1, py1], fill=FREE)

    return img, (min_x, min_y)


def write_map(img, origin, resolution, output_prefix):
    pgm_path = f"{output_prefix}.pgm"
    yaml_path = f"{output_prefix}.yaml"
    img.save(pgm_path)

    image_basename = pgm_path.rsplit("/", 1)[-1]
    with open(yaml_path, "w") as f:
        f.write(f"image: {image_basename}\n")
        f.write(f"resolution: {resolution}\n")
        f.write(f"origin: [{origin[0]}, {origin[1]}, 0.0]\n")
        f.write("negate: 0\n")
        f.write("occupied_thresh: 0.65\n")
        f.write("free_thresh: 0.25\n")

    return pgm_path, yaml_path


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", required=True, help="Path to the .ifc file")
    parser.add_argument(
        "--output", required=True,
        help="Output path prefix, e.g. maps/bim_map (writes .pgm + .yaml)",
    )
    parser.add_argument("--resolution", type=float, default=0.05,
                         help="Metres per pixel (default 0.05)")
    parser.add_argument("--padding", type=float, default=1.0,
                         help="Extra metres of free space around the model bounds")
    parser.add_argument(
        "--storey", default=None,
        help=(
            "Only include elements on this IfcBuildingStorey.Name. Omit to "
            "combine every storey into one map - fine for a single-floor "
            "model, wrong for a multi-storey building."
        ),
    )
    parser.add_argument(
        "--include-types", default=",".join(DEFAULT_INCLUDE_TYPES),
        help="Comma-separated IFC classes to rasterise as obstacles",
    )
    parser.add_argument(
        "--no-clear-doors", action="store_true",
        help=(
            "Don't force door footprints to free space. By default every "
            "IfcDoor's own (padded) footprint is carved out as free space "
            "after walls are rasterised - many real IFC files don't cleanly "
            "model the wall opening at each door, which otherwise leaves "
            "doorways rendered as solid, unbroken wall."
        ),
    )
    parser.add_argument(
        "--door-padding", type=float, default=0.05,
        help="Extra metres cleared around each door's own footprint (default 0.05)",
    )
    args = parser.parse_args()

    include_types = [t.strip() for t in args.include_types.split(",") if t.strip()]

    model = ifcopenshell.open(args.input)
    triangles = project_triangles(model, include_types, args.storey)

    clear_boxes = None
    if not args.no_clear_doors:
        clear_boxes = list(door_bounding_boxes(model, args.storey, args.door_padding))
        if not clear_boxes:
            print(
                "note: no IfcDoor geometry found to clear - doorways will "
                "render as solid wall if the source file doesn't separately "
                "model their openings",
                file=sys.stderr,
            )

    img, origin = rasterise(triangles, args.resolution, args.padding, clear_boxes)
    pgm_path, yaml_path = write_map(img, origin, args.resolution, args.output)

    print(f"Wrote {pgm_path}")
    print(f"Wrote {yaml_path}")


if __name__ == "__main__":
    main()
