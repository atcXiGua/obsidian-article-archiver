#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""article-to-obsidian 分类管理组件 · 归档后的标准化与图谱关联

把「标签收敛 → 物理分文件夹 → 双链关联 → MOC/图谱配色」沉淀为可复用命令。
归档落盘只是第一步；本组件负责把新笔记纳入既有的分类体系与知识图谱。

设计原则：
1. 幂等 —— 重复运行不会重复添加标签 / 重复建目录 / 重复加链接。
2. 不破坏原文 —— 只动 frontmatter 的 tags 和文末追加「相关文章」区块，
   正文一个字符都不改（唯一的例外是物理分文件夹时修正图片相对路径）。
3. 单一命令入口 —— 模型/流程只调 cli 一条命令，分类规则集中在本文件的
   RULES 常量里，改规则不改逻辑。

用法：
    # 1. 给新笔记补一级主题锚点标签（归档后立即做）
    python classify.py tag --notes <库根>/notes

    # 2. 物理分文件夹（按一级主题移动，同步修正图片相对路径）
    python classify.py move --notes <库根>/notes

    # 3. 建双链关联（按 RULES 里的语义关系，强/中关联连，弱关联不连）
    python classify.py link --notes <库根>/notes

    # 4. 生成 MOC 总览页（Dataview 聚合 + 静态速览）
    python classify.py moc --vault <库根> --notes <库根>/notes

    # 5. 生成图谱颜色分组配置
    python classify.py graph --vault <库根>

    # 一步到位：tag + move + link + moc + graph
    python classify.py all --vault <库根>

输出：stdout JSON，形如 {"ok": true, "tagged": 3, "moved": 3, "linked": 3}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as appconfig  # noqa: E402

# ---------------------------------------------------------------------------
# RULES —— 分类规则集中于此，改规则不改逻辑
#
# 通用化说明：以下常量是「默认兜底」，实际运行时优先读 config.json 的
# taxonomy 配置（config.example.json 有模板）。用户可自定义自己的分类体系，
# 不必改代码。见 config.py 的 primary_themes() / title_to_theme() / graph_colors()。
# ---------------------------------------------------------------------------

# 一级主题锚点（主分类）。归档时给每篇笔记的 tags 里补一个「主题/<主类>」。
# 主类决定物理文件夹和 Dataview 聚合分组。
PRIMARY_THEMES = [
    "数据工程",
    "AI工程",
    "基础设施",
    "个人成长",
    "商业",
]

# 文件名关键字 -> 一级主题主类（顺序即优先级，先匹配到为准）。
# 新增分类时只在这里加一行。
TITLE_TO_THEME = [
    ("数仓", "数据工程"),
    ("数据仓库", "数据工程"),
    ("数据治理", "数据工程"),
    ("维度建模", "数据工程"),
    ("实时数仓", "数据工程"),
    ("OneData", "数据工程"),
    ("本体", "数据工程"),
    ("DB数据同步", "数据工程"),
    ("Codex", "AI工程"),
    ("Coding-Agent", "AI工程"),
    ("智能体", "AI工程"),
    ("Agent", "AI工程"),
    ("技能", "AI工程"),
    ("存储", "基础设施"),
    ("分布式", "基础设施"),
    ("ChatGPT", "基础设施"),
    ("成长", "个人成长"),
    ("成功", "个人成长"),
    ("品牌", "个人成长"),
    ("生意", "商业"),
    ("商业", "商业"),
    ("赚钱", "商业"),
]

# 图谱颜色分组（按一级主题标签着色）。rgb 为 0-16777215 十进制。
# 数据工程红 / AI工程蓝 / 基础设施橙 / 个人成长绿 / 商业金黄 / MOC 灰。
GRAPH_COLOR_GROUPS = [
    {"query": "tag:#主题/数据工程", "rgb": 14048348},
    {"query": "tag:#主题/AI工程", "rgb": 4521984},
    {"query": "tag:#主题/基础设施", "rgb": 16750848},
    {"query": "tag:#主题/个人成长", "rgb": 4359936},
    {"query": "tag:#主题/商业", "rgb": 16729344},
    {"query": "tag:#类型/MOC", "rgb": 8421504},
]


