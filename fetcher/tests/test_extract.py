#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析层回归测试。

覆盖正文提取、图片收集、元数据提取，以及上一轮修复的三个关键 bug：
  1. void 元素（img/br）吞掉后续兄弟节点
  2. 内联文本顺序颠倒（<p>包含<strong>加粗</strong>关键词</p>）
  3. 段落文本丢失
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import extract  # noqa: E402


class TestExtractMain(unittest.TestCase):
    def _run(self, html_text, url="https://example.com/x", selectors=None):
        return extract.extract_main(html_text, url=url, selectors=selectors)

    def test_paragraph_text_not_lost(self):
        html = '<div id="js_content"><p>第一段正文。</p><p>第二段正文。</p></div>'
        md, _ = self._run(html, selectors={"tag": "div", "id": "js_content"})
        self.assertIn("第一段正文。", md)
        self.assertIn("第二段正文。", md)

    def test_inline_text_order(self):
        # 回归 bug2：strong 内容不应跑到句尾
        html = '<div id="js_content"><p>包含<strong>加粗</strong>关键词。</p></div>'
        md, _ = self._run(html, selectors={"tag": "div", "id": "js_content"})
        self.assertIn("包含**加粗**关键词。", md)

    def test_inline_link_and_em(self):
        html = '<div id="js_content"><p>点<a href="https://x.com">这里</a>和<em>斜体</em>。</p></div>'
        md, _ = self._run(html, selectors={"tag": "div", "id": "js_content"})
        self.assertIn("点[这里](https://x.com)和*斜体*。", md)

    def test_void_img_does_not_swallow_siblings(self):
        # 回归 bug1：img 之后的内容不应丢失
        html = (
            '<div id="js_content"><p>段落A</p>'
            '<img src="https://e.com/a.jpg" alt="图">'
            '<blockquote>引用文字</blockquote>'
            '<pre><code>print(1)</code></pre>'
            '<table><tr><th>列1</th></tr><tr><td>a</td></tr></table></div>'
        )
        md, imgs = self._run(html, selectors={"tag": "div", "id": "js_content"})
        self.assertIn("> 引用文字", md)
        self.assertIn("print(1)", md)
        self.assertIn("| 列1 |", md)
        self.assertEqual(len(imgs), 1)

    def test_noise_stripped(self):
        html = (
            '<body><nav>导航</nav><div id="js_content"><p>正文。</p></div>'
            '<footer>页脚</footer></body>'
        )
        md, _ = self._run(html, selectors={"tag": "div", "id": "js_content"})
        self.assertNotIn("导航", md)
        self.assertNotIn("页脚", md)
        self.assertIn("正文。", md)

    def test_image_collection_and_data_skip(self):
        html = (
            '<div id="js_content">'
            '<img src="https://e.com/real.jpg" alt="真图">'
            '<img src="data:image/png;base64,xxx">'
            '<img src="//cdn.e.com/x.png">'
            '</div>'
        )
        md, imgs = self._run(html, selectors={"tag": "div", "id": "js_content"})
        self.assertEqual(len(imgs), 2)  # data: 占位图应跳过
        self.assertIn("https://cdn.e.com/x.png", md)  # 协议相对路径补 https

    def test_lazy_loading_data_src(self):
        html = '<div id="js_content"><img data-src="https://e.com/lazy.jpg" alt="懒加载"></div>'
        _, imgs = self._run(html, selectors={"tag": "div", "id": "js_content"})
        self.assertEqual(imgs[0]["src"], "https://e.com/lazy.jpg")

    def test_heuristic_fallback_when_no_selector(self):
        # 无选择器时，靠密度启发式找到正文容器
        html = '<body><div><p>短导航文本</p></div><article><p>' + "正文内容" * 60 + "</p></article></body>"
        md, _ = self._run(html, selectors=None)
        self.assertIn("正文内容", md)

    def test_empty_raises_no_content(self):
        from errors import NoContentError

        # 页面里没有任何正文文本（只有 nav/footer 噪声），应抛 NoContentError
        html = "<html><body><nav>导航</nav><footer>页脚</footer></body></html>"
        with self.assertRaises(NoContentError):
            self._run(html, selectors={"id": "不存在"})

    def test_list_and_table(self):
        html = (
            '<div id="js_content"><ul><li>条目A</li><li>条目B</li></ul>'
            '<ol><li>第一</li><li>第二</li></ol>'
            '<table><tr><th>名</th><th>值</th></tr><tr><td>a</td><td>1</td></tr></table></div>'
        )
        md, _ = self._run(html, selectors={"tag": "div", "id": "js_content"})
        self.assertIn("- 条目A", md)
        self.assertIn("1. 第一", md)
        self.assertIn("| 名 | 值 |", md)


