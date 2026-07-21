# Omarchy first-login contract

Omarchy starts only after the base installation and target validation marker
exist and the target non-root user opens an interactive login shell. The profile
hook launches `/usr/local/bin/omarchy-first-login`, which enters the installed
Python module.

The launcher verifies the release-paired HTTPS source hash before execution,
uses a real pseudo-terminal, stores only an output transcript, and records
source/version/hash/provenance in atomic user-owned state. A partial attempt does
not retry automatically. The user must review it and explicitly request one
retry. Independent Omarchy and boot-policy markers are both required before the
overall completion marker is created.
