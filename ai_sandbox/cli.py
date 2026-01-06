#!/usr/bin/env python3
"""Build and run the Codex container with the repo mounted at /workspace."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import textwrap
from typing import Iterable, List, Sequence

DEFAULT_AUTH_FILES = (
    "~/.codex/device_auth.json",
    "~/.codex/auth.json",
)

REDACT_KEYS = {"GITHUB_TOKEN", "GH_TOKEN", "GITHUB_AI_PAT_TOKEN", "PASSWORD", "SECRET"}
_CONTAINER_CLI: str | None = None


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


def _get_container_cli() -> str:
    if _CONTAINER_CLI is None:
        return _check_docker_available()
    return _CONTAINER_CLI


def image_exists(image: str) -> bool:
    """Check if a Docker image exists locally."""
    logger = logging.getLogger("ai_sandbox")
    container_cli = _get_container_cli()
    try:
        result = run_subprocess(
            [container_cli, "image", "inspect", image],
            check=False,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        logger.debug("Failed to check if image %s exists", image)
        return False


def build_image(image: str, dockerfile: str, context: str) -> None:
    logger = logging.getLogger("ai_sandbox")
    container_cli = _get_container_cli()
    cmd = [container_cli, "build", "-t", image, "-f", dockerfile, context]
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
    container_cli = _get_container_cli()
    cmd = [
        container_cli,
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


def get_package_root() -> str | None:
    """Find the ai_sandbox package installation directory containing Dockerfile."""
    import ai_sandbox
    
    # Try to find the package directory
    package_dir = os.path.dirname(os.path.abspath(ai_sandbox.__file__))
    # Go up one level to the project root
    project_root = os.path.dirname(package_dir)
    
    # Check if Dockerfile exists in the project root
    dockerfile_path = os.path.join(project_root, "Dockerfile")
    if os.path.isfile(dockerfile_path):
        return project_root
    
    return None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and run the Codex Docker image with the repo mounted."
    )
    parser.add_argument("--image", default="ai-sandbox-codex", help="Docker image name")
    parser.add_argument("--name", default=None, help="Optional container name")
    parser.add_argument(
        "--dockerfile",
        default=None,
        help="Path to the Dockerfile (default: auto-detect from package installation)",
    )
    parser.add_argument(
        "--build-context",
        default=None,
        help="Build context directory (default: auto-detect from package installation)",
    )
    parser.add_argument(
        "--mount-dir",
        default=os.getcwd(),
        help="Host directory to mount into /workspace (default: current directory)",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip docker build",
    )
    parser.add_argument(
        "--force-build",
        action="store_true",
        help="Force docker build even if image exists",
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
    # Legacy support
    parser.add_argument(
        "--context",
        dest="_legacy_context",
        default=None,
        help=argparse.SUPPRESS,
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


def _check_docker_available() -> str:
    global _CONTAINER_CLI
    if _CONTAINER_CLI is not None:
        return _CONTAINER_CLI

    logger = logging.getLogger("ai_sandbox")
    container_cli: str | None = None

    if shutil.which("docker"):
        container_cli = "docker"
    elif shutil.which("podman"):
        container_cli = "podman"

    if not container_cli:
        logger.error(
            "Neither docker nor podman commands were found on PATH. "
            "Install Docker Desktop or Podman before running ai-sandbox."
        )
        raise FileNotFoundError("docker or podman command not found on PATH")

    try:
        run_subprocess([container_cli, "info"], timeout=10)
    except Exception:
        logger.exception(
            "%s does not appear to be available. Ensure the service is running and you have access to it.",
            container_cli.capitalize(),
        )
        raise

    if container_cli == "podman":
        logger.info("Using podman as container engine because docker was not found.")

    _CONTAINER_CLI = container_cli
    return container_cli


def main(argv: Sequence[str] | None = None) -> int:
    _configure_logging()
    logger = logging.getLogger("ai_sandbox")
    try:
        args = parse_args(argv)
        
        # Handle legacy --context argument (only warn if actually used)
        if hasattr(args, '_legacy_context') and args._legacy_context is not None:
            logger.warning(
                "--context is deprecated. Use --build-context for build directory "
                "and --mount-dir for directory to mount into container."
            )
            if args.build_context is None:
                args.build_context = args._legacy_context
            if args.mount_dir == os.getcwd():
                args.mount_dir = args._legacy_context
        
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
        
        # Resolve mount directory (where user is running from)
        mount_dir = os.path.abspath(os.path.expanduser(args.mount_dir))
        
        # Resolve build context and dockerfile
        if args.build_context is not None:
            # User specified build context explicitly
            build_context = os.path.abspath(os.path.expanduser(args.build_context))
            if args.dockerfile is not None:
                if os.path.isabs(args.dockerfile):
                    dockerfile = args.dockerfile
                else:
                    dockerfile = os.path.join(build_context, args.dockerfile)
            else:
                dockerfile = os.path.join(build_context, "Dockerfile")
        else:
            # Auto-detect from package installation
            package_root = get_package_root()
            if package_root:
                build_context = package_root
                if args.dockerfile is not None:
                    if os.path.isabs(args.dockerfile):
                        dockerfile = args.dockerfile
                    else:
                        dockerfile = os.path.join(build_context, args.dockerfile)
                else:
                    dockerfile = os.path.join(build_context, "Dockerfile")
            else:
                # Fallback to current directory (for development)
                logger.warning(
                    "Could not auto-detect package root. Using current directory as build context."
                )
                build_context = mount_dir
                if args.dockerfile is not None:
                    if os.path.isabs(args.dockerfile):
                        dockerfile = args.dockerfile
                    else:
                        dockerfile = os.path.join(build_context, args.dockerfile)
                else:
                    dockerfile = os.path.join(build_context, "Dockerfile")
        
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
            resolved_auth_candidates = resolve_auth_candidates(mount_dir, auth_candidates)
            auth_file = resolve_auth_file(mount_dir, auth_candidates)
            if not auth_file:
                logger.warning(
                    "Auth file not found at %s. Continuing without mounting credentials.",
                    ", ".join(resolved_auth_candidates),
                )

        # validate Docker early and give a helpful error
        _check_docker_available()

        # Determine if we need to build
        needs_build = False
        if args.force_build:
            needs_build = True
            logger.info("Force build requested")
        elif args.no_build:
            needs_build = False
        elif not image_exists(args.image):
            needs_build = True
            logger.info("Image %s not found locally, will build", args.image)
        else:
            logger.info("Image %s exists, skipping build", args.image)
        
        if needs_build:
            if not os.path.isfile(dockerfile):
                logger.error(
                    "Dockerfile not found at %s. Cannot build image. "
                    "Use --dockerfile or --build-context to specify the correct location.",
                    dockerfile,
                )
                return 1
            build_image(args.image, dockerfile, build_context)
        
        run_container(
            args.image,
            mount_dir,
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
