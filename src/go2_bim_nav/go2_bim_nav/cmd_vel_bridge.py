#!/usr/bin/env python3
"""
@author Brandon Lichter (Yoshidog)

Bridge Nav2's /cmd_vel (geometry_msgs/msg/Twist) to the Go2's native
Sport API (/api/sport/request, unitree_api/msg/Request).

This is NOT a guessed schema - it's a direct translation of this robot's
own /home/unitree/unitree_ros2/example/src/{include,src}/common/
ros2_sport_client.{h,cpp}:

    const int32_t ROBOT_SPORT_API_ID_MOVE = 1008;
    const int32_t ROBOT_SPORT_API_ID_STOPMOVE = 1003;

    void SportClient::Move(Request &req, float vx, float vy, float vyaw) {
      nlohmann::json js;
      js["x"] = vx; js["y"] = vy; js["z"] = vyaw;
      req.parameter = js.dump();
      req.header.identity.api_id = ROBOT_SPORT_API_ID_MOVE;
      req_puber_->publish(req);
    }

Requires unitree_ros2's workspace to be built AND sourced (for the
unitree_api message package) in the same shell as this one - source
unitree_ros2's install/setup.bash BEFORE this package's, every time.

Usage:
    ros2 run go2_bim_nav cmd_vel_bridge
"""
import json

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist

try:
    from unitree_api.msg import Request
except ImportError as e:
    raise ImportError(
        "unitree_api message package not found. Source unitree_ros2's "
        "install/setup.bash (before this package's own) in this shell, "
        "then try again."
    ) from e

ROBOT_SPORT_API_ID_STOPMOVE = 1003
ROBOT_SPORT_API_ID_MOVE = 1008

# How long without a new /cmd_vel before this bridge stops the robot on its
# own, rather than trusting a stale velocity command indefinitely - guards
# against Nav2 (or this bridge's own upstream) dying mid-motion.
WATCHDOG_TIMEOUT_SEC = 0.5
WATCHDOG_CHECK_PERIOD_SEC = 0.1


class CmdVelBridge(Node):
    def __init__(self):
        super().__init__('cmd_vel_to_sport_bridge')
        self._pub = self.create_publisher(Request, '/api/sport/request', 10)
        self._sub = self.create_subscription(Twist, '/cmd_vel', self._on_cmd_vel, 10)
        self._last_msg_time = None
        self._stopped = True  # avoid re-sending StopMove every tick once already stopped
        self.create_timer(WATCHDOG_CHECK_PERIOD_SEC, self._check_watchdog)
        self.get_logger().info(
            'cmd_vel -> /api/sport/request bridge up '
            '(Move api_id=1008, parameter={"x","y","z"})'
        )

    def _on_cmd_vel(self, msg: Twist):
        self._last_msg_time = self.get_clock().now()
        self._publish_move(msg.linear.x, msg.linear.y, msg.angular.z)
        self._stopped = (msg.linear.x == 0.0 and msg.linear.y == 0.0 and msg.angular.z == 0.0)

    def _publish_move(self, vx, vy, vyaw):
        req = Request()
        req.header.identity.api_id = ROBOT_SPORT_API_ID_MOVE
        req.parameter = json.dumps({"x": vx, "y": vy, "z": vyaw})
        self._pub.publish(req)

    def _publish_stop(self):
        req = Request()
        req.header.identity.api_id = ROBOT_SPORT_API_ID_STOPMOVE
        self._pub.publish(req)

    def _check_watchdog(self):
        if self._last_msg_time is None or self._stopped:
            return
        age_sec = (self.get_clock().now() - self._last_msg_time).nanoseconds / 1e9
        if age_sec > WATCHDOG_TIMEOUT_SEC:
            self.get_logger().warn(f'No /cmd_vel for {age_sec:.2f}s - sending StopMove')
            self._publish_stop()
            self._stopped = True


def main():
    rclpy.init()
    node = CmdVelBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._publish_stop()  # don't leave the robot moving if this node dies
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
