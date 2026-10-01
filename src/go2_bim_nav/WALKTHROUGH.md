# go2_bim_nav — Setup Walkthrough

Ordered, copy-pasteable steps for both machines. For the reasoning behind
any of this (why two machines, why doors/furniture/slabs are handled the
way they are, tuning notes, what's unverified), see `README.md` - this
file is just the steps.

## Part 1 — Workstation: generate the map

### 1. Set up the venv (one time)

```bash
python3 -m venv bim_env
source bim_env/bin/activate
pip install -r requirements-workstation.txt
```

### 2. Generate the map

```bash
python go2_bim_nav/ifc_to_map.py \
  --input /path/to/model.ifc \
  --output bim_map \
  --resolution 0.05 \
  --storey "Level 1"
```

Drop `--storey` only if the model is genuinely single-floor - otherwise
every storey gets combined into one map, which is wrong. This writes
`bim_map.pgm` + `bim_map.yaml` right there - nothing ROS-related touched
at all.

By default this also clears each door's footprint to free space, since
many real IFC files don't cleanly model the wall opening at a door -
without it, a doorway can render as solid, unbroken wall. If you see that
in the preview (next step), it's confirming this exact gap in the source
file, not a bug in this script - disable with `--no-clear-doors` if you'd
rather trust the file's own modeling instead.

### 3. Confirm it actually looks right

```bash
python go2_bim_nav/preview_map.py --map bim_map.yaml
```

Opens the map with a metre grid overlaid, correct aspect ratio, no
ROS2/rviz2/dog needed - eyeball it against the real floor plan before
shipping it anywhere. Use `--save preview.png` instead over SSH / without
a display.

### 4. (Optional) Look up room coordinates for named waypoints

```bash
python go2_bim_nav/list_spaces.py --input model.ifc
```

Copy the numbers you want into `config/waypoints.yaml`.

### 5. Get the files onto the dog

```bash
scp bim_map.pgm bim_map.yaml config/waypoints.yaml unitree@<dog-ip>:~/maps/
```

## Part 2 — Dog: from scratch (Ubuntu 20.04 + Foxy + base Python, nothing else)

### 1. Source Foxy and install build tooling

Base Python doesn't include colcon, rosdep, or even pip.

```bash
source /opt/ros/foxy/setup.bash
sudo apt update
sudo apt install python3-pip python3-rosdep python3-colcon-common-extensions
```

### 2. Init rosdep (one time per machine)

```bash
sudo rosdep init   # skip if it reports already initialized
rosdep update
```

### 3. Get the package onto the robot and into a workspace

```bash
scp go2_bim_nav.zip unitree@<dog-ip>:~/     # from your workstation
# then, on the dog:
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src
unzip ~/go2_bim_nav.zip
```

### 4. Resolve dependencies

This is what actually pulls in Nav2, since it's not part of a stock Go2
setup - `rosdep` reads the list straight from `package.xml`.

```bash
cd ~/ros2_ws
rosdep install --from-paths src --ignore-src -r -y
```

### 5. Build

```bash
colcon build --packages-select go2_bim_nav
source install/setup.bash
echo "source ~/ros2_ws/install/setup.bash" >> ~/.bashrc
```

**If this fails with `AttributeError: module 'importlib_metadata' has no
attribute 'EntryPoints'`:** this is a known `setuptools`/`importlib_metadata`
version clash (`setuptools` >= 71.0.0 on Python 3.8) - it dies inside
`import setuptools` itself, before Python ever reaches this package's
`setup.py`, so it's not this package's code. Usually caused by an earlier
`pip3 install --user` (e.g. the PyYAML install in step 4 of Part 1, or
anything else) silently pulling in a newer `setuptools` as a transitive
dependency into `~/.local/lib/python3.8/site-packages/`, which then shadows
the older one Foxy expects. Fix:

```bash
pip3 install --user "setuptools==58.2.0"
colcon build --packages-select go2_bim_nav
```

### 6. Confirm the Go2 driver is running and find its real topic names

Yours may not match this package's default guesses.

```bash
ros2 topic list
```

Look specifically for the lidar cloud topic (`--lidar_cloud_topic` in step
7). If you're on Unitree's native `unitree_ros2` driver, there's no
`cmd_vel`-compatible topic at all - motion goes through
`/api/sport/request` instead, which `cmd_vel_bridge.py` (already wired
into the launch file) handles. If your setup uses a different driver that
does expose a real `cmd_vel`, you don't need that bridge - just don't
launch it, or ignore it if unused.

### 7. Launch

Source `unitree_ros2`'s workspace *before* this one, every time - the
bridge imports `unitree_api`, which lives in `unitree_ros2`'s install, not
this package's:

```bash
source ~/unitree_ros2/install/setup.bash   # before this package's own
source ~/ros2_ws/install/setup.bash

ros2 launch go2_bim_nav bim_nav_bringup.launch.py \
  map:=/home/unitree/bim_nav_ws/src/go2_bim_nav/maps/bim_map.yaml \
  lidar_cloud_topic:=/utlidar/cloud_base_restamped \
  use_odom_to_tf:=false
```

python3 lidar_restamp.py --ros-args -p publish_odom_tf:=true

### 8. Set the initial pose

Companion computers are usually headless - don't fight to run RViz on the
dog itself.

- **Easiest:** hardcode a known dock position via `set_initial_pose: true`
  plus `initial_pose.[x, y, yaw]` in `config/nav2_params.yaml`.
- **Interactive:** run RViz from your workstation instead (needs its own
  separate ROS2 Foxy install there, same network - different from the
  plain-Python venv from Part 1), and use "2D Pose Estimate" against the
  dog's live topics.

### 9. Send it somewhere

```bash
ros2 run go2_bim_nav send_goal --waypoint kitchen \
  --waypoints-file ~/maps/waypoints.yaml
```
```bash
ros2 run go2_bim_nav send_goal --x 1.0 --y 0.0 --yaw 0.0
```

## Before trusting this near anything you care about

Test in an open, empty room first, with a way to kill power/e-stop within
reach. See the "What this has NOT been verified against" section of
`README.md` for specifics on what's still unconfirmed - none of this has
been run against a real IFC file, a real Go2, or ROS2 Foxy itself.
