#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""article-to-obsidian 抓取组件 · 传输层

负责「把 HTML / 图片字节从远端拿回来」这一件事，与解析、平台适配解耦。
所有平台共用：统一 UA / Referer 注入、重试、编码探测、超时控制。

刻意只用标准库（urllib），不依赖 requests/bs4，保证换机后零安装即可跑。
"""
from __future__ import annotations

import gzip
import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from typing import Optional

from errors import FetchError

logger = logging.getLogger("fetcher.transport")

# 统一浏览器 UA，降低被识别为脚本的概率。抓取一律用桌面 UA。
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 各平台的 Referer 要求（防盗链关键）。图片请求要带对应站的 Referer 才不会被 403。
DEFAULT_REFERER_BY_HOST = {
    "mp.weixin.qq.com": "https://mp.weixin.qq.com/",
    "mmbiz.qpic.cn": "https://mp.weixin.qq.com/",
    "x.com": "https://x.com/",
    "twitter.com": "https://x.com/",
    "pbs.twimg.com": "https://x.com/",
}

# 常见网页编码别名 → Python 编码名，用于应对 GBK 等非 UTF-8 页面。
_ENCODING_ALIASES = {
    "gb2312": "gb18030",
    "gbk": "gb18030",
    "gb-2312": "gb18030",
}

_CTX = ssl.create_default_context()


def _decode_body(data: bytes, content_type: str = "") -> str:
    """按 Content-Type 或 meta 推断编码，返回解码后的文本。"""
    charset = None
    if "charset=" in content_type.lower():
        charset = content_type.lower().split("charset=")[-1].split(";")[0].strip(" \"'")
    if charset:
        charset = _ENCODING_ALIASES.get(charset.lower(), charset)
        try:
            return data.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    # 兜底：先试 UTF-8，再试常见中文编码
    for enc in ("utf-8", "gb18030", "big5"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def fetch_text(
    url: str,
    *,
    referer: Optional[str] = None,
    headers: Optional[dict] = None,
    timeout: int = 20,
    retries: int = 2,
) -> str:
    """抓取网页文本，自动解 gzip、探测编码。失败抛异常（由上层决定降级）。"""
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", DEFAULT_UA)
        req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
        req.add_header("Accept-Encoding", "gzip")
        if referer:
            req.add_header("Referer", referer)
        elif DEFAULT_REFERER_BY_HOST.get(_host_of(url)):
            req.add_header("Referer", DEFAULT_REFERER_BY_HOST[_host_of(url)])
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                return _decode_body(raw, ctype)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"fetch_text 失败（已重试 {retries} 次）: {url} -> {last_err}")


def fetch_bytes(
    url: str,
    *,
    referer: Optional[str] = None,
    headers: Optional[dict] = None,
    timeout: int = 30,
    retries: int = 1,
) -> bytes:
    """抓取图片等二进制内容。带防盗链 Referer 与 UA。"""
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", DEFAULT_UA)
        req.add_header("Accept", "image/avif,image/webp,image/apng,image/*,*/*;q=0.8")
        if referer:
            req.add_header("Referer", referer)
        elif DEFAULT_REFERER_BY_HOST.get(_host_of(url)):
            req.add_header("Referer", DEFAULT_REFERER_BY_HOST[_host_of(url)])
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.0)
    raise FetchError(f"fetch_bytes 失败: {url} -> {last_err}")


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc.lower()


def fetch_json(
    url: str,
    *,
    headers: Optional[dict] = None,
    timeout: int = 20,
    retries: int = 2,
) -> object:
    """抓取 JSON 接口（如 X 的 oEmbed / 公众号 JS 接口）。"""
    text = fetch_text(
        url,
        headers=dict(headers or {}, Accept="application/json, text/plain, */*"),
        timeout=timeout,
        retries=retries,
    )
    try:
        return json.loads(text)
    except ValueError as e:
        raise FetchError(f"fetch_json 解析失败: {url} -> {e}") from e


if __name__ == "__main__":
    import sys

    # 自测：python fetcher/transport.py <url>
    if len(sys.argv) > 1:
        body = fetch_text(sys.argv[1])
        print(body[:500])
