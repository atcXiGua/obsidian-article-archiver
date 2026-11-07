---
name: obsidian-article-archiver
display_name: 文章归档入仓
display_name_en: Article To Obsidian
description: "用户发来任意网页链接（包括只发一个链接、没有任何说明文字的情况）、一段长文本、或一个 PDF 附件时，立即抓取全文并整体落盘为本地 Obsidian 笔记。URL 一出现就触发，不需要「归档」「保存」等关键词，也不要先做摘要再问是否保存。覆盖公众号、X/Twitter、知乎、Medium、Substack、博客及任意网页。硬性约束：原文完整保留（不压缩、不精编、不点评）、图片下载到本地原位插入、frontmatter 写全出处与标签、文件名「标题-YYYY-MM-DD」。"
description_zh: "文章归档入仓（Article To Obsidian）：输入 URL / 长文本 / PDF，自动抓取完整内容（含图片与排版），非中文先译后理，按文章类型差异化整理，落盘为本地 Obsidian Markdown 笔记。裸链接（无任何说明文字）同样直接触发，不先摘要、不先征求同意。"
category: document
version: 1.0.0
author: obsidian-article-archiver
---

# 文章归档入仓（Article To Obsidian）

把一篇文章**完整地**存进本地 Obsidian 库。不是摘要，不是精编，不是读后感——是**原文的完整留存 + 出处 + 标签**，让人以后能回看原文、按标签聚合、在 Obsidian 里反链搜索。

> 本 skill 只做「抓取 → 翻译 → 完整落盘」这一件事。不做价值评判，不做跨篇硬凑关联，不写点评。

## 0. 硬性闸门（先读这一节）

以下五条是红线，违反任意一条即为执行失败：

1. **裸链接也算明确指令。** 用户消息里只有一个 URL、一句说明都没有 —— 这就是「归档它」。**不要问「你是想存档还是想让我总结」**，直接走流程。
2. **禁止先摘要后询问。** 不允许「我先读一下给你看看，需要存吗」这种两步走。抓取和落盘是同一次原子操作，要么一次做完，要么不做。
3. **不要为了了解内容而绕过本 skill 直接 WebFetch。** 抓取动作发生在本 skill 内部；如果模型已经在用通用工具读这篇文章，说明路由已经错了。
4. **用户明说「只看 / 别存 / 总结一下 / 解释下」时才不落盘。** 除此之外，一律落盘。这条是唯一的例外通道。
5. **本 skill 会被多个会话 / 自动化并行使用。** 归档动作必须遵守 §9 的并发安全规范——只提交自己的文件、提交前先 `pull --rebase`、绝不 `git add -A`。违反这条会覆盖别人的改动或把别人的半成品一起提交，属于执行失败。

## 1. 触发方式

三种输入，全部直接触发，**不需要触发词**：

| 输入 | 判定 | 处理 |
|---|---|---|
| URL（含裸链接） | 消息里出现任何 `http(s)://` 文章链接 | 走 §2 全流程 |
| 长文本 | 用户直接粘贴 ≥200 字正文 | 跳过抓取，直接译 + 落盘 |
| PDF 附件 | 附件传入 | 先转文本（可联动 `mineru-pdf-to-structured-markdown`），再落盘 |

**不触发**：用户只是问「这个链接讲什么」，或明确说只看不存 → 直接回答，不落盘。

## 2. 处理流程（一次原子操作，全成或全不动）

按序勾选，不要跳步：

