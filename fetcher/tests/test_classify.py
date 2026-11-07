#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分类管理组件回归测试：标签收敛、分文件夹、图片路径修正、MOC、图谱配色。

通用化：测试用显式 config 注入主题体系（不依赖内置默认值），
验证「config 驱动分类」这一核心机制。
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import classify  # noqa: E402

# 测试用 config：明确的主题体系，避免依赖内置默认
TEST_CFG = {
    "vault_path": "",
    "notes_dir": "notes",
    "attachments_dir": "attachments",
    "taxonomy": {
        "primary_themes": ["数据工程", "AI工程"],
        "title_to_theme": [
            ["数仓", "数据工程"],
            ["Codex", "AI工程"],
        ],
        "graph_colors": [
            {"query": "tag:#主题/数据工程", "rgb": 14048348},
            {"query": "tag:#主题/AI工程", "rgb": 4521984},
        ],
    },
}


class TestResolveTheme(unittest.TestCase):
    def test_数仓匹配数据工程(self):
        self.assertEqual(classify.resolve_theme("数仓规范2026版", TEST_CFG), "数据工程")

    def test_codex匹配AI工程(self):
        self.assertEqual(classify.resolve_theme("深入解析Codex智能体循环", TEST_CFG), "AI工程")

    def test_未命中返回None(self):
        self.assertIsNone(classify.resolve_theme("一篇讲烹饪的文章", TEST_CFG), None)


class TestFixImgPaths(unittest.TestCase):
    def test_depth2加一层回退(self):
        content = "![图](../attachments/x/01.png)"
        out = classify._fix_img_paths(content, depth=2)
        self.assertIn("](../../attachments/x/01.png)", out)

    def test_depth1不变(self):
        content = "![图](../attachments/x/01.png)"
        self.assertEqual(classify._fix_img_paths(content, depth=1), content)


class TestCmdTag(unittest.TestCase):
    def _make_note(self, d, title, theme_tag=None):
        tags = ["  - 类型/教程规范\n"]
        if theme_tag:
            tags.append(f"  - 主题/{theme_tag}\n")
        tags.append("  - 主题/其他\n")
        content = (
            f"---\ntitle: {title}\nsource: 测试\n"
            f"published: 2026-01-01\ntags:\n{''.join(tags)}---\n\n正文\n"
        )
        p = os.path.join(d, f"{title}-2026-01-01.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_补一级主题锚点(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._make_note(d, "数仓规范2026版")
            r = classify.cmd_tag(d, TEST_CFG)
            self.assertEqual(r["tagged"], 1)
            with open(p, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("  - 主题/数据工程\n", content)

    def test_幂等_已存在不重复加(self):
        with tempfile.TemporaryDirectory() as d:
            self._make_note(d, "数仓规范2026版", theme_tag="数据工程")
            r = classify.cmd_tag(d, TEST_CFG)
            self.assertEqual(r["tagged"], 0)


class TestCmdMove(unittest.TestCase):
    def test_移动到子目录并修图片路径(self):
        with tempfile.TemporaryDirectory() as d:
            notes = os.path.join(d, "notes")
            os.makedirs(notes)
            fname = "数仓规范2026版-2026-11-05.md"
            p = os.path.join(notes, fname)
            content = (
                "---\ntitle: 数仓规范2026版\n"
                "tags:\n  - 主题/数据工程\n---\n\n"
                "![图](../attachments/x/01.png)\n"
            )
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)

            r = classify.cmd_move(notes, TEST_CFG)
            self.assertEqual(r["moved"], 1)
            moved = os.path.join(notes, "数据工程", fname)
            self.assertTrue(os.path.exists(moved))
            with open(moved, encoding="utf-8") as f:
                moved_content = f.read()
            self.assertIn("](../../attachments/x/01.png)", moved_content)


class TestCmdMoc(unittest.TestCase):
    def test_生成总览页(self):
        with tempfile.TemporaryDirectory() as d:
            notes = os.path.join(d, "notes")
            os.makedirs(os.path.join(notes, "数据工程"))
            r = classify.cmd_moc(d, notes, TEST_CFG)
            self.assertTrue(r["ok"])
            moc = os.path.join(d, "00-总览.md")
            self.assertTrue(os.path.exists(moc))
            with open(moc, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("[[#数据工程]]", content)


class TestCmdGraph(unittest.TestCase):
    def test_生成颜色分组(self):
        with tempfile.TemporaryDirectory() as d:
            obs = os.path.join(d, ".obsidian")
            os.makedirs(obs)
            graph_path = os.path.join(obs, "graph.json")
            with open(graph_path, "w", encoding="utf-8") as f:
                json.dump({"colorGroups": []}, f)

            r = classify.cmd_graph(d, TEST_CFG)
            self.assertTrue(r["ok"])
            with open(graph_path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(len(data["colorGroups"]), 2)
            self.assertEqual(data["colorGroups"][0]["query"], "tag:#主题/数据工程")


if __name__ == "__main__":
    unittest.main()
