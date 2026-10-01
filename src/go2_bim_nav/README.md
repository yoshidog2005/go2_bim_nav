# go2_bim_nav

ROS 2 Foxy navigation stack for the Unitree Go2 that treats a BIM (IFC)
model as ground truth for the static map, and layers live lidar-based
obstacle detection on top for anything not in the BIM - people, boxes,
furniture, closed doors.

## How it fits together

1. **Offline, once per floor**: `ifc_to_map` reads the IFC file with
   IfcOpenShell, rasterises the structural elements (walls, columns,
   railings, stair flights) into a 2D occupancy grid, and writes it as a
   standard `map_server` map (`.pgm` + `.yaml`).
2. **At runtime**: `map_server` serves that map, `amcl` localizes the robot
   against it using a 2D scan, and Nav2's layered costmap combines:
   - a **static layer** = the BIM map (trusted, rarely changes)
   - an **obstacle layer** = live lidar hits (people, boxes, furniture,
     closed doors - whatever the BIM doesn't know about)
   - an **inflation layer** on top of both
3. The **global planner** (NavFn/A*) plans routes against the merged
   costmap, effectively trusting the BIM's walls. The **local planner**
   (DWB) does moment-to-moment dodging around whatever the obstacle layer
   is currently reporting.

## Why some things are handled the way they are

- **Floors/ceilings (`IfcSlab`) are excluded from the converter by
  default.** Projected straight to 2D, a slab is a giant flat plane that
  would blank out an entire room. Only vertical, permanent barriers
  (walls, columns, railings, stair flights) are included by default -
  tune `--include-types` if you need something else, but check the
  `PredefinedType` first if you add slabs back in.
- **Doors are excluded from the static map's obstacle list on purpose.**
  Whether a door counts as an obstacle depends on whether it's open or
  shut *right now*, which the BIM doesn't know. Leaving doors out of the
  static layer and letting the live obstacle layer mark a closed door when
  the lidar actually hits it is simpler and self-correcting - no separate
  door-state tracking needed.
- **Separately, door *footprints* are still cleared to free space by
  default.** If your `.pgm` shows a solid black line straight through a
  doorway instead of a gap, this is why: IfcOpenShell only cuts a
  door-shaped hole in a wall if the source file correctly relates that
  wall to an `IfcOpeningElement` via `IfcRelVoidsElement`. A lot of
  real-world IFC files don't - it's a documented, recurring data-quality
  gap (see IfcOpenShell issue #2237), not something a settings flag fixes
  after the fact. `ifc_to_map.py` compensates by carving each `IfcDoor`'s
  own (padded) footprint back to free space after walls are rasterised,
  regardless of whether the wall's own opening was modeled correctly.
  Disable with `--no-clear-doors` if you'd rather trust the source file's
  own modeling as-is.
- **Furniture (`IfcFurnishingElement`) is excluded too**, since your use
  case is furniture that gets moved. If you have furniture you know is
  fixed (built-in counters, etc.), you can add it to `--include-types` and
  it'll be baked into the trusted static layer instead of relying on the
  lidar to see it every time.

## Two machines, not one

This runs better split across two machines, and the package is now laid
out that way:

- **Your workstation** (laptop/desktop, any recent OS): generates the BIM
  map. Needs Python 3.9+ and `ifcopenshell`/`numpy`/`Pillow` - nothing
  ROS-related at all.
- **The dog's companion computer** (Ubuntu 20.04 + ROS2 Foxy, already set
  up per your setup): runs Nav2, localizes, plans, drives the robot. Never
  needs ifcopenshell installed.

Why this split is worth doing rather than just tolerating:
- **Sidesteps the Python version problem entirely.** Recent IfcOpenShell
  releases (0.8.x) only ship wheels for Python 3.10+, but Ubuntu 20.04
  (required by Foxy) ships Python 3.8. On your own workstation you just
  use whatever Python you already have - no PPA, no venv juggling on the
  robot's compute.
- **The dog's companion computer is usually the weakest machine in the
  room.** Go2 companion computers are embedded SBCs (Jetson-class or
  similar), not built for parsing a large IFC model's geometry. Your
  laptop will do it faster and with more headroom.
- **It's a one-time (or once-per-floor) offline step**, not something
  that needs to live on the robot at runtime. The only thing crossing
  the gap is a flat `.pgm` + `.yaml` pair - `map_server` doesn't care what
  produced them, or from what machine.
- **No rebuild needed to update a map.** `scp` the new `.pgm`/`.yaml`
  anywhere on the robot and point the launch file's `map:=` argument at
  that path directly - you don't need them inside this package's own
  `maps/` folder, and you don't need to `colcon build` again just because
  the map changed.

`ifc_to_map.py` and `list_spaces.py` are plain Python with no `rclpy`
import - copy those two files plus `requirements-workstation.txt` to your
workstation and run them directly with `python3`, no ROS2 install needed
there at all.

## Given Foxy + Ubuntu 20.04 are already on the robot, what's left to install

### On the dog (companion computer)

Starting from nothing but Ubuntu 20.04 + ROS2 Foxy + the system Python -
no workspace, no colcon, no rosdep, no copy of this package yet:

```bash
# 0. Make sure Foxy's environment is sourced in this shell
source /opt/ros/foxy/setup.bash

# 1. Build tooling - "base python" doesn't include any of this yet
sudo apt update
sudo apt install python3-pip python3-rosdep python3-colcon-common-extensions

# 2. rosdep needs a one-time init per machine, then an update
sudo rosdep init   # skip if this exact error appears: "already initialized"
rosdep update

# 3. Create a workspace and drop this package into its src/
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src
unzip ~/go2_bim_nav.zip        # wherever you transferred the zip to
# now ~/ros2_ws/src/go2_bim_nav/ should exist

# 4. Resolve this package's ROS dependencies from its package.xml
cd ~/ros2_ws
rosdep install --from-paths src --ignore-src -r -y

# 5. Build and source
colcon build --packages-select go2_bim_nav
source install/setup.bash
echo "source ~/ros2_ws/install/setup.bash" >> ~/.bashrc
```

Step 3 assumes you've already gotten `go2_bim_nav.zip` onto the robot
somehow - `scp go2_bim_nav.zip unitree@<dog-ip>:~/` from your workstation
is the usual way, or a USB stick if the dog isn't networked yet.

Step 4's `rosdep install` is what actually pulls in Nav2 - it reads
`package.xml`, which declares nav2_bringup, nav2_map_server, nav2_amcl,
nav2_controller, nav2_planner, nav2_recoveries, nav2_bt_navigator,
nav2_costmap_2d, nav2_lifecycle_manager, and pointcloud_to_laserscan.
Explicit package names, if you'd rather see them:
`ros-foxy-navigation2 ros-foxy-nav2-bringup ros-foxy-pointcloud-to-laserscan`.

That's it for the dog - no `ifcopenshell`, no `numpy`, no `Pillow` needed
there at all under this split. `send_goal.py`'s optional `--waypoint` flag
wants PyYAML, which is pure-Python with no version-cliff problem like
ifcopenshell has - `pip3 install --user pyyaml` under Foxy's own Python
3.8 if it isn't already present (many ROS2 installs pull it in already;
`python3 -c "import yaml"` tells you either way).

