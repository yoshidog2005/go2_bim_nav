#!/usr/bin/env python3
"""
@author Brandon Lichter (Yoshidog)

Send a NavigateToPose goal to Nav2 - this is the "go here" input.

Everything else in this package (map, costmaps, planners) only reacts once
something calls the bt_navigator's navigate_to_pose action. This script is
that caller.

Usage:
    # raw coordinates in the map (BIM) frame, metres + radians
    ros2 run go2_bim_nav send_goal --x 3.5 --y 1.2 --yaw 0.0

    # named waypoint from a YAML file (see config/waypoints.yaml)
    ros2 run go2_bim_nav send_goal --waypoint kitchen \
        --waypoints-file /path/to/waypoints.yaml

Blocks until the robot reaches the goal, is aborted/canceled, or the
action server can't be reached, then exits (0 on success, 1 otherwise) -
suitable for calling from a shell script or a higher-level task node.
"""
import argparse
import math
import sys

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose

try:
    import yaml
except ImportError:
    yaml = None


def yaw_to_quaternion(yaw):
    return 0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)


class GoalSender(Node):
    def __init__(self):
        super().__init__('go2_bim_nav_goal_sender')
        self._client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self._feedback_count = 0

    def send(self, x, y, yaw, frame_id='map'):
        if not self._client.wait_for_server(timeout_sec=10.0):
            self.get_logger().error(
                "navigate_to_pose action server not available - is Nav2's "
                "bt_navigator running? (check 'ros2 launch go2_bim_nav "
                "bim_nav_bringup.launch.py' is up)"
            )
            return False

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = frame_id
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        _, _, qz, qw = yaw_to_quaternion(yaw)
        goal.pose.pose.orientation.z = qz
        goal.pose.pose.orientation.w = qw

        self.get_logger().info(f"Sending goal: x={x}, y={y}, yaw={yaw} (frame={frame_id})")
        send_future = self._client.send_goal_async(goal, feedback_callback=self._feedback_cb)
        rclpy.spin_until_future_complete(self, send_future)
        goal_handle = send_future.result()

        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().error("Goal was rejected by Nav2")
            return False

        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)
        status = result_future.result().status

        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info("Goal reached")
            return True
        self.get_logger().error(f"Navigation did not succeed (status={status})")
        return False

    def _feedback_cb(self, feedback_msg):
        # Throttled manually rather than relying on a specific rclpy logger
        # API version - log every ~10th feedback message instead of every one.
        self._feedback_count += 1
        if self._feedback_count % 10 != 0:
            return
        distance = getattr(feedback_msg.feedback, 'distance_remaining', None)
        if distance is not None:
            self.get_logger().info(f"Distance remaining: {distance:.2f} m")


def load_waypoint(waypoints_file, name):
    if yaml is None:
        print("PyYAML is required for --waypoint: pip3 install --user pyyaml",
              file=sys.stderr)
        sys.exit(1)
    with open(waypoints_file) as f:
        waypoints = yaml.safe_load(f) or {}
    if name not in waypoints:
        print(f"'{name}' not in {waypoints_file}. Known: {list(waypoints.keys())}",
              file=sys.stderr)
        sys.exit(1)
    wp = waypoints[name]
    return wp['x'], wp['y'], wp.get('yaw', 0.0)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--x', type=float, help='Target x in the map (BIM) frame, metres')
    parser.add_argument('--y', type=float, help='Target y in the map (BIM) frame, metres')
    parser.add_argument('--yaw', type=float, default=0.0, help='Target heading, radians')
    parser.add_argument('--frame-id', default='map')
    parser.add_argument('--waypoint', default=None, help='Named waypoint key from --waypoints-file')
    parser.add_argument('--waypoints-file', default=None, help='YAML file of name: {x, y, yaw}')
    args = parser.parse_args()

    if args.waypoint:
        if not args.waypoints_file:
            print("--waypoint requires --waypoints-file", file=sys.stderr)
            sys.exit(1)
        x, y, yaw = load_waypoint(args.waypoints_file, args.waypoint)
    elif args.x is not None and args.y is not None:
        x, y, yaw = args.x, args.y, args.yaw
    else:
        print("Provide either --x/--y or --waypoint (with --waypoints-file)", file=sys.stderr)
        sys.exit(1)

    rclpy.init()
    node = GoalSender()
    ok = node.send(x, y, yaw, args.frame_id)
    node.destroy_node()
    rclpy.shutdown()
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
