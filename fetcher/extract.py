#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""article-to-obsidian 抓取组件 · 解析层

把 HTML 字符串转成「正文 Markdown + 图片清单」。
不依赖 bs4，用 html.parser 自建轻量提取器，零安装可跑。

核心策略（通用性来源）：
1. 先按平台选择器精确定位正文容器（命中率高、干净）；
2. 选择器未命中时，回退到「可读性启发式」——按 <p> 文本密度和块级标签
   判断哪个容器是正文，天然对任意网页生效；
3. 正文内的 <img> 全部收集为图片清单，附带 alt / 标题供落盘时命名。
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from errors import NoContentError, ParseError

# 需要整体剥离的噪声块（导航 / 推荐 / 评论 / 广告 / 页脚）。
_NOISE_CLASS_HINTS = (
    "nav", "navbar", "header", "footer", "sidebar", "aside", "comment",
    "recommend", "related", "share", "toolbar", "breadcrumb", "advert",
    "advertisement", "promotion", "copyright", "subscribe", "follow",
    "paywall", "login", "download",
)

# 这些标签上的 class/id 即使命中噪声词也不整块剥离。
# 典型误杀：文档站的标题锚点 <a class="header-anchor">、<span class="footer-note">，
# 剥掉会把标题正文一起吞了（VuePress / Docusaurus 站点必现）。
_NOISE_GUARD_TAGS = {
    "a", "span", "em", "strong", "b", "i", "code", "small", "sub", "sup",
    "h1", "h2", "h3", "h4", "h5", "h6",
}


class _Node:
    __slots__ = ("tag", "attrs", "parent", "children", "content")

    def __init__(self, tag: str, attrs: dict, parent: Optional["_Node"]):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: List[_Node] = []
        # content 按文档顺序记录「文本片段(str) 与 子节点(_Node)」的交替，
        # 用于 inline_text 严格还原 <a>xx</a>yy 这种子元素后还有文本的顺序。
        self.content: List = []

    def add_text(self, t: str):
        if t:
            self.content.append(t)

    def add_child(self, c: "_Node"):
        self.children.append(c)
        self.content.append(c)

    def text(self) -> str:
        return "".join(x for x in self.content if isinstance(x, str))

    def full_text(self) -> str:
        parts = []
        for x in self.content:
            if isinstance(x, str):
                parts.append(x)
            else:
                parts.append(x.full_text())
        return "".join(parts)

    def inline_text(self) -> str:
        """按文档顺序合并内联文本，<strong>/<b> 加粗、<em>/<i> 斜体、<a> 取链接文本。

        只处理内联元素；遇到块级元素（p/div/h/li/ul/…）则不再深入。
        """
        out: List[str] = []
        self._inline_walk(out)
        return "".join(out)

    def _inline_walk(self, out: List[str]):
        for x in self.content:
            if isinstance(x, str):
                out.append(x)
                continue
            c = x
            if c.tag == "strong" or c.tag == "b":
                inner = c.inline_text()
                if inner:
                    out.append(f"**{inner}**")
            elif c.tag == "em" or c.tag == "i":
                inner = c.inline_text()
                if inner:
                    out.append(f"*{inner}*")
            elif c.tag == "a":
                inner = c.inline_text()
                href = c.attrs.get("href", "")
                if inner:
                    # 页内锚点（href="#xxx"）是标题自链接，只留文字，不留链接
                    out.append(inner if href.startswith("#") else f"[{inner}]({href})")
            elif c.tag in _BLOCK_TAGS or c.tag in ("img", "br"):
                continue
            else:
                c._inline_walk(out)

    def p_count(self) -> int:
        n = 1 if self.tag == "p" else 0
        for c in self.children:
            n += c.p_count()
        return n


# HTML void 元素：无闭合标签，不能压入栈，否则会吞掉后续兄弟节点
_VOID_TAGS = {"img", "br", "hr", "input", "meta", "link", "source", "wbr", "area", "base", "col", "embed", "track", "param"}

