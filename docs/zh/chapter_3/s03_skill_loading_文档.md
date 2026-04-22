# s03: Skill Loading (技能加载) - 代码文档

---

## 概述

### 核心改进

**从固定工具到动态知识扩展**

s03 在 s02 的基础上引入了 **Skill 系统**，允许模型动态加载领域知识文档。这解决了系统提示词长度受限与领域知识无限增长之间的矛盾。

### 设计思想

> **"Don't put everything in the system prompt. Load on demand."**

s03 的核心设计思想：**Knowledge-as-Code（知识即代码）**。将领域知识以 Markdown 文档的形式存放在 `skills/` 目录下，通过两层加载机制实现按需获取：

- **Layer 1（低成本）**：系统提示中仅包含技能名称和简短描述（约 100 tokens/技能）
- **Layer 2（按需加载）**：当模型调用 `load_skill` 工具时，返回完整技能文档内容

### 代码文件路径

```
v1_task_manager/chapter_3/s03_skill_loading.py
```

### 核心架构图（对比 s02）

**s02 架构（固定工具集）**：
```
    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch    |
    |  prompt  |      |       |      | {bash, read,     |
    +----------+      +---+---+      |  write, edit}    |
                          ^          +------------------+
                          |                 |
                          +-----------------+
                               tool_result
```

**s03 架构（动态知识注入）**：
```
    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch    |
    |  prompt  |      |       |      | {bash, read,     |
    +----------+      +---+---+      |  write, edit,    |
                          ^          |  load_skill}     |
                          |          +------------------+
                          |                 |
                    +-----+-----+           |
                    |  Skill    | <---------+
                    |  Prompt   |  load_skill("pdf")
                    |  (Layer 1)|
                    +-----+-----+
                          |
                    +-----v-----+
                    |  Skill    |
                    |  Document |  <--- skills/pdf/SKILL.md
                    |  (Layer 2)|       skills/jsonl_handler/SKILL.md
                    +-----------+
```

**架构说明**：
1. 系统初始化时，`SkillLoader` 扫描 `skills/` 目录，解析所有 `SKILL.md` 文件的 frontmatter 元数据
2. Layer 1 元数据（名称、描述、标签）注入到 SYSTEM 提示词中
3. LLM 根据任务需求判断是否需要加载特定技能
4. 调用 `load_skill("技能名")` 工具，返回完整技能文档（Layer 2）
5. 模型基于完整技能知识执行任务

---

## 与 s02 的对比

### 变更总览

| 组件 | s02 | s03 | 变化说明 |
|------|-----|-----|----------|
| **导入模块** | 标准库 | + `re` | 新增正则表达式模块用于解析 frontmatter |
| **技能目录** | 无 | `SKILLS_DIR = WORKDIR / "skills"` | 新增技能文档存储目录 |
| **数据结构** | 无 | `SkillLoader` 类 | 新增技能加载器，管理技能元数据和内容 |
| **工具集** | 4 个工具 | 5 个工具 | 新增 `load_skill` 工具 |
| **SYSTEM 提示词** | 固定文本 | 动态注入技能列表 | 系统提示包含可用技能描述 |
| **知识管理** | 硬编码在提示词 | 外部文档按需加载 | Knowledge-as-Code 实现 |

### 新增组件架构

```
    skills/
    ├── pdf_handler/
    │   └── SKILL.md      # Frontmatter + 完整技能文档
    ├── jsonl_handler/
    │   └── SKILL.md
    └── code-review/
        └── SKILL.md

    SkillLoader 类
    ├── _load_all()       # 扫描并解析所有 SKILL.md
    ├── _parse_frontmatter()  # 解析 YAML frontmatter
    ├── get_descriptions()    # Layer 1: 获取简短描述
    └── get_content()         # Layer 2: 获取完整内容

    SYSTEM 提示词
    ┌─────────────────────────────────────┐
    │ You are a coding agent at WORKDIR.  │
    │ Use load_skill to access specialized│
    │ knowledge before tackling unfamiliar│
    │ topics.                             │
    │ Skills available:                   │
    │   - pdf_handler: ... [tags]         │  <-- Layer 1
    │   - jsonl_handler: ... [tags]       │
    └─────────────────────────────────────┘
```

