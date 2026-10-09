"""
@author Brandon Lichter (Yoshidog)

Launch file for the BIM navigation system (Docker / Nav2 on the Go2).

Localization is EXTERNAL. FAST-LIO + open3d_loc on the PC provide:
    map -> odom                                          global localization (3D map)
    odom -> camera_init -> body -> imu_link -> base_link FAST-LIO odometry (TF)
    /odom                                                nav_msgs/Odometry, odom -> base_link, with twist
So this launch runs NO AMCL, NO odom_to_tf, and uses nothing from the Go2's
leg odometry (which under-counts distance by ~15 %).

Nav2 plans in the BIM frame. A fixed bim -> map alignment is published here
(from the FAST-LIO handoff's align_map_to_bim result), so:
    * goals given in BIM coordinates need no conversion (send_goal --frame-id bim)
    * initial poses given in BIM coordinates are converted to `map` for the
      localizer by initialpose_bim_to_map (publish them on /initialpose_bim)

TF tree:   bim -> map -> odom -> ... -> base_link
Exactly one node may publish each link: do not also run odom_to_tf or any
other bim -> map publisher.
"""

import os
import sys

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription
from launch.conditions import LaunchConfigurationEquals
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory('go2_bim_nav')
    nav2_bringup_share = get_package_share_directory('nav2_bringup')

    map_yaml = LaunchConfiguration('map')
    params_file = LaunchConfiguration('params_file')
    lidar_cloud_topic = LaunchConfiguration('lidar_cloud_topic')
    scan_topic = LaunchConfiguration('scan_topic')
    use_sim_time = LaunchConfiguration('use_sim_time')
    bim_x = LaunchConfiguration('bim_x')
    bim_y = LaunchConfiguration('bim_y')
    bim_z = LaunchConfiguration('bim_z')
    bim_yaw = LaunchConfiguration('bim_yaw')

    declare_map = DeclareLaunchArgument(
        'map',
        default_value=os.path.join(pkg_share, 'maps', 'bim_map.yaml'),
        description="Full path to the BIM-derived map yaml, from 'ros2 run go2_bim_nav ifc_to_map'",
    )

    declare_params = DeclareLaunchArgument(
        'params_file',
        default_value=os.path.join(pkg_share, 'config', 'nav2_params.yaml'),
        description='Full path to the Nav2 params file',
    )

    declare_scan_source = DeclareLaunchArgument(
        'scan_source',
        default_value='local',
        description=(
            "'local': this launch bridges the Go2's L1 lidar (lidar_bridge) and slices "
            "/scan from it. 'external': /scan already arrives from the PC (FAST-LIO "
            "MID360 scan) - nothing lidar-related is started here. Never run both: "
            "two publishers on /scan."
        ),
    )

    declare_lidar_topic = DeclareLaunchArgument(
        'lidar_cloud_topic',
        default_value='/utlidar/cloud',
        description="PointCloud2 topic published by lidar_bridge (scan_source:=local only)",
    )

    declare_scan_topic = DeclareLaunchArgument(
        'scan_topic',
        default_value='/scan_2d',
        description=("2D LaserScan topic used by the costmaps. Must match the 'topic:' of the "
                     "obstacle layers in nav2_params.yaml. Not /scan: the PC publishes a "
                     "PointCloud2 there."),
    )

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time', default_value='false', description='Use simulation clock if true'
    )

    # Pose of the `map` frame (FAST-LIO's 3D-map frame) expressed in the `bim`
    # frame - the result of align_map_to_bim.py. Defaults are from the FAST-LIO
    # handoff's bim_alignment.yaml; REPLACE them if the 3D map is re-made or the
    # alignment is re-run.
    declare_bim_x = DeclareLaunchArgument('bim_x', default_value='-4.501',
                                          description='map origin x in the bim frame, metres')
    declare_bim_y = DeclareLaunchArgument('bim_y', default_value='-0.331',
                                          description='map origin y in the bim frame, metres')
    declare_bim_z = DeclareLaunchArgument('bim_z', default_value='0.326',
                                          description='map origin z in the bim frame, metres')
    declare_bim_yaw = DeclareLaunchArgument('bim_yaw', default_value='0.18748',
                                            description='map yaw in the bim frame, radians')

    # bim -> map: parent `bim`, child `map`; the numbers are the pose of `map`
    # in `bim` (same meaning as the handoff's static_transform_publisher call).
    bim_to_map = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='bim_to_map_static_tf',
        arguments=[
            '--x', bim_x, '--y', bim_y, '--z', bim_z,
            '--yaw', bim_yaw, '--pitch', '0', '--roll', '0',
            '--frame-id', 'bim', '--child-frame-id', 'map',
        ],
        output='screen',
    )

    # Converts an initial pose given in BIM coordinates (/initialpose_bim, e.g.
    # RViz with fixed frame `bim`) into the localizer's `map` frame and
    # publishes it on /initialpose. Run as a module so no setup.py entry point
    # is required; sys.executable keeps it on the same Python as ros2 launch.
    initialpose_converter = ExecuteProcess(
        cmd=[sys.executable, '-m', 'go2_bim_nav.initialpose_bim_to_map'],
        name='initialpose_bim_to_map',
        output='screen',
    )

    # ---- scan_source:=local - the Go2's L1 lidar via lidar_bridge -----------
    # Bridges the Go2's LiDAR from the robot's CycloneDDS bus (unitree_sdk2py,
    # domain 0, ethrobot) onto ROS 2 (Fast DDS, $ROS_DOMAIN_ID) as a
    # sensor_msgs/PointCloud2. Run as a module (no setup.py entry point needed);
    # the remap ties its output topic to the lidar_cloud_topic argument.
    lidar_bridge = ExecuteProcess(
        cmd=[sys.executable, '-m', 'go2_bim_nav.lidar_bridge',
             '--ros-args', '-r', ['/utlidar/cloud:=', lidar_cloud_topic]],
        name='go2_lidar_bridge',
        output='screen',
        condition=LaunchConfigurationEquals('scan_source', 'local'),
    )

    # The costmaps expect a 2D LaserScan, so slice a horizontal band out of
    # the bridge's cloud. min/max height are relative to base_link - tune
    # these to sit above the ground/legs and below head height. Needs a TF path
    # from the cloud's frame to base_link (the PC's FAST-LIO chain provides
    # base_link; the L1's own frame needs a static transform to it).
    pointcloud_to_scan = Node(
        package='pointcloud_to_laserscan',
        executable='pointcloud_to_laserscan_node',
        name='pointcloud_to_laserscan',
        remappings=[('cloud_in', lidar_cloud_topic), ('scan', scan_topic)],
        parameters=[{
            'target_frame': 'base_link',
            'transform_tolerance': 0.5,
            'min_height': 0.05,     # TUNE: above legs/ground clutter
            'max_height': 0.35,     # TUNE: below any overhanging structure you want ignored
            'angle_min': -3.14159,
            'angle_max': 3.14159,
            'angle_increment': 0.0087,
            'scan_time': 0.1,
            'range_min': 0.15,
            'range_max': 12.0,
            'use_inf': True,
            'use_sim_time': use_sim_time,
        }],
        output='screen',
        condition=LaunchConfigurationEquals('scan_source', 'local'),
    )

    # Nav2 (via velocity_smoother) publishes velocity commands to /cmd_vel as a
    # plain geometry_msgs/Twist. This bridge forwards them to the Go2 through
    # unitree_sdk2py's ObstaclesAvoidClient.Move() (CycloneDDS, domain 0,
    # ethrobot), with a watchdog, hard velocity ceilings, and API control
    # released on exit. Because it talks to the robot through the SDK rather
    # than a ROS topic, ROS_DOMAIN_ID does not affect it. While it runs, the
    # dog takes commands from here rather than the handheld remote's sticks.
    cmd_vel_bridge = Node(
        package='go2_bim_nav',
        executable='cmd_vel_bridge',
        name='cmd_vel_to_sdk_bridge',
        output='screen',
    )

    # The BIM map, published in the `bim` frame (frame_id comes from the params
    # file). Own map_server + lifecycle manager because nav2_bringup's
    # bringup_launch.py would also start AMCL, which must not run here.
    map_server = Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        output='screen',
        parameters=[params_file, {'yaml_filename': map_yaml, 'use_sim_time': use_sim_time}],
    )

    lifecycle_manager_map = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_map',
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'autostart': True,
            'node_names': ['map_server'],
        }],
    )

    # Navigation half of nav2_bringup only (controller, planner, smoother,
    # behaviors, bt_navigator, waypoint_follower, velocity_smoother + their
    # lifecycle manager). No localization half -> no AMCL.
    nav2_navigation_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_bringup_share, 'launch', 'navigation_launch.py')
        ),
        launch_arguments={
            'params_file': params_file,
            'use_sim_time': use_sim_time,
            'autostart': 'true',
        }.items(),
    )

    return LaunchDescription([
        declare_map,
        declare_params,
        declare_scan_source,
        declare_lidar_topic,
        declare_scan_topic,
        declare_use_sim_time,
        declare_bim_x,
        declare_bim_y,
        declare_bim_z,
        declare_bim_yaw,
        bim_to_map,
        initialpose_converter,
        lidar_bridge,
        pointcloud_to_scan,
        cmd_vel_bridge,
        map_server,
        lifecycle_manager_map,
        nav2_navigation_launch,
    ])