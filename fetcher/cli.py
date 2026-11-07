#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""article-to-obsidian 抓取组件 · 统一编排入口

这是 skill 抓取动作的「唯一命令行入口」。模型/流程只需调这一条命令，
平台差异、降级、防盗链、正文提取、元数据抓取、图片下载全部封装在 fetcher 包内。

用法：
    python fetcher/cli.py <url> [--out-dir <图片目录>] [--verbose]

输出（stdout，JSON）：
    {
      "title": "文章标题",
      "author": "作者",
      "published": "YYYY-MM-DD 或空",
      "markdown": "正文 Markdown（图片已原位插入，路径相对 notes）",
      "images": [{"src": "...", "saved_as": "01.png", "ok": true}, ...],
      "platform": "wechat",
      "status": "complete" | "degraded"
    }

错误分级：
    FetchError / NoContentError → status=degraded（站点反爬 / 无正文，可降级）
    ParseError / 其他异常      → 非零退出 + error 字段（代码 bug，应暴露）

模型拿到这个 JSON 后，只需做「翻译 + 类型鉴别 + frontmatter 落盘」，
标题 / 作者 / 日期直接取自 JSON，不再猜测。
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adapters import detect  # noqa: E402
import transport  # noqa: E402
import extract  # noqa: E402
import entry  # noqa: E402
import config as appconfig  # noqa: E402
from errors import FetchError, NoContentError, ParseError, FetcherError  # noqa: E402

logger = logging.getLogger("fetcher.cli")


def _title_from_url(url: str) -> str:
    host = urlparse(url).netloc
    return f"{host}-{re.sub(r'[^a-zA-Z0-9_-]', '-', urlparse(url).path)[:40]}"


def _guess_ext(url: str, content_type: str = "") -> str:
    m = re.search(r"\.(jpg|jpeg|png|gif|webp|avif)(?:\?|$)", url, re.I)
    if m:
        return m.group(1).lower()
    ct = content_type.lower()
    if "png" in ct:
        return "png"
    if "webp" in ct:
        return "webp"
    if "gif" in ct:
        return "gif"
    return "jpg"


def _download_one(src: str, out_dir: str, referer: str, idx: int) -> dict:
    """下载单张图片，失败不抛出，返回结果 dict。"""
    try:
        data = transport.fetch_bytes(src, referer=referer or None)
        ext = _guess_ext(src)
        fname = f"{idx:02d}.{ext}"
        with open(os.path.join(out_dir, fname), "wb") as f:
            f.write(data)
        return {"src": src, "saved_as": fname, "ok": True}
    except FetchError as e:
        logger.warning("图片下载失败: %s -> %s", src, e)
        return {"src": src, "saved_as": None, "ok": False}


def _save_images(images: list, out_dir: str, cfg: dict, max_workers: int = 6) -> list:
    """并发下载图片，按 src 去重。返回与去重后图片对应的结果列表。"""
    os.makedirs(out_dir, exist_ok=True)
    # 去重，保持首次出现顺序
    unique: list = []
    seen: set = set()
    for im in images:
        src = im["src"]
        if src not in seen:
            seen.add(src)
            unique.append(src)

    referer = cfg.get("img_referer") or ""
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(_download_one, src, out_dir, referer, i)
            for i, src in enumerate(unique, 1)
        ]
        return [f.result() for f in futures]


def _notes_dir(out_dir: str, cfg: dict | None = None) -> str:
    """由附件目录反推笔记目录：<vault>/<attachments_dir>/<x> → <vault>/<notes_dir>。

    目录名可配置（config.json 的 notes_dir / attachments_dir），默认 notes / attachments。
    非 attachments 结构时退回 $OBSIDIAN_VAULT/<notes_dir>，再退回 cwd/<notes_dir>。
    """
    cfg = cfg or appconfig.load_config()
    notes = appconfig.notes_dir(cfg)
    att = appconfig.attachments_dir(cfg)

    p = os.path.abspath(out_dir).replace(os.sep, "/")
    parts = p.split("/")
    if att in parts:
        i = len(parts) - 1 - parts[::-1].index(att)
        if i > 0:
            vault = os.sep.join(parts[:i])  # 保留盘符，如 D:\vault
            return os.path.join(vault, notes)
    vault = os.environ.get("OBSIDIAN_VAULT", "").strip()
    return os.path.join(vault, notes) if vault else os.path.join(notes)