---

## 按执行顺序详解

### 第 1 阶段：新增导入模块

#### re 模块的引入

**机制概述**：
s03 新增导入 `re` 模块（正则表达式），用于解析技能文档中的 YAML frontmatter 格式。frontmatter 是一种在 Markdown 文件顶部存储元数据的约定格式，使用 `---` 分隔符包裹 YAML 内容。

```python
import re
```

**设计思想**：
- 使用正则而非 YAML 解析库，减少外部依赖
- frontmatter 格式简单，正则足以处理 `key: value` 键值对
- 保持项目的轻量级和可移植性

**Frontmatter 格式示例**：
```markdown
---
name: pdf_handler
description: Comprehensive best practices for PDF files.
tags: python, pdf, document-processing
---

# PDF Handler Skill

完整技能文档内容...
```

---

### 第 2 阶段：技能目录配置

**机制概述**：
定义 `SKILLS_DIR` 常量，指向工作目录下的 `skills/` 子目录。该目录用于存储所有技能文档，每个技能占据一个子目录，包含一个 `SKILL.md` 文件。

```python
WORKDIR = Path.cwd()
SKILLS_DIR = WORKDIR / "skills"
```

**技能目录结构设计**：
```
skills/
├── pdf_handler/
│   └── SKILL.md
├── jsonl_handler/
│   └── SKILL.md
└── code-review/
    └── SKILL.md
```

**设计思想**：
- 每个技能独立目录，便于组织和管理
- 统一命名为 `SKILL.md`，便于自动扫描
- 支持嵌套子目录（使用 `rglob` 递归查找）
- 使用大写字母命名 `SKILL.md`，突出其特殊性

---

### 第 3 阶段：技能数据结构定义

#### SkillLoader 类

**机制概述**：
`SkillLoader` 类负责扫描 `skills/` 目录，解析所有 `SKILL.md` 文件，并提供两层访问接口：
- Layer 1：`get_descriptions()` 返回简短描述，用于注入系统提示
- Layer 2：`get_content(name)` 按需加载指定技能的完整内容

该类采用 ** eager loading（急切加载）** 策略：初始化时立即扫描并解析所有技能元数据，但完整内容仅在请求时读取。

```python
class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills = {}
        self._load_all()  # 初始化时扫描所有技能
    
    def _load_all(self):
        if not self.skills_dir.exists():
            return
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            text = f.read_text()
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}
```

**数据结构设计**：
```python
self.skills = {
    "pdf_handler": {
        "meta": {
            "name": "pdf_handler",
            "description": "Comprehensive best practices...",
            "tags": "python, pdf, document-processing"
        },
        "body": "# PDF Handler Skill\n\n完整内容...",
        "path": "/path/to/skills/pdf_handler/SKILL.md"
    },
    "jsonl_handler": { ... }
}
```

**嵌套式数据结构设计思想**：
- `meta`：存储 frontmatter 解析的元数据，用于 Layer 1
- `body`：存储 frontmatter 之后的完整文档内容，用于 Layer 2
- `path`：存储文件路径，便于调试和错误报告
- 使用字典而非数据类，保持灵活性和简洁性

---

### 第 4 阶段：SkillLoader 类详解

#### _parse_frontmatter() 方法

**机制概述**：
解析 Markdown 文件顶部的 YAML frontmatter。使用正则表达式匹配 `---` 分隔符之间的内容，逐行解析 `key: value` 键值对。

```python
def _parse_frontmatter(self, text: str) -> tuple:
    """Parse YAML frontmatter between --- delimiters."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text  # 无 frontmatter，返回空元数据和全文
    meta = {}
    for line in match.group(1).strip().splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip()
    return meta, match.group(2).strip()
```


**设计思想**：
- 简单 YAML 解析：仅处理 `key: value` 格式，不支持复杂嵌套
- 容错处理：无 frontmatter 时返回全文作为 body
- 冒号分割：`split(":", 1)` 确保值中包含冒号时正确处理

---

#### get_descriptions() 方法（Layer 1）

