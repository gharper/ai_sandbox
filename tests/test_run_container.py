import logging
import os
import unittest
from unittest import mock

from ai_sandbox import cli


class TestRunContainer(unittest.TestCase):
    def setUp(self):
        self._orig_cli = cli._CONTAINER_CLI
        cli._CONTAINER_CLI = "docker"

    def tearDown(self):
        cli._CONTAINER_CLI = self._orig_cli

    @mock.patch("ai_sandbox.cli.run_subprocess")
    def test_build_image_defaults(self, run_mock):
        cli.build_image("img", "Dockerfile", "/ctx")
        run_mock.assert_called_once_with(
            ["docker", "build", "-t", "img", "-f", "Dockerfile", "/ctx"],
            timeout=900,
        )

    def test_build_run_command_defaults(self):
        cmd = cli.build_run_command(
            "img",
            "/ctx",
            None,
            [],
            ["codex", "--full-auto"],
            "/ctx/mock/device_auth.json",
            True,
        )
        self.assertEqual(
            cmd,
            [
                "docker",
                "run",
                "--rm",
                "--add-host",
                "host.docker.internal:host-gateway",
                "-v",
                "/ctx:/workspace",
                "-w",
                "/workspace",
                "-v",
                "/ctx/mock/device_auth.json:/root/.codex/auth.json:ro",
                "-it",
                "img",
                "codex",
                "--full-auto",
            ],
        )
        self.assertNotIn("-p", cmd)

    def test_build_run_command_with_name_and_args(self):
        cmd = cli.build_run_command(
            "img",
            "/ctx",
            "my-container",
            ["-e", "FOO=bar"],
            ["codex", "--full-auto"],
            "/ctx/mock/device_auth.json",
            True,
        )
        self.assertIn("--name", cmd)
        self.assertIn("my-container", cmd)
        self.assertIn("-e", cmd)
        self.assertIn("FOO=bar", cmd)

    def test_build_run_command_without_tty(self):
        cmd = cli.build_run_command(
            "img",
            "/ctx",
            None,
            [],
            ["codex", "--full-auto"],
            "/ctx/mock/device_auth.json",
            False,
        )
        self.assertNotIn("-it", cmd)

    def test_build_run_command_without_auth_file(self):
        cmd = cli.build_run_command(
            "img",
            "/ctx",
            None,
            [],
            ["codex", "--full-auto"],
            None,
            True,
        )
        self.assertNotIn("/root/.codex/auth.json", " ".join(cmd))

    def test_has_env_arg_variants(self):
        self.assertTrue(cli.has_env_arg(["-e", "GITHUB_TOKEN=foo"], "GITHUB_TOKEN"))
        self.assertTrue(cli.has_env_arg(["--env", "GITHUB_TOKEN=foo"], "GITHUB_TOKEN"))
        self.assertTrue(cli.has_env_arg(["--env=GITHUB_TOKEN=foo"], "GITHUB_TOKEN"))
        self.assertTrue(cli.has_env_arg(["-eGITHUB_TOKEN=foo"], "GITHUB_TOKEN"))
        self.assertTrue(cli.has_env_arg(["-e=GITHUB_TOKEN=foo"], "GITHUB_TOKEN"))
        self.assertTrue(cli.has_env_arg(["GITHUB_TOKEN=foo"], "GITHUB_TOKEN"))
        self.assertFalse(cli.has_env_arg(["-e", "OTHER=foo"], "GITHUB_TOKEN"))

    @mock.patch("ai_sandbox.cli.run_subprocess")
    def test_run_container_invokes_docker(self, run_mock):
        cli.run_container(
            "img",
            "/ctx",
            None,
            [],
            ["codex", "--full-auto"],
            "/ctx/mock/device_auth.json",
            True,
        )
        run_mock.assert_called_once_with(
            [
                "docker",
                "run",
                "--rm",
                "--add-host",
                "host.docker.internal:host-gateway",
                "-v",
                "/ctx:/workspace",
                "-w",
                "/workspace",
                "-v",
                "/ctx/mock/device_auth.json:/root/.codex/auth.json:ro",
                "-it",
                "img",
                "codex",
                "--full-auto",
            ],
            check=True,
            capture=False,
            timeout=None,
        )

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.subprocess.run")
    def test_main_strips_double_dash(self, run_mock, _docker_mock):
        run_mock.return_value.returncode = 0
        with mock.patch.dict(os.environ, {"GITHUB_AI_PAT_TOKEN": "token"}):
            cli.main(
                [
                    "--no-build",
                    "--no-tty",
                    "--auth-file",
                    "~/.codex/device_auth.json",
                    "--",
                    "/bin/bash",
                ]
            )
        run_mock.assert_called_once()
        cmd = run_mock.call_args[0][0]
        self.assertNotIn("--", cmd)
        self.assertIn("/bin/bash", cmd)

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.run_container")
    @mock.patch("ai_sandbox.cli.build_image")
    @mock.patch("ai_sandbox.cli.image_exists", return_value=False)
    def test_main_resolves_context_and_dockerfile(
        self, _image_exists_mock, build_mock, run_mock, _docker_mock
    ):
        rel_context = os.path.relpath("some/context", os.getcwd())
        expected_context = os.path.abspath(os.path.expanduser(rel_context))
        expected_dockerfile = os.path.join(expected_context, "Dockerfile")

        with mock.patch.dict(os.environ, {"GITHUB_AI_PAT_TOKEN": "token"}):
            with mock.patch("ai_sandbox.cli.os.path.isfile", return_value=True):
                cli.main(
                    ["--context", rel_context, "--auth-file", "~/.codex/device_auth.json"]
                )

        build_mock.assert_called_once_with(
            "ai-sandbox-codex",
            expected_dockerfile,
            expected_context,
        )
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.args[1], expected_context)

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_missing_auth_file_warns_and_continues(self, run_mock, _docker_mock):
        with mock.patch.dict(os.environ, {"GITHUB_AI_PAT_TOKEN": "token"}):
            with self.assertLogs("ai_sandbox", level="WARNING"):
                cli.main(
                    [
                        "--no-build",
                        "--context",
                        ".",
                        "--auth-file",
                        "/nonexistent/device_auth.json",
                    ]
                )
        self.assertIsNone(run_mock.call_args.args[5])

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_no_auth_skips_warning(self, run_mock, _docker_mock):
        # Test that NO AUTH warnings appear when --no-auth is used
        with mock.patch.dict(os.environ, {"GITHUB_AI_PAT_TOKEN": "token"}):
            with self.assertLogs("ai_sandbox", level="WARNING") as captured:
                cli.main(
                    [
                        "--no-build",
                        "--context",
                        ".",
                        "--no-auth",
                    ]
                )
        self.assertIsNone(run_mock.call_args.args[5])
        # Should only have the --context deprecation warning, NOT auth warnings
        auth_warnings = [log for log in captured.output if "Auth file not found" in log]
        self.assertEqual(len(auth_warnings), 0)

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_auth_file_none_skips_warning(self, run_mock, _docker_mock):
        # Test that NO AUTH warnings appear when --auth-file none is used
        with mock.patch.dict(os.environ, {"GITHUB_AI_PAT_TOKEN": "token"}):
            with self.assertLogs("ai_sandbox", level="WARNING") as captured:
                cli.main(
                    [
                        "--no-build",
                        "--context",
                        ".",
                        "--auth-file",
                        "none",
                    ]
                )
        self.assertIsNone(run_mock.call_args.args[5])
        # Should only have the --context deprecation warning, NOT auth warnings
        auth_warnings = [log for log in captured.output if "Auth file not found" in log]
        self.assertEqual(len(auth_warnings), 0)

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.os.path.isfile", return_value=False)
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_missing_auth_file_warns_with_resolved_candidates(
        self,
        run_mock,
        _isfile_mock,
        _docker_mock,
    ):
        with mock.patch.dict(os.environ, {"GITHUB_AI_PAT_TOKEN": "token"}):
            with self.assertLogs("ai_sandbox", level="WARNING") as captured:
                cli.main(
                    [
                        "--no-build",
                        "--context",
                        "/ctx",
                        "--auth-file",
                        "~/.codex/device_auth.json",
                    ]
                )
        self.assertIsNone(run_mock.call_args.args[5])
        self.assertIn(
            f"WARNING:ai_sandbox:Auth file not found at "
            f"{os.path.expanduser('~/.codex/device_auth.json')}. "
            "Continuing without mounting credentials.",
            captured.output,
        )

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.os.path.isfile", return_value=False)
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_auth_file_relative_uses_context(
        self, run_mock, _isfile_mock, _docker_mock
    ):
        with mock.patch.dict(os.environ, {"GITHUB_AI_PAT_TOKEN": "token"}):
            with self.assertLogs("ai_sandbox", level="WARNING") as captured:
                cli.main(
                    [
                        "--no-build",
                        "--context",
                        "/ctx",
                        "--auth-file",
                        "rel/device_auth.json",
                    ]
                )
        self.assertIsNone(run_mock.call_args.args[5])
        self.assertIn(
            "WARNING:ai_sandbox:Auth file not found at "
            "/ctx/rel/device_auth.json. "
            "Continuing without mounting credentials.",
            captured.output,
        )

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.os.path.isfile")
    @mock.patch("ai_sandbox.cli.run_container")
    @mock.patch("ai_sandbox.cli.build_image")
    def test_main_uses_first_existing_auth_default(
        self,
        build_mock,
        run_mock,
        isfile_mock,
        _docker_mock,
    ):
        def isfile_side_effect(path):
            return path.endswith("/.codex/auth.json")

        isfile_mock.side_effect = isfile_side_effect

        with mock.patch.dict(os.environ, {"GITHUB_AI_PAT_TOKEN": "token"}):
            cli.main(
                [
                    "--no-build",
                    "--context",
                    "/ctx",
                ]
            )

        self.assertEqual(
            run_mock.call_args.args[5],
            os.path.expanduser("~/.codex/auth.json"),
        )

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.os.path.isfile", return_value=True)
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_no_auth_overrides_auth_file(
        self, run_mock, _isfile_mock, _docker_mock
    ):
        # Test that --no-auth overrides --auth-file and no auth warnings appear
        with mock.patch.dict(os.environ, {"GITHUB_AI_PAT_TOKEN": "token"}):
            with self.assertLogs("ai_sandbox", level="WARNING") as captured:
                cli.main(
                    [
                        "--no-build",
                        "--context",
                        ".",
                        "--auth-file",
                        "~/.codex/device_auth.json",
                        "--no-auth",
                    ]
                )
        self.assertIsNone(run_mock.call_args.args[5])
        # Should only have the --context deprecation warning, NOT auth warnings
        auth_warnings = [log for log in captured.output if "Auth file not found" in log]
        self.assertEqual(len(auth_warnings), 0)

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_sets_github_token_from_env(self, run_mock, _docker_mock):
        with mock.patch.dict(os.environ, {"GITHUB_AI_PAT_TOKEN": "token"}):
            cli.main(
                [
                    "--no-build",
                    "--context",
                    ".",
                    "--no-auth",
                ]
            )
        extra_args = run_mock.call_args.args[3]
        self.assertIn("-e", extra_args)
        self.assertIn("GITHUB_TOKEN=token", extra_args)

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_does_not_override_github_token(self, run_mock, _docker_mock):
        with mock.patch.dict(os.environ, {"GITHUB_AI_PAT_TOKEN": "token"}):
            cli.main(
                [
                    "--no-build",
                    "--context",
                    ".",
                    "--no-auth",
                    "--docker-arg",
                    "GITHUB_TOKEN=override",
                ]
            )
        extra_args = run_mock.call_args.args[3]
        self.assertNotIn("GITHUB_TOKEN=token", extra_args)

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_agent_copilot_sets_tokens(self, run_mock, _docker_mock):
        with mock.patch.dict(
            os.environ,
            {"GH_TOKEN": "gh-token", "GITHUB_TOKEN": "github-token"},
            clear=True,
        ):
            cli.main(
                [
                    "--no-build",
                    "--context",
                    ".",
                    "--no-auth",
                    "--agent",
                    "copilot",
                ]
            )
        extra_args = run_mock.call_args.args[3]
        self.assertIn("-e", extra_args)
        self.assertIn("GH_TOKEN=gh-token", extra_args)
        self.assertIn("GITHUB_TOKEN=github-token", extra_args)

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_agent_copilot_does_not_override_tokens(self, run_mock, _docker_mock):
        with mock.patch.dict(
            os.environ,
            {"GH_TOKEN": "gh-token", "GITHUB_TOKEN": "github-token"},
            clear=True,
        ):
            cli.main(
                [
                    "--no-build",
                    "--context",
                    ".",
                    "--no-auth",
                    "--agent",
                    "copilot",
                    "--docker-arg",
                    "GH_TOKEN=override-gh",
                    "--docker-arg",
                    "GITHUB_TOKEN=override-github",
                ]
            )
        extra_args = run_mock.call_args.args[3]
        self.assertNotIn("GH_TOKEN=gh-token", extra_args)
        self.assertNotIn("GITHUB_TOKEN=github-token", extra_args)

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_agent_copilot_ignores_ai_pat_token(self, run_mock, _docker_mock):
        with mock.patch.dict(
            os.environ,
            {"GITHUB_AI_PAT_TOKEN": "token"},
            clear=True,
        ):
            cli.main(
                [
                    "--no-build",
                    "--context",
                    ".",
                    "--no-auth",
                    "--agent",
                    "copilot",
                ]
            )
        extra_args = run_mock.call_args.args[3]
        self.assertNotIn("GITHUB_TOKEN=token", extra_args)

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.subprocess.run")
    def test_main_agent_copilot(self, run_mock, _docker_mock):
        run_mock.return_value.returncode = 0
        with mock.patch.dict(os.environ, {"GITHUB_AI_PAT_TOKEN": "token"}):
            cli.main(
                [
                    "--no-build",
                    "--no-tty",
                    "--agent",
                    "copilot",
                ]
            )
        cmd = run_mock.call_args[0][0]
        self.assertIn("copilot", cmd)
        self.assertIn("--add-dir", cmd)
        self.assertIn("/workspace", cmd)
        self.assertIn("--allow-all-tools", cmd)

    @mock.patch("ai_sandbox.cli._check_docker_available")
    @mock.patch("ai_sandbox.cli.subprocess.run")
    def test_main_agent_codex_default(self, run_mock, _docker_mock):
        run_mock.return_value.returncode = 0
        with mock.patch.dict(os.environ, {"GITHUB_AI_PAT_TOKEN": "token"}):
            cli.main(
                [
                    "--no-build",
                    "--no-tty",
                ]
            )
        cmd = run_mock.call_args[0][0]
        self.assertIn("codex", cmd)
        self.assertIn("--full-auto", cmd)

    @mock.patch("ai_sandbox.cli.run_subprocess")
    @mock.patch("ai_sandbox.cli.shutil.which")
    def test_check_docker_falls_back_to_podman(self, which_mock, run_mock):
        cli._CONTAINER_CLI = None

        def which_side_effect(cmd):
            if cmd == "docker":
                return None
            if cmd == "podman":
                return "/usr/bin/podman"
            return None

        which_mock.side_effect = which_side_effect
        run_mock.return_value.returncode = 0

        self.assertEqual(cli._check_docker_available(), "podman")
        self.assertEqual(cli._CONTAINER_CLI, "podman")
        run_mock.assert_called_once_with(["podman", "info"], timeout=10)

    @mock.patch("ai_sandbox.cli.shutil.which", return_value=None)
    def test_check_docker_raises_when_no_engines(self, which_mock):
        cli._CONTAINER_CLI = None
        with self.assertRaises(FileNotFoundError):
            cli._check_docker_available()
        self.assertEqual(which_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
