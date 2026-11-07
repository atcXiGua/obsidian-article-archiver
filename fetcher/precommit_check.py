"""提交前校验：防止把不属于本次任务的脏文件一起提交。

多会话并行使用同一个库时，工作区里可能躺着别人正在写、还没提交的文件。
本脚本对比「本次任务应提交的文件」与「git 实际未提交/未跟踪的文件」，
列出所有「本次不该动、却处于脏状态」的文件，提示先停下来确认，避免 git add 误伤。

用法：
    python precommit_check.py --keep "notes/xxx.md" "attachments/yyy/"

    --keep 传入本次任务自己产生的文件/目录（相对库根，可多个）。
    脚本会报告：① 有哪些脏文件不在 --keep 清单里（他人产物，别 add）；
                ② 本次 --keep 的文件里有哪些已存在同名（可能撞车）。

退出码：
    0  安全：工作区干净，或脏文件全部在 --keep 清单内
    1  警告：存在 --keep 清单之外的脏文件（他人产物，谨慎 add）
    2  错误：无法读取 git 状态（不在 git 仓库内等）
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _git_status_porcelain() -> list[str]:
    """返回 git status --porcelain 的输出行（不含空行）。"""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError:
        return []
    if out.returncode != 0:
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def _parse_path(line: str) -> str:
    """从 porcelain 行提取文件路径（处理重命名 `R  old -> new`）。"""
    line = line.rstrip()
    if " -> " in line:
        return line.split(" -> ", 1)[1]
    return line[3:]


def _is_under(path: str, keep: list[str]) -> bool:
    """判断路径是否落在任一 --keep 项之下（精确文件名或目录前缀）。"""
    p = path.replace("\\", "/")
    for k in keep:
        k = k.replace("\\", "/").rstrip("/")
        if p == k or p.startswith(k + "/"):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="提交前校验：列出不属于本次任务的脏文件")
    ap.add_argument(
        "--keep",
        nargs="*",
        default=[],
        help="本次任务自己产生的文件/目录（相对库根，可多个）",
    )
    ap.add_argument("--quiet", action="store_true", help="仅输出问题，无问题时不打印")
    args = ap.parse_args()

    dirty = _git_status_porcelain()
    if not dirty:
        if not args.quiet:
            print("工作区干净，无待提交文件。")
        return 0

    dirty_paths = [_parse_path(ln) for ln in dirty]

    # ① 不在 --keep 清单里的脏文件 = 他人产物
    others = [p for p in dirty_paths if not _is_under(p, args.keep)]

    # ② 本次 --keep 清单里，实际命中的文件（供确认）
    mine = [p for p in dirty_paths if _is_under(p, args.keep)]

    if others:
        print("⚠ 检测到 --keep 清单之外的脏文件（可能是其他会话的产物，请勿 add -A）：")
        for p in others:
            print(f"    - {p}")
        print()
    else:
        if not args.quiet:
            print("✓ 所有脏文件都在 --keep 清单内，可安全提交。")

    if mine:
        if not args.quiet:
            print("本次任务将提交的文件：")
            for p in mine:
                print(f"    + {p}")
    elif not others:
        print("⚠ 未命中任何 --keep 文件，请检查路径是否正确。")

    if others:
        print("建议：只 git add 本次自己的文件；确认无误后再提交。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
