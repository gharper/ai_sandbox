import os
import unittest


class TestDockerfile(unittest.TestCase):
    def test_copilot_installed(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        dockerfile_path = os.path.join(repo_root, "Dockerfile")
        with open(dockerfile_path, "r", encoding="utf-8") as handle:
            contents = handle.read()
        self.assertIn("@github/copilot", contents)


if __name__ == "__main__":
    unittest.main()