**机制概述**：
生成用于系统提示词的技能描述列表。遍历所有已加载的技能，提取元数据中的 `description` 和 `tags` 字段，格式化为易读的列表。

```python
def get_descriptions(self) -> str:
    """Layer 1: short descriptions for the system prompt."""
    if not self.skills:
        return "(no skills available)"
    lines = []
    for name, skill in self.skills.items():
        desc = skill["meta"].get("description", "No description")
        tags = skill["meta"].get("tags", "")
        line = f"  - {name}: {desc}"
        if tags:
            line += f" [{tags}]"
        lines.append(line)
    return "\n".join(lines)
```

**输出示例**：
```
Skills available:
  - pdf_handler: Comprehensive best practices for PDF files. [python, pdf, document-processing]
  - jsonl_handler: Best practices for processing JSONL files. [python, data-processing]
```

**设计思想**：
- 紧凑格式：每行一个技能，减少 token 消耗
- 标签可选：有 tags 时追加显示，便于模型快速识别技能领域
- 空技能处理：无技能时返回提示文本，避免系统提示为空

---

#### get_content() 方法（Layer 2）

**机制概述**：
按需加载指定技能的完整文档内容。接收技能名称，返回格式化的 XML 标签包裹的技能正文。如果技能不存在，返回错误信息和可用技能列表。

```python
def get_content(self, name: str) -> str:
    """Layer 2: full skill body returned in tool_result."""
    skill = self.skills.get(name)
    if not skill:
        return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
    return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"
```

**输出示例**：
```xml
<skill name="pdf_handler">
# PDF Handler Skill

This skill provides comprehensive patterns for handling PDF files...

## 1. Reading PDF Files
...
</skill>
```

**设计思想**：
- XML 标签包裹：使用 `<skill name="...">` 明确标识技能内容边界
- 错误友好：技能不存在时提示可用选项，引导正确使用
- 按需加载：完整内容仅在调用时返回，避免一次性消耗大量 token

---

### 第 5 阶段：新增工具 - load_skill

#### 工具定义

**机制概述**：
`load_skill` 是 s03 新增的核心工具，允许模型在需要时动态加载特定技能的完整文档。该工具接收技能名称，返回格式化的技能内容。

**JSON Schema 定义**：
```python
{"type": "function", "function": {
    "name": "load_skill",
    "description": "Load specialized knowledge by name.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name to load"
            }
        },
        "required": ["name"]
    }
}}
```

**工具处理函数**：
```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_LOADER.get_content(kw["name"]),  # 新增
}
```

**与其他工具的协作关系**：
```
任务：处理 PDF 文件并提取文本

1. LLM 接收任务，查看系统提示中的技能列表
   → 发现 "pdf_handler: Comprehensive best practices for PDF files"

2. LLM 调用 load_skill("pdf_handler")
   → 获取完整 PDF 处理技能文档

3. LLM 基于技能文档中的代码示例，调用 bash 安装依赖
   → bash("pip install PyPDF2 pypdf reportlab")

4. LLM 调用 write_file 创建处理脚本
   → write_file("process_pdf.py", "...代码...")

5. LLM 调用 bash 执行脚本
   → bash("python process_pdf.py")
```

---

### 第 6 阶段：SYSTEM 提示词变化

#### s02 vs s03 对比

**s02 SYSTEM 提示词**：
```python
SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks. Act, don't explain."
```

**s03 SYSTEM 提示词**：
```python
SKILL_LOADER = SkillLoader(SKILLS_DIR)
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use load_skill to access specialized knowledge before tackling unfamiliar topics.
Skills available: {SKILL_LOADER.get_descriptions()}"""
```

**变化说明**：
1. **新增技能使用指导**：明确告知模型使用 `load_skill` 工具获取领域知识
2. **动态注入技能列表**：通过 `SKILL_LOADER.get_descriptions()` 动态生成可用技能描述
3. **行为引导**：建议模型在处理不熟悉的主题前先加载相关技能

