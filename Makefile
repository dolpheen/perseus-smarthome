SHELL := /bin/bash
.DEFAULT_GOAL := help

help:                ## Print this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / \
	  {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:             ## Script install on this host (idempotent)
	sudo ./scripts/install.sh install

upgrade:             ## Re-deploy code and restart the service on this host
	sudo ./scripts/install.sh upgrade

uninstall:           ## Stop service, remove unit. Use PURGE=1 to also remove /opt/raspberry-smarthome
	sudo ./scripts/install.sh uninstall $(if $(PURGE),--purge,)

status:              ## Print service status and reachability
	./scripts/install.sh status

remote-install:      ## Run install over SSH from this Mac (uses .env)
	./scripts/remote-install.sh install

remote-upgrade:      ## Run upgrade over SSH from this Mac (uses .env)
	./scripts/remote-install.sh upgrade

remote-uninstall:    ## Run uninstall over SSH. Use PURGE=1 to also wipe /opt/raspberry-smarthome
	./scripts/remote-install.sh uninstall $(if $(PURGE),--purge,)

remote-status:       ## Print remote service status (uses .env)
	./scripts/remote-install.sh status

deb:                 ## Build .deb (must run on armv7l Pi)
	./packaging/build-deb.sh

deb-install:         ## apt install the most recent built .deb
	sudo apt install -y ./dist/perseus-smarthome_*_armhf.deb

deb-uninstall:       ## apt remove the package (keeps config)
	sudo apt remove -y perseus-smarthome

deb-purge:           ## apt purge the package (removes /opt/raspberry-smarthome)
	sudo apt purge -y perseus-smarthome

clean:               ## Remove build artifacts
	rm -rf _build dist

test:                ## Run unit tests (excluding e2e and hardware)
	uv run pytest -m "not e2e and not hardware"

.PHONY: help install upgrade uninstall status \
        remote-install remote-upgrade remote-uninstall remote-status \
        deb deb-install deb-uninstall deb-purge clean test
