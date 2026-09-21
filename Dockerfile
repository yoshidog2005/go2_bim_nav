# humble_base
# Ubuntu 20.04 + ROS 2 Humble + Python 3.8, built for NVIDIA Jetson (L4T R35.3.1 / JetPack 5.1.1)
# Target host: Unitree Go2 Jetson (aarch64), L4T R35 series.
#
# Base image: dustynv/ros humble-DESKTOP for L4T r35.3.1 (exact match to host L4T).
# The desktop variant is used instead of ros-base because it is the REP-2001
# variant that contains rviz2 (at /opt/ros/humble/install/bin/rviz2), so the
# LiDAR can be visualised on the robot itself rather than on a laptop.
#
# NOTE: this image builds ROS Humble from source under /opt/ros/humble/install/
# in a MERGED layout (bin/, lib/, share/ at the top level -- no per-package
# directories, and NOT the Debian /opt/ros/humble/{lib,setup.bash} layout). It
# already ships rmw_cyclonedds_cpp as the default RMW. Its apt sources point at
# 'focal', so ros-humble-* Debian packages are NOT apt-installable here --
# don't add them.
FROM dustynv/ros:humble-desktop-l4t-r35.3.1

# Use bash so we can 'source' ROS setup files in RUN steps.
SHELL ["/bin/bash", "-c"]

# Non-interactive apt during build only (not persisted to runtime env).
ARG DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------------
# Refresh the ROS apt signing key.
# This base image predates the June-2025 ROS GPG key rotation, so its baked-in
# key is expired and 'apt-get update' fails with EXPKEYSIG F42ED6FBAB17C654.
# Overwriting the keyring with the current key from the ROS distro repo fixes it.
# ---------------------------------------------------------------------------
RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
        -o /usr/share/keyrings/ros-archive-keyring.gpg

# ---------------------------------------------------------------------------
# System packages (plain Ubuntu tools only).
#   - git: needed to clone the Unitree SDK from source
#   - iproute2 / iputils-ping / net-tools: interface + connectivity debugging
#     (useful given the DDS/interface work on this robot)
#   - vim, tmux, less: quality-of-life inside the container
# CycloneDDS RMW is already built into the base image, so it is NOT listed here.
# Clean apt lists in the SAME layer so the cache doesn't bloat the image.
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        iproute2 \
        iputils-ping \
        net-tools \
        vim \
        tmux \
        less \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Python dependencies
# Kept in requirements.txt so the dependency set is a readable, diffable record.
# Copied and installed on its own layer so a code change later doesn't force a
# reinstall of Python deps.
# ---------------------------------------------------------------------------
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# ---------------------------------------------------------------------------
# Unitree SDK2 Python interface (talks to the Go2 MCU over CycloneDDS).
# Clones master (most recent commit) and installs non-editable.
#
# The SDK's install needs to locate CycloneDDS, or it fails with
# "Could not locate cyclonedds. Try to set CYCLONEDDS_HOME". This image builds
# ROS (and CycloneDDS) under /opt/ros/humble/install/, so CYCLONEDDS_HOME is set
# there as the best guess. If the build fails on this step, locate the library:
#     find / -name "libddsc.so*" 2>/dev/null
# and set CYCLONEDDS_HOME to the prefix that CONTAINS lib/libddsc.so (and its
# include/), then rebuild.
# ---------------------------------------------------------------------------
ENV CYCLONEDDS_HOME=/opt/ros/humble/install
RUN git clone https://github.com/unitreerobotics/unitree_sdk2_python.git /opt/unitree_sdk2_python \
    && cd /opt/unitree_sdk2_python \
    && pip3 install --no-cache-dir .

# ---------------------------------------------------------------------------
# DDS / ROS runtime default.
# The base image ships rmw_cyclonedds_cpp as its default. Override it with Fast
# DDS, which is stock ROS 2's default, so external machines running an untouched
# Humble install interoperate without configuring anything on their end.
# Interface binding / domain / peers are chosen at RUN time, not baked in.
# NOTE: Dockerfiles have no trailing comments -- a '#' is only a comment at the
# start of a line, otherwise ENV parses it as another name=value pair.
# ---------------------------------------------------------------------------
ENV RMW_IMPLEMENTATION=rmw_fastrtps_cpp

# ---------------------------------------------------------------------------
# Only use Python packages that are built into this image.
# run_container.sh mounts the host $HOME, which exposes the host's
# ~/.local/lib/python3.8/site-packages ("user site"). Python searches the user
# site BEFORE /usr/local/lib/python3.8/dist-packages, so any host
# `pip install --user` silently shadows the image's packages. An old host
# install of unitree_sdk2py + cyclonedds did exactly that, and the host-built
# cyclonedds binding segfaulted against this image's CycloneDDS library.
# Disabling the user site also stops its .pth files (e.g. easy-install.pth)
# from adding host paths.
# ---------------------------------------------------------------------------
ENV PYTHONNOUSERSITE=1

# ---------------------------------------------------------------------------
# Your ROS 2 workspace / code
# Uncomment and adapt once you have a workspace to build.
# ---------------------------------------------------------------------------
# COPY ros_ws/ /root/ros_ws/
# RUN source /opt/ros/humble/install/setup.bash \
#     && cd /root/ros_ws \
#     && colcon build --symlink-install

# Entrypoint sources ROS and drops into the requested command.
COPY ros_entrypoint.sh /ros_entrypoint.sh
RUN chmod +x /ros_entrypoint.sh
ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["bash"]
