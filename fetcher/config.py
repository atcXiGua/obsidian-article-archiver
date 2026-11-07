#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""obsidian-article-archiver 配置加载器

通用化的核心：所有「个人定制」收敛到一个 config.json 文件。
本模块提供统一配置入口，其余组件只读 config，不再硬编码。

配置优先级（从高到低）：
    1. 命令行参数（--vault / --config）
    2. 环境变量 OBSIDIAN_VAULT
    3. 配置文件 config.json（skill 目录下，或 --config 指定）
    4. 内置默认值（见 DEFAULT_CONFIG）

开源仓库只提交 config.example.json；真实 config.json 应进 .gitignore，
用户 clone 后 `cp config.example.json config.json` 再填自己的路径。

用法：
    from config import load_config
    cfg = load_config()                 # 自动按优先级解析
    cfg = load_config(vault="D:/vault") # 显式指定 vault
    cfg = load_config(config_path="...")# 指定配置文件位置
"""

from __future__ import annotations

import json
import os

# 内置默认值：未配置时的兜底，保证「开箱即用」但不含任何个人路径
DEFAULT_CONFIG = {
    "vault_path": "",           # 空 = 必须由用户配置或环境变量提供
    "notes_dir": "notes",
    "attachments_dir": "attachments",
    "language": "zh-CN",
    "translate": True,          # 非目标语言时是否自动翻译
    "taxonomy": {
        "primary_themes": ["技术", "产品", "设计", "商业", "个人成长"],
        "title_to_theme": [],
        "graph_colors": [],
    },
}

# 配置文件查找顺序（相对 skill 目录）
CONFIG_CANDIDATES = [
    "config.json",
    os.path.join("..", "config.json"),  # skill 上级目录
]


def _skill_dir() -> str:
    """返回本模块所在目录（fetcher/ 的上级，即 skill 根）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_config_file(explicit: str | None = None) -> str | None:
    """按优先级找 config.json，返回路径或 None。"""
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for cand in CONFIG_CANDIDATES:
        p = os.path.join(_skill_dir(), cand)
        if os.path.exists(p):
            return p
    return None


def _merge(base: dict, override: dict) -> dict:
    """浅合并两层 dict（taxonomy 这类嵌套结构整体覆盖即可）。"""
    out = dict(base)
    for k, v in override.items():
        out[k] = v
    return out


def load_config(
    vault: str | None = None,
    config_path: str | None = None,
) -> dict:
    """加载配置，按优先级解析。返回完整配置 dict。

    参数:
        vault:       显式指定 vault 路径（最高优先级，覆盖一切）
        config_path: 显式指定配置文件路径
    """
    cfg = dict(DEFAULT_CONFIG)

    # 3. 配置文件
    cf = _find_config_file(config_path)
    if cf:
        try:
            with open(cf, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            cfg = _merge(cfg, user_cfg)
        except (json.JSONDecodeError, OSError):
            # 配置文件损坏时静默回退到默认，不阻断（报错反而影响可用性）
            pass

    # 2. 环境变量
    env_vault = os.environ.get("OBSIDIAN_VAULT", "").strip()
    if env_vault:
        cfg["vault_path"] = env_vault

    # 1. 命令行参数（最高优先级）
    if vault:
        cfg["vault_path"] = vault

    return cfg


def resolve_vault(cfg: dict) -> str:
    """从配置解析出 vault 根路径；解析不出返回空串（由调用方提示用户）。"""
    return cfg.get("vault_path", "").strip()


def notes_dir(cfg: dict) -> str:
    return cfg.get("notes_dir", "notes")


def attachments_dir(cfg: dict) -> str:
    return cfg.get("attachments_dir", "attachments")


def primary_themes(cfg: dict) -> list[str]:
    tax = cfg.get("taxonomy", {})
    return tax.get("primary_themes", []) or DEFAULT_CONFIG["taxonomy"]["primary_themes"]


def title_to_theme(cfg: dict) -> list[list[str]]:
    tax = cfg.get("taxonomy", {})
    return tax.get("title_to_theme", []) or []


def graph_colors(cfg: dict) -> list[dict]:
    tax = cfg.get("taxonomy", {})
    return tax.get("graph_colors", []) or []
