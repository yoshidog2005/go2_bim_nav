# Go2_Docker

This repository contains information on how to use the Go2, particularly regarding Docker set up.

It builds `humble_base`: an Ubuntu 22.04 + ROS 2 Humble + Python 3.8 image for the
Unitree Go2's onboard Jetson (aarch64, L4T R35.3.1 / JetPack 5.1.1), with the Unitree SDK2 Python interface installed.

## Prerequisites

## Build

From the repository root:

```bash
docker build -t humble_base:test .
```

## Run

```bash
./run_container.sh                      # interactive bash inside the container
./run_container.sh ros2 topic list      # run a single command and exit
```

With a different image tag:

```bash
IMAGE=humble_base:dev ./run_container.sh
```

If the script is not executable yet:

```bash
chmod +x run_container.sh
```

### What the run script sets up

See the comments in [run_container.sh](run_container.sh) for the full rationale.
In short:

- `--network host` and `--ipc host` — required for DDS discovery to reach
  machines outside this box. Multicast does not cross Docker's bridge network,
  and Fast DDS's shared-memory transport needs the host IPC namespace.
- `--user $(id -u):$(id -g)` — runs as you, not root, so files created inside
  the container (`build/`, `install/`, `log/`, `__pycache__`) stay owned by you
  on the host.
- `-v $HOME:$HOME`, `-e HOME`, `-w $HOME` — your home directory is mounted at
  the same path inside and out, and is the working directory. The image default
  `/root` is not writable by uid 1000.
- `--rm` — the container is deleted on exit, so nothing accumulates. Anything
  you want to keep belongs under your mounted home.

The entrypoint ([ros_entrypoint.sh](ros_entrypoint.sh)) sources
`/opt/ros/humble/install/setup.bash`, sources `/root/ros_ws/install/setup.bash`
if a workspace was built into the image, and sets `ROS_DOMAIN_ID=1` before
running your command.

## Verify it works

Inside the container:

```bash
ros2 topic list                         # ROS 2 environment is sourced
python3 -c "import unitree_sdk2py; print('sdk ok')"
echo $RMW_IMPLEMENTATION                # rmw_fastrtps_cpp
```

To talk to another machine, make sure it uses the same `ROS_DOMAIN_ID` (1) and
the same RMW. The image overrides the base image's CycloneDDS default with Fast
DDS (`rmw_fastrtps_cpp`) so a stock ROS 2 Humble install elsewhere interoperates
without extra configuration.

## Adding your own code

- **Python dependencies** go in [requirements.txt](requirements.txt), pinned
  where possible, then rebuild.
- **A ROS 2 workspace** can either be mounted (it is already there, under your
  home) and built inside the container with `colcon build --symlink-install`, or
  baked into the image by uncommenting the `COPY ros_ws/` / `colcon build` block
  near the end of the [Dockerfile](Dockerfile).
