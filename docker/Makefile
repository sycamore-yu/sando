.PHONY: build build-ampl build-no-cache run-demo run-interactive run-mac-interactive shell preflight stop \
        run-static-easy run-static-medium run-static-hard run-dynamic-easy \
        run-dynamic-medium run-dynamic-hard run-unknown-easy \
        run-unknown-medium run-unknown-hard

UNAME_S := $(shell uname -s)
ROOT_DIR := $(abspath $(CURDIR)/..)
ifeq ($(UNAME_S),Darwin)
PLATFORM_FLAG = --platform linux/amd64
else
PLATFORM_FLAG =
endif

IMAGE ?= sando-ampl
GPU ?= true
ifeq ($(GPU),true)
GPU_FLAGS = --gpus all --env=NVIDIA_DRIVER_CAPABILITIES=all
else
GPU_FLAGS =
endif

AMPL_UUID_FILE ?= $(HOME)/.config/ampl/uuid
RESULTS_DIR ?= $(CURDIR)/results
BUILD_JOBS ?= 2
SCENARIO ?= static_easy
ROS_DOMAIN_ID ?= 42
GAZEBO_MASTER_URI ?= http://127.0.0.1:11346
NUM_OBSTACLES ?= 50
DYNAMIC_RATIO ?= 0.65
SOURCE_COMMIT ?= $(shell git -C "$(ROOT_DIR)" rev-parse HEAD 2>/dev/null || echo unknown)
SANDO_AMPL_MODE ?= persistent
SANDO_AMPL_VERIFY_UPDATES ?= 0
SANDO_AMPL_TRACE ?= 0
CONTAINER_NAME ?= sando-ampl-session

build:
	docker build $(PLATFORM_FLAG) -f "$(ROOT_DIR)/docker/Dockerfile.ampl" -t $(IMAGE) \
		--build-arg BUILD_JOBS=$(BUILD_JOBS) --build-arg SANDO_SOURCE_COMMIT=$(SOURCE_COMMIT) "$(ROOT_DIR)"

build-ampl: build

build-no-cache:
	docker build $(PLATFORM_FLAG) --no-cache -f "$(ROOT_DIR)/docker/Dockerfile.ampl" -t $(IMAGE) \
		--build-arg BUILD_JOBS=$(BUILD_JOBS) --build-arg SANDO_SOURCE_COMMIT=$(SOURCE_COMMIT) "$(ROOT_DIR)"

define RUN_IMAGE
	@test -r "$(AMPL_UUID_FILE)" || { echo "Set AMPL_UUID_FILE to a readable UUID file" >&2; exit 64; }
	@mkdir -p "$(RESULTS_DIR)"
	@container_name_flags=""; if [ -n "$(CONTAINER_NAME)" ]; then container_name_flags="--name $(CONTAINER_NAME)"; fi; \
	if [ -n "$$DISPLAY" ]; then \
		xhost +si:localuser:root || exit $$?; trap 'xhost -si:localuser:root' EXIT; \
		docker run -it --rm $(GPU_FLAGS) --privileged --network=host \
			--env=QT_X11_NO_MITSHM=1 --env=DISPLAY=$$DISPLAY \
			--env=GAZEBO_MASTER_URI=$(GAZEBO_MASTER_URI) --env=ROS_DOMAIN_ID=$(ROS_DOMAIN_ID) --env=SANDO_AMPL_MODE=$(SANDO_AMPL_MODE) --env=SANDO_AMPL_VERIFY_UPDATES=$(SANDO_AMPL_VERIFY_UPDATES) --env=SANDO_AMPL_TRACE=$(SANDO_AMPL_TRACE) \
			--volume=/tmp/.X11-unix:/tmp/.X11-unix:ro \
			--mount=type=bind,src=$(AMPL_UUID_FILE),dst=/run/secrets/ampl_uuid,readonly \
			$$container_name_flags --volume=$(RESULTS_DIR):/results $(1) $(IMAGE) $(2); \
	else \
		docker run -it --rm $(GPU_FLAGS) --privileged --network=host --env=HEADLESS=1 \
			--env=GAZEBO_MASTER_URI=$(GAZEBO_MASTER_URI) --env=ROS_DOMAIN_ID=$(ROS_DOMAIN_ID) --env=SANDO_AMPL_MODE=$(SANDO_AMPL_MODE) --env=SANDO_AMPL_VERIFY_UPDATES=$(SANDO_AMPL_VERIFY_UPDATES) --env=SANDO_AMPL_TRACE=$(SANDO_AMPL_TRACE) \
			--mount=type=bind,src=$(AMPL_UUID_FILE),dst=/run/secrets/ampl_uuid,readonly \
			$$container_name_flags --volume=$(RESULTS_DIR):/results $(1) $(IMAGE) $(2); \
	fi
