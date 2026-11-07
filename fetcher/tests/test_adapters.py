#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""适配层 + 传输层单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import adapters  # noqa: E402
import transport  # noqa: E402


class TestDetect(unittest.TestCase):
    def test_wechat(self):
        cfg = adapters.detect("https://mp.weixin.qq.com/s/abc")
        self.assertEqual(cfg["body_selectors"]["id"], "js_content")

    def test_x(self):
        cfg = adapters.detect("https://x.com/user/status/123")
        self.assertEqual(cfg["entry"], "x_status")

    def test_zhihu(self):
        cfg = adapters.detect("https://www.zhihu.com/question/1")
        self.assertEqual(cfg["body_selectors"]["class"], "RichContent-inner")

    def test_generic_fallback(self):
        cfg = adapters.detect("https://example.com/blog/post")
        self.assertEqual(cfg["body_selectors"], None)

    def test_no_false_match_evil_x(self):
        # evil-x.com 不应命中 x.com（精确后缀匹配）
        cfg = adapters.detect("https://evil-x.com/status/1")
        self.assertIsNone(cfg["body_selectors"])
        self.assertEqual(cfg.get("entry"), None)


class TestTransportHelpers(unittest.TestCase):
    def test_decode_utf8(self):
        self.assertEqual(transport._decode_body("你好".encode("utf-8")), "你好")

    def test_decode_gbk_via_content_type(self):
        data = "你好".encode("gb18030")
        self.assertEqual(
            transport._decode_body(data, 'text/html; charset="gbk"'), "你好"
        )

    def test_decode_gbk_fallback(self):
        # 无 charset 时，utf-8 解不了，自动回退 gb18030
        data = "你好".encode("gb18030")
        self.assertEqual(transport._decode_body(data, ""), "你好")


if __name__ == "__main__":
    unittest.main()