- [ ] **0. 使用前同步** — 跑 `use_check.py` 拉最新（跨设备必做，保证数据一致，见 §9.1）
- [ ] **1. 识别输入** — URL / 文本 / PDF
- [ ] **2. 抓取全文** — 调 `fetcher/cli.py` 取正文 Markdown + 图片清单 + 元数据（标题/作者/日期已抓取，§3.1），拿不到就走降级链
- [ ] **3. 下载图片** — 组件已把图片落到 `attachments\{文章简称}\` 并原位插入；文末二维码、引导关注图、与正文重复的封面图**跳过**
- [ ] **4. 语言处理** — 按 config 的 `language`/`translate` 决定是否翻译；默认不翻译（保留原文），用户可配置成自动译成目标语言
- [ ] **5. 类型鉴别** — 判断作者想让读者发生什么变化，按 §4 决定正文结构。**禁止一套模板通用**
- [ ] **6. 整理落盘** — 完整保留原文（文字 / 标题 / 列表 / 表格 / 引用 / 代码），不压缩、不删节、不加点评、不硬凑「相关笔记」
- [ ] **7. 标记元数据** — frontmatter 按 §5 写全
- [ ] **8. 分类关联** — 跑 `classify.py all`（补一级主题锚点 → 分文件夹 → 建强关联双链 → 刷新 MOC/图谱，见 §8.1）
- [ ] **9. 保存 + 提交** — 写入库 `notes\`，图片入 `attachments\`，本地 git commit（路径见 §9）
- [ ] **10. 回执** — 报路径、图片数、标签、是否完整、commit 号

## 3. 平台抓取策略

**抓取不再手写脚本，统一调封装好的 `fetcher` 组件**（见 §3.1）。它已内置平台适配、防盗链、编码探测、正文提取与图片下载。新增平台只需在 `adapters.py` 追加一段配置，不改核心逻辑。

先直抓，失败再降级。**任何情况下都不得因为抓不全而放弃落盘**（降级见 §8）。

| 平台 | 抓法 | 注意 |
|---|---|---|
| 微信公众号 | `fetcher` 直抓，选择器 `#js_content` | 图片在 `mmbiz.qpic.cn`，组件已内置 Referer + 浏览器 UA 防盗链 |
| X / Twitter | `fetcher` 专用入口 `x_status`：直抓帖子页为主，oEmbed 兜底 | 长文帖可直出正文与配图；短帖信息量少，串内多条以首条为主 |
| 知乎 / Medium / Substack | `fetcher` 直抓，各自选择器已配好 | 部分需浏览器 UA，组件已默认携带 |
| 普通博客 / 新闻站 | `fetcher` 直抓，走可读性启发式 | 自动剔除导航、推荐位、评论区 |
| 付费墙 / 登录墙 | 取可见部分 | 标 `source_status: degraded`，回执提示待补 |

抓取一律走 `fetcher` 组件；不要用浏览器自动化去绕登录，成本不成比例。

### 3.1 fetcher 组件（可复用抓取库）

组件位于本 skill 目录 `fetcher/`，纯标准库实现，换机零安装即用。唯一入口是 `cli.py`，模型只需执行一条命令，拿到 JSON 后做「翻译 + 类型鉴别 + frontmatter + 落盘」即可，**不写任何抓取脚本**。

```bash
python <skill目录>/fetcher/cli.py "<URL>" --out-dir "<库根>/<attachments_dir>/<文章简称>" [--config <配置文件>]
```

输出 JSON 字段：`title` / `author` / `published` / `markdown` / `images` / `platform` / `status`。

**错误分级**：`status=degraded` 表示站点反爬 / 无正文（可降级）；非零退出 + `error` 字段表示代码 bug（应暴露）。

**模块拆分**（职责单一）：