# 块级标签：inline 文本合并时遇到它们即停止深入
_BLOCK_TAGS = {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6",
               "ul", "ol", "li", "blockquote", "pre", "table", "tr", "td", "th", "figure", "figcaption"}


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, None)
        self.stack: List[_Node] = [self.root]
        self._skip_depth = 0  # 噪声块嵌套深度，>0 表示在噪声块内

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self._skip_depth > 0:
            # 跳过区内只统计「有闭合标签」的元素。void 元素（img/input/br…）
            # 不会产生 handle_endtag，若也计数会让深度只增不减，
            # 把后面整篇正文一起吞掉（页头带 <img>/<input> 的站点几乎必现）。
            if tag not in _VOID_TAGS:
                self._skip_depth += 1
            return
        if tag in ("script", "style", "noscript", "iframe", "svg", "nav", "header", "footer", "aside"):
            self._skip_depth = 1
            return
        cls = (a.get("class") or "") + " " + (a.get("id") or "")
        if tag not in _NOISE_GUARD_TAGS and any(h in cls.lower() for h in _NOISE_CLASS_HINTS):
            self._skip_depth = 1
            return
        node = _Node(tag, a, self.stack[-1])
        self.stack[-1].add_child(node)
        # void 元素不入栈；块级标签补换行
        if tag in _VOID_TAGS:
            if tag == "br":
                node.add_text("\n")
            return
        self.stack.append(node)
        if tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "blockquote", "tr"):
            node.add_text("\n")

    def handle_endtag(self, tag):
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if self.stack and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        self.stack[-1].add_text(data)


def _img_markdown(node: _Node, imgs: List[dict], base_url: str) -> Optional[str]:
    """单个 <img> → Markdown 图片语法，并把图片记入清单；占位图返回 None。"""
    src = (node.attrs.get("data-src") or node.attrs.get("data-original")
           or node.attrs.get("src") or "")
    alt = node.attrs.get("alt") or node.attrs.get("title") or ""
    if src.startswith("//"):
        src = "https:" + src
    elif src.startswith("/"):
        src = urljoin(base_url, src)
    # 跳过 base64 占位图
    if not src or src.startswith("data:"):
        return None
    imgs.append({"src": src, "alt": alt})
    return f"\n![{alt}]({src})\n"


def _node_to_markdown(node: _Node, out: List[str], imgs: List[dict], base_url: str):
    """递归把正文节点渲染成 Markdown，并收集图片。"""
    for child in node.children:
        if child.tag == "img":
            md = _img_markdown(child, imgs, base_url)
            if md:
                out.append(md)
            continue
        if child.tag in ("script", "style", "noscript"):
            continue
        text = child.full_text().strip()
        if not text and not child.children:
            continue
        if child.tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            out.append(f"\n{'#' * int(child.tag[1])} {_collapse(child.inline_text())}\n")
        elif child.tag == "blockquote":
            for line in child.inline_text().split("\n"):
                if line.strip():
                    out.append(f"> {line.strip()}")
        elif child.tag in ("ul", "ol"):
            _list_to_markdown(child, out, imgs, base_url)
        elif child.tag == "pre":
            code = child.full_text()
            out.append(f"\n```\n{code}\n```\n")
        elif child.tag == "table":
            _table_to_markdown(child, out)
        elif child.tag == "p":
            # 段落：按文档顺序合并内联文本，保留加粗/斜体/链接
            text = _collapse(child.inline_text())
            if text:
                out.append(f"{text}\n")
            # 图文混排的 <p><img></p>：段落里的图不能被丢弃
            for c in child.children:
                if c.tag == "img":
                    md = _img_markdown(c, imgs, base_url)
                    if md:
                        out.append(md)
        else:
            # 容器（div/span/…）：先递归子节点，再补自身文本（如 <div>文字<em>强调</em></div>）
            _node_to_markdown(child, out, imgs, base_url)
            text = _collapse(child.inline_text())
            if text and not _ends_with_newline(out):
                out.append(f"{text}\n")


def _list_to_markdown(node: _Node, out: List[str], imgs: List[dict], base_url: str):
    ordered = node.tag == "ol"
    idx = 1
    for li in node.children:
        if li.tag != "li":
            continue
        text = li.inline_text().strip()
        if not text:
            continue
        marker = f"{idx}." if ordered else "-"
        if ordered:
            idx += 1
        out.append(f"{marker} {_collapse(text)}")
        # li 内嵌图片
        for c in li.children:
            if c.tag == "img":
                src = c.attrs.get("data-src") or c.attrs.get("src") or ""
                if src and not src.startswith("data:"):
                    if src.startswith("//"):
                        src = "https:" + src
                    imgs.append({"src": src, "alt": c.attrs.get("alt") or ""})
                    out.append(f"  ![{c.attrs.get('alt') or ''}]({src})")


