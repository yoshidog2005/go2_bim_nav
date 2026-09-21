# Go2 Docker Template

A template for building a Docker container for any project that runs on the
Unitree Go2's onboard Jetson. Copy it into your project, give the image your
project's name, add your dependencies, and run.

## Go2 quick reference

| | |
| --- | --- |
| Dog IP address (on network `EH-5400`) | `192.168.123.46` |
| Dog password | `ucirobotics` |
| OS | Ubuntu 20.04 (L4T R35.3.1 / JetPack 5.1.1, aarch64) |
| ROS | ROS 2 Humble |
| Python | 3.8.10 |

SSH into the dog (use the username for your account on the dog):

```bash
ssh <user>@192.168.123.46
```

Build and run everything below **on the dog**.

---

## How to build a container for your project

### 1. Copy this template into your project

**Starting a new project** — clone the template, then point it at your own
repository so `git push` never goes to this template repository:

```bash
git clone https://github.com/AICPS/go2_docker.git <project_name>
cd <project_name>
git remote remove origin
git remote add origin <your_project_repo_url>
git push -u origin main
```

**Adding to an existing project** — from the root of your project repository,
copy only the template's files (no `.git`, so your remote is unchanged, and
your own `README.md` is not overwritten):

```bash
git clone --depth 1 https://github.com/AICPS/go2_docker.git /tmp/go2_docker
git -C /tmp/go2_docker archive HEAD \
    Dockerfile requirements.txt run_container.sh ros_entrypoint.sh .dockerignore examples \
    | tar -x -C .
rm -rf /tmp/go2_docker
git add Dockerfile requirements.txt run_container.sh ros_entrypoint.sh .dockerignore examples
git commit -m "Add Go2 Docker setup"
```

Check that it worked with `git remote -v` — it should list only your project's
repository.

### 2. Build the image, tagged with your project name

From the project root (the folder containing the `Dockerfile`):

```bash
docker build -t <project_name>:latest .
```

Use a lowercase name with no spaces (Docker requires it), e.g.
`docker build -t go2_mapping:latest .`. Tagging each project's image with its
own name keeps them apart — `docker images` lists all existing images.

The first build downloads the base image and can take a while. Rebuild any
time you change the `Dockerfile` or `requirements.txt`.

### 3. Point `run_container.sh` at your image

Open [run_container.sh](run_container.sh) and change the default image name
on this line:

```bash
IMAGE="${IMAGE:-humble_desktop:test}"
```

to the tag you built in step 2:

```bash
IMAGE="${IMAGE:-<project_name>:latest}"
```

Then start the container:

```bash
chmod +x run_container.sh    # once
./run_container.sh           # interactive shell inside the container
```

Inside the container you are your normal user, and your home directory is
mounted at the same path, so `cd` to your project folder and your code is
there. Files you create are saved on the dog, not lost when the container
exits. The container itself is deleted on exit (`--rm`), so anything installed
by hand inside it is lost — see step 4.

### 4. Add Python dependencies

Add each package your code imports to [requirements.txt](requirements.txt),
one per line, pinned to an exact version:

```text
numpy==1.24.4
scipy==1.10.1
```

Then rebuild the image (step 2). Packages must support Python 3.8.

**Track every dependency in `requirements.txt` and the `Dockerfile`, and
commit both to your project repository.** Do not `pip install` or
`apt-get install` inside a running container to get things working: those
changes vanish when the container exits, and nobody else (including you in six
months) can reproduce them. If a dependency is in these two files, anyone can
clone your repo, run `docker build`, and get the exact same environment.

- Python packages → `requirements.txt`
- System (apt) packages → the `apt-get install` list in the `Dockerfile`