| 文件 | 职责 | 是否需按平台改 |
|---|---|---|
| `transport.py` | 传输层：UA / Referer 注入、重试、gzip、编码探测 | 否 |
| `extract.py` | 解析层：HTML → 正文 Markdown + 图片清单 + 元数据 | 否 |
| `adapters.py` | 适配层：每平台一个配置 dict，`detect(url)` 按 host 匹配 | **新增平台只改这里** |
| `entry.py` | 特殊入口：直抓拿不到正文的站点专用函数（如 `x_status`） | 仅特殊平台 |
| `cli.py` | 编排入口：`detect → fetch → extract → 元数据 → 下载图片 → JSON` | 否 |
| `classify.py` | 分类管理：`tag`/`move`/`link`/`moc`/`graph` | 分类规则改 config |
| `config.py` | 配置加载：统一读 `config.json`（路径、目录名、分类体系、语言） | 否 |
| `use_check.py` | 使用前同步：自动 `pull --rebase` 拉最新 | 否 |
| `sync_check.py` | 提交前防覆盖：查 ahead/behind/skill 冲突 | 否 |
| `precommit_check.py` | 提交前防脏文件 | 否 |
| `errors.py` | 异常层级：`FetchError`/`NoContentError`/`ParseError` | 否 |
| `tests/` | unittest 测试套件 | 否，改核心逻辑需跑一遍 |

**通用性来源**：三层解耦——传输层屏蔽网络差异，解析层「选择器优先 + 密度启发式兜底」覆盖未知站点，适配层把平台差异收敛成配置。新增站点 = 加一段 dict；站点改版 = 只调对应选择器。

**调试**：抓取异常时直接跑 `cli.py` 看 JSON 定位出错层。改核心逻辑后跑测试：

```bash
cd <skill目录>/fetcher && python -m unittest discover -s tests
```

## 4. 类型 → 沉淀策略

判断依据是**作者想让读者发生什么变化**，不是题材。未命中的类型，只保留原文和出处，不硬套结构。

| 类型 | 识别特征 | 正文结构 |
|---|---|---|
| 科普 / 讲解 | 讲清楚一个概念或机制 | 保留原文分段 |
| 新闻 / 资讯 | 陈述事实与多方说法 | 事实链 + 各方说法 |
| 教程 / 规范 | 可照着操作 | 保留步骤、清单、表格、示例代码 |
| 观点 / 评论 | 表达作者判断 | 保留论点、论证、结论 |
| 访谈 / 对话 | 问答形式 | 保留问答原貌 + 关键引语 |
| 报告 / 研究 | 数据 + 结论 | 保留数据、图表说明、结论 |
| 资料汇编 / 图解 | 图为主、文字为辅 | 图原位插入 + 每图讲解 |
| 清单 / 推荐 | 罗列条目并逐条点评 | 条目逐条完整保留 |

## 5. 输出格式（单篇笔记结构）

```markdown
---
title: 文章标题
source: 公众号/网站名
author: 作者名
published: YYYY-MM-DD
url: 原文链接
type: 类型（对应 §4 表格）
source_status: complete   # 抓不全时写 degraded
tags:
  - 类型/xxx
  - 主题/xxx
  - 人物/xxx（如有）
---

# 文章标题

![图片说明](../attachments/xxx/01.png)

（完整原文正文）
```

- **文件名**：`标题-YYYY-MM-DD.md`（日期取原文发布日；无则取归档日）。
- **图片**：下载到 `attachments\{文章简称}\`，相对路径 `../attachments/{简称}/NN.ext` 引用。
- **正文**：完整原文，不删减、不改写、不点评。

## 6. 标签体系

标签用两级结构 `分类/词汇`：

- `类型/…`：类型名称（访谈记录、教程规范、新闻资讯…）。
- `主题/…`：内容主题，分两级——**一级主题锚点**（主分类，决定文件夹与聚合分组，来自 config 的 `taxonomy.primary_themes`）+ **二级主题词**（精细检索，自由细分）。
- `人物/…`：主要人物或作者（如有）。

> **一级主题锚点可自动补**：落盘后跑 `classify.py tag`，脚本按 config 的 `taxonomy.title_to_theme` 自动补上。

## 7. 关联规则（分层关联）

| 强度 | 判断标准 | 是否连 |
|---|---|---|
| **强关联** | 系列/前后篇、直接回应补充反驳、同作者思想脉络 | ✅ 必连（`classify.py link` 处理） |
| **中关联** | 同一具体子主题 | ✅ 连 + 说明（模型判断后手动加） |
| **弱关联** | 只有宽泛交集（「都讲 AI」） | ❌ 不连 |

双链格式（文末追加）：

```markdown
## 🔗 相关文章

