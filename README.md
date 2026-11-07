# obsidian-article-archiver

把网页文章**完整地**归档到本地 Obsidian 库的通用 skill。

- **完整留存**：不是摘要、不是精编，是原文的完整保留 + 出处 + 标签
- **零依赖**：抓取组件纯 Python 标准库，换机零安装
- **可配置**：路径、目录名、分类体系、翻译策略全部集中在 `config.json`
- **多平台**：公众号 / X(Twitter) / 知乎 / Medium / Substack / 博客 / 任意网页
- **图谱友好**：自动补一级主题标签、建双链、生成 MOC 主页和图谱配色
- **宿主无关**：不绑定任何特定 AI 助手，任何支持 skill 机制的平台都能装

## 快速开始

```bash
# 1. 安装 skill 到你所用 AI 助手的 skills 目录（以 <SKILLS_DIR> 占位，按实际平台替换）
mkdir -p <SKILLS_DIR>/obsidian-article-archiver
cp -r fetcher <SKILLS_DIR>/obsidian-article-archiver/
cp SKILL.md <SKILLS_DIR>/obsidian-article-archiver/

# 2. 配置
cd <SKILLS_DIR>/obsidian-article-archiver
cp config.example.json config.json
#    编辑 config.json，填入你的 Obsidian 库路径 vault_path

# 3. 使用：在支持 skill 的 AI 助手里贴一个文章链接即可触发归档
```

> `<SKILLS_DIR>` 是你所用平台的用户级 skills 目录。例如某平台为 `~/.workbuddy/skills`，
> 其他平台各有约定路径，请参照该平台的 skill 安装文档填写。

## 配置说明

所有个性化配置集中在 `config.json`（模板 `config.example.json`）：

```json
{
  "vault_path": "D:/your/obsidian/vault",   // Obsidian 库根路径（必填）
  "notes_dir": "notes",                      // 笔记目录名
  "attachments_dir": "attachments",          // 图片目录名
  "language": "zh-CN",                       // 目标语言
  "translate": false,                        // 是否自动翻译非目标语言内容
  "taxonomy": {
    "primary_themes": ["技术", "产品", ...],  // 一级主题（决定文件夹）
    "title_to_theme": [["数仓", "技术"], ...], // 标题关键词 → 主题映射
    "graph_colors": [{"query": "tag:#主题/技术", "rgb": 14048348}]
  }
}
```

配置优先级：命令行参数 > 环境变量 `OBSIDIAN_VAULT` > `config.json` > 内置默认。

## 组件结构

```
fetcher/
├── cli.py              抓取编排入口（唯一命令行接口）
├── classify.py         分类管理：tag / move / link / moc / graph
├── config.py           配置加载器
├── transport.py        传输层（UA/Referer/重试/编码探测）
├── extract.py          解析层（HTML → Markdown + 图片 + 元数据）
├── adapters.py         平台适配层（新增平台只改这里）
├── entry.py            特殊平台入口
├── use_check.py        使用前同步（自动 pull --rebase）
├── sync_check.py       提交前防覆盖
├── precommit_check.py  提交前防脏文件
├── errors.py           异常层级
└── tests/              单元测试 + 集成测试
```

## 常见用法

```bash
cd <skill目录>/fetcher

# 抓取一篇
python cli.py "https://..." --out-dir "<库>/attachments/<简称>"

# 归档后分类（一步到位）
python classify.py all --vault <库根>

# 运行测试
python -m unittest discover -s tests
```

## 设计原则

1. **职责单一**：抓取、分类、同步各自独立组件，换模型/换会话行为一致
2. **配置优先**：个人定制（路径、分类法、语言）全部收敛到 config，不改代码
3. **幂等**：分类命令可重复运行，不重复加标签/建目录/加链接
4. **不破坏原文**：只动 frontmatter 和文末关联区块，正文一字不改

## License

MIT
