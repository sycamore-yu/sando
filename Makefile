.PHONY: build build-ampl build-no-cache run-demo run-interactive run-mac-interactive shell preflight

build build-ampl build-no-cache run-demo run-interactive run-mac-interactive shell preflight \
run-static-easy run-static-medium run-static-hard run-dynamic-easy \
run-dynamic-medium run-dynamic-hard run-unknown-easy run-unknown-medium \
run-unknown-hard:
	$(MAKE) -C docker $@
