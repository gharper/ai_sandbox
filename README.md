# AI Sandbox

Dockerized environment for running agents with full permissions.

## Quick start

Build and run the container with the current repo mounted at `/workspace`. The default command is `codex --full-auto`:

```bash
python -m ai_sandbox
```

Install as a CLI tool inside a virtual environment:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
ai_sandbox
```

Run as a module:

```bash
python -m ai_sandbox
```

The runner injects auth at runtime by mounting the first existing auth file from `~/.codex/device_auth.json` or `~/.codex/auth.json` into the container at `/root/.codex/auth.json`. If neither file exists, it logs a warning with the resolved absolute paths and continues without mounting credentials. To skip auth mounting and the warning, pass `--no-auth` (or `--auth-file none`).

Auth mapping:

`~/.codex/device_auth.json` → `/root/.codex/auth.json` or

`~/.codex/auth.json` → `/root/.codex/auth.json`.

Override it with:

```bash
ai_sandbox --auth-file /abs/path/to/device_auth.json
```

Pass extra Docker args or a specific command:

```bash
ai_sandbox --docker-arg -e --docker-arg FOO=bar -- /bin/bash
```

Disable TTY allocation (useful in non-interactive shells):

```bash
ai_sandbox --no-tty -- /bin/bash
```

The runner adds `host.docker.internal` mapped to the host gateway by default.

Need published ports? Use `--docker-arg -p --docker-arg HOST:CONTAINER` to map them explicitly.

## Development

Set up a virtual environment and install the CLI:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

Run tests:

```bash
python -m unittest discover -s tests
```
