import os
import unittest
from unittest import mock

from ai_sandbox import cli


class TestRunContainer(unittest.TestCase):
    @mock.patch("ai_sandbox.cli.subprocess.run")
    def test_build_image_defaults(self, run_mock):
        cli.build_image("img", "Dockerfile", "/ctx")
        run_mock.assert_called_once_with(
            ["docker", "build", "-t", "img", "-f", "Dockerfile", "/ctx"],
            check=True,
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

    @mock.patch("ai_sandbox.cli.subprocess.run")
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
        )

    @mock.patch("ai_sandbox.cli.subprocess.run")
    def test_main_strips_double_dash(self, run_mock):
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

    @mock.patch("ai_sandbox.cli.run_container")
    @mock.patch("ai_sandbox.cli.build_image")
    def test_main_resolves_context_and_dockerfile(self, build_mock, run_mock):
        rel_context = os.path.relpath("some/context", os.getcwd())
        expected_context = os.path.abspath(os.path.expanduser(rel_context))
        expected_dockerfile = os.path.join(expected_context, "Dockerfile")

        cli.main(["--context", rel_context, "--auth-file", "~/.codex/device_auth.json"])

        build_mock.assert_called_once_with(
            "ai-sandbox-codex",
            expected_dockerfile,
            expected_context,
        )
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.args[1], expected_context)

    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_missing_auth_file_warns_and_continues(self, run_mock):
        with mock.patch("ai_sandbox.cli.sys.stderr", new_callable=mock.MagicMock):
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

    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_no_auth_skips_warning(self, run_mock):
        with mock.patch(
            "ai_sandbox.cli.sys.stderr", new_callable=mock.MagicMock
        ) as stderr_mock:
            cli.main(
                [
                    "--no-build",
                    "--context",
                    ".",
                    "--no-auth",
                ]
            )
        self.assertIsNone(run_mock.call_args.args[5])
        stderr_mock.write.assert_not_called()

    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_auth_file_none_skips_warning(self, run_mock):
        with mock.patch(
            "ai_sandbox.cli.sys.stderr", new_callable=mock.MagicMock
        ) as stderr_mock:
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
        stderr_mock.write.assert_not_called()

    @mock.patch("ai_sandbox.cli.os.path.isfile", return_value=False)
    @mock.patch("ai_sandbox.cli.sys.stderr", new_callable=mock.MagicMock)
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_missing_auth_file_warns_with_resolved_candidates(
        self,
        run_mock,
        stderr_mock,
        _isfile_mock,
    ):
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
        stderr_mock.write.assert_any_call(
            "Warning: auth file not found at "
            f"{os.path.expanduser('~/.codex/device_auth.json')}. "
            "Continuing without mounting credentials."
        )

    @mock.patch("ai_sandbox.cli.os.path.isfile", return_value=False)
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_auth_file_relative_uses_context(self, run_mock, _isfile_mock):
        with mock.patch(
            "ai_sandbox.cli.sys.stderr", new_callable=mock.MagicMock
        ) as stderr_mock:
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
        stderr_mock.write.assert_any_call(
            "Warning: auth file not found at "
            "/ctx/rel/device_auth.json. "
            "Continuing without mounting credentials."
        )

    @mock.patch("ai_sandbox.cli.os.path.isfile")
    @mock.patch("ai_sandbox.cli.run_container")
    @mock.patch("ai_sandbox.cli.build_image")
    def test_main_uses_first_existing_auth_default(
        self,
        build_mock,
        run_mock,
        isfile_mock,
    ):
        def isfile_side_effect(path):
            return path.endswith("/.codex/auth.json")

        isfile_mock.side_effect = isfile_side_effect

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

    @mock.patch("ai_sandbox.cli.os.path.isfile", return_value=True)
    @mock.patch("ai_sandbox.cli.run_container")
    def test_main_no_auth_overrides_auth_file(self, run_mock, _isfile_mock):
        with mock.patch(
            "ai_sandbox.cli.sys.stderr", new_callable=mock.MagicMock
        ) as stderr_mock:
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
        stderr_mock.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
