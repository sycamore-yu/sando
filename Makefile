.PHONY: build build-ampl build-no-cache run-demo run-interactive run-mac-interactive shell preflight stop

build build-ampl build-no-cache run-demo run-interactive run-mac-interactive shell preflight \
run-static-easy run-static-medium run-static-hard run-dynamic-easy stop \
run-dynamic-medium run-dynamic-hard run-unknown-easy run-unknown-medium \
run-unknown-hard:
	$(MAKE) -C docker $@
