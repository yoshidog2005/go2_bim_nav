#!/usr/bin/env python3
"""
@author Brandon Lichter (Yoshidog)

Convert an initial pose given in BIM coordinates into the FAST-LIO `map`
frame the PC's localizer expects on /initialpose.

Why this exists: Nav2 plans in the `bim` frame, so RViz (fixed frame `bim`)
and humans naturally give poses in BIM coordinates. The localizer on the PC,
however, treats /initialpose as a pose in its own `map` frame. Feeding it a
BIM pose directly would put the robot's estimate in the wrong place by the
whole bim <-> map alignment (a ~4.5 m shift and ~10.7 deg rotation).

This node listens on /initialpose_bim, looks up the live TF from the pose's
frame to `map` (so the alignment lives in exactly one place - the static
bim -> map transform in the launch file), and republishes on /initialpose.

It deliberately uses a DIFFERENT input topic than its output: reading and
writing /initialpose would loop, and the localizer would also see the
unconverted pose first.

Usage:
  * RViz (fixed frame `bim`): point the "2D Pose Estimate" tool at /initialpose_bim.
  * Command line:
      ros2 topic pub --once /initialpose_bim geometry_msgs/msg/PoseWithCovarianceStamped \\
        "{header: {frame_id: bim}, pose: {pose: {position: {x: 3.0, y: 1.0}, orientation: {z: 0.0, w: 1.0}}}}"

A pose already in the `map` frame is forwarded unchanged.
"""
import math
import sys

import rclpy
from rclpy.node import Node
from rclpy.time import Time
from geometry_msgs.msg import PoseWithCovarianceStamped
from tf2_ros import Buffer, TransformException, TransformListener


# ---- small pure-python rigid-transform helpers (no tf2_geometry_msgs version
# ---- differences to worry about); quaternions are (x, y, z, w) -------------

def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def quat_normalize(q):
    n = math.sqrt(sum(c * c for c in q))
    if n < 1e-6:
        return (0.0, 0.0, 0.0, 1.0)  # unset/zero quaternion -> identity
    return tuple(c / n for c in q)


def quat_rotate(q, v):
    x, y, z, w = q
    r = quat_mul(quat_mul(q, (v[0], v[1], v[2], 0.0)), (-x, -y, -z, w))
    return r[0], r[1], r[2]


def quat_yaw(q):
    x, y, z, w = q
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def transform_pose(tf_translation, tf_rotation, position, orientation):
    """Express a pose given in frame S in frame T, where (tf_translation,
    tf_rotation) is the transform that takes points from S to T (what
    tf2's lookup_transform(T, S) returns)."""
    q_tf = quat_normalize(tf_rotation)
    q_pose = quat_normalize(orientation)
    rx, ry, rz = quat_rotate(q_tf, position)
    new_pos = (rx + tf_translation[0], ry + tf_translation[1], rz + tf_translation[2])
    new_q = quat_normalize(quat_mul(q_tf, q_pose))
    return new_pos, new_q


class InitialPoseBimToMap(Node):
    def __init__(self):
        super().__init__('initialpose_bim_to_map')
        self.declare_parameter('in_topic', '/initialpose_bim')
        self.declare_parameter('out_topic', '/initialpose')
        self.declare_parameter('target_frame', 'map')
        in_topic = self.get_parameter('in_topic').value
        out_topic = self.get_parameter('out_topic').value
        self._target = self.get_parameter('target_frame').value

        self._buffer = Buffer()
        self._listener = TransformListener(self._buffer, self)
        self._pub = self.create_publisher(PoseWithCovarianceStamped, out_topic, 10)
        self.create_subscription(PoseWithCovarianceStamped, in_topic, self._on_pose, 10)
        self.get_logger().info(
            f'{in_topic} (any frame with a TF path to {self._target}) -> {out_topic} ({self._target})')

    def _on_pose(self, msg):
        src = msg.header.frame_id or self._target
        out = PoseWithCovarianceStamped()
        out.header.stamp = msg.header.stamp
        out.header.frame_id = self._target
        out.pose.covariance = msg.pose.covariance  # RViz's default xy covariance is isotropic, so
                                                   # rotating it would change nothing

        p = msg.pose.pose
        if src == self._target:
            out.pose.pose = p
            self._pub.publish(out)
            self.get_logger().info(f'forwarded pose already in {self._target}')
            return

        try:
            # timeout 0 on purpose: waiting inside a callback would block the
            # executor that delivers the TF messages being waited for.
            tf = self._buffer.lookup_transform(self._target, src, Time())
        except TransformException as exc:
            self.get_logger().error(
                f'No TF {self._target} <- {src} yet ({exc}); initial pose NOT sent. '
                f'Is the bim -> map static transform running?')
            return

        t, r = tf.transform.translation, tf.transform.rotation
        pos, q = transform_pose(
            (t.x, t.y, t.z), (r.x, r.y, r.z, r.w),
            (p.position.x, p.position.y, p.position.z),
            (p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w))

        out.pose.pose.position.x, out.pose.pose.position.y, out.pose.pose.position.z = pos
        (out.pose.pose.orientation.x, out.pose.pose.orientation.y,
         out.pose.pose.orientation.z, out.pose.pose.orientation.w) = q
        self._pub.publish(out)

        src_yaw = quat_yaw((p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w))
        self.get_logger().info(
            f'{src} ({p.position.x:.2f}, {p.position.y:.2f}, yaw {src_yaw:.3f}) -> '
            f'{self._target} ({pos[0]:.2f}, {pos[1]:.2f}, yaw {quat_yaw(q):.3f})')


def main():
    rclpy.init(args=sys.argv)
    node = InitialPoseBimToMap()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