def _table_rows(node: _Node):
    """按文档顺序产出所有 <tr>。要穿透 thead / tbody / tfoot ——
    只认直接子节点会把带表头的标准表格整张丢掉（渲染站点普遍这么写）。"""
    for c in node.children:
        if c.tag == "tr":
            yield c
        elif c.tag in ("thead", "tbody", "tfoot"):
            yield from _table_rows(c)


def _table_to_markdown(node: _Node, out: List[str]):
    rows: List[List[str]] = []
    for tr in _table_rows(node):
        cells = [c.inline_text().strip() for c in tr.children if c.tag in ("td", "th")]
        if cells:
            rows.append(cells)
    if not rows:
        return
    width = max(len(r) for r in rows)
    header = rows[0]
    out.append("\n| " + " | ".join(_collapse(c) for c in header) + " |")
    out.append("| " + " | ".join(["---"] * width) + " |")
    for r in rows[1:]:
        r = r + [""] * (width - len(r))
        out.append("| " + " | ".join(_collapse(c) for c in r) + " |")
    out.append("")


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _ends_with_newline(out: List[str]) -> bool:
    return out and out[-1].endswith("\n")


def _density_score(node: _Node) -> Tuple[int, int]:
    """返回 (文本长度, 段落数)，用于可读性启发式。"""
    return len(node.full_text().strip()), node.p_count()


def extract_main(
    html_text: str,
    *,
    url: str,
    selectors: Optional[dict] = None,
) -> Tuple[str, List[dict]]:
    """从 HTML 提取正文 Markdown 与图片清单。

    参数:
        html_text: 页面 HTML 字符串
        url:      原始页面 URL，用于把相对图片路径转绝对
        selectors: 平台配置里的 body_selectors，形如
                   {"tag": "div", "id": "js_content"} 或 {"class": "RichContent-inner"}
                   命中则精确定位，未命中自动回退启发式。

    返回:
        (markdown, images)  images 为 [{"src":..., "alt":...}, ...]
    """
    parser = _Extractor()
    parser.feed(html_text)
    root = parser.root

    body_node: Optional[_Node] = None

    # 1) 平台选择器优先
    if selectors:
        body_node = _find_by_selectors(root, selectors)

    # 2) 回退：可读性启发式，选文本密度最高的容器
    if body_node is None:
        best, best_score = None, 0
        for node in _walk(root):
            if node.tag in ("article", "main") or node.tag == "div":
                score = _density_score(node)
                if score[0] > best_score and score[0] > 200:
                    best, best_score = node, score[0]
        body_node = best or root

    out: List[str] = []
    imgs: List[dict] = []
    _node_to_markdown(body_node, out, imgs, url)
    md = _clean_blank_lines("\n".join(out))
    if not md.strip():
        raise NoContentError("正文提取为空：选择器未命中且启发式无正文")
    return md, imgs


def _find_by_selectors(root: _Node, selectors: dict) -> Optional[_Node]:
    """按 selectors 找节点。支持 id / class / tag 三种键，取交集。"""
    wanted_id = selectors.get("id")
    wanted_class = selectors.get("class")
    wanted_tag = selectors.get("tag")
    for node in _walk(root):
        if wanted_tag and node.tag != wanted_tag:
            continue
        if wanted_id and node.attrs.get("id") != wanted_id:
            continue
        if wanted_class and wanted_class not in (node.attrs.get("class") or ""):
            continue
        # 满足所有给定条件即可（id/class/tag 可能只给了部分）
        if wanted_id or wanted_class or wanted_tag:
            return node
    return None


def _walk(node: _Node):
    yield node
    for c in node.children:
        yield from _walk(c)


def _clean_blank_lines(s: str) -> str:
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip() + "\n"


# meta 标签里候选属性名 → 用途
_META_TITLE_ATTRS = ("og:title", "twitter:title", "title")
_META_PUBLISHED_ATTRS = (
    "article:published_time", "og:article:published_time",
    "article:published", "datePublished", "pubdate", "publish_time",
    "publish-date", "publish_time",
)
_META_AUTHOR_ATTRS = ("author", "og:author", "article:author", "twitter:creator", "byl")