### On your workstation

```bash
python3 -m venv bim_env
source bim_env/bin/activate
pip install -r requirements-workstation.txt
```

Then generate the map (see Usage below) and copy the resulting
`.pgm`/`.yaml` over to the robot - `scp`, a USB stick, whatever you'd
normally use to get a file onto the companion computer.

### The Go2's own ROS2 driver

Whatever bridges the robot's native interface to ROS2 topics/actions -
odometry, tf, the lidar cloud, `cmd_vel`. Given your "already set up"
assumption this is presumably already running - just confirm it and note
its real topic names before launching (`ros2 topic list`).

**Update, confirmed against this robot's actual driver:** there is no
plain `cmd_vel`-compatible topic. This robot runs Unitree's native
`unitree_ros2` driver, which controls motion through a request/response
API instead - you publish a `unitree_api/msg/Request` to
`/api/sport/request`, not a `geometry_msgs/Twist` to `/cmd_vel`. Nav2's
`controller_server` only knows how to publish the latter, so a bridge is
required in between - `cmd_vel_bridge.py` in this package is that bridge,
built directly from this robot's own
`~/unitree_ros2/example/src/include/common/ros2_sport_client.h` and
`.../src/common/ros2_sport_client.cpp` (`ROBOT_SPORT_API_ID_MOVE = 1008`,
`parameter = {"x": vx, "y": vy, "z": vyaw}` JSON), not a guessed schema.
It's wired into `bim_nav_bringup.launch.py` already. It also runs a
watchdog: if `/cmd_vel` goes stale for >0.5s, it sends `StopMove`
(api_id=1003) rather than trusting a stale velocity command indefinitely.