def _active_primary_themes(cfg: dict | None = None) -> list[str]:
    """当前生效的一级主题（config 优先，无则用内置默认）。"""
    cfg = cfg or appconfig.load_config()
    themes = appconfig.primary_themes(cfg)
    return themes if themes else PRIMARY_THEMES


def _active_title_to_theme(cfg: dict | None = None) -> list[list[str]]:
    """当前生效的标题→主题映射（config 优先，无则用内置默认）。"""
    cfg = cfg or appconfig.load_config()
    mapping = appconfig.title_to_theme(cfg)
    if mapping:
        return [tuple(x) for x in mapping]
    return [tuple(x) for x in TITLE_TO_THEME]


def resolve_theme(title: str, cfg: dict | None = None) -> str | None:
    """按标题关键字匹配一级主题主类，未命中返回 None。"""
    for key, theme in _active_title_to_theme(cfg):
        if key in title:
            return theme
    return None


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def list_notes(notes_dir: str) -> list[str]:
    """递归列出 notes 目录下所有 .md 文件（含子目录）。"""
    out = []
    for root, _dirs, files in os.walk(notes_dir):
        for f in files:
            if f.endswith(".md"):
                out.append(os.path.join(root, f))
    return sorted(out)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def frontmatter_theme(path: str, cfg: dict | None = None) -> str | None:
    """读取笔记 frontmatter 里已有的一级主题主类（若存在）。"""
    content = read_text(path)
    for theme in _active_primary_themes(cfg):
        if f"  - 主题/{theme}\n" in content:
            return theme
    return None


# ---------------------------------------------------------------------------
# 1. tag —— 标签收敛：补一级主题锚点
# ---------------------------------------------------------------------------


def add_primary_theme(path: str, cfg: dict | None = None) -> bool:
    """给笔记补「主题/<主类>」标签，返回是否新增。幂等：已存在则跳过。"""
    content = read_text(path)
    title = ""
    m = re.search(r"^title:\s*(.+)$", content, re.M)
    if m:
        title = m.group(1).strip()
    theme = resolve_theme(title, cfg)
    if not theme:
        return False
    if f"  - 主题/{theme}\n" in content:
        return False

    # 插到第一个 主题/ 行之前，保持 类型 -> 主题 顺序
    tags_match = re.search(r"^tags:\n", content, flags=re.M)
    if not tags_match:
        return False
    insert_at = tags_match.end()
    first_theme = re.search(r"^  - 主题/", content, flags=re.M)
    if first_theme:
        insert_at = first_theme.start()
    new_content = content[:insert_at] + f"  - 主题/{theme}\n" + content[insert_at:]
    write_text(path, new_content)
    return True


def cmd_tag(notes_dir: str, cfg: dict | None = None) -> dict:
    n = 0
    for p in list_notes(notes_dir):
        if add_primary_theme(p, cfg):
            n += 1
    return {"ok": True, "tagged": n}


# ---------------------------------------------------------------------------
# 2. move —— 物理分文件夹 + 修正图片路径
# ---------------------------------------------------------------------------


def _target_dir(path: str, cfg: dict | None = None) -> str | None:
    theme = frontmatter_theme(path, cfg)
    if not theme:
        return None
    return theme


def _fix_img_paths(content: str, depth: int) -> str:
    """把 ../attachments/ 改成 depth 层的 ../../attachments/。

    notes 根目录笔记 depth=1（../attachments），
    notes/<子目录>/ 笔记 depth=2（../../attachments）。
    """
    if depth <= 1:
        return content
    prefix = "../" * depth
    return content.replace("](../attachments/", f"]({prefix}attachments/")


def cmd_move(notes_dir: str, cfg: dict | None = None) -> dict:
    moved = 0
    for src in list_notes(notes_dir):
        base = os.path.basename(src)
        # 已在子目录里（不是 notes 根）则跳过
        if os.path.dirname(src) != os.path.normpath(notes_dir):
            continue
        theme = _target_dir(src, cfg)
        if not theme:
            continue
        dstdir = os.path.join(notes_dir, theme)
        os.makedirs(dstdir, exist_ok=True)
        dst = os.path.join(dstdir, base)
        if os.path.exists(dst):
            continue

        # 移动到子目录后，图片相对路径要多回退一层
        content = read_text(src)
        content = _fix_img_paths(content, depth=2)
        write_text(src, content)
        os.replace(src, dst)
        moved += 1
    return {"ok": True, "moved": moved}