- [[目标文章-YYYY-MM-DD|标题]]：关联说明
```

## 8. 边界与降级

- **抓取不完整**：标注 `source_status: degraded`，只落盘可见部分，不替原文补写。
- **抓取失败 / 付费墙**：不丢弃，回执标明「待补全文」。
- **图片下载失败**：单张失败跳过，留 `<!-- 图片缺失 -->` 占位。
- **重复归档**：按 `url` 字段查重，已存在不建第二份。

## 8.1 分类管理（归档后的标准化）

```bash
# 一步到位
python <skill目录>/fetcher/classify.py all --vault <库根> [--config <配置文件>]

# 分步
python classify.py tag   --notes <库根>/notes
python classify.py move  --notes <库根>/notes
python classify.py link  --notes <库根>/notes
python classify.py moc   --vault <库根> --notes <库根>/notes
python classify.py graph --vault <库根>
```

**目录结构**（分文件夹后）：

```
<库根>/
├── 00-总览.md              # MOC 主页（Dataview 聚合）
├── notes/
│   ├── 技术/               # 一级主题锚点决定文件夹
│   └── ...
└── attachments/            # 图片
```

> 分类规则（一级主题、标题映射、图谱配色）全部在 `config.json` 的 `taxonomy` 里配置，改配置不改代码。

## 9. 配置与路径

**所有个性化配置集中在 `config.json`**（模板见 `config.example.json`）。库根路径按优先级解析：

1. 命令行参数 `--vault` / `--config`
2. 环境变量 `$OBSIDIAN_VAULT`
3. 配置文件 `config.json` 的 `vault_path`
4. 都不存在 → 交互询问一次，写回 config.json

```bash
# 首次使用：复制配置模板并填写
cp config.example.json config.json
# 编辑 config.json，填入你的 vault_path
```

### 9.1 同步与提交规范（多设备 / 多人并行时遵守）

```bash
cd <库根>

# 0. 使用前同步（自动 pull --rebase）
python <skill目录>/fetcher/use_check.py --repo .

# 1. 提交前防覆盖
python <skill目录>/fetcher/sync_check.py --repo .

# 2. 提交前防脏文件
python <skill目录>/fetcher/precommit_check.py --keep "notes/<本篇>" "attachments/<简称>/"

# 3. 只 add 本次自己的文件（不要 -A）
git add "notes/<本篇>" "attachments/<简称>/"

# 4. 提交 + 推送
git commit -m "归档: <标题>"
git push
```

**三个脚本分工**：`use_check.py`（使用前拉最新）/ `sync_check.py`（提交前防覆盖）/ `precommit_check.py`（提交前防脏文件）。

## 10. 安装到新终端

```bash
# 1. 拉取本 skill 仓库
git clone <本仓库地址> obsidian-article-archiver

# 2. 拷贝到你所用 AI 助手的用户级 skills 目录（<SKILLS_DIR> 按平台实际路径替换）
mkdir -p <SKILLS_DIR>/obsidian-article-archiver
cp -r obsidian-article-archiver/fetcher <SKILLS_DIR>/obsidian-article-archiver/
cp obsidian-article-archiver/SKILL.md <SKILLS_DIR>/obsidian-article-archiver/

# 3. 配置
cd <SKILLS_DIR>/obsidian-article-archiver
cp config.example.json config.json
# 编辑 config.json 填入 vault_path
```

> `<SKILLS_DIR>` 为宿主平台的用户级 skills 目录（各平台约定不同，如某平台为
> `~/.workbuddy/skills`），请参照所用平台的 skill 安装文档。

- 依赖的现成 skill（可选）：`mineru-pdf-to-structured-markdown`（PDF 输入）。
- 安装后贴一个 URL 即触发；首次使用会确认库路径。
