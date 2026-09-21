#!/usr/bin/env python3
"""
Publish "hello world" on /chatter at 1 Hz.

A smoke test for the ROS 2 side of the container: if another machine can see
this topic, DDS discovery and transport are working, and any problem with a
real bridge is in the bridge rather than the network.

    ./pub_test.py
    ./pub_test.py --ros-args -r /chatter:=/other   # standard ROS remapping

Listen from anywhere on the same ROS_DOMAIN_ID:

    ros2 topic echo /chatter
"""

import sys

TOPIC = "/chatter"
PERIOD_S = 1.0
TEXT = "hello world"


def main() -> int:
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from std_msgs.msg import String

    rclpy.init(args=sys.argv)
    node = Node("pub_test")
    pub = node.create_publisher(String, TOPIC, 10)

    count = 0

    def tick() -> None:
        nonlocal count
        count += 1
        msg = String(data=f"{TEXT} {count}")
        pub.publish(msg)
        node.get_logger().info(f"published: {msg.data}")

    node.create_timer(PERIOD_S, tick)
    node.get_logger().info(f"publishing '{TEXT}' on {pub.topic_name} every {PERIOD_S}s")

    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        # Ctrl-C, or SIGTERM from `docker stop`. Both are a normal exit.
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
