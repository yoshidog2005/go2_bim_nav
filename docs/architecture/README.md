# Architecture overview

A rough, high-level map of how `go2_bim_nav` fits together. The diagrams are
Mermaid; GitHub and VS Code (with a Mermaid extension) render them inline.

The system has three phases:

1. **Offline map generation** on a workstation: IFC (BIM) model → 2D occupancy grid.
2. **Container build/startup** on the Go2's Jetson: Docker image with ROS 2 Humble + Nav2 + this package.
3. **Runtime navigation** on the dog: Nav2 localizes against the BIM map, plans, and drives the robot through the Unitree Sport API.

---

## 1. End-to-end

```mermaid
flowchart LR
    subgraph WS["Workstation (plain Python, no ROS)"]
        IFC[("model.ifc<br/>(BIM)")]
        I2M["ifc_to_map.py"]
        PREV["preview_map.py"]
        LS["list_spaces.py"]
        MAP[("bim_map.pgm<br/>+ bim_map.yaml")]
        WP[("waypoints.yaml")]
        IFC --> I2M --> MAP
        MAP --> PREV
        IFC --> LS -->|room centroids| WP
    end

    subgraph DOG["Go2 Jetson (Docker container, ROS 2 Humble, domain 1)"]
        LAUNCH["bim_nav_bringup.launch.py"]
        NAV2["Nav2 stack"]
        GOAL["send_goal"]
        BRIDGE["cmd_vel_bridge"]
    end

    ROBOT[["Go2 firmware / MCU"]]

    MAP -->|scp| LAUNCH
    WP -->|scp| GOAL
    LAUNCH --> NAV2
    GOAL -->|NavigateToPose action| NAV2
    NAV2 -->|/cmd_vel| BRIDGE
    BRIDGE -->|/api/sport/request| ROBOT
    ROBOT -->|lidar cloud + odometry| NAV2
```

---

## 2. Offline: IFC → occupancy map (`ifc_to_map.py`)

```mermaid
flowchart TD
    A["Open IFC with IfcOpenShell"] --> B["Select element types<br/>(IfcWall, IfcColumn, IfcRailing,<br/>IfcStairFlight, IfcCurtainWall, IfcPlate)"]
    B --> C{"--storey given?"}
    C -- yes --> D["Keep only elements on that storey"]
    C -- no --> E["Keep all storeys"]
    D --> F["Triangulate each element in world coords"]
    E --> F
    F --> G["Project triangles to XY and<br/>rasterise as OCCUPIED (0)"]
    G --> H{"--no-clear-doors?"}
    H -- no (default) --> I["Carve each IfcDoor's padded<br/>bounding box back to FREE (254)"]
    H -- yes --> J
    I --> J["Write .pgm image + .yaml<br/>(resolution, origin, thresholds)"]
```

Deliberately left out of the static map: slabs/ceilings/roofs (would blank
out whole rooms), doors (open/closed state unknown), and furniture (moves).
Anything not in the BIM is left for the live lidar obstacle layer.

---

## 3. Container build and startup

```mermaid
flowchart TD
    subgraph BUILD["docker build (Dockerfile)"]
        B0["Base: dustynv/ros:humble-desktop-l4t-r35.3.1<br/>(Ubuntu 20.04, ROS 2 Humble from source)"]
        B1["apt system libs + pip requirements.txt"]
        B2["unitree_sdk2_python<br/>(CycloneDDS, talks to MCU)"]
        B3["Nav2 + pointcloud_to_laserscan<br/>built from source into /opt/nav2_ws<br/>(skipped if base already has them)"]
        B4["rosdep for go2_bim_nav package.xml,<br/>check required ROS pkgs exist,<br/>colcon build go2_bim_nav"]
        B0 --> B1 --> B2 --> B3 --> B4
    end

    subgraph RUN["./run_container.sh"]
        R0["docker run --network host --ipc host<br/>--user you, mount $HOME, nvidia runtime, X11"]
        R1["ros_entrypoint.sh sources, in order:<br/>ROS Humble → /opt/nav2_ws →<br/>$UNITREE_ROS2_WS (refused if Foxy-built) →<br/>~/bim_nav_ws (or /root fallback)"]
        R2["export ROS_DOMAIN_ID=1<br/>warn if any Foxy paths leaked in"]
        R3["bash --norc (or given command)"]
        R0 --> R1 --> R2 --> R3
    end

    BUILD --> RUN
```

