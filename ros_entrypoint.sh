#!/bin/bash
# Entrypoint for humble_base.
# Sources the ROS 2 Humble environment, plus the project workspace if present,
# then execs whatever command was passed (defaults to bash via the Dockerfile CMD).
set -e

# ROS 2 Humble
source /opt/ros/humble/install/setup.bash

# Project overlay workspace (only if it was built into the image)
if [ -f /root/ros_ws/install/setup.bash ]; then
    source /root/ros_ws/install/setup.bash
fi

export ROS_DOMAIN_ID=1

exec "$@"