**Requires `unitree_ros2`'s workspace sourced before this package's own**,
in every shell you launch from - `unitree_api` (the message package
`cmd_vel_bridge.py` imports) is built there, not here:

```bash
source ~/unitree_ros2/install/setup.bash   # or wherever it actually is
source ~/ros2_ws/install/setup.bash        # this package, sourced AFTER
```

**Worth a deliberate decision, not a default:** that same header file
defines `ROBOT_SPORT_API_ID_SWITCHAVOIDMODE = 2058` - this robot's firmware
has its own native obstacle-avoidance mode, separate from anything Nav2
does. Whether it's on or off right now is worth knowing explicitly rather
than assuming, since the firmware's own avoidance behavior and Nav2's
obstacle layer + DWB could interact in ways you don't expect if both are
independently trying to influence the robot's motion. Decide on purpose
which one (or both) should be active before trusting this near anything
you care about - this package doesn't touch that switch either way.

### If you want to generate the map on the dog anyway

Possible, but you'll hit the Python 3.8/ifcopenshell-wheel problem
directly. The `deadsnakes` PPA + venv workaround still works if you want
this:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update && sudo apt install python3.11 python3.11-venv
python3.11 -m venv ~/ifc_env && source ~/ifc_env/bin/activate
pip install -r requirements-workstation.txt
```

but there's no upside to doing this over just using your existing
workstation, and it's more setup on the machine you'd rather keep lean.

## Usage

### 1. Generate the BIM map (on your workstation)

```bash
source bim_env/bin/activate   # the venv from requirements-workstation.txt
python go2_bim_nav/ifc_to_map.py \
  --input /path/to/model.ifc \
  --output bim_map \
  --resolution 0.05 \
  --storey "Level 1"
```

Omit `--storey` only if the model is genuinely single-floor - otherwise
every storey gets combined into one map, which is wrong. This writes
`bim_map.pgm` + `bim_map.yaml` right there on your workstation - copy both
onto the robot next (`scp bim_map.* dog:/home/unitree/maps/`, or however
you normally move files onto it).

Before shipping it anywhere, confirm it actually looks right - same
venv, no ROS2/rviz2/dog needed:

```bash
python go2_bim_nav/preview_map.py --map bim_map.yaml
```

This opens the map as an image with a metre grid overlaid, at the correct
aspect ratio, so you can eyeball whether it actually resembles the floor
plan, at a sane scale, before it ever touches the robot. Pass `--save
preview.png` instead if you're doing this over SSH without a display.

### 2. Verify your Go2 driver's topic names (on the dog)

This package assumes a ROS2 Foxy driver (`unitree_ros2`, `go2_ros2_sdk`, or
similar) is already running and publishing odometry/tf and the lidar
point cloud, and subscribing to `cmd_vel`. **Topic names vary between
drivers** - check yours and override the launch arguments accordingly:

```bash
ros2 topic list   # confirm the actual lidar cloud topic name
```

### 3. Launch (on the dog)

```bash
ros2 launch go2_bim_nav bim_nav_bringup.launch.py \
  map:=/home/unitree/maps/bim_map.yaml \
  lidar_cloud_topic:=/utlidar/cloud
```

### 4. Send it somewhere (on the dog, or anywhere on the same ROS2 network)

Everything above only reacts once something asks it to navigate - it's the
`send_goal` script that actually does the asking:

```bash
# raw coordinates in the map (BIM) frame
ros2 run go2_bim_nav send_goal --x 3.5 --y 1.2 --yaw 0.0

