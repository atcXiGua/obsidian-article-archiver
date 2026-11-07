#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""article-to-obsidian 抓取组件 · 平台适配层

每个平台一个 dict，声明「正文选择器 / 图片下载规则 / 特殊请求头 / 抓取入口」。
核心逻辑（transport / extract）不看平台差异，只看这里的配置——
新增一个平台，只需在此追加一段，不必改核心代码。

字段说明：
    body_selectors: 传给 extract.extract_main 的定位条件（id / class / tag）
    img_referer:    图片下载时的 Referer（防盗链）；留空用 transport 的默认映射
    img_headers:    图片下载时额外注入的头
    extra_headers:  抓正文时额外注入的头（如公众号需要特定 UA 之外的字段）
    note:           抓取注意事项，供模型阅读、回执提示
    entry:          （可选）特殊抓取入口函数名，见 fetcher/entry.py
"""
from __future__ import annotations

PLATFORMS = {
    "wechat": {
        "match": ["mp.weixin.qq.com"],
        "body_selectors": {"tag": "div", "id": "js_content"},
        "img_referer": "https://mp.weixin.qq.com/",
        "img_headers": {},
        "extra_headers": {},
        "note": "图片在 mmbiz.qpic.cn，必须带 Referer 与浏览器 UA，否则 403。文末二维码、引导关注图跳过。",
    },
    "x": {
        "match": ["x.com", "twitter.com", "t.co"],
        "body_selectors": None,  # X 正文结构多变，走启发式 + oEmbed 兜底
        "img_referer": "https://x.com/",
        "img_headers": {},
        "extra_headers": {},
        "entry": "x_status",
        "note": "单条长文帖可直出正文与配图；串楼以首条为主。图片在 pbs.twimg.com，带 Referer 防 403。",
    },
    "zhihu": {
        "match": ["zhihu.com"],
        "body_selectors": {"class": "RichContent-inner"},
        "img_referer": "https://www.zhihu.com/",
        "img_headers": {},
        "extra_headers": {},
        "note": "部分需带浏览器 UA；图片在 pic*.zhimg.com，部分有防盗链。",
    },
    "medium": {
        "match": ["medium.com"],
        "body_selectors": {"tag": "article"},
        "img_referer": "https://medium.com/",
        "img_headers": {},
        "extra_headers": {},
        "note": "正文在 <article> 内；图片在 cdn-images 或 miro.medium.com。",
    },
    "substack": {
        "match": ["substack.com"],
        "body_selectors": {"class": "available-content"},
        "img_referer": "",
        "img_headers": {},
        "extra_headers": {},
        "note": "正文在 .available-content；付费部分拿不到则标 degraded。",
    },
    "meituantech": {
        "match": ["tech.meituan.com"],
        "body_selectors": None,  # VuePress SPA，正文内联在页面专属 JS，走专用入口
        "img_referer": "",
        "img_headers": {},
        "extra_headers": {},
        "entry": "vuepress_page",
        "note": "美团技术博客为 VuePress SPA，正文由 JS 渲染，需从 modulepreload 定位页面 JS 提取。图片在 awps-assets.meituan.net / p0.meituan.net。",
    },
    # 兜底：任何未匹配的站点都走这条，启发式提取正文
    "generic": {
        "match": [],
        "body_selectors": None,
        "img_referer": "",
        "img_headers": {},
        "extra_headers": {},
        "note": "无平台规则，走可读性启发式提取正文；剔除导航/推荐/评论。",
    },
}


def detect(url: str) -> dict:
    """根据 URL 返回匹配的平台配置，未命中返回 generic。

    host 匹配用精确后缀（host == m 或 host.endswith(".m")），
    避免 evil-x.com 误命中 x.com 这类子串误配。
    """
    from urllib.parse import urlparse

    host = urlparse(url).netloc.lower()
    for cfg in PLATFORMS.values():
        for m in cfg["match"]:
            if m and (host == m or host.endswith("." + m)):
                return cfg
    return PLATFORMS["generic"]


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cfg = detect(sys.argv[1])
        print(f"host={sys.argv[1]!r} -> platform matched, body_selectors={cfg['body_selectors']}")
