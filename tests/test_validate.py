import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = Path(".github/workflows/common-repo.yaml")
SOURCE = ROOT / "src" / WORKFLOW
VERSION = "v0.38.2"


def command(*args, cwd, env=None):
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)


def shell_step(name):
    text = SOURCE.read_text()
    step = text.split(f"      - name: {name}\n", 1)[1].split("\n      - ", 1)[0]
    if "        run: |\n" in step:
        return "\n".join(line[10:] for line in step.split("        run: |\n", 1)[1].splitlines())
    return step.split("        run: ", 1)[1].strip()


class ConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.consumer = Path(self.temp.name)
        self.config = self.consumer / ".common-repo.yaml"
        self.config.write_text(f"- repo:\n    url: {ROOT}\n")
        self.rendered = self.consumer / WORKFLOW

    def cr(self, *args):
        return command("common-repo", *args, cwd=self.consumer)

    def apply(self):
        result = self.cr("apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return self.rendered.read_text()

    def test_public_defaults_need_no_app_token(self):
        text = self.apply()
        self.assertNotIn("__COMMON_REPO__", text)
        self.assertIn('PRIVATE_REPOSITORIES: ""', text)
        self.assertIn(f"version: {VERSION}", text)
        self.assertIn("run: common-repo validate", text)
        self.assertIn("run: common-repo diff", text)
        self.assertEqual(text.count("if: env.PRIVATE_REPOSITORIES != ''"), 2)

    def test_private_upstreams_render_consumer_values(self):
        self.config.write_text(
            self.config.read_text()
            + "    with:\n"
            + "      - template-vars:\n"
            + "          GH_APP_ID_SECRET: FIXTURE_CLIENT_ID\n"
            + "          GH_APP_KEY_SECRET: FIXTURE_PRIVATE_KEY\n"
            + "          GH_APP_OWNER: fixture-org\n"
            + "          VALIDATE_PRIVATE_REPOSITORIES: private-a,private-b\n"
            + "          COMMON_REPO_VERSION: v0.38.1\n"
        )
        text = self.apply()
        for value in (
            "secrets.FIXTURE_CLIENT_ID", "secrets.FIXTURE_PRIVATE_KEY",
            'APP_OWNER: "fixture-org"',
            'PRIVATE_REPOSITORIES: "private-a,private-b"', "version: v0.38.1",
        ):
            self.assertIn(value, text)
        self.assertNotIn("COMMON_REPO_BOT", text)
        self.assertNotIn("__COMMON_REPO__", text)

    def test_only_validation_is_exported_and_custom_ci_survives(self):
        custom = self.consumer / ".github/workflows/ci.yaml"
        custom.parent.mkdir(parents=True)
        original = b"name: Custom CI\non: [pull_request, merge_group]\njobs: {}\n"
        custom.write_bytes(original)
        self.apply()
        self.assertEqual(custom.read_bytes(), original)
        actual = {str(path.relative_to(self.consumer)) for path in self.consumer.rglob("*") if path.is_file()}
        self.assertEqual(actual, {".common-repo.yaml", str(WORKFLOW), ".github/workflows/ci.yaml"})

    def test_validate_and_clean_diff_succeed(self):
        self.apply()
        for operation in ("validate", "diff"):
            result = self.cr(operation)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_apply_is_idempotent(self):
        self.apply()
        first = self.rendered.read_bytes()
        self.apply()
        self.assertEqual(self.rendered.read_bytes(), first)
        self.assertEqual(self.cr("diff").returncode, 0)

    def test_modified_managed_workflow_fails_without_repairing_it(self):
        self.apply()
        changed = self.rendered.read_text().replace("run: common-repo diff", "run: true")
        self.rendered.write_text(changed)
        result = self.cr("diff")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.rendered.read_text(), changed)

    def test_deleted_managed_workflow_fails(self):
        self.apply()
        self.rendered.unlink()
        result = self.cr("diff")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse(self.rendered.exists())

    def test_unmanaged_file_does_not_fail_parity(self):
        self.apply()
        (self.consumer / "application.txt").write_text("consumer-owned\n")
        self.assertEqual(self.cr("diff").returncode, 0)


