import time
import sys

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.go2.obstacles_avoid.obstacles_avoid_client import ObstaclesAvoidClient

NAV_TIMEOUT = 15.0 # seconds to wait for arrival before giving up

def enable_obstacle_avoidance(client: ObstaclesAvoidClient, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        code, enabled = client.SwitchGet()
        if code == 0 and enabled:
            return True
        client.SwitchSet(True)
        time.sleep(0.1)
    return False

def prompt_goal() -> tuple:
    while True:
        try:
            raw = input("\nEnter target  x  y  yaw  (metres, metres, radians) or 'q' to quit: ").strip()
            if raw.lower() == 'q':
                return None
            parts = raw.split()
            if len(parts) != 3:
                print("  Need exactly 3 values, e.g.:  1.0 0.0 0.0")
                continue
            return float(parts[0]), float(parts[1]), float(parts[2])
        except ValueError:
            print("  Invalid input — use numbers only.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        ChannelFactoryInitialize(0, sys.argv[1])
    else:
        ChannelFactoryInitialize(0)

    client = ObstaclesAvoidClient()
    client.SetTimeout(3.0)
    client.Init()

    try:
        print("Enabling obstacle avoidance...")
        if not enable_obstacle_avoidance(client):
            print("ERROR: obstacle avoidance service did not respond. Is the dog standing?")
            sys.exit(1)
        print("Obstacle avoidance ON")

        print("Taking API control...")
        client.UseRemoteCommandFromApi(True)
        time.sleep(0.3)

        while True:
            goal = prompt_goal()
            if goal is None:
                print("Quitting.")
                break

            x, y, yaw = goal
            print(f"Navigating to x={x}, y={y}, yaw={yaw}...")
            client.MoveToAbsolutePosition(x, y, yaw)

            print(f"Waiting up to {NAV_TIMEOUT:.0f}s for arrival (Ctrl+C to abort)...")
            time.sleep(NAV_TIMEOUT)
            print("Ready for next goal.")

    except KeyboardInterrupt:
        print("\nAborted by user.")

    finally:
        client.Move(0.0, 0.0, 0.0)
        client.UseRemoteCommandFromApi(False)
        print("API control released.")
