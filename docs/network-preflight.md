# Live network preflight

NetworkManager reporting `connected` proves only link state. Installation is
allowed only when all of these independent checks pass:

1. NetworkManager link state
2. IPv4 address configuration
3. DNS resolution for `archlinux.org`
4. CA-validated TLS to `archlinux.org`
5. HTTPS response from Arch Linux
6. HTTPS response from the official Arch package mirror
7. HTTPS response from the Omarchy bootstrap site
8. NetworkManager does not report a captive portal

Any negative or unavailable result is an install-blocking state. The UI should
suggest wired ethernet, interactive Wi-Fi, or USB phone tethering and rerun the
entire preflight after the connection changes.

Wi-Fi credentials are never accepted from the USB handoff. `nmcli --ask` and
`nmtui` run with inherited terminal I/O, so a password is neither placed in argv
nor captured in ordinary process output. Supplying a password in a programmatic
profile is rejected before command execution. Diagnostics record only stage
status and boolean readiness, never prompt responses.