### Two DDS networks side by side

```mermaid
flowchart LR
    MCU[["Go2 MCU<br/>motors, sensors, sport service"]]
    subgraph D0["CycloneDDS, domain 0, iface ethrobot"]
        SDK["unitree_sdk2py<br/>(examples/*, lidar_bridge.py)"]
        UR2["unitree_ros2 driver<br/>(unitree_api msgs)"]
    end
    subgraph D1["ROS 2 Fast DDS, domain 1"]
        NODES["go2_bim_nav + Nav2 nodes"]
        LAPTOP["Laptop / RViz<br/>(ROS_DOMAIN_ID=1)"]
    end
    MCU <--> SDK
    MCU <--> UR2
    SDK -->|republish via rclpy| NODES
    UR2 <--> NODES
    NODES <--> LAPTOP
```

---

## 4. Runtime: navigation data flow

Started by `ros2 launch go2_bim_nav bim_nav_bringup.launch.py map:=... lidar_cloud_topic:=...`.

```mermaid
flowchart LR
    subgraph SRC["Robot data sources"]
        LIDAR["Lidar PointCloud2<br/>(/utlidar/cloud, e.g. from lidar_bridge.py)"]
        ODOM["/utlidar/robot_odom<br/>(nav_msgs/Odometry)"]
    end

    subgraph PKG["go2_bim_nav launch"]
        P2L["pointcloud_to_laserscan<br/>slice 0.05–0.35 m → /scan"]
        O2T["odom_to_tf<br/>odom → base_link tf<br/>(use_odom_to_tf, default true)"]
        CVB["cmd_vel_bridge<br/>Twist → Sport API Move (1008)<br/>watchdog: StopMove (1003) after 0.5 s"]
    end

    subgraph NAV2["Nav2 (nav2_bringup, params: config/nav2_params.yaml)"]
        MS["map_server<br/>(BIM map)"]
        AMCL["amcl<br/>map → odom tf"]
        GC["global_costmap<br/>static(BIM) + obstacle(/scan) + inflation"]
        LC["local_costmap 6×6 m rolling<br/>obstacle(/scan) + inflation"]
        BT["bt_navigator<br/>navigate_to_pose"]
        PL["planner_server<br/>NavFn A*, no unknown space"]
        SM["smoother_server"]
        CTL["controller_server<br/>DWB local planner"]
        BEH["behavior_server<br/>spin / backup / wait"]
        VS["velocity_smoother"]
    end

    GOAL["send_goal<br/>--x --y --yaw or --waypoint"]
    RVIZ["RViz (optional, from laptop)<br/>2D Pose Estimate / Nav2 Goal"]
    SPORT[["/api/sport/request<br/>→ Go2 firmware"]]

    LIDAR --> P2L
    ODOM --> O2T
    ODOM --> CTL
    P2L -->|/scan| AMCL
    P2L -->|/scan| GC
    P2L -->|/scan| LC
    O2T -->|tf| AMCL
    MS -->|/map| AMCL
    MS -->|/map| GC

    GOAL -->|NavigateToPose| BT
    RVIZ -.-> BT
    RVIZ -.->|/initialpose| AMCL
    BT --> PL
    PL --> GC
    BT --> SM
    BT --> CTL
    BT --> BEH
    CTL --> LC
    CTL -->|cmd_vel_nav| VS
    VS -->|/cmd_vel| CVB
    CVB --> SPORT
```

### TF tree

```mermaid
flowchart LR
    MAPF["map"] -->|amcl| ODOMF["odom"] -->|odom_to_tf<br/>(or lidar_restamp.py)| BASE["base_link"]
```

