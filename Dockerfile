# humble_base
# Ubuntu 20.04 + ROS 2 Humble (built from source) + Python 3.8, NVIDIA Jetson (L4T R35.3.1)
# Target: Unitree Go2 Jetson (aarch64). Build context: /home/unitree/bim_nav_ws
#
#   bim_nav_ws/
#     Dockerfile  requirements.txt  ros_entrypoint.sh
#     src/go2_bim_nav/   (package.xml, setup.py, launch/, config/, maps/, ...)
#
# Build:  cd /home/unitree/bim_nav_ws && docker build -t humble_base .
#
# NOTE: ROS lives under /opt/ros/humble/install/ in a MERGED layout and apt
# sources point at 'focal', so ros-humble-* Debian packages are NOT installable
# and `rosdep install` cannot resolve ROS packages via apt. Everything ROS-side
# that is missing must be built from source (see the Nav2 step).
FROM dustynv/ros:humble-desktop-l4t-r35.3.1

SHELL ["/bin/bash", "-c"]
ARG DEBIAN_FRONTEND=noninteractive
# Jetson-friendly build parallelism for the from-source steps (raise if you have RAM).
ARG BUILD_JOBS=2

# --- Refresh ROS apt signing key (base image predates the June-2025 rotation) ---
RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
        -o /usr/share/keyrings/ros-archive-keyring.gpg

# --- System packages (plain Ubuntu only) ---
#   libompl-dev / libgraphicsmagick++1-dev / libboost-dev / libeigen3-dev:
#     system libraries needed to compile Nav2 from source on focal.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git iproute2 iputils-ping net-tools vim tmux less \
        libompl-dev libgraphicsmagick++1-dev libboost-dev libeigen3-dev uuid-dev \
    && rm -rf /var/lib/apt/lists/*

# --- Python dependencies (everything pinned in requirements.txt) ---
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# --- Unitree SDK2 Python (talks to the Go2 MCU over CycloneDDS) ---
# If this fails with "Could not locate cyclonedds": find / -name "libddsc.so*"
# and point CYCLONEDDS_HOME at the prefix containing lib/libddsc.so.
ENV CYCLONEDDS_HOME=/opt/ros/humble/install
RUN git clone https://github.com/unitreerobotics/unitree_sdk2_python.git /opt/unitree_sdk2_python \
    && cd /opt/unitree_sdk2_python \
    && pip3 install --no-cache-dir .

# --- DDS / runtime defaults (interface, domain, peers are set at RUN time) ---
ENV RMW_IMPLEMENTATION=rmw_fastrtps_cpp
ENV FASTRTPS_DEFAULT_PROFILES_FILE=/home/unitree/bim_nav_ws/fastdds_wifi.xml
# Ignore host ~/.local site-packages (run_container.sh mounts $HOME).
ENV PYTHONNOUSERSITE=1

# --- rosdep, initialised once (needs network at build time) ---
ENV ROS_DISTRO=humble
RUN (rosdep init || true) && rosdep update

# ---------------------------------------------------------------------------
# Nav2 (+ pointcloud_to_laserscan) from source, ONLY if the base lacks it.
# Built into the /opt/nav2_ws overlay and sourced by ros_entrypoint.sh.
# Packages whose system deps don't exist on focal (xsimd, nanoflann, gazebo, ompl key)
# or that aren't needed headless are COLCON_IGNOREd: nav2_system_tests, nav2_route,
# nav2_mppi_controller, nav2_smac_planner, nav2_rviz_plugins. diagnostics is built
# from source because nav2_lifecycle_manager needs diagnostic_updater.
# This step is the least-verified part: Humble on focal is unsupported, so if it
# errors, read the first failing package and tell me. System deps are resolved
# by rosdep, skipping every ROS package already present in the base image.
# ---------------------------------------------------------------------------
RUN source /opt/ros/humble/install/setup.bash && \
    if ros2 pkg prefix nav2_bringup >/dev/null 2>&1 && \
       ros2 pkg prefix pointcloud_to_laserscan >/dev/null 2>&1; then \
        echo "Nav2 + pointcloud_to_laserscan already in base image - skipping source build"; \
    else \
        mkdir -p /opt/nav2_ws/src && cd /opt/nav2_ws/src && \
        git clone --depth 1 -b humble   https://github.com/ros-planning/navigation2.git && \
        git clone --depth 1 -b 3.8.7    https://github.com/BehaviorTree/BehaviorTree.CPP.git && \
        git clone --depth 1 -b ros2     https://github.com/ros/bond_core.git && \
        git clone --depth 1 -b humble-devel https://github.com/ros/angles.git && \
        git clone --depth 1 -b humble   https://github.com/ros-perception/pointcloud_to_laserscan.git && \
        git clone --depth 1 -b ros2-humble https://github.com/ros/diagnostics.git && \
        for d in nav2_system_tests nav2_route nav2_mppi_controller nav2_smac_planner nav2_rviz_plugins; do \
            touch navigation2/$d/COLCON_IGNORE; \
        done && \
        cd /opt/nav2_ws && \
        apt-get update && \
        rosdep install --from-paths src --ignore-src -r -y \
            --dependency-types=build --dependency-types=buildtool --dependency-types=exec \
            --skip-keys "$(ros2 pkg list | tr '\n' ' ')" || true && \
        rm -rf /var/lib/apt/lists/* && \
        MAKEFLAGS="-j${BUILD_JOBS}" colcon build --symlink-install \
            --parallel-workers "${BUILD_JOBS}" \
            --packages-up-to nav2_bringup pointcloud_to_laserscan \
            --event-handlers console_cohesion+ \
            --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
        || { echo '=== NAV2 BUILD FAILED - stderr of failed packages ==='; \
             for f in /opt/nav2_ws/log/latest_build/*/stderr.log; do \
                 [ -s "$f" ] && { echo "--- $f"; tail -n 60 "$f"; }; \
             done; exit 1; }; \
    fi

