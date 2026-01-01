#!/usr/bin/env python3
"""Build and run the Codex container with the repo mounted at /workspace."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import textwrap
from typing import Iterable, List, Sequence

DEFAULT_AUTH_FILES = (
    "~/.codex/device_auth.json",
    "~/.codex/auth.json",
)

REDACT_KEYS = {"GITHUB_TOKEN", "GH_TOKEN", "GITHUB_AI_PAT_TOKEN", "PASSWORD", "SECRET"}


def _configure_logging() -> None:
    level_name = os.getenv("AI_SANDBOX_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = os.getenv(
        "AI_SANDBOX_LOG_FMT",
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.basicConfig(level=level, format=fmt)


def _redact_item(item: str) -> str:
    for key in REDACT_KEYS:
        if item.startswith(f"{key}=") or ("=" in item and item.split("=", 1)[0] == key):
            return f"{key}=REDACTED"
        # also redact inline occurrences like "--env GITHUB_TOKEN=..."
        if f"{key}=" in item:
            left, _ = item.split(f"{key}=", 1)
            return f"{left}{key}=REDACTED"
    return item


def _redact_cmd(cmd: Sequence[str]) -> str:
    return " ".join(_redact_item(str(c)) for c in cmd)


def run_subprocess(
    cmd: Sequence[str],
    *,
    check: bool = True,
    timeout: int | None = 120,
    capture: bool = True,
) -> subprocess.CompletedProcess:
    logger = logging.getLogger("ai_sandbox.subproc")
    logger.debug("Running command: %s", _redact_cmd(cmd))
    try:
        if capture:
            completed = subprocess.run(
                list(cmd),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if completed.returncode != 0 and check:
                # Trim long outputs for logs
                stdout = (completed.stdout or "").strip()
                stderr = (completed.stderr or "").strip()
                logger.error(
                    "Command failed (rc=%s). stdout=%s stderr=%s",
                    completed.returncode,
                    (stdout[:1000] + "...") if len(stdout) > 1000 else stdout,
                    (stderr[:1000] + "...") if len(stderr) > 1000 else stderr,
                )
                raise subprocess.CalledProcessError(
                    completed.returncode,
                    cmd,
                    output=completed.stdout,
                    stderr=completed.stderr,
                )
            logger.debug(
                "Command finished (rc=%s). stdout=%s",
                completed.returncode,
                (completed.stdout or "")[:500],
            )
            return completed
        else:
            # stream output directly (useful for interactive TTY runs)
            completed = subprocess.run(list(cmd), check=False)
            if completed.returncode != 0 and check:
                logger.error("Command failed with rc=%s", completed.returncode)
                raise subprocess.CalledProcessError(completed.returncode, cmd)
            return completed
    except subprocess.TimeoutExpired as e:
        logger.exception("Command timed out: %s", _redact_cmd(cmd))
        raise


def build_image(image: str, dockerfile: str, context: str) -> None:
    logger = logging.getLogger("ai_sandbox")
    cmd = ["docker", "build", "-t", image, "-f", dockerfile, context]
    logger.info("Building Docker image %s using %s", image, dockerfile)
    run_subprocess(cmd, timeout=900)


def build_run_command(
    image: str,
    context: str,
    name: str | None,
    extra_args: Sequence[str],
    container_cmd: Sequence[str],
    auth_file: str | None,
    use_tty: bool,
) -> List[str]:
    cmd = [
        "docker",
        "run",
        "--rm",
        "--add-host",
        "host.docker.internal:host-gateway",
        "-v",
        f"{context}:/workspace",
        "-w",
        "/workspace",
    ]
    if auth_file:
        cmd.extend(["-v", f"{auth_file}:/root/.codex/auth.json:ro"])
    if use_tty:
        cmd.append("-it")
    if name:
        cmd.extend(["--name", name])
    cmd.extend(list(extra_args))
    cmd.append(image)
    cmd.extend(list(container_cmd))
    return cmd


def has_env_arg(extra_args: Sequence[str], key: str) -> bool:
    key_prefix = f"{key}="
    idx = 0
    while idx < len(extra_args):
        item = extra_args[idx]
        if item in ("-e", "--env"):
            if idx + 1 < len(extra_args) and extra_args[idx + 1].startswith(key_prefix):
                return True
            idx += 2
            continue
        if item.startswith(key_prefix):
            return True
        if item.startswith("--env="):
            candidate = item[len("--env=") :]
            if candidate.startswith(key_prefix):
                return True
        if item.startswith("-e") and item != "-e":
            candidate = item[len("-e") :]
            if candidate.startswith("="):
                candidate = candidate[1:]
            if candidate.startswith(key_prefix):
                return True
        idx += 1
    return False


def run_container(
    image: str,
    context: str,
    name: str | None,
    extra_args: Sequence[str],
    container_cmd: Sequence[str],
    auth_file: str | None,
    use_tty: bool,
) -> None:
    logger = logging.getLogger("ai_sandbox")
    cmd = build_run_command(
        image,
        context,
        name,
        extra_args,
        container_cmd,
        auth_file,
        use_tty,
    )
    logger.info("Running container with image %s", image)
    # If interactive TTY, stream output directly so user can interact.
    try:
        run_subprocess(cmd, check=True, capture=not use_tty, timeout=None)
    except subprocess.CalledProcessError:
        logger.exception(
            "Docker run failed; consider re-running without -it to capture logs"
        )
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and run the Codex Docker image with the repo mounted."
    )
    parser.add_argument("--image", default="ai-sandbox-codex", help="Docker image name")
    parser.add_argument("--name", default=None, help="Optional container name")
    parser.add_argument(
        "--dockerfile",
        default="Dockerfile",
        help="Path to the Dockerfile",
    )
    parser.add_argument(
        "--context",
        default=os.getcwd(),
        help="Build context and host directory to mount",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip docker build",
    )
    parser.add_argument(
        "--docker-arg",
        action="append",
        default=[],
        help="Extra argument passed to docker run (repeatable)",
    )
    parser.add_argument(
        "--no-tty",
        action="store_true",
        help="Disable TTY allocation for docker run",
    )
    parser.add_argument(
        "--auth-file",
        default=None,
        help=(
            "Path to auth.json to mount into the container "
            f"(default: first existing of {', '.join(DEFAULT_AUTH_FILES)})"
        ),
    )
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Disable auth mounting (overrides --auth-file)",
    )
    parser.add_argument(
        "--agent",
        choices=["codex", "copilot"],
        default="codex",
        help="AI agent to run inside the container (default: codex)",
    )
    parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command to run in the container (default: /bin/bash)",
    )
    return parser.parse_args(argv)


def resolve_auth_candidates(context: str, candidates: Iterable[str]) -> list[str]:
    resolved_candidates = []
    for candidate in candidates:
        expanded = os.path.expanduser(candidate)
        if os.path.isabs(expanded):
            resolved = expanded
        else:
            resolved = os.path.join(context, candidate)
        resolved_candidates.append(resolved)
    return resolved_candidates


def resolve_auth_file(
    context: str,
    candidates: Iterable[str],
) -> str | None:
    for resolved in resolve_auth_candidates(context, candidates):
        if os.path.isfile(resolved):
            return resolved
    return None


def _check_docker_available() -> None:
    logger = logging.getLogger("ai_sandbox")
    try:
        run_subprocess(["docker", "info"], timeout=10)
    except Exception:
        logger.exception(
            "Docker does not appear to be available. Ensure the Docker daemon is running and you have access to it."
        )
        raise


def main(argv: Sequence[str] | None = None) -> int:
    _configure_logging()
    logger = logging.getLogger("ai_sandbox")
    try:
        args = parse_args(argv)
        cmd_args = list(args.cmd)
        if cmd_args[:1] == ["--"]:
            cmd_args = cmd_args[1:]
        if cmd_args:
            container_cmd = cmd_args
        elif args.agent == "copilot":
            container_cmd = ["copilot", "--add-dir", "/workspace", "--allow-all-tools"]
        else:
            container_cmd = ["codex", "--full-auto"]
        use_tty = not args.no_tty
        context = os.path.abspath(os.path.expanduser(args.context))
        extra_args = list(args.docker_arg)
        if args.agent == "copilot":
            gh_token = os.getenv("GH_TOKEN")
            if gh_token and not has_env_arg(extra_args, "GH_TOKEN"):
                extra_args.extend(["-e", f"GH_TOKEN={gh_token}"])
            github_token = os.getenv("GITHUB_TOKEN")
            if github_token and not has_env_arg(extra_args, "GITHUB_TOKEN"):
                extra_args.extend(["-e", f"GITHUB_TOKEN={github_token}"])
        github_token = os.getenv("GITHUB_AI_PAT_TOKEN")
        if (
            github_token
            and args.agent != "copilot"
            and not has_env_arg(extra_args, "GITHUB_TOKEN")
        ):
            extra_args.extend(["-e", f"GITHUB_TOKEN={github_token}"])
        auth_candidates = (
            [args.auth_file] if args.auth_file else list(DEFAULT_AUTH_FILES)
        )
        if args.no_auth or (args.auth_file and args.auth_file.lower() == "none"):
            auth_file = None
        else:
            resolved_auth_candidates = resolve_auth_candidates(context, auth_candidates)
            auth_file = resolve_auth_file(context, auth_candidates)
            if not auth_file:
                logger.warning(
                    "Auth file not found at %s. Continuing without mounting credentials.",
                    ", ".join(resolved_auth_candidates),
                )
        if os.path.isabs(args.dockerfile):
            dockerfile = args.dockerfile
        else:
            dockerfile = os.path.join(context, args.dockerfile)

        # validate Docker early and give a helpful error
        _check_docker_available()

        if not args.no_build:
            build_image(args.image, dockerfile, context)
        run_container(
            args.image,
            context,
            args.name,
            extra_args,
            container_cmd,
            auth_file,
            use_tty,
        )
        return 0
    except KeyboardInterrupt:
        logger = logging.getLogger("ai_sandbox")
        logger.info("Interrupted by user. Exiting.")
        return 130
    except subprocess.CalledProcessError as e:
        logger = logging.getLogger("ai_sandbox")
        logger.error("External command failed: %s", e)
        return 2
    except Exception:
        logger = logging.getLogger("ai_sandbox")
        logger.exception("Unhandled error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