endef

run-demo:
	$(call RUN_IMAGE,-e MODE=demo -e SCENARIO=$(SCENARIO),)

run-interactive:
	$(call RUN_IMAGE,-e MODE=interactive -e NUM_OBSTACLES=$(NUM_OBSTACLES) -e DYNAMIC_RATIO=$(DYNAMIC_RATIO),)

stop:
	docker stop $(CONTAINER_NAME)

run-mac-interactive:
	docker run $(PLATFORM_FLAG) -it --rm --privileged \
		--env=USE_XPRA=true --env=MODE=interactive \
		--env=NUM_OBSTACLES=$(NUM_OBSTACLES) --env=DYNAMIC_RATIO=$(DYNAMIC_RATIO) \
		--env=GAZEBO_MASTER_URI=$(GAZEBO_MASTER_URI) --env=ROS_DOMAIN_ID=$(ROS_DOMAIN_ID) --env=SANDO_AMPL_MODE=$(SANDO_AMPL_MODE) --env=SANDO_AMPL_VERIFY_UPDATES=$(SANDO_AMPL_VERIFY_UPDATES) --env=SANDO_AMPL_TRACE=$(SANDO_AMPL_TRACE) \
		--publish=8080:8080 --mount=type=bind,src=$(AMPL_UUID_FILE),dst=/run/secrets/ampl_uuid,readonly \
		$(if $(CONTAINER_NAME),--name $(CONTAINER_NAME)) --volume=$(RESULTS_DIR):/results $(IMAGE)

shell:
	$(call RUN_IMAGE,,/bin/bash)

preflight: build
	docker run --rm --mount=type=bind,src=$(AMPL_UUID_FILE),dst=/run/secrets/ampl_uuid,readonly $(IMAGE) \
		bash -lc 'cmake -S /root/sando_ws/src/sando/tests/ampls -B /tmp/ampls-preflight -DAMPLS_ROOT=/opt/ampls-api -DGUROBI_ROOT=/opt/ampls-api/libs/gurobi -DAMPL_EXECUTABLE=$$AMPL_BASE_BIN/ampl && cmake --build /tmp/ampls-preflight --target ampls_real_preflight -j$(BUILD_JOBS) && ctest --test-dir /tmp/ampls-preflight --output-on-failure'
	docker run --rm --mount=type=bind,src=$(AMPL_UUID_FILE),dst=/run/secrets/ampl_uuid,readonly $(IMAGE) \
		bash -lc 'source /opt/ros/humble/setup.bash && source /root/sando_ws/install/setup.bash && ctest --test-dir /root/sando_ws/build/sando --output-on-failure && ctest --test-dir /root/sando_ws/build/sando --repeat until-fail:20 -R "^ampl_cold_concurrent_start$$" --output-on-failure'

run-static-easy:
	$(MAKE) run-demo SCENARIO=static_easy
run-static-medium:
	$(MAKE) run-demo SCENARIO=static_medium
run-static-hard:
	$(MAKE) run-demo SCENARIO=static_hard
run-dynamic-easy:
	$(MAKE) run-demo SCENARIO=dynamic_easy
run-dynamic-medium:
	$(MAKE) run-demo SCENARIO=dynamic_medium
run-dynamic-hard:
	$(MAKE) run-demo SCENARIO=dynamic_hard
run-unknown-easy:
	$(MAKE) run-demo SCENARIO=unknown_dynamic_easy
run-unknown-medium:
	$(MAKE) run-demo SCENARIO=unknown_dynamic_medium
run-unknown-hard:
	$(MAKE) run-demo SCENARIO=unknown_dynamic_hard