**技能列表动态注入机制**：
```python
# 初始化时执行
SKILL_LOADER = SkillLoader(SKILLS_DIR)  # 扫描 skills/ 目录

# 生成系统提示时调用
SYSTEM = f"""...
Skills available: {SKILL_LOADER.get_descriptions()}"""

# get_descriptions() 输出示例：
#   - pdf_handler: Comprehensive best practices... [python, pdf]
#   - jsonl_handler: Best practices for JSONL... [python, data]
```

**设计思想**：
- 技能发现：模型通过系统提示了解可用技能
- 按需决策：模型根据任务需求判断是否需要加载技能
- 低成本：技能描述仅占用约 100 tokens/技能，远小于完整文档

---

## 完整框架流程图

```
┌─────────────┐
│    User     │  输入任务："处理这个 PDF 文件，提取所有文本"
└──────┬──────┘
       │
       ▼
┌─────────────┐
│     LLM     │  查看系统提示中的技能列表
│  (初始状态) │  → 发现 "pdf_handler: ..."
└──────┬──────┘
       │
       │ 需要技能知识？
       ├─────────────────┐
       │ 是              │ 否
       ▼                 │
┌─────────────┐          │
│  load_skill │          │
│ ("pdf_      │          │
│  handler")  │          │
└──────┬──────┘          │
       │                 │
       ▼                 │
┌─────────────┐          │
│ SkillLoader │          │
│ .get_content│          │
└──────┬──────┘          │
       │                 │
       ▼                 │
┌─────────────┐          │
│ tool_result │          │
│ <skill>     │          │
│ 完整文档    │          │
│ </skill>    │          │
└──────┬──────┘          │
       │                 │
       └────────┬────────┘
                │
                ▼
         ┌─────────────┐
         │     LLM     │  基于技能文档中的指导
         │ (增强状态)  │  生成执行计划
         └──────┬──────┘
                │
                ▼
         ┌─────────────┐
         │ Tool Call   │  bash, write_file, etc.
         └─────────────┘
```

---

## 技能文档格式规范

### SKILL.md 文件结构

````markdown
---
name: 技能名称（用于 load_skill 调用）
description: 简短描述（用于系统提示，建议 50-100 字符）
tags: 逗号分隔的标签（可选，用于分类）
---

# 技能标题

## 章节 1: 主题

详细说明...

```python
# 代码示例
def example():
    pass
```

## 章节 2: 主题

...
````

### Frontmatter 格式

**必需字段**：
- `name`：技能唯一标识，用于 `load_skill("技能名")` 调用
- `description`：简短描述，注入系统提示词

**可选字段**：
- `tags`：逗号分隔的标签，帮助模型快速识别技能领域

**格式要求**：
- 使用 `---` 分隔符包裹 YAML 内容
- 每个字段占一行，格式为 `key: value`
- Frontmatter 必须位于文件开头

### 内容编写规范

1. **结构清晰**：使用 Markdown 标题组织内容（`##`, `###`）
2. **代码示例**：提供可直接使用的代码片段
3. **最佳实践**：包含常见陷阱和解决方案
4. **快速参考**：可添加表格总结关键信息
5. **语言中立**：使用英文编写，便于国际化

---

## 设计点总结

### Knowledge-as-Code 原则

**核心思想**：将领域知识以代码文档的形式管理，而非硬编码在系统提示中。

**优势**：
- **可维护性**：技能文档独立于代码，易于更新和版本控制
- **可扩展性**：添加新技能只需在 `skills/` 目录新增文件
- **模块化**：每个技能自包含，便于复用和组合
- **Token 效率**：按需加载，避免系统提示词膨胀

### 动态知识注入机制

**两层架构**：
- **Layer 1（元数据）**：系统提示中包含技能名称和描述（低成本）
- **Layer 2（完整内容）**：工具调用返回完整技能文档（按需）

**工作流程**：
```
初始化 → 扫描技能 → 注入元数据 → 模型决策 → 按需加载 → 执行任务
```

### 技能与工具的分离设计

**工具（Tools）**：
- 执行具体操作（bash、文件读写等）
- 改变外部状态
- 数量有限（通常 5-10 个）

**技能（Skills）**：
- 提供领域知识
- 不直接执行操作
- 数量可扩展（理论上无限）

