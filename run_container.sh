#!/bin/bash
# Launch the humble_base container with a shell.
#
#   ./run_container.sh                    -> interactive bash
#   ./run_container.sh ros2 topic list    -> run one command and exit
#
# --network host / --ipc host are required for DDS discovery to reach machines
# outside this box (multicast does not cross Docker's bridge network, and the
# shared-memory transport needs the host IPC namespace).
#
# --user runs the container as you rather than root, so files created inside it
# (colcon build/, install/, log/, __pycache__) stay owned by you on the host and
# do not need sudo to delete. This requires HOME to point at the mounted home --
# the image's default /root is not writable by uid 1000.
#
# /etc/passwd is mounted read-only only so the shell prompt shows your username
# instead of "I have no name!"; the container gains nothing from it.
set -e

IMAGE="${IMAGE:-humble_base:test}"

# Held in an array rather than a backslash-continued command so each flag can
# carry its own comment (a trailing comment is a syntax error after a '\').
DOCKER_ARGS=(
    -it                             # interactive + TTY, so you get a usable shell
    --rm                            # delete the container on exit; nothing accumulates
    --network host                  # Use host network interfaces
    --ipc host                      # Fast DDS shared-memory transport needs the host IPC ns
    --user "$(id -u):$(id -g)"      # run as you, not root -> no sudo to delete created files
    -v /etc/passwd:/etc/passwd:ro   # cosmetic: gives uid 1000 a name, so the prompt isn't "I have no name!"
    -v "$HOME:$HOME"                # your whole home, at the same path inside and out
    -e HOME="$HOME"                 # image default is /root, which uid 1000 cannot write
    -w "$HOME"                      # start in your home instead of /
)

exec docker run "${DOCKER_ARGS[@]}" "$IMAGE" "$@"
