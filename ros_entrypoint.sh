#!/bin/bash
# Entrypoint for humble_base.
# Sources ROS 2 Humble, Nav2 overlay, unitree_ros2 (Humble build only) and
# go2_bim_nav (in that order), then execs the given command (default: bash).
set -e

# ROS 2 Humble
source /opt/ros/humble/install/setup.bash

# Nav2 overlay (exists only if the Dockerfile had to build Nav2 from source)
[ -f /opt/nav2_ws/install/setup.bash ] && source /opt/nav2_ws/install/setup.bash

# unitree_ros2 (provides unitree_api) - HUMBLE build only. A workspace built
# against Foxy references /opt/ros/foxy in its setup scripts; skip it if so.
if [ -n "$UNITREE_ROS2_WS" ] && [ -f "$UNITREE_ROS2_WS/install/setup.bash" ]; then
    if grep -rqi foxy "$UNITREE_ROS2_WS/install/setup.bash" "$UNITREE_ROS2_WS/install/local_setup.bash" 2>/dev/null; then
        echo "[entrypoint] REFUSING to source $UNITREE_ROS2_WS: it was built against Foxy. Rebuild it inside this container." >&2
    else
        source "$UNITREE_ROS2_WS/install/setup.bash"
    fi
fi

# go2_bim_nav - must come after unitree_ros2.
# Prefer the mounted host workspace ($HOME/bim_nav_ws, where you colcon build
# inside the container). The copy baked into the image lives under /root,
# which is unreadable when running with --user, so it's only a fallback.
if [ -r "$HOME/bim_nav_ws/install/setup.bash" ]; then
    source "$HOME/bim_nav_ws/install/setup.bash"
elif [ -r /root/bim_nav_ws/install/setup.bash ]; then
    source /root/bim_nav_ws/install/setup.bash
fi

# Project overlay workspace (only if it was built into the image)
[ -r /root/ros_ws/install/setup.bash ] && source /root/ros_ws/install/setup.bash

# Domain 1 on purpose: keeps this stack off the dog's own (low-level) domain.
export ROS_DOMAIN_ID=1

# No Foxy anywhere. Warn loudly if any Foxy path leaked into the environment
# (mounted-$HOME dotfiles are the usual source).
if printenv AMENT_PREFIX_PATH CMAKE_PREFIX_PATH LD_LIBRARY_PATH PYTHONPATH PATH 2>/dev/null | grep -qi foxy; then
    echo "[entrypoint] WARNING: 'foxy' found in the environment - Foxy libs can crash Humble tools:" >&2
    printenv AMENT_PREFIX_PATH CMAKE_PREFIX_PATH LD_LIBRARY_PATH PYTHONPATH PATH | tr ':' '\n' | grep -i foxy >&2
fi

exec "$@"