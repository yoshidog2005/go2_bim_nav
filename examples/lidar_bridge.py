#!/usr/bin/env python3
"""
Bridge the Go2's LiDAR point cloud from the robot's CycloneDDS bus onto ROS 2.

Two independent DDS stacks live in this one process, and that separation is the
whole point:

  robot side   unitree_sdk2py -> CycloneDDS, domain 0, bound to `ethrobot`
                 (the wired link to the Go2 MCU; topic rt/utlidar/cloud_base)
  ROS side     rclpy -> Fast DDS, $ROS_DOMAIN_ID
                 (where your laptop / other machines listen)

The robot side is pinned by ChannelFactoryInitialize's networkInterface
argument: the SDK turns it into a CycloneDDS <NetworkInterface name="..."/>
config, so that participant only ever uses ethrobot.

The ROS side is left on its defaults deliberately. Forcing Fast DDS onto one
interface takes an XML profile with an interfaceWhiteList, and a participant
configured that way is not discoverable by normally-configured ROS nodes -- so
every other node, including ros2 CLI tools, would need the same profile. Not
worth it: ROS traffic already leaves over wlan0 because that is where the
default route points.

They cannot interfere: different libraries, different domains, different config
mechanisms. That only holds while ROS uses Fast DDS. Do NOT set
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp here -- the SDK writes its config with
<Domain Id="any">, so it would capture the ROS participant too and pin your ROS
traffic to ethrobot.

Usage (inside the container, which must be run with --network host):

    ./lidar_bridge.py

Everything below is a fixed property of this robot, so it is a constant rather
than a command-line flag. The one thing worth changing at runtime is the output
topic, and ROS 2 already has a standard way to do that -- no custom flag needed:

    ./lidar_bridge.py --ros-args -r /utlidar/cloud:=/go2/points
"""

import array
import sys
import threading
import time

ROBOT_IFACE = "ethrobot"              # wired link to the Go2 MCU
ROBOT_DOMAIN = 0                      # CycloneDDS domain the MCU publishes on
IN_TOPIC = "rt/utlidar/cloud_base"    # robot-side DDS topic
OUT_TOPIC = "/utlidar/cloud"          # ROS 2 topic (remap with --ros-args -r)
QUEUE_DEPTH = 10                      # SDK reader queue; decouples the DDS thread

# ---------------------------------------------------------------------------
# Message conversion
#
# The Unitree IDL type and sensor_msgs/PointCloud2 are the same message -- the
# SDK's is just a separately generated copy. So this is a field-for-field copy
# with no interpretation of the payload: every field the LiDAR publishes
# (intensity, ring, time, ...) survives, not only xyz.
# ---------------------------------------------------------------------------


def to_ros_cloud(msg, PointCloud2, PointField, clock):
    out = PointCloud2()

    # Arrival time, not capture time: the MCU->bridge transit (~3 ms mean, ~7 ms
    # p95 against a 66 ms frame period) lands in the stamp as error. Small enough
    # not to matter here, and it sidesteps the MCU clock being minutes off from
    # this host's. If you ever need true capture time, measure that offset at
    # startup and apply msg.header.stamp + offset instead.
    out.header.stamp = clock.now().to_msg()

    out.header.frame_id = msg.header.frame_id
    out.height = msg.height
    out.width = msg.width
    out.fields = [
        PointField(name=f.name, offset=f.offset, datatype=f.datatype, count=f.count)
        for f in msg.fields
    ]
    out.is_bigendian = msg.is_bigendian
    out.point_step = msg.point_step
    out.row_step = msg.row_step
    # array('B', ...) hits rosidl's fast path. Assigning bytes or a list would
    # make it validate every element in turn -- noticeable on a full cloud.
    out.data = array.array("B", bytes(msg.data))
    out.is_dense = msg.is_dense
    return out


def main() -> int:
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import QoSPresetProfiles
    from sensor_msgs.msg import PointCloud2, PointField

    from unitree_sdk2py.core.channel import ChannelSubscriber, ChannelFactoryInitialize
    from unitree_sdk2py.idl.sensor_msgs.msg.dds_ import PointCloud2_

    # args=sys.argv so `--ros-args -r <from>:=<to>` works without a custom flag.
    rclpy.init(args=sys.argv)
    node = Node("go2_lidar_bridge")

    # SENSOR_DATA (best effort, keep last): the right default for a 15 Hz sensor
    # over wifi -- a dropped cloud is better than a stalled publisher.
    pub = node.create_publisher(PointCloud2, OUT_TOPIC,
                                QoSPresetProfiles.SENSOR_DATA.value)

    clock = node.get_clock()
    count = 0
    lock = threading.Lock()

    def on_cloud(msg: PointCloud2_) -> None:
        # Runs on the SDK's reader thread (queue depth > 0 keeps the DDS
        # callback thread free). It is the only thread that publishes.
        nonlocal count
        try:
            pub.publish(to_ros_cloud(msg, PointCloud2, PointField, clock))
        except Exception as exc:  # a bad frame should not kill the bridge
            node.get_logger().error(f"dropping frame: {exc}")
            return

        with lock:
            count += 1
            n = count

        if n == 1:
            # Report the MCU/host clock skew once, as a diagnostic: it is the
            # reason these clouds are restamped rather than passed through.
            skew = time.time() - (msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9)
            node.get_logger().info(
                f"MCU clock is {skew:+.1f}s from this host's; restamping with ROS time")
        if n == 1 or n % 100 == 0:
            node.get_logger().info(
                f"forwarded {n} clouds (last: {msg.width * msg.height} points, "
                f"frame '{msg.header.frame_id}')")

    ChannelFactoryInitialize(ROBOT_DOMAIN, ROBOT_IFACE)
    sub = ChannelSubscriber(IN_TOPIC, PointCloud2_)
    sub.Init(on_cloud, QUEUE_DEPTH)
    node.get_logger().info(
        f"bridging {IN_TOPIC} (domain {ROBOT_DOMAIN}, {ROBOT_IFACE}) "
        f"-> {pub.topic_name}")

    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        # Ctrl-C, or SIGTERM from `docker stop`. Both are a normal exit.
        pass
    finally:
        sub.Close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