class WorkflowContractTests(unittest.TestCase):
    def test_template_variables_match_source_and_self_defaults(self):
        config = (ROOT / ".common-repo.yaml").read_text()
        defaults = dict(re.findall(r"^    ([A-Z_]+): (.*)$", config, re.M))
        self_defaults = dict(re.findall(r"^      ([A-Z_]+): (.*)$", config, re.M))
        sentinels = set(re.findall(r"__COMMON_REPO__([A-Z_]+)__", SOURCE.read_text()))
        self.assertEqual(set(defaults), sentinels)
        self.assertEqual(defaults, self_defaults)
        self.assertEqual(defaults["COMMON_REPO_VERSION"], VERSION)
        self.assertIn(f"version: {VERSION}", (ROOT / ".github/workflows/ci.yaml").read_text())

    def test_gate_is_read_only_pinned_and_merge_queue_compatible(self):
        text = SOURCE.read_text()
        for line in ("  pull_request:", "  merge_group:", "  workflow_call:", "  workflow_dispatch:"):
            self.assertIn(line, text)
        self.assertNotIn("pull_request_target", text)
        self.assertNotIn("continue-on-error", text)
        self.assertNotIn(": write", text)
        self.assertIn("permission-contents: read", text)
        self.assertIn("repositories: ${{ env.PRIVATE_REPOSITORIES }}", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("if: always() && env.PRIVATE_REPOSITORIES != ''", text)
        for workflow in (SOURCE, ROOT / ".github/workflows/ci.yaml"):
            actions = re.findall(r"uses: (\S+)", workflow.read_text())
            self.assertTrue(actions)
            for action in actions:
                self.assertRegex(action, r"^[\w.-]+/[\w./-]+@[a-f0-9]{40}$")


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "RUNNER_TEMP": str(self.root),
            "GITHUB_ENV": str(self.root / "github-env"),
            "PRIVATE_REPOSITORIES": "private-a, private-b",
            "APP_OWNER": "fixture-org",
            "UPSTREAM_TOKEN": "fixture-not-a-real-token",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"),
        }
        self.auth_config = self.root / "common-repo-auth.gitconfig"

    def run_step(self, name):
        return command("bash", "-euo", "pipefail", "-c", shell_step(name), cwd=self.root, env=self.env)

    def test_auth_routes_only_listed_upstream_urls(self):
        result = self.run_step("Authenticate private upstream clones")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.auth_config.stat().st_mode & 0o777, 0o600)
        self.assertIn(f"GIT_CONFIG_GLOBAL={self.auth_config}", Path(self.env["GITHUB_ENV"]).read_text())
        env = {**self.env, "GIT_CONFIG_GLOBAL": str(self.auth_config)}
        for repository in ("private-a", "private-b"):
            for suffix in ("", ".git"):
                url = f"https://github.com/fixture-org/{repository}{suffix}"
                result = command("git", "ls-remote", "--get-url", url, cwd=self.root, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), url.replace("https://", "https://x-access-token:fixture-not-a-real-token@"))
        for url in ("https://github.com/other-org/private-a", "https://github.com/fixture-org/public"):
            result = command("git", "ls-remote", "--get-url", url, cwd=self.root, env=env)
            self.assertEqual(result.stdout.strip(), url)
        self.assertEqual(self.run_step("Remove private upstream credentials").returncode, 0)
        self.assertFalse(self.auth_config.exists())

    def test_invalid_repository_is_rejected_and_cleanup_is_safe(self):
        self.env["PRIVATE_REPOSITORIES"] = "private-a,../other-org"
        result = self.run_step("Authenticate private upstream clones")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(Path(self.env["GITHUB_ENV"]).exists())
        for _ in range(2):
            self.assertEqual(self.run_step("Remove private upstream credentials").returncode, 0)
        self.assertFalse(self.auth_config.exists())
