# humble_base
# Ubuntu 22.04 + ROS 2 Humble + Python 3.10, built for NVIDIA Jetson (L4T R35.3.1 / JetPack 5.1.1)
# Target host: Unitree Go2 Jetson (aarch64), L4T R35 series.
#
# Base image: dustynv/ros humble-ros-base for L4T r35.3.1 (exact match to host L4T).
# Pinned by digest for reproducibility; the tag is kept in the comment for readability.
FROM dustynv/ros:humble-ros-base-l4t-r35.3.1@sha256:0a43789d92801cebbc7510fe8fd7acdfc16f8c62e56790435a89a596f9b7c3ba

# Use bash so we can 'source' ROS setup files in RUN steps.
SHELL ["/bin/bash", "-c"]

# Non-interactive apt during build only (not persisted to runtime env).
ARG DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------------
# System packages (least-frequently changing -> early layer for good caching)
#   - rmw_cyclonedds_cpp: CycloneDDS RMW for ROS 2 (apt-installable on Humble;
#     no need to compile from source as on Foxy)
#   - iproute2 / iputils-ping / net-tools: interface + connectivity debugging
#     (useful given the DDS/interface work on this robot)
#   - vim, tmux, less: quality-of-life inside the container
# Clean apt lists in the SAME layer so the cache doesn't bloat the image.
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-humble-rmw-cyclonedds-cpp \
        ros-humble-rosidl-generator-dds-idl \
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
# DDS / ROS runtime configuration
# NOTE: interface binding is intentionally NOT hardcoded here. RMW is set to
# CycloneDDS, but ROS_DOMAIN_ID and CYCLONEDDS_URI are chosen at RUN time so the
# same image can serve both the MCU side (domain 0) and the ROS 2 side
# (domain 2) with different interface bindings. A default CycloneDDS config that
# binds ROS 2 to the Wi-Fi interface is shipped to /config for convenience.
# ---------------------------------------------------------------------------
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
COPY config/ /config/

# ---------------------------------------------------------------------------
# Your ROS 2 workspace / code (most-frequently changing -> latest layer).
# Uncomment and adapt once you have a workspace to build.
# ---------------------------------------------------------------------------
# COPY ros_ws/ /root/ros_ws/
# RUN source /opt/ros/humble/setup.bash \
#     && cd /root/ros_ws \
#     && colcon build --symlink-install

# Entrypoint sources ROS and drops into the requested command.
COPY ros_entrypoint.sh /ros_entrypoint.sh
RUN chmod +x /ros_entrypoint.sh
ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["bash"]
