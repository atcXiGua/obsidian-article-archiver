#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""article-to-obsidian 抓取组件 · 异常层级

把「抓取失败」按成因分成三类，让上层能区分
「站点反爬 / 网络问题」「页面无正文」「解析器自身 bug」，分别处理。

    FetchError     —— 网络 / 反爬 / HTTP 错误：可降级（标 degraded）
    NoContentError —— 页面成功拿到，但提取不到正文：可降级
    ParseError     —— 解析器自身异常：应报错暴露，而非静默降级
"""
from __future__ import annotations


class FetcherError(Exception):
    """fetcher 组件所有异常的基类。"""


class FetchError(FetcherError):
    """网络请求失败 / 反爬 / 超时 / 非 200。可降级。"""


class NoContentError(FetcherError):
    """页面拿到了，但提取不到正文（选择器未命中且启发式也空）。可降级。"""


class ParseError(FetcherError):
    """HTML 解析过程抛出的异常，通常是代码 bug，不应静默吞掉。"""