# ---------------------------------------------------------------------------
# 3. link —— 双链关联（强/中关联连，弱关联不连）
#
# 关联分层（对齐 SKILL.md §7 升级后的原则）：
#   强关联：明确系列/前后篇、直接回应补充反驳、同作者思想脉络 —— 必连
#   中关联：同一具体子主题（实时数仓、元数据治理、Coding Agent）—— 连 + 说明
#   弱关联：只有宽泛交集（都讲 AI / 都讲数据）—— 不连
#
# 由于「中关联」依赖对内容的语义理解，这里只内置「强关联」的确定性规则
# （系列/前后篇、同作者、同具体技术点），中/弱关联由模型在归档时按 §7 判断后
# 手动追加，不自动批量连——避免把宽泛交集误连成噪音。
# ---------------------------------------------------------------------------

# 确定性强关联规则：文件名关键字 -> 相关文章关键字列表（说明）
# 仅收录「系列前后篇」「同作者」「同具体技术点」这类不会误判的关系。
#
# 通用化说明：这是「个人知识库特有的关联」，开源版默认为空。
# 用户可按需在这里补充自己的关联规则（系列文章、同作者等），格式：
#   "文章标题关键字": [("目标文章关键字", "关联说明"), ...]
HARD_LINKS = {}


def _add_related_block(path: str, links: list[tuple[str, str]]) -> bool:
    """在文末追加「相关文章」区块，返回是否新增。幂等：已存在则跳过。"""
    content = read_text(path)
    if "## 🔗 相关文章" in content:
        return False
    lines = ["", "## 🔗 相关文章", ""]
    for target_kw, desc in links:
        # 在 notes 里找匹配 target_kw 的目标文件
        target = _find_note_by_kw(os.path.dirname(path), target_kw)
        if not target:
            continue
        target_base = os.path.basename(target)
        title = re.sub(r"-\d{4}-\d{2}-\d{2}\.md$", "", target_base)
        lines.append(f"- [[{target_base}|{title}]]：{desc}")
    if len(lines) == 3:  # 没有有效目标
        return False
    content = content.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    write_text(path, content)
    return True


def _find_note_by_kw(notes_dir: str, kw: str) -> str | None:
    """在 notes 目录（含子目录）里按关键字找笔记文件。"""
    for p in list_notes(notes_dir):
        if kw in os.path.basename(p):
            return p
    return None


def cmd_link(notes_dir: str) -> dict:
    n = 0
    for p in list_notes(notes_dir):
        base = os.path.basename(p)
        for kw, links in HARD_LINKS.items():
            if kw in base:
                if _add_related_block(p, links):
                    n += 1
                break
    return {"ok": True, "linked": n}


# ---------------------------------------------------------------------------
# 4. moc —— 生成 MOC 总览页（Dataview 聚合）
# ---------------------------------------------------------------------------


# 主题的展示说明与 emoji（MOC 目录导航用）。通用化：仅作兜底，
# 用户自定义的主题若不在这些表里，会用主题名本身作为说明、📄 作为 emoji。
THEME_DESC = {
    "数据工程": "数仓、数据治理、维度建模、实时数仓",
    "AI工程": "智能体、Coding Agent、Codex、技能图谱",
    "基础设施": "存储系统、分布式、扩展性",
    "个人成长": "目标设定、个人品牌",
    "商业": "AI 商业、创作者经济",
}

THEME_EMOJI = {
    "数据工程": "📊",
    "AI工程": "🤖",
    "基础设施": "🏗️",
    "个人成长": "🌱",
    "商业": "💰",
}


