"""提交前同步检查：防止本地落后于远端却 push 覆盖掉远端更新。

核心场景：多会话并行用同一个库，远端可能已被别的会话推进了。
本脚本在提交前做两层检查：
  1. 提交计数：本地是 ahead / behind / 分叉？
  2. 文件级：skill 文件（SKILL.md + fetcher/）在远端是否被改动过？

判定与退出码：
  0  安全：本地领先或齐平远端，且远端未改动 skill，可直接提交
  1  需人工确认：本地落后远端（behind），或远端改动了 skill 文件
  2  错误：不在 git 仓库 / 无法 fetch

用法：
  python sync_check.py [--repo <库根>]
"""

from __future__ import annotations

import argparse
import subprocess
import sys

SKILL_DIR = ".workbuddy/skills/article-to-obsidian"


def _run(args: list[str], cwd: str | None = None) -> str:
    """执行 git 命令，返回 stdout（去尾部换行）。失败返回空串。"""
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=cwd,
        )
    except FileNotFoundError:
        return ""
    return out.stdout.strip()


def _count(revspec: str, cwd: str) -> int:
    """返回 revspec 指定的提交数，失败返回 -1。"""
    out = _run(["rev-list", "--count", revspec], cwd=cwd)
    if out == "" or not out.isdigit():
        return -1
    return int(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="提交前同步检查")
    ap.add_argument("--repo", default=".", help="库根路径")
    args = ap.parse_args()
    repo = args.repo

    # 0) 确认在 git 仓库内
    if not _run(["rev-parse", "--is-inside-work-tree"], cwd=repo):
        print("错误：不在 git 仓库内。")
        return 2

    # 1) fetch 远端（不碰工作区，只更新 origin/master 引用）
    print("fetch 远端引用…")
    _run(["fetch", "origin", "master"], cwd=repo)

    # 2) 提交计数：ahead / behind
    ahead = _count("origin/master..master", cwd=repo)
    behind = _count("master..origin/master", cwd=repo)

    if ahead < 0 or behind < 0:
        print("错误：无法读取远端提交（远端可能尚未 fetch 成功）。")
        return 2

    # 3) 文件级：远端是否改动了 skill 文件
    #    diff 本地工作区 SKILL.md / fetcher/ 与 origin/master 对应内容
    skill_changed_remote = False
    changed_files: list[str] = []

    # SKILL.md
    if _run(["diff", "--name-only", "master", "origin/master", "--", f"{SKILL_DIR}/SKILL.md"], cwd=repo):
        skill_changed_remote = True
        changed_files.append(f"{SKILL_DIR}/SKILL.md")

    # fetcher/ 目录
    if _run(["diff", "--name-only", "master", "origin/master", "--", f"{SKILL_DIR}/fetcher"], cwd=repo):
        skill_changed_remote = True
        changed_files.append(f"{SKILL_DIR}/fetcher/")

    # 4) 分类判定
    print(f"本地领先 {ahead} 个提交，落后远端 {behind} 个提交。")

    if behind > 0:
        print("\n⚠ 本地落后远端，远端有新的提交，提交前需人工确认：")
        print("  远端新增内容可能包含别人刚改的 skill 或笔记，直接 push 会覆盖。")
        print("  建议：先 git pull --rebase，合并远端后再决定。")
        return 1

    if skill_changed_remote:
        print("\n⚠ 远端改动了 skill 文件（有人也在维护 skill）：")
        for f in changed_files:
            print(f"    - {f}")
        print("  直接 push 会覆盖远端的 skill 更新。请人工确认：")
        print("    ① git log origin/master -3 -- skill路径 看别人改了什么；")
        print("    ② 决定是 rebase 合并、还是保留远端放弃本地。")
        return 1

    if ahead > 0:
        print("✓ 本地领先远端，且远端未改动 skill，可安全提交推送。")
    else:
        print("✓ 本地与远端齐平，无待推送提交。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
