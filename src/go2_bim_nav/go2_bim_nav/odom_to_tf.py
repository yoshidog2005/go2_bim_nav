#!/usr/bin/env python3
"""Broadcast /utlidar/robot_odom (nav_msgs/msg/Odometry) as a real
odom -> base_link tf transform.

Confirmed directly from this robot (ros2 topic echo /utlidar/robot_odom):
the message already carries header.frame_id=odom, child_frame_id=base_link
- exactly the frame names the rest of this package's config assumes
everywhere (amcl, both costmaps). The native driver publishes this data as
a plain topic but never broadcasts it as tf, and AMCL/costmaps need actual
tf, not just the topic - this node is a straight broadcast of what's
already there, not a remap or a guess at different frame names.

Usage:
    ros2 run go2_bim_nav odom_to_tf
"""
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster


class OdomToTf(Node):
    def __init__(self):
        super().__init__('odom_to_tf_broadcaster')
        self._broadcaster = TransformBroadcaster(self)
        # sensor-data QoS (best-effort) so this subscribes regardless of
        # whether the upstream publisher is reliable or best-effort -
        # a reliable-only subscription can silently receive nothing at
        # all if the publisher is best-effort, with no error either way.
        self._sub = self.create_subscription(
            Odometry, '/utlidar/robot_odom', self._on_odom, qos_profile_sensor_data
        )
        self.get_logger().info(
            'Broadcasting /utlidar/robot_odom as odom -> base_link tf'
        )

    def _on_odom(self, msg: Odometry):
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()  # instead of msg.header.stamp
        t.header.frame_id = msg.header.frame_id       # "odom"
        t.child_frame_id = msg.child_frame_id          # "base_link"
        t.transform.translation.x = msg.pose.pose.position.x
        t.transform.translation.y = msg.pose.pose.position.y
        t.transform.translation.z = msg.pose.pose.position.z
        t.transform.rotation = msg.pose.pose.orientation
        self._broadcaster.sendTransform(t)


def main():
    rclpy.init()
    node = OdomToTf()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