def run(url: str, out_dir: str | None = None, app_config: dict | None = None) -> dict:
    """核心编排：抓取 → 提取 → 元数据 → 下载图片 → 返回结果 dict。

    app_config: 可选，传入已加载的配置（供目录名解析）。不传则内部加载。
    """
    app_config = app_config or appconfig.load_config()
    cfg = detect(url)
    platform = cfg["match"][0] if cfg["match"] else "generic"

    status = "complete"
    meta = {"title": "", "author": "", "published": ""}
    markdown = ""
    images: list = []
    try:
        if cfg.get("entry"):
            fn = getattr(entry, cfg["entry"])
            markdown, images, meta = fn(url)
        else:
            html_text = transport.fetch_text(url, headers=cfg.get("extra_headers"))
            markdown, images = extract.extract_main(
                html_text, url=url, selectors=cfg.get("body_selectors")
            )
            meta = extract.extract_meta(html_text)
    except (FetchError, NoContentError) as e:
        # 可降级：网络/反爬/无正文 → degraded，尽量落盘标题信息
        logger.warning("抓取降级: %s", e)
        markdown = f"<!-- 抓取失败：{e} -->\n\n（正文抓取失败，待补全文）\n"
        images = []
        status = "degraded"
    except (ParseError, FetcherError):
        raise  # 解析器 bug 不应静默降级

    # 标题兜底：元数据抓不到时用 URL 拼接
    if not meta.get("title"):
        meta["title"] = _title_from_url(url)

    # 图片原位插入 + 落盘
    image_results = []
    if images and out_dir:
        image_results = _save_images(images, out_dir, cfg)
        # 建立 src → 本地相对路径 映射（相对 notes 目录），精确替换
        src_to_local = {}
        for res in image_results:
            if res["ok"]:
                abs_img = os.path.abspath(os.path.join(out_dir, res["saved_as"]))
                # 图片相对 notes 目录引用；notes 目录由 out_dir 反推，
                # 不能用相对 cwd 的 'notes'（库可能在另一个盘符，relpath 会直接抛错）。
                local = os.path.relpath(abs_img, _notes_dir(out_dir, app_config)).replace(os.sep, "/")
                src_to_local[res["src"]] = local
        for src, local in src_to_local.items():
            markdown = markdown.replace(src, local)

    return {
        "title": meta["title"],
        "author": meta.get("author", ""),
        "published": meta.get("published", ""),
        "markdown": markdown,
        "images": image_results,
        "platform": platform,
        "status": status,
        "note": cfg.get("note", ""),
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: cli.py <url> [--out-dir DIR] [--config FILE] [--verbose]"}, ensure_ascii=False))
        sys.exit(2)
    url = sys.argv[1]
    out_dir = None
    if "--out-dir" in sys.argv:
        out_dir = sys.argv[sys.argv.index("--out-dir") + 1]
    config_path = None
    if "--config" in sys.argv:
        config_path = sys.argv[sys.argv.index("--config") + 1]
    if "--verbose" in sys.argv:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)

    # 加载配置（供 _notes_dir 使用），命令行 --config 优先
    app_config = appconfig.load_config(config_path=config_path)

    try:
        result = run(url, out_dir, app_config)
        print(json.dumps(result, ensure_ascii=False))
    except FetcherError as e:
        # 解析器 bug 等不应降级的问题：非零退出 + error 字段
        print(json.dumps({"error": str(e), "status": "error"}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