**设计优势**：
- 工具保持精简，聚焦核心能力
- 技能独立扩展，不修改核心代码
- 模型清晰区分"做什么"（工具）和"怎么做"（技能）

### 延迟加载优化

**实现策略**：
- 初始化时仅加载元数据（轻量）
- 完整内容在 `get_content()` 调用时返回
- 避免一次性加载所有技能文档

**Token 节省**：
```
假设 10 个技能，每个技能文档 2000 tokens

❌ 全部放入系统提示：20,000 tokens
✅ Layer 1 元数据：1,000 tokens（100 tokens/技能）
✅ Layer 2 按需加载：仅加载实际使用的技能
```

---

## 实践指南

### 如何创建新技能

**步骤 1：创建技能目录**
```bash
mkdir -p skills/your-skill-name
```

**步骤 2：创建 SKILL.md 文件**
```markdown
---
name: your-skill-name
description: 简短描述此技能的功能
tags: 相关标签，如 python, web, api
---

# Your Skill Name

## Overview

技能概述...

## Usage

使用方法和代码示例...

## Best Practices

最佳实践和注意事项...
```

**步骤 3：验证技能加载**
```bash
# 运行 s03，调用 load_skill("your-skill-name")
python v1_task_manager/chapter_3/s03_skill_loading.py
```

### 技能目录结构示例

```
skills/
├── pdf_handler/
│   └── SKILL.md          # PDF 处理技能
├── jsonl_handler/
│   └── SKILL.md          # JSONL 处理技能
├── code-review/
│   └── SKILL.md          # 代码审查技能
├── web-scraping/
│   └── SKILL.md          # 网页爬取技能
└── database/
    └── SKILL.md          # 数据库操作技能
```

### 测试示例

**测试脚本**：
```python
from pathlib import Path
from s03_skill_loading import SkillLoader

# 初始化技能加载器
SKILLS_DIR = Path.cwd() / "skills"
loader = SkillLoader(SKILLS_DIR)

# 测试 Layer 1：获取技能描述
print("=== 可用技能 ===")
print(loader.get_descriptions())

# 测试 Layer 2：加载完整技能
print("\n=== 加载 pdf_handler 技能 ===")
content = loader.get_content("pdf_handler")
print(content[:500])  # 打印前 500 字符

# 测试错误处理
print("\n=== 测试不存在技能 ===")
print(loader.get_content("non-existent"))
```

**预期输出**：
```
=== 可用技能 ===
  - pdf_handler: Comprehensive best practices... [python, pdf]
  - jsonl_handler: Best practices for JSONL... [python, data]

=== 加载 pdf_handler 技能 ===
<skill name="pdf_handler">
# PDF Handler Skill

This skill provides comprehensive patterns...
</skill>

=== 测试不存在技能 ===
Error: Unknown skill 'non-existent'. Available: pdf_handler, jsonl_handler
```

---

## 整体设计思想总结

### 1. 关注点分离（Separation of Concerns）

将**工具执行**与**领域知识**分离：
- 工具负责"做什么"（执行操作）
- 技能负责"怎么做"（提供方法）
- 两者独立演进，互不影响

### 2. 按需加载（Lazy Loading）

避免预加载所有知识：
- 系统提示仅包含轻量元数据
- 完整内容在需要时加载
- 减少初始 token 消耗，提高响应速度

### 3. 知识即代码（Knowledge-as-Code）

用代码工程化方法管理知识：
- 技能文档版本控制（Git）
- 代码审查流程
- 自动化测试验证
- 文档与代码同等对待

### 4. 可扩展性优先（Scalability First）

设计支持无限扩展：
- 新增技能无需修改核心代码
- 技能目录自动扫描
- 工具调用接口统一

### 5. 用户体验优化（UX Optimization）

为模型提供友好的知识获取体验：
- 系统提示中清晰列出可用技能
- 技能描述简洁明了
- 错误信息提供可用选项

### 6. Token 经济性（Token Economics）

优化 token 使用效率：
- Layer 1 元数据约 100 tokens/技能
- Layer 2 按需加载，避免浪费
- 相比全量注入节省 90%+ token

---

*文档版本：v1.0*
*基于代码：v1_task_manager/chapter_3/s03_skill_loading.py*