def extract_meta(html_text: str) -> dict:
    """从页面 HTML 提取 {title, author, published} 元数据，按优先级回退。

    标题：<h1> → og:title → twitter:title → <title>
    作者：meta[name=author] / meta[property=author] → og:author → byline 类
    日期：meta[property/article:published_time] → <time datetime> → 放弃
    """
    title = _extract_title(html_text)
    author = _extract_author(html_text)
    published = _extract_published(html_text)
    return {"title": title, "author": author, "published": published}


def _extract_title(html_text: str) -> str:
    # 1) <h1>
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.S | re.I)
    if m:
        t = _strip_tags(m.group(1)).strip()
        if t:
            return t
    # 2) meta og:title / twitter:title
    for attr in ("og:title", "twitter:title"):
        t = _meta_content(html_text, attr)
        if t:
            return t
    # 3) <title>
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.S | re.I)
    if m:
        return _strip_tags(m.group(1)).strip()
    return ""


def _extract_author(html_text: str) -> str:
    # meta author（name 或 property）
    for attr in ("author", "og:author", "article:author"):
        a = _meta_content(html_text, attr)
        if a:
            return _clean_author(a)
    # byline / author 类
    m = re.search(
        r'<(?:span|div|a|p)[^>]*(?:class|id)=["\'][^"\']*(?:byline|author-name|article-author|post-author|post-department)[^"\']*["\'][^>]*>(.*?)</(?:span|div|a|p)>',
        html_text, re.S | re.I,
    )
    if m:
        a = _strip_tags(m.group(1)).strip()
        if a:
            return _clean_author(a)
    return ""


def _clean_author(a: str) -> str:
    """作者字段可能是完整 URL（如 X 的 og:author），净化为纯用户名/名称。"""
    a = a.strip()
    # 完整 URL → 取末尾用户名
    if a.startswith("http"):
        m = re.search(r"/([^/?#]+)/?$", a)
        if m:
            return m.group(1)
    # 去掉 @ 前缀外的多余符号
    return a


def _extract_published(html_text: str) -> str:
    # 1) meta article:published_time 等
    for attr in _META_PUBLISHED_ATTRS:
        d = _meta_content(html_text, attr)
        if d:
            return _normalize_date(d)
    # 2) <time datetime>
    m = re.search(r"<time[^>]*datetime=[\"']([^\"']+)[\"'][^>]*>", html_text, re.I)
    if m:
        return _normalize_date(m.group(1))
    # 3) VuePress / 文档站：日期直接写在 class 含 post-date 的元素文本里
    m = re.search(
        r'<(?:span|div|time|p)[^>]*class=["\'][^"\']*(?:post-date|publish-date|date-posted)[^"\']*["\'][^>]*>(.*?)</(?:span|div|time|p)>',
        html_text, re.S | re.I,
    )
    if m:
        d = _normalize_date(_strip_tags(m.group(1)))
        if d:
            return d
    return ""


def _meta_content(html_text: str, attr: str) -> str:
    """取 <meta name=attr 或 property=attr> 的 content。"""
    m = re.search(
        rf'<meta[^>]*(?:name|property)=["\']{re.escape(attr)}["\'][^>]*content=["\']([^"\']+)["\']',
        html_text, re.I,
    )
    if not m:
        m = re.search(
            rf'<meta[^>]*content=["\']([^"\']+)["\'][^>]*(?:name|property)=["\']{re.escape(attr)}["\']',
            html_text, re.I,
        )
    return m.group(1).strip() if m else ""


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def _normalize_date(d: str) -> str:
    """把各种日期格式归一化成 YYYY-MM-DD。"""
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", d)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # 纯时间戳（如 2026-11-03T05:10:00Z）
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", d)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return d.strip()


if __name__ == "__main__":
    import sys

    from transport import fetch_text

    if len(sys.argv) > 1:
        u = sys.argv[1]
        html_text = fetch_text(u)
        md, imgs = extract_main(html_text, url=u)
        print("=== MARKDOWN ===")
        print(md[:2000])
        print("=== IMAGES ===")
        for im in imgs:
            print(im["src"])
