# AI Sandbox

Dockerized environment for running agents with full permissions.

## Quick start

Set up your credentials:
* For codex, ensure you have your credentials in `~/.codex/device_auth.json` or `~/.codex/auth.json`.
* For copilot, ensure you have your GitHub Copilot token exported to `GH_TOKEN` or `GITHUB_TOKEN`

Install the package:

```bash
python -m venv .venv
source .venv/bin/activate
python -m ensurepip --upgrade
pip install -e .
which ai_sandbox
```

Calling `ai_sandbox` will run the container with the current directory mounted at `/workspace`:

## Details:

To run with a specific agent, use:
```bash
ai_sandbox --agent codex
ai_sandbox --agent copilot
```

The command will automatically:
- Use an existing `ai-sandbox-codex` image if available (no rebuild needed)
- If the image doesn't exist, builds it from the package installation directory
- Mounts your **current working directory** into the container at `/workspace`
- Use the appropriate login method for the specified agent

This means you can install `ai_sandbox` once and use it from any project directory!

If an agent is not specified, the default is `codex`.

## Advanced Options

### Force rebuild

To force a rebuild even if the image exists:

```bash
ai_sandbox --force-build
```

### Skip build check

To skip building entirely (fails if image doesn't exist):

```bash
ai_sandbox --no-build
```

### Custom build context

For development, specify where to find the Dockerfile:

```bash
ai_sandbox --build-context /path/to/ai-sandbox --mount-dir /path/to/project
```

### Authentication

#### Codex auth
The runner injects auth at runtime by mounting the first existing auth file from `~/.codex/device_auth.json` or `~/.codex/auth.json` into the container at `/root/.codex/auth.json`. If neither file exists, it logs a warning with the resolved absolute paths and continues without mounting credentials. To skip auth mounting and the warning, pass `--no-auth` (or `--auth-file none`).

Auth mapping:

`~/.codex/device_auth.json` → `/root/.codex/auth.json` or
`~/.codex/auth.json` → `/root/.codex/auth.json`.

Override it with:

```bash
ai_sandbox --auth-file /abs/path/to/device_auth.json
```
#### Copilot auth
The runner injects the GitHub Copilot token at runtime by checking and passing in the following environment variables:
- `GH_TOKEN`
- `GITHUB_TOKEN`
- `GITHUB_AI_PAT_TOKEN`

### Docker options

#### Pass extra Docker args or a specific command:

```bash
ai_sandbox --docker-arg -e --docker-arg FOO=bar -- /bin/bash
```
Note: This is useful for getting an interactive shell inside the container without starting the agent.

#### Disable TTY allocation (useful in non-interactive shells):

```bash
ai_sandbox --no-tty -- /bin/bash
```

## Development

### Run tests:

```bash
python -m unittest discover -s tests
```

### Manual build:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[build]"
python -m build
```
