FROM ros:humble AS dependencies

LABEL Maintainer="Kota Kondo <kkondo@mit.edu>" \
      Description="Ubuntu 22.04, ROS2 Humble, and AMPLS for SANDO"

ENV ROS_DISTRO=humble \
    DEBIAN_FRONTEND=noninteractive \
    SANDO_WS=/root/sando_ws \
    LIVOX_WS=/root/livox_ws \
    AMPL_VENV=/opt/ampl-venv \
    AMPLS_ROOT=/opt/ampls-api
ARG BUILD_JOBS=2

RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
      git tmux vim wget curl unzip tmuxp make gdb ca-certificates \
      python3-venv python3-dev cmake build-essential swig xvfb \
      libgl1-mesa-glx libgl1-mesa-dri psmisc xpra && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-${ROS_DISTRO}-gazebo-ros-pkgs \
      ros-${ROS_DISTRO}-pcl-conversions \
      ros-${ROS_DISTRO}-example-interfaces \
      ros-${ROS_DISTRO}-pcl-ros \
      ros-${ROS_DISTRO}-rviz2 \
      ros-${ROS_DISTRO}-rviz-common \
      ros-${ROS_DISTRO}-rqt-gui \
      ros-${ROS_DISTRO}-rqt-gui-py \
      ros-${ROS_DISTRO}-tf2-tools \
      ros-${ROS_DISTRO}-tf-transformations \
      ros-${ROS_DISTRO}-desktop \
      ros-dev-tools \
      ros-${ROS_DISTRO}-gazebo-ros2-control \
      ros-${ROS_DISTRO}-xacro \
      libpcl-dev nlohmann-json3-dev && \
    rm -rf /var/lib/apt/lists/*

# Install pinned AMPL Python modules, AMPLS, and the Gurobi 13 public native
# libraries. No license is copied into the image; activation is runtime-only.
COPY scripts/install_ampls.sh /usr/local/bin/install_ampls.sh
RUN chmod 0755 /usr/local/bin/install_ampls.sh && /usr/local/bin/install_ampls.sh

ENV GUROBI_HOME=/opt/ampls-api/libs/gurobi \
    PATH=/opt/ampls-api/libs/gurobi/lib/linux64:${PATH} \
    LD_LIBRARY_PATH=/usr/local/lib:/opt/ampls-api/libs/ampls/linux64:/opt/ampls-api/libs/gurobi/lib/linux64

RUN mkdir -p ${SANDO_WS}/src
COPY deps ${SANDO_WS}/src/sando/deps

# Symlink deps for colcon package discovery (Livox packages are built below).
WORKDIR ${SANDO_WS}/src
RUN for d in sando/deps/*/; do \
      name=$(basename "$d"); \
      case "$name" in Livox-SDK2|livox_ros_driver2) continue;; esac; \
      [ ! -e "$name" ] && ln -s "$d" "$name"; \
    done

WORKDIR ${SANDO_WS}/src/sando/deps/Livox-SDK2
RUN mkdir -p build && cd build && cmake .. && make -j"${BUILD_JOBS:-2}" && make install

RUN mkdir -p ${LIVOX_WS}/src
WORKDIR ${LIVOX_WS}/src
RUN cp -r ${SANDO_WS}/src/sando/deps/livox_ros_driver2 livox_ros_driver2 && \
    cd livox_ros_driver2 && rm -f COLCON_IGNORE && \
    cp -f package_ROS2.xml package.xml && cp -rf launch_ROS2/ launch/
SHELL ["/bin/bash", "-c"]
WORKDIR ${LIVOX_WS}
RUN source /opt/ros/humble/setup.bash && \
    colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release -DROS_EDITION=ROS2 -DHUMBLE_ROS=humble

ENV MAKEFLAGS=-j${BUILD_JOBS}
WORKDIR ${SANDO_WS}
RUN source /opt/ros/humble/setup.bash && \
    colcon build --packages-select decomp_util --parallel-workers ${BUILD_JOBS} \
      --cmake-args -DCMAKE_BUILD_TYPE=Release
RUN source /opt/ros/humble/setup.bash && source ${SANDO_WS}/install/setup.bash && \
    colcon build --packages-ignore ros2_livox_simulation sando livox_ros_driver2 livox_sdk2 \
      --parallel-workers ${BUILD_JOBS} \
      --cmake-args -DCMAKE_BUILD_TYPE=Release
RUN source /opt/ros/humble/setup.bash && source ${SANDO_WS}/install/setup.bash && \
    source ${LIVOX_WS}/install/setup.bash && \
    colcon build --packages-select ros2_livox_simulation --parallel-workers ${BUILD_JOBS} \
      --cmake-args -DCMAKE_BUILD_TYPE=Release

# Keep this stage usable as a stable cache target while local adapter changes
# are compiled in the final stage below.
FROM dependencies AS final
ARG BUILD_JOBS=2
ARG SANDO_SOURCE_COMMIT=unknown
RUN mkdir -p ${SANDO_WS}/src
# The final image receives the complete local checkout; no remote SANDO clone.
COPY . ${SANDO_WS}/src/sando
RUN printf '%s\n' "${SANDO_SOURCE_COMMIT}" > /opt/sando-source.commit && \
    find ${SANDO_WS}/src/sando \
      -path '*/build' -prune -o -path '*/install' -prune -o \
      -path '*/log' -prune -o -type f -print | sort | xargs sha256sum \
      > /opt/sando-source.sha256
WORKDIR ${SANDO_WS}
RUN source /opt/ros/humble/setup.bash && source ${SANDO_WS}/install/setup.bash && \
    source ${LIVOX_WS}/install/setup.bash && \
    colcon build --packages-select sando --parallel-workers ${BUILD_JOBS} \
      --cmake-args -DCMAKE_BUILD_TYPE=Release -DSANDO_USE_AMPL=ON -DAMPLS_ROOT=${AMPLS_ROOT}

RUN echo 'pcm.!default { type plug; slave.pcm "null" }' >> /usr/share/alsa/alsa.conf
RUN echo "alias tks='tmux kill-server'" >> ~/.bashrc && \
    echo "alias roscd='cd ${SANDO_WS}'" >> ~/.bashrc && \
    echo "alias ss='source ${SANDO_WS}/install/setup.bash'" >> ~/.bashrc && \
    echo "alias cbd='cd ${SANDO_WS} && colcon build --packages-select sando && ss'" >> ~/.bashrc && \
    echo "alias cbps='cd ${SANDO_WS} && colcon build --packages-select'" >> ~/.bashrc

COPY docker/sando.sh /sando.sh
COPY docker/entrypoint_ampl.sh /entrypoint_ampl.sh
RUN chmod 0755 /sando.sh /entrypoint_ampl.sh
ENTRYPOINT ["/entrypoint_ampl.sh"]
