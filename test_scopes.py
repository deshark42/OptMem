#!/usr/bin/env python3
"""Observable memory behaviors. Run: python3 -B -m unittest test_scopes."""

import importlib.util
from importlib.machinery import SourceFileLoader
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest


MEMO = Path(__file__).resolve().with_name("memo")
SCOPES = ("user", "global", "workspace")


def fingerprint(path):
    return {str(p.relative_to(path)): p.read_bytes()
            for p in Path(path).rglob("*") if p.is_file() and p.name != ".lock"}


class MemoryBehavior(unittest.TestCase):
    def setUp(self):
        scratch = Path.home() / "tmp" / "OptMem"
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="scopes-", dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home, self.project, self.other = [self.base / p for p in ("home", "project's dir", "other")]
        for path in (self.home, self.project, self.other):
            path.mkdir()
        self.root = self.base / "memory root"
        self.env = {k: v for k, v in os.environ.items()
                    if k not in {"MEMORY_DIR", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"}}
        self.env.update(HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1")
        loader = SourceFileLoader("memo_fixture", str(MEMO))
        self.fixture = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(self.fixture)

    def cli(self, *args, cwd=None, env=None, root=True, error=None):
        argv = [sys.executable, str(MEMO), *map(str, args)]
        if root:
            argv += ["--memory-dir", str(self.root)]
        result = subprocess.run(argv, cwd=cwd or self.project, env=env or self.env,
                                capture_output=True, text=True, timeout=20)
        self.assertNotIn("Traceback", result.stderr)
        if error is None:
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        self.assertNotEqual(result.returncode, 0)
        self.assertRegex(result.stdout + result.stderr, error)
        return result.stdout + result.stderr

    def seed(self, scope, entries, levels=None):
        """Build histories cheaply; behavior assertions always use the CLI."""
        if isinstance(entries, int):
            entries = [("2020-01-01", "%s memory %d" % (scope, i)) for i in range(entries)]
        path = (self.fixture.ensure_workspace(str(self.root), str(self.project))
                if scope == "workspace" else str(self.root / scope))
        self.fixture.log_append(path, entries)
        count, size = self.fixture.log_len(path), 2
        while size <= count:
            if levels is None or size in levels:
                for lo in range(0, count - size + 1, size):
                    self.fixture.tree_put(path, lo, lo + size, "summary")
            size *= 2
        return path

    def continuation(self, output):
        return next((line[5:] for line in output.splitlines()
                     if line.startswith("Run: ") and "--snapshot" in line), None)

    def pages(self, first, line_cap=500, byte_cap=20000):
        pages, page = [], first
        while True:
            self.assertLess(len(pages), 100)
            self.assertLessEqual(len(page.encode()), byte_cap)
            self.assertLessEqual(len(page.splitlines()), line_cap)
            pages.append(page)
            order = self.continuation(page)
            if order is None:
                self.assertTrue(page.rstrip().endswith("You are awake."))
                return "\n".join(pages)
            self.assertNotIn("You are awake.", page)
            env = dict(self.env, MEMORY_DIR=str(self.base / "wrong root"))
            result = subprocess.run(order, shell=True, cwd=self.other, env=env,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            page = result.stdout

    def test_init_creates_only_shared_memory_and_preserves_existing_history(self):
        self.assertIn("the user's preferences and background", self.cli("init"))
        for scope in ("user", "global"):
            self.assertTrue((self.root / scope / "LOG.txt").is_file())
        self.assertFalse((self.root / "workspaces").exists())
        self.assertNotIn("Scopes:", self.cli("wake"))
        self.cli("note", "personal", "--scope", "user")
        before = fingerprint(self.root)
        self.cli("init")
        self.assertEqual(fingerprint(self.root), before)
        self.assertEqual(list(self.project.iterdir()), [])
        self.assertFalse(list(self.home.rglob("AGENTS.md")))

    def test_switching_directories_shares_personal_memory_but_not_workspace_memory(self):
        self.cli("init")
        self.cli("wake")
        for scope in SCOPES:
            self.cli("note", "fact " + scope, "--scope", scope)
        self.cli("wake", cwd=self.other)
        output = self.cli("recall", "fact", cwd=self.other)
        self.assertIn("user:#0", output)
        self.assertIn("global:#0", output)
        self.assertNotIn("fact workspace", output)
        output = self.cli("wake", "--workspace", self.project, cwd=self.other)
        self.assertIn("workspace:#0", output)
        self.assertNotIn("[workspace:", output)

    def test_writes_need_an_initialized_store_and_an_explicit_scope(self):
        self.cli("wake", error="memo init")
        self.assertFalse(self.root.exists())
        self.cli("init")
        self.cli("note", "fact", "--scope", "workspace", error="wake")
        self.assertIn("skipped", self.cli("recall", "."))
        for args in (("note", "fact"), ("nap",), ("zoom", "0-1"),
                     ("forget", "0-1"), ("import", "unused.txt")):
            with self.subTest(command=args[0]):
                self.cli(*args, error="--scope")
        self.assertFalse((self.root / "workspaces").exists())

    def test_root_selection_prefers_cli_then_environment_then_saved_init(self):
        self.cli("init")
        self.cli("note", "saved", "--scope", "user", root=False)
        env = dict(self.env, MEMORY_DIR=str(self.base / "env memory"))
        self.cli("init", env=env, root=False)
        self.cli("note", "environment", "--scope", "user", root=False, env=env)
        self.cli("note", "explicit", "--scope", "user", env=env)
        output = self.cli("recall", ".", "--scope", "user", root=False)
        self.assertIn("saved", output)
        self.assertIn("explicit", output)
        self.assertNotIn("environment", output)
        self.assertIn("environment", self.cli("recall", ".", root=False, env=env))

    def test_scope_filter_ignores_other_stores_and_does_not_create_a_workspace(self):
        self.cli("init")
        self.seed("user", 2)
        (self.root / "global" / "LOG.txt").write_bytes(b"corrupt unselected store")
        for command in (("wake",), ("recall", "memory")):
            self.assertIn("user:#0", self.cli(*command, "--scope", "user"))
        self.assertFalse((self.root / "workspaces").exists())

    def test_config_rejects_invalid_changes_without_losing_previous_settings(self):
        self.cli("init")
        self.cli("config", "USER_WAKE_WEIGHT=3", "ENTRY_CHARS=20")
        before = (self.root / "config").read_bytes()
        self.cli("config", "USER_WAKE_WEIGHT=7", "GLOBAL_WAKE_WEIGHT=0", error="positive")
        self.assertEqual((self.root / "config").read_bytes(), before)
        self.cli("note", "x" * 21, "--scope", "user", error="long|bytes")
        self.cli("config", "USER_WAKE_WEIGHT=")
        self.assertRegex(self.cli("config"), r"USER_WAKE_WEIGHT\s+1\b")

    def test_init_and_wake_do_not_reclassify_legacy_history(self):
        self.root.mkdir()
        (self.root / "LOG.txt").write_text("legacy history")
        before = fingerprint(self.root)
        for command in ("init", "wake"):
            self.cli(command, error="[Ll]egacy|migration")
            self.assertEqual(fingerprint(self.root), before)

    def test_colliding_workspace_names_cannot_read_or_overwrite_another_history(self):
        first, second = self.base / "a-b" / "c", self.base / "a" / "b-c"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        self.cli("init")
        self.cli("wake", "--workspace", first)
        before = fingerprint(self.root)
        self.cli("recall", ".", "--workspace", second, error="collision")
        self.cli("note", "no write", "--scope", "workspace", "--workspace", second, error="collision")
        self.assertEqual(fingerprint(self.root), before)

    def test_linked_memory_directories_and_files_work_as_normal_paths(self):
        self.cli("init")
        user, linked = self.root / "user", self.base / "linked user"
        user.rename(linked)
        user.symlink_to(linked, target_is_directory=True)
        target = self.base / "linked log"
        log = user / "LOG.txt"
        log.rename(target)
        log.symlink_to(target)
        self.cli("note", "linked memory", "--scope", "user")
        self.assertIn("linked memory", self.cli("recall", "linked", "--scope", "user"))
        self.assertIn("linked memory", target.read_text())

    @unittest.skipUnless(os.path.isdir("/proc/self/fd"), "Linux long-path support")
    def test_long_unicode_and_percent_paths_can_keep_separate_memories_centrally(self):
        self.cli("init")
        linked = self.base / "linked workspaces"
        linked.mkdir()
        (self.root / "workspaces").symlink_to(linked, target_is_directory=True)
        for component, depth in (("项目" * 12, 4), ("%" * 100, 14)):
            with self.subTest(component=component[:2]):
                project = self.base
                for _ in range(depth):
                    project /= component
                project.mkdir(parents=True)
                self.cli("wake", "--workspace", project)
                self.cli("note", component[:2], "--scope", "workspace", "--workspace", project)
                self.assertIn(component[:2], self.cli("wake", "--workspace", project))
                self.assertEqual(list(project.iterdir()), [])

    def test_unused_budget_is_reassigned_and_scope_filter_gets_the_whole_budget(self):
        self.cli("init")
        for scope, count in zip(SCOPES, (8, 12, 100)):
            self.seed(scope, count)
        self.assertIn("user=8, global=12, workspace=76 (total 96/96)", self.cli("wake"))
        output = self.cli("wake", "--scope", "workspace")
        self.assertEqual(len(re.findall(r"(?m)^workspace:#", output)), 96)
        self.seed("user", 120)
        self.seed("global", 116)
        self.cli("config", "USER_WAKE_WEIGHT=10", "GLOBAL_WAKE_WEIGHT=1", "WORKSPACE_WAKE_WEIGHT=1")
        self.assertIn("user=80, global=8, workspace=8 (total 96/96)", self.cli("wake"))

    def test_insufficient_budget_refuses_to_hide_history_and_keeps_recall_available(self):
        self.cli("init")
        for scope in SCOPES:
            self.seed(scope, 3)
        self.cli("config", "WAKE_LINES=4")
        self.cli("wake", error="Increase WAKE_LINES")
        self.assertIn("3 matches", self.cli("recall", "memory", "--scope", "user"))

    def test_pages_keep_all_memories_and_compression_prompts_within_transport_limits(self):
        self.cli("init")
        for scope in SCOPES:
            self.seed(scope, [("2020-01-01", "é" * 140 if i < 16 else "tail " + "x" * 35)
                              for i in range(32)], levels=(2, 4, 8))
        for line_cap in (500, 10):
            with self.subTest(line_cap=line_cap):
                self.cli("config", "PART_LINES=%d" % line_cap)
                output = self.pages(self.cli("wake"), line_cap=line_cap)
                for scope in SCOPES:
                    self.assertEqual(re.findall(r"(?m)^" + scope + r":#(\d+) ", output),
                                     list(map(str, range(32))))
                self.assertEqual(output.count("Compress memories #0-15"), 3)

    def test_continuations_keep_the_original_read_despite_new_notes_or_context_changes(self):
        self.cli("init")
        self.cli("config", "PART_LINES=8")
        for scope in SCOPES:
            self.seed(scope, 4, levels=())
        first = self.cli("wake")
        for scope in SCOPES:
            self.cli("note", "added after snapshot", "--scope", scope)
            path = self.root / scope if scope != "workspace" else self.fixture.ensure_workspace(
                str(self.root), str(self.project))
            for lo, hi in ((0, 2), (2, 4), (0, 4)):
                self.fixture.tree_put(str(path), lo, hi, "finished mid-snapshot")
        output = self.pages(first, line_cap=8)
        self.assertNotIn("added after snapshot", output)
        self.assertEqual(output.count("Compress memories #0-1"), 3)
        for scope in SCOPES:
            self.assertEqual(len(re.findall(r"(?m)^" + scope + r":#\d+ ", output)), 4)

    def test_continuation_refuses_changed_settings_or_rewritten_summaries(self):
        self.cli("init")
        self.seed("user", 16)
        self.cli("config", "WAKE_LINES=8", "PART_LINES=8")
        first = self.cli("wake")
        args = shlex.split(self.continuation(first))
        part, token = args[args.index("wake") + 1], args[-1]
        self.cli("config", "USER_WAKE_WEIGHT=3")
        self.cli("wake", part, "--snapshot", token, error="limits changed")
        self.cli("config", "USER_WAKE_WEIGHT=")
        block = re.search(r"user:#(\d+-\d+) ", first).group(1)
        self.cli("forget", block, "--scope", "user")
        while True:
            prompt = self.cli("nap", "--scope", "user")
            block = re.search(r"Compress memories #(\d+-\d+)", prompt)
            if block is None:
                break
            self.cli("nap", block.group(1), "rewritten summary", "--scope", "user")
        self.cli("wake", part, "--snapshot", token, error="contents changed")

    def test_malformed_pages_and_unusable_limits_report_errors_before_reading(self):
        self.cli("init")
        self.cli("wake", "²", error="usage: memo wake")
        self.assertFalse((self.root / "workspaces").exists())
        self.seed("user", [("2025-01-01", "needle" + "\u2028" * 20 + "tail")])
        self.cli("config", "PART_LINES=5")
        output = self.cli("wake", "--scope", "user", error="Increase the paging limits")
        self.assertNotIn("user:#", output)

    def test_compression_recovery_and_tree_maintenance_stay_in_the_selected_scope(self):
        self.cli("init")
        self.seed("user", 8, levels=())
        self.cli("config", "WAKE_LINES=4")
        output = self.cli("wake", "--scope", "user", error="Complete the scoped compression")
        self.assertIn("--scope user", output)
        for scope in ("global", "workspace"):
            self.seed(scope, 4)
        before = self.cli("recall", "memory", "--scope", "workspace")
        self.assertIn("global:#1", self.cli("zoom", "0-1", "--scope", "global"))
        self.cli("forget", "0-1", "--scope", "global")
        self.assertIn("--scope global", self.cli("nap", "--scope", "global"))
        self.cli("nap", "0-1", "rebuilt", "--scope", "global")
        self.assertEqual(self.cli("recall", "memory", "--scope", "workspace"), before)

    def test_recall_keeps_newest_matches_across_scopes_even_after_future_dated_imports(self):
        self.cli("init")
        self.seed("user", [("2099-01-01", "needle future"), ("2026-01-01", "needle today"),
                           ("2100-01-01", "needle " + "x" * 200)])
        self.seed("global", [("2025-01-01", "needle global " + "é" * 8)])
        self.seed("workspace", [("2020-01-01", "needle " + "é" * 12)] * 6)
        self.cli("config", "PART_CHARS=120")
        output = self.cli("recall", "needle")
        self.assertIn("user:#0 2099", output)
        self.assertIn("user:#1 2026", output)
        self.assertNotIn("workspace:#", output)
        self.assertNotIn("user:#2", output)
        self.assertIn("of 10 matches shown", output)


if __name__ == "__main__":
    unittest.main()
