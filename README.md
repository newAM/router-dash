# Router Dash

A dashboard for my router.

Router Dash displays the DHCPv4 leases of my [Kea] DHCP server, with OIDC for
authorization and authentication.

## Technology

- Language: [Python](https://www.python.org)
- Web framework: [Flask](https://flask.palletsprojects.com)
- WSGI server: [Gunicorn](https://gunicorn.org)
- Session management: [Flask-Session](https://flask-session.readthedocs.io)
- OIDC / OAuth2 client: [Authlib](https://authlib.org)
- CSRF protection: [Flask-WTF](https://flask-wtf.readthedocs.io)
- HTTP client: [Requests](https://requests.readthedocs.io)
- DHCP server: [Kea](https://kea.readthedocs.io)

## Configuration

This is designed to work with [NixOS], and will only be supported for NixOS.
However, it should work on any Linux distro with systemd.

Reference the NixOS module (`nixos/module.nix`) for configuration options.

You also need a Kea DHCP server with the HTTP control socket enabled, see
[Kea configuration](#kea-configuration) below.

## Development

The nix development shell provides all required packages.
Load the nix development shell with:

- `nix develop`
- Automatically with [`nix-direnv`](https://github.com/nix-community/nix-direnv)

### Running checks

Run these commands from the repository root:

- `pytest`
- `ruff check .`
- `ruff format --check .`
- `ty check .`

Running `nix flake check -L` builds all packages and runs the full test suite
including end-to-end NixOS tests.

### Interactive VM for manual end to end testing

The NixOS test spins up a fully provisioned VM with kanidm (OIDC), kea (DHCP),
and router-dash already configured, which is the easiest way to test the full
login flow without setting up your own SSO provider.

From your host, add this line to `/etc/hosts`:

```
127.0.0.1 router-dash.home.arpa kanidm.home.arpa
```

Start the interactive VM with port forwarding:

```bash
QEMU_NET_OPTS="hostfwd=tcp::10443-:10443,hostfwd=tcp::20443-:20443" nix run .#checks.x86_64-linux.nixos-basic.driverInteractive
```

This drops you into a Python REPL. Boot the machines:

```python
start_all()
```

To get a shell on the VM run this command in the REPL,
or log in as `root` with no password at the VM login prompt.

```python
server.shell_interact()
```

To get a usable password for the kanidm `testuser`, run inside the VM:

```bash
kanidmd recover-account testuser 2>&1 | grep -oP '[A-Za-z0-9]{48}'
```

Then visit `https://router-dash.home.arpa:10443`. Kanidm is at
`https://kanidm.home.arpa:20443`.

## AI disclosure

This project was built with extensive assistance of AI coding agents.

[NixOS]: https://nixos.org
[nginx]: https://nginx.org
[Kea]: https://kea.readthedocs.io
