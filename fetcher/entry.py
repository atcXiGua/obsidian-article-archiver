#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""article-to-obsidian 抓取组件 · 特殊入口层

针对「直抓 HTML 拿不到正文」的站点，提供专用入口：
  - x_status：X 帖子，直抓 + oEmbed 兜底
  - vuepress_page：VuePress 类 SPA（美团技术博客等），正文内联在页面专属 JS 里，
    从初始 HTML 的 <link rel="modulepreload"> 定位 JS，再从中提取正文 HTML。
其余平台默认走 transport.fetch_text + extract.extract_main 的标准链路。
"""
from __future__ import annotations

import re
from typing import Tuple
from urllib.parse import urljoin

import extract
import transport
from errors import FetchError


def x_status(url: str) -> Tuple[str, list, dict]:
    """X 帖子专用入口：优先直抓帖子页（可拿全文），失败再降级 oEmbed。

    返回 (markdown, images, meta)。meta 为 {title, author, published}。
    images 为 [{"src":..., "alt":...}, ...]。
    """
    # 1) 直抓帖子页：长文帖能拿到完整正文与配图
    try:
        html_text = transport.fetch_text(url, referer="https://x.com/")
        md, images = extract.extract_main(html_text, url=url)
        meta = extract.extract_meta(html_text)
        # 直抓若只拿到空壳（正文过短且无图片），退回 oEmbed
        if len(md.strip()) > 40 or images:
            return md, images, meta
    except (FetchError, extract.NoContentError):
        pass

    # 2) 降级：oEmbed，至少拿到作者与标题，标 degraded 由上层处理
    status_id = _extract_status_id(url)
    if status_id:
        oembed_url = f"https://publish.twitter.com/oembed?url={url}&omit_script=true"
        try:
            data = transport.fetch_json(oembed_url)
            author = data.get("author_name", "")
            title = data.get("title", "")
            html_text = data.get("html", "")
            md = f"# {author}\n\n{_strip_html(title)}\n\n{_strip_html(html_text)}\n"
            meta = {"title": title, "author": author, "published": ""}
            return md, [], meta
        except FetchError:
            pass

    raise FetchError("X 帖子抓取失败：直抓与 oEmbed 均未取到正文")


def vuepress_page(url: str) -> Tuple[str, list, dict]:
    """VuePress 类 SPA 页面入口：正文由客户端 JS 渲染，直抓 HTML 只有 meta。

    正文以 HTML 字符串内联在「页面专属 JS」（如 binlog-dw.html-xxx.js）里，
    由初始 HTML 的 <link rel="modulepreload" href="...js"> 指向。
    流程：抓 HTML → 定位页面专属 JS → 抓 JS → 提取内联 HTML → 交给 extract。

    返回 (markdown, images, meta)。
    """
    html_text = transport.fetch_text(url)
    meta = extract.extract_meta(html_text)

    # 1) 定位页面专属 JS（modulepreload 里与当前页面路径同名的那个）
    js_url = _find_page_js(html_text, url)
    if not js_url:
        raise FetchError(f"VuePress 页面未找到内联正文 JS: {url}")

    # 2) 抓 JS，提取内联 HTML 字符串
    js_text = transport.fetch_text(js_url)
    inner_html = _extract_vp_html(js_text)
    if not inner_html:
        raise FetchError(f"VuePress JS 中未提取到正文 HTML: {js_url}")

    # 3) 交给通用解析器（图片相对路径以页面 URL 为基准）
    md, images = extract.extract_main(inner_html, url=url)
    return md, images, meta


def _find_page_js(html_text: str, page_url: str) -> str:
    """从 HTML 的 modulepreload 里找页面专属 JS 的绝对地址。

    VuePress 会在 <link rel="modulepreload" href="/assets/<slug>-xxx.js"> 里
    预载页面专属 JS，其文件名与页面 slug 一致。
    """
    from urllib.parse import urlparse

    slug = urlparse(page_url).path.rstrip("/").rsplit("/", 1)[-1]  # 如 binlog-dw.html
    m = re.search(
        rf'<link[^>]*rel="modulepreload"[^>]*href="([^"]*{re.escape(slug)}[^"]*\.js)"',
        html_text,
    )
    if m:
        return urljoin(page_url, m.group(1))
    return ""


def _extract_vp_html(js_text: str) -> str:
    """从 VuePress 渲染 JS 里提取内联的正文 HTML 字符串。

    正文形如 n('<h2 id="背景">...</h2><p>...</p>...')，即渲染函数的字符串参数。
    从每个 n(' 起始，手动扫描到匹配的结束 ')'（处理 \\' 与 \\n 转义），
    取含正文标签（<h2>/<p>）且最长的那段。
    """
    best = ""
    start = 0
    while True:
        i = js_text.find("n('", start)
        if i < 0:
            break
        inner = _scan_js_string(js_text, i + 2)  # 跳过 "n("，指向 ' 之后
        if inner is not None:
            if ("<p" in inner or "<h2" in inner or "<h1" in inner) and len(inner) > len(best):
                best = inner
        start = i + 2
    if best:
        best = best.replace("\\n", "\n").replace("\\/", "/").replace("\\'", "'")
    return best


def _scan_js_string(js_text: str, quote_pos: int) -> str:
    """从 js_text 中 quote_pos（单引号位置）起，扫描到配对的闭合单引号。

    返回字符串内容（不含引号，未反转义）。遇到 \\' 跳过。失败返回 None。
    """
    if quote_pos >= len(js_text) or js_text[quote_pos] != "'":
        return None
    out = []
    j = quote_pos + 1
    while j < len(js_text):
        ch = js_text[j]
        if ch == "\\":
            # 保留转义（含下一个字符），统一留到外层反转义
            if j + 1 < len(js_text):
                out.append(js_text[j:j + 2])
                j += 2
                continue
        if ch == "'":
            return "".join(out)
        out.append(ch)
        j += 1
    return None


def _extract_status_id(url: str) -> str:
    m = re.search(r"/status/(\d+)", url)
    return m.group(1) if m else ""


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()