# ---------------------------------------------------------------------------
# go2_bim_nav - driven by its package.xml.
# 1) Copy ONLY package.xml so the dependency layer is cached until it changes.
# 2) rosdep resolves what package.xml declares. ROS packages are skipped (they
#    come from the base image / Nav2 overlay above, not apt); only plain system
#    keys such as python3-yaml are installed.
# 3) Copy the full package and colcon build it.
# ---------------------------------------------------------------------------
WORKDIR /root/bim_nav_ws
COPY src/go2_bim_nav/package.xml src/go2_bim_nav/package.xml
RUN source /opt/ros/humble/install/setup.bash && \
    { [ ! -f /opt/nav2_ws/install/setup.bash ] || source /opt/nav2_ws/install/setup.bash; } && \
    apt-get update && \
    rosdep install --from-paths src --ignore-src -r -y \
        --dependency-types=build --dependency-types=buildtool --dependency-types=exec \
        --skip-keys "$(ros2 pkg list | tr '\n' ' ') ament_python" && \
    rm -rf /var/lib/apt/lists/*

COPY src/go2_bim_nav src/go2_bim_nav
# Fail the build early if a declared ROS dependency isn't actually available.
RUN source /opt/ros/humble/install/setup.bash && \
    { [ ! -f /opt/nav2_ws/install/setup.bash ] || source /opt/nav2_ws/install/setup.bash; } && \
    MISSING="" && \
    for p in nav2_bringup nav2_map_server nav2_amcl nav2_controller nav2_planner \
             nav2_behaviors nav2_bt_navigator nav2_costmap_2d nav2_lifecycle_manager \
             nav2_msgs nav2_navfn_planner nav2_waypoint_follower nav2_util \
             nav2_smoother nav2_velocity_smoother \
             pointcloud_to_laserscan tf2_ros tf2_geometry_msgs; do \
        ros2 pkg prefix "$p" >/dev/null 2>&1 || MISSING="$MISSING $p"; \
    done && \
    if [ -n "$MISSING" ]; then \
        echo "MISSING ROS PACKAGES:$MISSING"; \
        echo "--- /opt/nav2_ws/install:"; ls /opt/nav2_ws/install 2>&1 | head -50; \
        echo "--- nav2/pointcloud packages visible to ros2:"; ros2 pkg list | grep -E "nav2|pointcloud|diagnostic"; \
        echo "--- AMENT_PREFIX_PATH=$AMENT_PREFIX_PATH"; \
        exit 1; \
    fi && \
    colcon build --symlink-install --packages-select go2_bim_nav

# Entrypoint sources ROS -> Nav2 overlay -> unitree_ros2 -> this workspace, in that order.
COPY ros_entrypoint.sh /ros_entrypoint.sh
RUN chmod +x /ros_entrypoint.sh
ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["bash"]