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

IMAGE="${IMAGE:-humble_desktop:test}"

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
    # GUI apps (rviz2). The container runs as your uid with your $HOME mounted at
    # the same path, so your existing ~/.Xauthority cookie is already valid --
    # no 'xhost +' needed. --runtime nvidia gives OGRE the Jetson GPU; without it
    # rviz falls back to software GL and crawls.
    -e DISPLAY                      # which X server to draw on
    -e XAUTHORITY="$HOME/.Xauthority"
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw
    --runtime nvidia
    # --user drops every supplementary group, so the container loses 'video'
    # (gid 44), which owns /dev/nvmap and /dev/nvhost-*. Without these the Jetson
    # GPU is unreachable and rviz dies with:
    #   NvRmMemInitNvmap failed with Permission denied ... Segmentation fault
    # Numeric gids are used because the container's /etc/group need not agree
    # with the host's naming; the kernel checks the number.
    --group-add 44                  # video
    --group-add 103                 # render
)

exec docker run "${DOCKER_ARGS[@]}" "$IMAGE" "$@"
