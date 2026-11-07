#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""article-to-obsidian 同步组件 · 使用前同步（拉最新）

解决「跨 PC 使用时要手动 pull」的痛点：每次归档**开始前**跑一次本脚本，
自动把本地同步到远端最新状态，保证数据一致性和最新性。

与 sync_check.py / precommit_check.py 的分工：
    use_check.py       使用前 —— 拉最新（本文件，主动同步）
    sync_check.py      提交前 —— 防覆盖（检查 ahead/behind/skill 冲突）
    precommit_check.py 提交前 —— 防脏文件（列出非本次任务的文件）

三步构成「使用前拉 → 提交前查 → 提交后推」的完整闭环。

同步策略（单作者 + 线性历史模型）：
    1. fetch 远端，计算 ahead / behind / 分叉；
    2. behind>0 且未分叉 → 自动 `git pull --rebase`（保持线性历史，无 merge commit）；
    3. 分叉（两边都改了）→ 停下，交人工处理（单作者下极罕见，通常意味着换机前忘提交）；
    4. ahead>0 → 提示本机有未推送提交，不阻断（用户可继续归档，稍后统一推）。

退出码（与 sync_check.py 对齐）：
    0  已同步（或本就最新），可继续归档
    1  需人工介入（rebase 冲突 / 分叉）
    2  错误（不在 git 仓库 / 无法 fetch）

用法：
    python use_check.py [--repo <库根>]
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def _run(args: list[str], cwd: str | None = None) -> tuple[int, str]:
    """执行 git 命令，返回 (exit_code, stdout)。找不到 git 时返回 (127, "")。"""
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=cwd,
        )
        return out.returncode, out.stdout.strip()
    except FileNotFoundError:
        return 127, ""


def _count(revspec: str, cwd: str) -> int:
    code, out = _run(["rev-list", "--count", revspec], cwd=cwd)
    if code != 0 or not out.isdigit():
        return -1
    return int(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="使用前同步：拉最新，保证数据一致性")
    ap.add_argument("--repo", default=".", help="库根路径")
    args = ap.parse_args()
    repo = args.repo

    # 0) 确认在 git 仓库内
    code, _ = _run(["rev-parse", "--is-inside-work-tree"], cwd=repo)
    if code != 0:
        print("错误：不在 git 仓库内。")
        return 2

    # 1) 当前分支
    code, branch = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    if code != 0 or not branch:
        print("错误：无法确定当前分支。")
        return 2

    # 2) fetch 远端（不碰工作区）
    print(f"同步检查（分支 {branch}）…")
    code, _ = _run(["fetch", "origin", branch], cwd=repo)
    if code != 0:
        print("错误：无法 fetch 远端（检查网络 / 远端地址）。")
        return 2

    # 3) 计算 ahead / behind
    ahead = _count(f"origin/{branch}..{branch}", cwd=repo)
    behind = _count(f"{branch}..origin/{branch}", cwd=repo)
    if ahead < 0 or behind < 0:
        print("错误：无法读取远端提交（远端可能尚未 fetch 成功）。")
        return 2

    # 4) 分叉检测：两边都有对方没有的提交
    if ahead > 0 and behind > 0:
        print("\n⚠ 本地与远端已分叉（本地领先 {} 提交，落后 {} 提交）：".format(ahead, behind))
        print("  这通常意味着你在另一台机器上提交后，这台机器没有先同步就又改了内容。")
        print("  自动合并有风险，请人工处理：")
        print("    ① git log --oneline origin/{}..{} 看本地多出的提交".format(branch, branch))
        print("    ② 决定用 git rebase 还是手动取舍")
        print("  回退可用：git rebase --abort")
        return 1

    # 5) 落后远端 → 自动 rebase
    if behind > 0:
        print(f"本地落后远端 {behind} 个提交，自动同步（pull --rebase）…")
        code, out = _run(["pull", "--rebase", "origin", branch], cwd=repo)
        if code != 0:
            print("\n⚠ 自动同步失败（rebase 冲突）：")
            print(out[-2000:] if out else "")
            print("  请人工处理：git rebase --abort 可回退，或手动解决冲突后 git rebase --continue。")
            return 1
        # rebase 成功后重新计算 ahead
        ahead = _count(f"origin/{branch}..{branch}", cwd=repo)
        print(f"✓ 已同步到远端最新（本地领先 {ahead} 个提交）。")
        return 0

    # 6) 领先远端 → 提示不阻断
    if ahead > 0:
        print(f"✓ 本地领先远端 {ahead} 个提交（本机有未推送的提交，稍后提交时统一推送）。")
        return 0

    print("✓ 本地与远端一致，已是最新。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