# or a named waypoint (edit config/waypoints.yaml first - see below)
ros2 run go2_bim_nav send_goal --waypoint kitchen \
  --waypoints-file $(ros2 pkg prefix go2_bim_nav)/share/go2_bim_nav/config/waypoints.yaml
```

It blocks until the robot arrives (or fails), and exits 0/1 accordingly, so
it's callable from a shell script or a higher-level task node. Under the
hood it's a `NavigateToPose` action client hitting `bt_navigator` - the same
action RViz's "Nav2 Goal" tool calls, if you'd rather click a point on the
map interactively (`ros2 launch nav2_bringup rviz_launch.py`, run
alongside `bim_nav_bringup.launch.py`).

To turn "the kitchen" into real coordinates instead of guessing (on your
workstation, same venv as step 1):

```bash
python go2_bim_nav/list_spaces.py --input model.ifc
```

This prints every `IfcSpace` name with its centroid in the same world
coordinates the map was built from - copy the numbers into
`config/waypoints.yaml`, then copy that file onto the dog too.

### 5. Set the initial pose (on the dog)

AMCL needs to know roughly where the robot starts in the BIM's coordinate
frame. Three ways to do it, roughly simplest-to-set-up first:

- **Hardcode it.** If the robot always starts from the same dock/charging
  spot, set `set_initial_pose: true` plus `initial_pose.[x, y, yaw]` in
  `config/nav2_params.yaml` to that spot's known coordinates. No GUI, no
  networking fuss - the right default if you don't have a display on the
  dog.
- **RViz, run from your workstation, not the dog.** Companion computers
  are usually headless - don't fight to run RViz on the robot itself.
  Since RViz is a ROS2 GUI tool it needs a ROS2 install to run at all, so
  this means installing `ros-foxy-desktop` (or at least `ros-foxy-rviz2`)
  on your workstation too, on the same network/`ROS_DOMAIN_ID` as the dog,
  then `rviz2` there and use "2D Pose Estimate" against the dog's live
  topics. This is a separate ROS2 install on the workstation from the
  plain-Python venv used for `ifc_to_map`/`list_spaces` - they don't
  overlap.
- **RViz directly on the dog**, if it actually has a display or you're
  VNC'd in - `sudo apt install ros-foxy-rviz2` there and run it locally.

This coordinate alignment step - getting the robot's localization frame to
agree with the BIM's coordinate system - is usually the trickiest part of
the whole setup, more so than the planning logic itself.

## Things you'll need to tune

- `config/nav2_params.yaml` footprint (`[[0.35, 0.16], ...]`) is a
  placeholder - measure your actual Go2 footprint and update both
  `local_costmap` and `global_costmap`.
- `max_vel_x` / `acc_lim_x` in the `FollowPath` (DWB) section should match
  whatever velocity limits your Go2 driver actually accepts on `cmd_vel`.
- `min_height` / `max_height` in the launch file's
  `pointcloud_to_laserscan` node control which horizontal slice of the 3D
  lidar cloud becomes the 2D scan - adjust for your lidar's mounting
  height.
- ROS2 Foxy is end-of-life; package APIs here (recoveries_server, plugin
  strings) match Foxy-era Nav2 - double check against your exact installed
  version if anything fails to load.

## What this has NOT been verified against

Being direct about this rather than letting it be assumed: the rasterizer
and map-writing logic in `ifc_to_map.py`, and the waypoint/quaternion logic
in `send_goal.py`, have been unit-tested against synthetic data. Nothing
here has been run against a real IFC file, a real Go2, or ROS2 Foxy
itself - I don't have any of those available to test with. Concretely,
still unverified:

- Parsing your actual IFC file (real files have quirks synthetic test
  geometry doesn't - missing representations, unexpected element types).
- The Go2 driver integration - topic names, message types, and whether
  `cmd_vel` is even the right interface for your specific driver.
- AMCL localizing correctly against a BIM-derived (rather than
  SLAM-derived) map - the geometry is cleaner than a real SLAM map, which
  usually helps, but confirm it in practice.
- Nav2 plugin/parameter names against your exact installed Foxy patch
  version.
- Everything, running on the actual robot, near actual obstacles.

Test in an open, empty area first, with a way to kill power/e-stop within
reach, before trusting this near people or anything fragile.
