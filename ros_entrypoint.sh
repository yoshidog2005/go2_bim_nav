#!/bin/bash
# Entrypoint for humble_base.
# Sources the ROS 2 Humble environment, plus the project workspace if present,
# then execs whatever command was passed (defaults to bash via the Dockerfile CMD).
set -e

# ROS 2 Humble
source /opt/ros/humble/install/setup.bash

# Nav2 overlay (exists only if the Dockerfile had to build Nav2 from source)
[ -f /opt/nav2_ws/install/setup.bash ] && source /opt/nav2_ws/install/setup.bash

# unitree_ros2 (provides unitree_api) - only if you set UNITREE_ROS2_WS at run time
[ -n "$UNITREE_ROS2_WS" ] && [ -f "$UNITREE_ROS2_WS/install/setup.bash" ] && source "$UNITREE_ROS2_WS/install/setup.bash"

# go2_bim_nav - must come after unitree_ros2
[ -f /root/bim_nav_ws/install/setup.bash ] && source /root/bim_nav_ws/install/setup.bash

# Project overlay workspace (only if it was built into the image)
if [ -f /root/ros_ws/install/setup.bash ]; then
    source /root/ros_ws/install/setup.bash
fi

export ROS_DOMAIN_ID=1

exec "$@"