#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""use_check.py 集成测试：在临时 git 仓库里验证同步逻辑。

覆盖四种场景：
  1. 本地与远端一致 → 退出码 0，不产生变更
  2. 本地落后远端 → 自动 rebase，退出码 0，本地追上远端
  3. 本地领先远端 → 退出码 0，不推送
  4. 分叉 → 退出码 1，停下交人工

依赖真实 git 命令，故归入集成测试；环境无 git 时跳过。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import use_check  # noqa: E402


def _git(args, cwd):
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", cwd=cwd
    )


def _have_git() -> bool:
    return shutil.which("git") is not None


@unittest.skipUnless(_have_git(), "环境无 git，跳过集成测试")
class TestUseCheck(unittest.TestCase):
    def _make_repo(self):
        """建一个本地仓库，带一个 'origin' 裸远端，返回 (workdir, bare_dir)。"""
        tmp = tempfile.mkdtemp()
        bare = os.path.join(tmp, "origin.git")
        work = os.path.join(tmp, "work")
        _git(["init", "--bare", bare], tmp)
        _git(["init", work], tmp)
        _git(["config", "user.email", "t@t.com"], work)
        _git(["config", "user.name", "t"], work)
        _git(["remote", "add", "origin", bare], work)
        # 初始提交并推送
        with open(os.path.join(work, "f.txt"), "w") as f:
            f.write("v1")
        _git(["add", "f.txt"], work)
        _git(["commit", "-m", "init"], work)
        _git(["push", "-u", "origin", "master"], work)
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return work, bare

    def _commit_and_push(self, work, content, msg):
        with open(os.path.join(work, "f.txt"), "w") as f:
            f.write(content)
        _git(["add", "f.txt"], work)
        _git(["commit", "-m", msg], work)
        _git(["push", "origin", "master"], work)

    def test_本地与远端一致_退出码0(self):
        work, _ = self._make_repo()
        code = subprocess.run(
            [sys.executable, "-m", "use_check", "--repo", work],
            capture_output=True, text=True, encoding="utf-8",
        ).returncode
        self.assertEqual(code, 0)

    def test_落后远端_自动rebase(self):
        work, bare = self._make_repo()
        # 用第二个克隆模拟「另一台机器」推进远端
        tmp = tempfile.mkdtemp()
        other = os.path.join(tmp, "other")
        _git(["clone", bare, other], tmp)
        _git(["config", "user.email", "t@t.com"], other)
        _git(["config", "user.name", "t"], other)
        self._commit_and_push(other, "v2-from-other", "remote advance")
        shutil.rmtree(tmp, ignore_errors=True)

        # 本机此时落后，跑 use_check 应自动 rebase
        # 直接调用 main 会走 argparse，这里用 subprocess 调用脚本更真实
        code = subprocess.run(
            [sys.executable, "-m", "use_check", "--repo", work],
            capture_output=True, text=True, encoding="utf-8",
        ).returncode
        self.assertEqual(code, 0)
        # 本地应已包含远端提交
        with open(os.path.join(work, "f.txt")) as f:
            self.assertEqual(f.read(), "v2-from-other")

    def test_领先远端_不推送_退出码0(self):
        work, _ = self._make_repo()
        self._commit_and_push(work, "v2-local", "local advance")  # 已推送，领先为0
        # 再本地提交但不推送
        with open(os.path.join(work, "f.txt"), "w") as f:
            f.write("v3-local-unpushed")
        _git(["add", "f.txt"], work)
        _git(["commit", "-m", "local unpushed"], work)

        code = subprocess.run(
            [sys.executable, "-m", "use_check", "--repo", work],
            capture_output=True, text=True, encoding="utf-8",
        ).returncode
        self.assertEqual(code, 0)

    def test_分叉_退出码1(self):
        work, bare = self._make_repo()
        # 另一台机器推进远端
        tmp = tempfile.mkdtemp()
        other = os.path.join(tmp, "other")
        _git(["clone", bare, other], tmp)
        _git(["config", "user.email", "t@t.com"], other)
        _git(["config", "user.name", "t"], other)
        self._commit_and_push(other, "v2-other", "other side")
        shutil.rmtree(tmp, ignore_errors=True)
        # 本机未先 pull 就本地提交 → 分叉
        with open(os.path.join(work, "f.txt"), "w") as f:
            f.write("v2-local")
        _git(["add", "f.txt"], work)
        _git(["commit", "-m", "local without pull"], work)

        code = subprocess.run(
            [sys.executable, "-m", "use_check", "--repo", work],
            capture_output=True, text=True, encoding="utf-8",
        ).returncode
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