### What happens when a goal is sent

```mermaid
sequenceDiagram
    participant U as send_goal
    participant BT as bt_navigator
    participant P as planner_server
    participant C as controller_server (DWB)
    participant V as velocity_smoother
    participant B as cmd_vel_bridge
    participant G as Go2 firmware

    U->>BT: NavigateToPose(x, y, yaw in map frame)
    BT->>P: compute path on global costmap (BIM + lidar)
    P-->>BT: path
    loop at 20 Hz until goal reached
        BT->>C: follow path
        C->>V: cmd_vel_nav (avoid live obstacles via local costmap)
        V->>B: /cmd_vel
        B->>G: Request api_id=1008 {"x","y","z"}
    end
    Note over BT,C: on failure: spin / backup / wait, then replan
    BT-->>U: SUCCEEDED → exit 0, otherwise exit 1
    Note over B,G: no /cmd_vel for 0.5 s → StopMove (1003)
```

---

## 5. File map

| Path | Role |
| --- | --- |
| `Dockerfile`, `requirements.txt` | Image: ROS 2 Humble (L4T), unitree_sdk2py, Nav2 from source, builds the package |
| `run_container.sh` | Runs the image with host networking, your user, mounted `$HOME`, GPU/X11 |
| `ros_entrypoint.sh` | Sources the workspaces in order and sets `ROS_DOMAIN_ID=1` |
| `examples/lidar_bridge.py` | Robot lidar (`rt/utlidar/cloud_base`, domain 0) → ROS `/utlidar/cloud` |
| `examples/pub_test.py` | ROS networking smoke test (`/chatter`) |
| `examples/obstacles_avoid/*` | Standalone unitree_sdk2py tests of the firmware's own move/avoid APIs (independent of Nav2) |
| `src/go2_bim_nav/go2_bim_nav/ifc_to_map.py` | IFC → `.pgm` + `.yaml` (workstation) |
| `src/go2_bim_nav/go2_bim_nav/preview_map.py` | Shows a generated map with a metre grid (workstation) |
| `src/go2_bim_nav/go2_bim_nav/list_spaces.py` | Prints `IfcSpace` centroids for waypoints (workstation) |
| `src/go2_bim_nav/go2_bim_nav/odom_to_tf.py` | `/utlidar/robot_odom` → `odom → base_link` tf |
| `src/go2_bim_nav/go2_bim_nav/cmd_vel_bridge.py` | `/cmd_vel` → Unitree Sport API, with stop watchdog |
| `src/go2_bim_nav/go2_bim_nav/send_goal.py` | `NavigateToPose` client (coordinates or named waypoint) |
| `src/go2_bim_nav/launch/bim_nav_bringup.launch.py` | Starts pointcloud_to_laserscan, odom_to_tf, cmd_vel_bridge, nav2_bringup |
| `src/go2_bim_nav/config/nav2_params.yaml` | AMCL, costmaps, planner, DWB, smoother, behaviors |
| `src/go2_bim_nav/config/waypoints.yaml` | Named goals `{x, y, yaw}` in the map frame |
| `src/go2_bim_nav/maps/` | `Project1.ifc` sample model and the generated `bim_map.*` |

## Loose ends noticed while mapping this

- The package `README.md`/`WALKTHROUGH.md` still describe ROS 2 **Foxy** on the host, while the Docker setup is **Humble** (and `nav2_params.yaml` has been updated for Humble).
- `WALKTHROUGH.md` refers to `lidar_restamp.py` (an alternative `odom → base_link` publisher, used with `use_odom_to_tf:=false`), but that script isn't in the repo.
- `cmd_vel_bridge` needs `unitree_api` from a Humble-built `unitree_ros2` workspace (`UNITREE_ROS2_WS`), which is not part of the image.
- The firmware's own obstacle avoidance (`SWITCHAVOIDMODE`, see `examples/obstacles_avoid`) is separate from Nav2's; nothing in the launch sets it either way.