Note: the base image builds ROS from source, so `ros-humble-*` apt packages
are **not** installable. Don't add them. To add ROS packages, see
[Installing ROS 2 packages (e.g. Nav2)](#installing-ros-2-packages-eg-nav2) at
the bottom.

---

## Networking summary

The container runs two separate DDS networks side by side:

1. **Robot side — CycloneDDS, domain 0.** The Unitree SDK
   (`unitree_sdk2py`) uses CycloneDDS to talk to the Go2's internal MCU
   (motors, sensors, sport/navigation services). It runs on domain 0 over the
   wired interface `ethrobot`.
2. **ROS side — ROS 2 Humble, domain 1.** Your own ROS 2 nodes run on the
   Jetson with `ROS_DOMAIN_ID=1` (set in
   [ros_entrypoint.sh](ros_entrypoint.sh)), using Fast DDS
   (`rmw_fastrtps_cpp`). This is how the dog talks to laptops and other
   devices on the network.

The two can't interfere with each other: they use different DDS libraries and
different domains. To bring robot data into ROS, a bridge reads it with the
SDK and republishes it with `rclpy` (see the LiDAR example below).

To see the dog's ROS topics from another machine, that machine must be on the
same network and use:

```bash
export ROS_DOMAIN_ID=1 # (Not default Domain of 0)
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp   # the ROS 2 Humble default
```

Don't set `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` inside the container — it
would collide with the SDK's CycloneDDS setup.

---

## Examples

Run these inside the container (`./run_container.sh`) from the project root.

### LiDAR → ROS 2 topic

[examples/lidar_bridge.py](examples/lidar_bridge.py) reads the Go2's LiDAR
point cloud from the robot (`rt/utlidar/cloud_base`, CycloneDDS domain 0) and
republishes it as a `sensor_msgs/PointCloud2` on the ROS 2 topic
`/utlidar/cloud` (domain 1).

```bash
python3 examples/lidar_bridge.py
```

Check it from the dog or another machine: `ros2 topic hz /utlidar/cloud`

### Network test

[examples/pub_test.py](examples/pub_test.py) publishes `hello world` on
`/chatter` once per second over ROS 2 Humble.

On the dog, inside the container:

```bash
python3 examples/pub_test.py
```

On another device on the same network (with `ROS_DOMAIN_ID=1`):

```bash
ros2 topic echo /chatter
```

If the messages show up, ROS 2 networking between the two machines works. If
not, check that both machines are on the same network and the same
`ROS_DOMAIN_ID`.

### Moving the robot

[examples/obstacles_avoid/test_nav2point.py](examples/obstacles_avoid/test_nav2point.py)
sends the dog to a target position using the Go2's built-in obstacle-avoidance
navigation.

**The dog must be standing, with clear space around it.** Keep the remote
controller in hand in case you need to stop it. **Do not run without a PhD student present.**

```bash
python3 examples/obstacles_avoid/test_nav2point.py ethrobot
```

At the prompt, type three numbers separated by spaces:

```text
Enter target  x  y  yaw  (metres, metres, radians) or 'q' to quit: 1.0 0.0 0.0
```

- `x` — metres forward
- `y` — metres to the left
- `yaw` — heading in radians (counter-clockwise positive; `1.57` ≈ 90° left)

These are measured from the position and orientation the dog had **when it
started up**, not from where it is now. So `0 0 0` returns it to its start-up
pose, and entering `1.0 0.0 0.0` twice does not move it 2 m.

After each goal the script waits 15 seconds, then asks for the next one. Type
`q` to quit, or press `Ctrl+C` to abort — either way the script stops the dog
and releases API control.

---

## Installing ROS 2 packages (e.g. Nav2)

> **⚠️ UNTESTED.** Nothing in this section has been run on the dog yet —
> not the Dockerfile block, the entrypoint change, or a Nav2 build. If you try
> it, update this section with what worked and what didn't, and remove this
> warning once it's been confirmed.

On a normal Ubuntu 22.04 machine you would `apt install ros-humble-navigation2`.
That doesn't work here: the dog runs Ubuntu 20.04, which has no `ros-humble-*`
apt packages, and the base image built ROS Humble from source into
`/opt/ros/humble/install`. Extra ROS packages have to be built from source
too, during `docker build`, in a second workspace layered on top of the base
ROS install.

**This is a method to try, not a guaranteed recipe.** See
[What to expect on Ubuntu 20.04](#what-to-expect-on-ubuntu-2004) before
starting.

The steps:

1. Generate a list of the package's source repositories **plus every ROS
   dependency the base image doesn't already have** (`rosinstall_generator`).
2. Download that source into a workspace (`vcs import`).
3. Install the non-ROS system libraries it needs with apt (`rosdep`).
4. Build it (`colcon build`).
5. Source the new workspace when the container starts.

### 1. Add a build block to the `Dockerfile`

Add this after the Unitree SDK block. Change `ROS_PACKAGES` to the packages
you need, space-separated (for example `navigation2 nav2_bringup`):

```dockerfile
# ---------------------------------------------------------------------------
# Extra ROS 2 packages, built from source (ros-humble-* debs don't exist for
# focal). rosinstall_generator lists each package and every ROS dependency it
# needs; --exclude RPP skips anything already in the base image, found through
# ROS_PACKAGE_PATH. Lives in /opt, not /root, so the non-root container user
# can read it.
# ---------------------------------------------------------------------------
ARG ROS_PACKAGES="navigation2 nav2_bringup"
WORKDIR /opt/ros_deps_ws
RUN pip3 install --no-cache-dir rosinstall_generator vcstool \
    && source /opt/ros/humble/install/setup.bash \
    && export ROS_PACKAGE_PATH=/opt/ros/humble/install/share \
    && mkdir -p src \
    && rosinstall_generator ${ROS_PACKAGES} --rosdistro humble --deps --exclude RPP > ros_deps.repos \
    && vcs import src < ros_deps.repos \
    && apt-get update \
    && (rosdep init || true) \
    && rosdep update --rosdistro humble \
    && rosdep install --from-paths src --ignore-src -r -y --rosdistro humble \
    && rm -rf /var/lib/apt/lists/* \
    && colcon build --merge-install --parallel-workers 2 \
        --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    && rm -rf build log
WORKDIR /
```

What each part does:

- `--exclude RPP` skips packages the base image already has, so only the
  missing ones are downloaded and built.
- `rosdep install` reads each package's `package.xml` and installs the
  **system** libraries (Eigen, Boost, etc.) with apt. `-r` keeps it going past
  anything it can't resolve.
- `--parallel-workers 2` limits how many packages build at once. Nav2 has many
  large C++ packages, and building too many in parallel can run the Jetson
  out of memory. If the build is killed with no clear error, lower it to `1`.
- `BUILD_TESTING=OFF` skips building tests, which saves a lot of time.
- `rm -rf build log` keeps intermediate build files out of the image.

### 2. Source the workspace in `ros_entrypoint.sh`

Add this line to [ros_entrypoint.sh](ros_entrypoint.sh), right after the line
that sources `/opt/ros/humble/install/setup.bash`:

```bash
source /opt/ros_deps_ws/install/setup.bash
```

### 3. Rebuild and check

```bash
docker build -t <project_name>:latest .
./run_container.sh
ros2 pkg list | grep nav2
```

Nav2 is large. Building it on the Jetson can take **hours**, so start it when
you don't need the dog. Docker caches the result, so later rebuilds skip this
step unless you change this block or anything above it in the `Dockerfile`.
Put the block **above** the `COPY requirements.txt` line if you expect to
change Python dependencies often, so editing `requirements.txt` doesn't
trigger a Nav2 rebuild.

### What to expect on Ubuntu 20.04

ROS 2 Humble officially supports only Ubuntu 22.04. The ROS core in this image
works because it was built from source and adjusted for 20.04. Packages you
add on top are in the same position: many will build, but nobody tests them on
20.04. Plain C++ and Python ROS packages usually work. Problems come from
20.04 shipping older versions of things Humble expects from 22.04:

- **Python 3.8 instead of 3.10.** Python packages that use newer syntax (e.g.
  `match` statements, or `list[int]`-style type hints evaluated at runtime)
  fail when imported.
- **Older compiler and CMake** (GCC 9 vs 11, CMake 3.16 vs 3.22). Occasionally
  a package uses a C++ feature or CMake command these don't have.
- **Older system libraries** from apt (Boost, xtensor, OpenCV, PCL, ...). For
  Nav2, the MPPI controller (`nav2_mppi_controller`) is the most likely to
  fail, since it needs a newer xtensor than 20.04 may provide.
- **rosdep keys** that are defined only for 22.04 and don't resolve on 20.04.
  `-r` lets the build continue, but you must install those libraries yourself.

For Nav2, expect the core stack to build, possibly with a few plugins needing
to be skipped. The only real test is running the build on the dog.

### If a package fails to build

- **Missing ROS dependency** (`Could not find a package configuration file
  provided by "X"`): add `X` to `ROS_PACKAGES` and rebuild.
- **A package you don't need fails** (for example a controller or plugin that
  won't compile on 20.04): skip it by adding
  `--packages-skip <package_name>` to the `colcon build` line, as long as
  nothing you use depends on it.
- **A package you do need fails:** try an older release of it (check out an
  earlier tag in `src/`, or edit its version in `ros_deps.repos`), or build the
  missing/too-old system library from source in an earlier `RUN` step.
- **Reproducibility:** `rosinstall_generator` pulls the current Humble release
  of each package, so a rebuild months later may get newer versions. To pin
  them, run the generator once, commit the resulting `ros_deps.repos` file to
  your project, and `COPY` it into the image instead of generating it during
  the build.
