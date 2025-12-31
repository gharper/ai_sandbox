#!/usr/bin/env python3
"""Build and run the Codex container with the repo mounted at /workspace."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Iterable, List, Sequence

DEFAULT_AUTH_FILES = (
    "~/.codex/device_auth.json",
    "~/.codex/auth.json",
)


def build_image(image: str, dockerfile: str, context: str) -> None:
    cmd = ["docker", "build", "-t", image, "-f", dockerfile]
    cmd.append(context)
    subprocess.run(cmd, check=True)


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
    cmd.extend(extra_args)
    cmd.append(image)
    cmd.extend(container_cmd)
    return cmd


def run_container(
    image: str,
    context: str,
    name: str | None,
    extra_args: Sequence[str],
    container_cmd: Sequence[str],
    auth_file: str | None,
    use_tty: bool,
) -> None:
    cmd = build_run_command(
        image,
        context,
        name,
        extra_args,
        container_cmd,
        auth_file,
        use_tty,
    )
    subprocess.run(cmd, check=True)


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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cmd_args = list(args.cmd)
    if cmd_args[:1] == ["--"]:
        cmd_args = cmd_args[1:]
    container_cmd = cmd_args or ["codex", "--full-auto"]
    use_tty = not args.no_tty
    context = os.path.abspath(os.path.expanduser(args.context))
    auth_candidates = [args.auth_file] if args.auth_file else list(DEFAULT_AUTH_FILES)
    if args.no_auth or (args.auth_file and args.auth_file.lower() == "none"):
        auth_file = None
    else:
        resolved_auth_candidates = resolve_auth_candidates(context, auth_candidates)
        auth_file = resolve_auth_file(context, auth_candidates)
        if not auth_file:
            print(
                "Warning: auth file not found at "
                f"{', '.join(resolved_auth_candidates)}. "
                "Continuing without mounting credentials.",
                file=sys.stderr,
            )
    if os.path.isabs(args.dockerfile):
        dockerfile = args.dockerfile
    else:
        dockerfile = os.path.join(context, args.dockerfile)
    if not args.no_build:
        build_image(args.image, dockerfile, context)
    run_container(
        args.image,
        context,
        args.name,
        args.docker_arg,
        container_cmd,
        auth_file,
        use_tty,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
