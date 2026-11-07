#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编排入口回归测试：图片相对路径推导。

回归 bug：图片链接曾用相对 cwd 的 'notes' 做 relpath 基准。
库和 cwd 不在同一个盘符（如库在 D:、cwd 在 C:）时 relpath 直接抛
ValueError: path is on mount 'D:', start on mount 'C:'，整次抓取失败。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cli  # noqa: E402


class TestNotesDir(unittest.TestCase):
    def test_derive_from_attachments_dir(self):
        out = os.path.join("D:" + os.sep, "vault", "attachments", "某文章")
        notes = cli._notes_dir(out)
        self.assertEqual(
            os.path.normcase(notes),
            os.path.normcase(os.path.join("D:" + os.sep, "vault", "notes")),
        )

    def test_fallback_to_cwd_notes(self):
        # 不落在 attachments 结构里时退回 notes
        self.assertTrue(cli._notes_dir("/tmp/whatever").endswith("notes"))


if __name__ == "__main__":
    unittest.main()