def cmd_moc(vault: str, notes_dir: str, cfg: dict | None = None) -> dict:
    themes = [t for t in _active_primary_themes(cfg) if os.path.isdir(os.path.join(notes_dir, t))]
    sections = []
    toc_rows = []
    for t in themes:
        desc = THEME_DESC.get(t, t)
        toc_rows.append(f"| [[#{t}]] | {desc} |")
        sections.append(
            f"## {THEME_EMOJI.get(t, '📄')} {t}\n\n"
            "```dataview\n"
            "TABLE\n"
            "  source AS \"来源\",\n"
            "  author AS \"作者\",\n"
            "  date(published) AS \"发布\"\n"
            f'FROM "notes/{t}"\n'
            "SORT published DESC\n"
            "```\n"
        )

    content = (
        "---\n"
        "title: 总览\n"
        "tags:\n"
        "  - 类型/MOC\n"
        "cssclasses:\n"
        "  - wide-page\n"
        "---\n\n"
        "# 📚 知识总览\n\n"
        "> 这是我的知识沉淀图谱主页，按主题聚合所有已归档文章。\n"
        "> 新增文章时，只要在 frontmatter 里写上对应的 `主题/一级类` 标签，下方列表会自动更新。\n\n"
        "## 🧭 目录导航\n\n"
        "| 分类 | 说明 |\n"
        "|---|---|\n"
        + "\n".join(toc_rows)
        + "\n\n---\n\n"
        + "\n\n---\n\n".join(sections)
        + "\n\n---\n\n## 👤 按作者浏览\n\n"
        "```dataview\n"
        "TABLE\n"
        "  rows.source AS \"来源\",\n"
        "  length(rows) AS \"篇数\"\n"
        'FROM "notes"\n'
        "WHERE author\n"
        "GROUP BY author\n"
        "SORT length(rows) DESC\n"
        "```\n"
    )
    out_path = os.path.join(vault, "00-总览.md")
    write_text(out_path, content)
    return {"ok": True, "moc": out_path}


# ---------------------------------------------------------------------------
# 5. graph —— 生成图谱颜色分组配置
# ---------------------------------------------------------------------------


def cmd_graph(vault: str, cfg: dict | None = None) -> dict:
    graph_path = os.path.join(vault, ".obsidian", "graph.json")
    if not os.path.exists(graph_path):
        return {"ok": False, "error": f"未找到 {graph_path}"}
    data = json.loads(read_text(graph_path))
    colors = appconfig.graph_colors(cfg or appconfig.load_config())
    if not colors:
        colors = GRAPH_COLOR_GROUPS
    data["colorGroups"] = [
        {"query": g["query"], "color": {"a": 1, "rgb": g["rgb"]}}
        for g in colors
    ]
    # 确保 colorGroups 展开显示
    data["collapse-color-groups"] = False
    write_text(graph_path, json.dumps(data, ensure_ascii=False, indent=2))
    return {"ok": True, "graph": graph_path}


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="obsidian-article-archiver 分类管理组件")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("tag", "move", "link"):
        p = sub.add_parser(name)
        p.add_argument("--notes", required=True, help="notes 目录绝对路径")
        p.add_argument("--config", default=None, help="配置文件路径（可选）")

    p = sub.add_parser("moc")
    p.add_argument("--vault", required=True)
    p.add_argument("--notes", required=True)
    p.add_argument("--config", default=None)

    p = sub.add_parser("graph")
    p.add_argument("--vault", required=True)
    p.add_argument("--config", default=None)

    p = sub.add_parser("all")
    p.add_argument("--vault", required=True)
    p.add_argument("--config", default=None)

    args = ap.parse_args()
    cfg = appconfig.load_config(config_path=getattr(args, "config", None))

    if args.cmd == "tag":
        result = cmd_tag(args.notes, cfg)
    elif args.cmd == "move":
        result = cmd_move(args.notes, cfg)
    elif args.cmd == "link":
        result = cmd_link(args.notes)
    elif args.cmd == "moc":
        result = cmd_moc(args.vault, args.notes, cfg)
    elif args.cmd == "graph":
        result = cmd_graph(args.vault, cfg)
    elif args.cmd == "all":
        notes = os.path.join(args.vault, appconfig.notes_dir(cfg))
        r1 = cmd_tag(notes, cfg)
        r2 = cmd_move(notes, cfg)
        r3 = cmd_link(notes)
        r4 = cmd_moc(args.vault, notes, cfg)
        r5 = cmd_graph(args.vault, cfg)
        result = {
            "ok": True,
            "tagged": r1["tagged"],
            "moved": r2["moved"],
            "linked": r3["linked"],
            "moc": r4.get("moc"),
            "graph": r5.get("graph"),
        }
    else:
        result = {"ok": False, "error": f"未知命令 {args.cmd}"}

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