class TestRenderFixes(unittest.TestCase):
    """美团技术博客回归用例：一次归档暴露的 4 个真实丢失点。"""

    def _run(self, html_text, url="https://example.com/x"):
        return extract.extract_main(html_text, url=url)

    def test_void_in_header_does_not_eat_article(self):
        # 页头里同时有 <img>/<input>（void 元素）。曾经它们会把跳过深度撑爆，
        # 使后面整篇正文被当噪声丢掉。
        body = "正文段落。" * 50
        html = (
            '<body><header class="site-header"><img src="https://e.com/logo.png">'
            '<input type="search"></header>'
            f"<div><p>{body}</p></div></body>"
        )
        md, _ = self._run(html)
        self.assertIn("正文段落。", md)
        self.assertGreater(len(md), 200)

    def test_heading_anchor_link_not_dropped(self):
        # <h2><a class="header-anchor" href="#x">标题</a></h2>：锚点类名含 header，
        # 曾被当噪声整块剥离，导致标题连文字一起消失。
        html = '<body><div><h2 id="背景"><a class="header-anchor" href="#背景"><span>背景</span></a></h2><p>正文。</p></div></body>'
        md, _ = self._run(html)
        self.assertIn("## 背景", md)
        self.assertNotIn("](#背景)", md)  # 页内锚点只留文字

    def test_img_inside_paragraph_collected(self):
        html = '<body><div><p><img src="https://e.com/a.png" alt=""><img src="https://e.com/b.png" alt="图B"></p></div></body>'
        md, imgs = self._run(html)
        self.assertEqual(len(imgs), 2)
        self.assertIn("https://e.com/b.png", md)

    def test_table_with_thead_tbody(self):
        html = (
            "<body><div><table>"
            "<thead><tr><th>类型</th><th>格式</th></tr></thead>"
            "<tbody><tr><td>日期</td><td>YYYY-MM-DD</td></tr></tbody>"
            "</table></div></body>"
        )
        md, _ = self._run(html)
        self.assertIn("| 类型 | 格式 |", md)
        self.assertIn("| 日期 | YYYY-MM-DD |", md)


class TestExtractMeta(unittest.TestCase):
    def test_title_from_h1(self):
        html = "<html><head><title>网页标题</title></head><body><h1>正文大标题</h1></body></html>"
        meta = extract.extract_meta(html)
        self.assertEqual(meta["title"], "正文大标题")

    def test_title_from_og(self):
        html = '<html><head><meta property="og:title" content="OG标题"></head><body></body></html>'
        meta = extract.extract_meta(html)
        self.assertEqual(meta["title"], "OG标题")

    def test_title_from_title_tag_fallback(self):
        html = "<html><head><title>网页标题</title></head><body></body></html>"
        meta = extract.extract_meta(html)
        self.assertEqual(meta["title"], "网页标题")

    def test_author_from_meta(self):
        html = '<html><head><meta name="author" content="小明"></head><body></body></html>'
        meta = extract.extract_meta(html)
        self.assertEqual(meta["author"], "小明")

    def test_author_url_cleaned_to_username(self):
        # X 的 og:author 返回完整 URL，应净化为纯用户名
        html = '<html><head><meta property="og:author" content="https://x.com/XiaohuiAI666"></head></html>'
        meta = extract.extract_meta(html)
        self.assertEqual(meta["author"], "XiaohuiAI666")

    def test_published_from_meta(self):
        html = (
            '<html><head>'
            '<meta property="article:published_time" content="2026-11-03T05:10:00Z">'
            "</head><body></body></html>"
        )
        meta = extract.extract_meta(html)
        self.assertEqual(meta["published"], "2026-11-03")

    def test_published_from_time_tag(self):
        html = '<html><body><time datetime="2026-11-03">11月3日</time></body></html>'
        meta = extract.extract_meta(html)
        self.assertEqual(meta["published"], "2026-11-03")

    def test_published_chinese_date(self):
        html = '<html><head><meta property="article:published_time" content="2026年11月3日"></head></html>'
        meta = extract.extract_meta(html)
        self.assertEqual(meta["published"], "2026-11-03")

    def test_empty_meta(self):
        meta = extract.extract_meta("<html><body></body></html>")
        self.assertEqual(meta, {"title": "", "author": "", "published": ""})


if __name__ == "__main__":
    unittest.main()
