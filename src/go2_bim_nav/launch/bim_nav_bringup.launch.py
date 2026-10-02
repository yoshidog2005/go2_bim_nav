
"""
@author Brandon Lichter (Yoshidog)

Launch file for the BIM navigation system.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
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
    use_odom_to_tf = LaunchConfiguration('use_odom_to_tf')

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

    declare_lidar_topic = DeclareLaunchArgument(
        'lidar_cloud_topic',
        default_value='/utlidar/cloud',
        description=(
            "Go2 3D lidar PointCloud2 topic - VERIFY this against whatever "
            "ROS2 driver you're running (unitree_ros2 / go2_ros2_sdk / other "
            "community driver); topic names differ between them."
        ),
    )

    declare_scan_topic = DeclareLaunchArgument(
        'scan_topic',
        default_value='/scan',
        description='2D LaserScan topic produced from the lidar cloud for AMCL + costmaps',
    )

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time', default_value='false', description='Use simulation clock if true'
    )

    declare_use_odom_to_tf = DeclareLaunchArgument(
        'use_odom_to_tf',
        default_value='true',
        description=(
            "Set to 'false' if something else already broadcasts odom -> "
            "base_link tf (e.g. lidar_restamp.py run with publish_odom_tf:="
            "true on a robot with a broken firmware clock) - running both "
            "at once double-publishes the same transform."
        ),
    )

    # The Go2's lidar is a 3D point cloud. AMCL and the 2D costmap layers in
    # this config expect a 2D LaserScan, so slice a horizontal band out of
    # the cloud. min/max height are relative to base_link - tune these to
    # sit above the ground/legs and below head height for your mounting.
    pointcloud_to_scan = Node(
        package='pointcloud_to_laserscan',
        executable='pointcloud_to_laserscan_node',
        name='pointcloud_to_laserscan',
        remappings=[('cloud_in', lidar_cloud_topic), ('scan', scan_topic)],
        parameters=[{
            'target_frame': 'base_link',
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
    )

    # This robot's native driver publishes odometry as a plain topic but
    # never broadcasts it as tf - AMCL and both costmaps need actual tf.
    # Confirmed directly from /utlidar/robot_odom: it already carries
    # frame_id=odom, child_frame_id=base_link, matching this config
    # throughout, so this is a straight broadcast, not a remap.
    odom_to_tf = Node(
        package='go2_bim_nav',
        executable='odom_to_tf',
        name='odom_to_tf_broadcaster',
        output='screen',
        condition=IfCondition(use_odom_to_tf),
    )

    # Nav2's controller_server publishes velocity commands to /cmd_vel as a
    # plain geometry_msgs/Twist - this robot's native driver doesn't listen
    # there at all, it takes commands via a request/response API instead.
    # This bridge translates each Twist into the Go2's actual Move command
    # (unitree_api/msg/Request, api_id=1008), built directly from this
    # robot's own ros2_sport_client.cpp, not a guessed schema. Requires
    # unitree_ros2's workspace sourced (for the unitree_api message
    # package) BEFORE this one, in the same shell.
    cmd_vel_bridge = Node(
        package='go2_bim_nav',
        executable='cmd_vel_bridge',
        name='cmd_vel_to_sport_bridge',
        output='screen',
    )

    # Reuses nav2_bringup's standard bringup (map_server, amcl, controller,
    # planner, recoveries, bt_navigator, lifecycle managers) rather than
    # reimplementing lifecycle management here.
    nav2_bringup_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_bringup_share, 'launch', 'bringup_launch.py')
        ),
        launch_arguments={
            'map': map_yaml,
            'params_file': params_file,
            'use_sim_time': use_sim_time,
            'autostart': 'true',
        }.items(),
    )

    return LaunchDescription([
        declare_map,
        declare_params,
        declare_lidar_topic,
        declare_scan_topic,
        declare_use_sim_time,
        declare_use_odom_to_tf,
        pointcloud_to_scan,
        odom_to_tf,
        cmd_vel_bridge,
        nav2_bringup_launch,
    ])