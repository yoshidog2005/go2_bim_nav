#!/usr/bin/env python3
"""
@author Brandon Lichter (Yoshidog)

Bridge Nav2's /cmd_vel (geometry_msgs/msg/Twist) to the Go2 through
unitree_sdk2py's ObstaclesAvoidClient - the same calls used by the
test_vel_command.py script, run continuously.

Two independent DDS stacks live in this one process (same split as
lidar_bridge.py):

  robot side   unitree_sdk2py -> CycloneDDS, domain 0, bound to `ethrobot`
  ROS side     rclpy -> Fast DDS, $ROS_DOMAIN_ID

Do NOT set RMW_IMPLEMENTATION=rmw_cyclonedds_cpp here - the SDK's Cyclone
config would capture the ROS participant too (see lidar_bridge.py).

How it works:
  * On start: switch the dog's obstacle-avoidance service on, then take
    API control (UseRemoteCommandFromApi(True)) - exactly as the test
    scripts do. While this node runs, the dog takes commands from here,
    not from the handheld remote's sticks. Keep the remote in hand.
  * /cmd_vel callbacks only store the latest command. A dedicated sender
    thread owns every SDK call and sends Move() at a steady rate, so a
    slow RPC can never stall ROS callbacks.
  * Watchdog: if no /cmd_vel arrives for WATCHDOG_TIMEOUT_SEC the sender
    commands zero velocity on its own (and keeps sending zeros while idle,
    like the test script's keepalive).
  * Hard velocity ceilings (ROS params) are applied regardless of what
    Nav2 asks for.
  * On exit: stop sending, command zero, release API control.

Usage:
    ros2 run go2_bim_nav cmd_vel_bridge
    ros2 run go2_bim_nav cmd_vel_bridge --ros-args -p max_vx:=0.4
"""
import math
import sys
import threading
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from geometry_msgs.msg import Twist

ROBOT_IFACE = "ethrobot"      # wired link to the Go2 (same as lidar_bridge.py)
ROBOT_DOMAIN = 0              # CycloneDDS domain the robot uses
SDK_TIMEOUT_SEC = 3.0         # RPC timeout, as in the test scripts

# How long without a new /cmd_vel before this bridge stops the robot on its
# own - guards against Nav2 (or this bridge's upstream) dying mid-motion.
WATCHDOG_TIMEOUT_SEC = 0.5
ACTIVE_PERIOD_SEC = 0.05      # 20 Hz while moving (matches controller_frequency)
IDLE_PERIOD_SEC = 0.1         # 10 Hz of zero-velocity keepalive while idle


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


