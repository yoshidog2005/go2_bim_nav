import time
import sys
import threading

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.go2.obstacles_avoid.obstacles_avoid_client import ObstaclesAvoidClient

MOVE_DURATION  = 2.0   # seconds to apply each velocity command
KEEPALIVE_HZ   = 10    # how often (per second) to send the stop command while idle

def enable_obstacle_avoidance(client: ObstaclesAvoidClient, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        code, enabled = client.SwitchGet()
        if code == 0 and enabled:
            return True
        client.SwitchSet(True)
        time.sleep(0.1)
    return False

def prompt_velocity() -> tuple:
    while True:
        try:
            raw = input("\nEnter velocity  vx  vy  vyaw  (m/s, m/s, rad/s) or 'q' to quit: ").strip()
            if raw.lower() == 'q':
                return None
            parts = raw.split()
            if len(parts) != 3:
                print("  Need exactly 3 values, e.g.:  0.5 0.0 0.0")
                continue
            return float(parts[0]), float(parts[1]), float(parts[2])
        except ValueError:
            print("  Invalid input — use numbers only.")

def keepalive_loop(client: ObstaclesAvoidClient, stop_event: threading.Event):
    """Continuously sends zero velocity while waiting for the next command."""
    interval = 1.0 / KEEPALIVE_HZ
    while not stop_event.is_set():
        client.Move(0.0, 0.0, 0.0)
        time.sleep(interval)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        ChannelFactoryInitialize(0, sys.argv[1])
    else:
        ChannelFactoryInitialize(0)

    client = ObstaclesAvoidClient()
    client.SetTimeout(3.0)
    client.Init()

    stop_keepalive = threading.Event()
    keepalive_thread = threading.Thread(target=keepalive_loop, args=(client, stop_keepalive), daemon=True)

    try:
        print("Enabling obstacle avoidance...")
        if not enable_obstacle_avoidance(client):
            print("ERROR: obstacle avoidance service did not respond. Is the dog standing?")
            sys.exit(1)
        print("Obstacle avoidance ON")

        print("Taking API control...")
        client.UseRemoteCommandFromApi(True)
        time.sleep(0.3)

        print(f"Sending stop commands at {KEEPALIVE_HZ}Hz while idle.")
        keepalive_thread.start()

        while True:
            vel = prompt_velocity()
            if vel is None:
                print("Quitting.")
                break

            vx, vy, vyaw = vel

            # pause keepalive so it doesn't fight the move command
            stop_keepalive.set()
            keepalive_thread.join()

            print(f"Moving at vx={vx}, vy={vy}, vyaw={vyaw} for {MOVE_DURATION}s...")
            client.Move(vx, vy, vyaw)
            time.sleep(MOVE_DURATION)
            client.Move(0.0, 0.0, 0.0)
            print("Stopped. Resuming idle stop commands.")

            # restart keepalive
            stop_keepalive.clear()
            keepalive_thread = threading.Thread(target=keepalive_loop, args=(client, stop_keepalive), daemon=True)
            keepalive_thread.start()

    except KeyboardInterrupt:
        print("\nAborted by user.")

    finally:
        stop_keepalive.set()
        client.Move(0.0, 0.0, 0.0)
        client.UseRemoteCommandFromApi(False)
        print("API control released.")
