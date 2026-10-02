#!/usr/bin/env python3
"""
@author Brandon Lichter (Yoshidog)

Preview a map_server map (.pgm + .yaml) on your workstation - no ROS2,
no rviz2, no dog required. A quick sanity check before copying the map
over: does this actually look like the floor plan, at the right scale
and proportions?

Usage:
    python preview_map.py --map bim_map.yaml
    python preview_map.py --map bim_map.yaml --save preview.png   # headless/SSH-friendly
"""
import argparse
import os
import sys

import numpy as np

try:
    import yaml
except ImportError:
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    raise

try:
    from PIL import Image
except ImportError:
    print("Pillow is required: pip install Pillow", file=sys.stderr)
    raise


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--map", required=True, help="Path to the map .yaml (not the .pgm)")
    parser.add_argument(
        "--save", default=None,
        help="Save a PNG instead of opening an interactive window (use this over SSH / without a display)",
    )
    args = parser.parse_args()

    if args.save:
        import matplotlib
        matplotlib.use("Agg")  # no display needed if we're just saving a file
    import matplotlib.pyplot as plt

    map_yaml_path = os.path.abspath(args.map)
    map_dir = os.path.dirname(map_yaml_path)

    with open(map_yaml_path) as f:
        meta = yaml.safe_load(f)

    # map_server convention: the image path in the yaml is relative to the
    # yaml file's own directory, not the current working directory.
    image_path = meta["image"]
    if not os.path.isabs(image_path):
        image_path = os.path.join(map_dir, image_path)

    resolution = meta["resolution"]
    origin_x, origin_y = meta["origin"][0], meta["origin"][1]

    img = np.array(Image.open(image_path))
    height_px, width_px = img.shape

    # Real-world extent in metres, matching map_server's convention that
    # image row 0 (the top of the .pgm) corresponds to the highest y value.
    extent = [
        origin_x,
        origin_x + width_px * resolution,
        origin_y,
        origin_y + height_px * resolution,
    ]

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(img, cmap="gray", vmin=0, vmax=254, extent=extent, origin="upper")
    ax.set_xlabel("x (m, map frame)")
    ax.set_ylabel("y (m, map frame)")
    ax.set_title(
        f"{os.path.basename(image_path)}  |  {width_px}x{height_px}px @ {resolution} m/px"
    )
    ax.set_aspect("equal")  # 1m in x must look the same as 1m in y, or proportions lie
    ax.grid(True, alpha=0.3, linewidth=0.5)

    if args.save:
        fig.savefig(args.save, dpi=150, bbox_inches="tight")
        print(f"Saved {args.save}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
