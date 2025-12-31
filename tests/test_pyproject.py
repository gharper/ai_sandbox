import os
import subprocess
import sys
import tomllib
import unittest


class TestPyproject(unittest.TestCase):
    def test_cli_entrypoint_declared(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        pyproject_path = os.path.join(repo_root, "pyproject.toml")
        with open(pyproject_path, "rb") as handle:
            data = tomllib.load(handle)

        scripts = data.get("project", {}).get("scripts", {})
        self.assertEqual(scripts.get("ai_sandbox"), "ai_sandbox.cli:main")

    def test_module_entrypoint_exists(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        main_path = os.path.join(repo_root, "ai_sandbox", "__main__.py")
        self.assertTrue(os.path.isfile(main_path))

    def test_cli_module_exists(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        cli_path = os.path.join(repo_root, "ai_sandbox", "cli.py")
        self.assertTrue(os.path.isfile(cli_path))

    def test_module_invocation_help(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        env = os.environ.copy()
        env["PYTHONPATH"] = repo_root
        result = subprocess.run(
            [sys.executable, "-m", "ai_sandbox", "--help"],
            cwd=repo_root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage:", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