class CmdVelBridge(Node):
    def __init__(self, client):
        super().__init__('cmd_vel_to_sdk_bridge')
        self._client = client

        # Hard ceilings, independent of Nav2's own limits (mirrors the
        # velocity_smoother limits in nav2_params.yaml by default).
        self.declare_parameter('max_vx', 0.8)
        self.declare_parameter('min_vx', -0.4)
        self.declare_parameter('max_vy', 0.3)
        self.declare_parameter('max_vyaw', 1.0)
        # The test scripts always switch the dog's avoidance service on
        # before moving; keep that behaviour unless told otherwise.
        self.declare_parameter('enable_avoidance', True)

        self._max_vx = float(self.get_parameter('max_vx').value)
        self._min_vx = float(self.get_parameter('min_vx').value)
        self._max_vy = float(self.get_parameter('max_vy').value)
        self._max_vyaw = float(self.get_parameter('max_vyaw').value)

        self._lock = threading.Lock()
        self._cmd = (0.0, 0.0, 0.0)
        self._last_cmd_time = None  # time.monotonic() of newest /cmd_vel
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._send_loop, daemon=True)
        self._control_taken = False

        self._sub = self.create_subscription(Twist, '/cmd_vel', self._on_cmd_vel, 10)

    # ---- robot-side setup / teardown (main thread, before/after sender) ----

    def take_control(self, timeout=5.0):
        """Switch obstacle avoidance on, then take API control. False on failure."""
        if self.get_parameter('enable_avoidance').value:
            deadline = time.time() + timeout
            enabled_ok = False
            while time.time() < deadline:
                code, enabled = self._client.SwitchGet()
                if code == 0 and enabled:
                    enabled_ok = True
                    break
                self._client.SwitchSet(True)
                time.sleep(0.1)
            if not enabled_ok:
                self.get_logger().error(
                    'Obstacle avoidance service did not respond. Is the dog standing?')
                return False
            self.get_logger().info('Obstacle avoidance ON')

        self._client.UseRemoteCommandFromApi(True)
        self._control_taken = True
        time.sleep(0.3)
        self.get_logger().info('API control taken')
        return True

    def start(self):
        self._thread.start()
        self.get_logger().info(
            f'/cmd_vel -> ObstaclesAvoidClient.Move bridge up '
            f'(ceilings: vx[{self._min_vx}, {self._max_vx}] '
            f'vy +-{self._max_vy} vyaw +-{self._max_vyaw})')

    def shutdown(self):
        """Stop the sender, command zero, release control. Safe to call twice."""
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        try:
            for _ in range(3):  # a few zeros so one dropped message can't leave it moving
                self._client.Move(0.0, 0.0, 0.0)
                time.sleep(0.05)
            if self._control_taken:
                self._client.UseRemoteCommandFromApi(False)
                self._control_taken = False
                print('API control released.')
        except Exception as exc:
            print(f'error during shutdown: {exc}', file=sys.stderr)

    # ---- ROS side ----

    def _on_cmd_vel(self, msg: Twist):
        vx, vy, vyaw = msg.linear.x, msg.linear.y, msg.angular.z
        if not all(math.isfinite(v) for v in (vx, vy, vyaw)):
            vx = vy = vyaw = 0.0  # never forward NaN/inf to the robot
        cmd = (
            _clamp(vx, self._min_vx, self._max_vx),
            _clamp(vy, -self._max_vy, self._max_vy),
            _clamp(vyaw, -self._max_vyaw, self._max_vyaw),
        )
        with self._lock:
            self._cmd = cmd
            self._last_cmd_time = time.monotonic()

    # ---- sender thread: the only place SDK Move() is called while running ----

    def _send_loop(self):
        was_moving = False
        while not self._stop_event.is_set():
            with self._lock:
                cmd = self._cmd
                t = self._last_cmd_time
            fresh = t is not None and (time.monotonic() - t) <= WATCHDOG_TIMEOUT_SEC
            vx, vy, vyaw = cmd if fresh else (0.0, 0.0, 0.0)

            if was_moving and not fresh:
                self.get_logger().warn(
                    f'No /cmd_vel for {WATCHDOG_TIMEOUT_SEC:.1f}s - commanding stop')

            try:
                self._client.Move(vx, vy, vyaw)
            except Exception as exc:
                self.get_logger().error(f'Move failed: {exc}',
                                        throttle_duration_sec=2.0)

            moving = fresh and (vx != 0.0 or vy != 0.0 or vyaw != 0.0)
            was_moving = moving
            self._stop_event.wait(ACTIVE_PERIOD_SEC if moving else IDLE_PERIOD_SEC)


def main() -> int:
    # Imported here (as in lidar_bridge.py) so this module stays importable
    # on machines without the SDK.
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.go2.obstacles_avoid.obstacles_avoid_client import ObstaclesAvoidClient

    rclpy.init(args=sys.argv)

    ChannelFactoryInitialize(ROBOT_DOMAIN, ROBOT_IFACE)
    client = ObstaclesAvoidClient()
    client.SetTimeout(SDK_TIMEOUT_SEC)
    client.Init()

    node = CmdVelBridge(client)
    exit_code = 0
    try:
        if not node.take_control():
            exit_code = 1
        else:
            node.start()
            rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass  # Ctrl-C, or SIGINT/SIGTERM from launch / `docker stop`
    finally:
        node.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return exit_code


if __name__ == '__main__':
    sys.exit(main())