# s10: System Prompt Rebuild (系统提示词重构) 

## 概述

s10 在 s09 记忆系统的基础上进行了**系统提示词结构化重构**。核心改进是从硬编码的系统提示字符串升级为模块化、可扩展的提示词构建器，使系统提示的各个组成部分独立可维护。

### 核心改进

1. **SystemPromptBuilder 类** - 核心创新，实现 6 层结构化提示词构建 pipeline
2. **main_build() / sub_build() 方法** - 分别为 Main Agent 和 Sub Agent 构建差异化的系统提示
3. **DYNAMIC_BOUNDARY 标记** - 分隔静态提示词和动态上下文，为后续缓存优化预留接口
4. **配置参数全面提升** - 适应更复杂的长上下文场景
5. **s09 功能完整保留** - MemoryManager、HookManager、PermissionManager 等核心组件无变化

### 设计思想

```
┌─────────────────────────────────────────────────────────────────┐
│                    s10 系统提示词架构                            │
├─────────────────────────────────────────────────────────────────┤
│  Section 1: Core instructions (核心指令)                         │
│  Section 2: Tool listing (工具列表)                              │
│  Section 3: Skill metadata (技能元数据)                          │
│  Section 4: Memory section (记忆内容)                            │
│  Section 5: CLAUDE.md chain (项目规范链) [预留]                   │
│  === DYNAMIC_BOUNDARY ===                                       │
│  Section 6: Dynamic context (动态上下文)                         │
└─────────────────────────────────────────────────────────────────┘
```

### 代码文件路径

- **源代码**：v1_task_manager/chapter_10/s10_build_system.py
- **参考文档**：v1_task_manager/chapter_9/s09_memory_system_文档.md
- **记忆目录**：`.memory/`（工作区根目录下的隐藏目录）
- **技能目录**：`skills/`（工作区根目录下）
- **钩子配置**：`.hooks.json`（工作区根目录下的钩子拦截管线配置文件）
- **Claude 信任标记**：`.claude/.claude_trusted`（工作区根目录下的隐藏目录，用于标识受信任的工作区）

---

## 与 s09 的对比

### 变更总览

| 组件 | s09 | s10 |
|------|-----|-----|
| 系统提示构建 | `build_system_prompt()` 函数拼接字符串 | `SystemPromptBuilder` 类模块化构建 |
| 提示词结构 | 3 部分：SYSTEM + Memory + Guidance | 6 层：Core → Tools → Skills → Memory → CLAUDE.md → Dynamic |
| 主 Agent 提示 | `build_system_prompt(SYSTEM)` | `prompt_builder.main_build()` |
| 子 Agent 提示 | `SUBAGENT_SYSTEM` 常量 | `prompt_builder.sub_build()` |
| 静态/动态分隔 | 无 | `DYNAMIC_BOUNDARY` 标记 |
| CONTEXT_LIMIT | 80000 | 100000 |
| PERSIST_THRESHOLD | 40000 | 60000 |
| PREVIEW_CHARS | 10000 | 20000 |
| PLAN_REMINDER_INTERVAL | 3 | 5 |
| KEEP_RECENT_TOOL_RESULTS | 3 | 5 |
| PermissionManager 初始化 | 从环境变量或参数获取 mode | 交互式输入 mode |
| MemoryManager | 完整实现 | 完整保留（无变化） |
| DreamConsolidator | 待激活 | 完整保留（无变化） |
| HookManager | 完整实现 | 完整保留（无变化） |
| PermissionManager | 完整实现 | 完整保留（初始化方式变更） |
| BashSecurityValidator | 完整实现 | 完整保留（无变化） |

### SystemPromptBuilder 类架构

```
SystemPromptBuilder
├── __init__(workdir, tools, sub_tools)
│   └── 初始化工作目录、主/子 Agent 工具列表、技能目录、记忆目录
├── _build_core()
│   └── Section 1: 核心指令（Agent 身份、基本行为准则）
├── _build_tool_listing(obj_tools)
│   └── Section 2: 工具列表（从 OpenAI 格式工具定义提取）
├── _build_skill_listing()
│   └── Section 3: 技能元数据（扫描 skills/ 目录下的 SKILL.md）
├── _build_memory_section()
│   └── Section 4: 记忆内容（扫描 .memory/ 目录下的记忆文件）
├── _build_claude_md()
│   └── Section 5: CLAUDE.md 链（预留，当前版本未激活）
├── _build_dynamic_context()
│   └── Section 6: 动态上下文（日期、工作目录、模型信息）
├── main_build()
│   └── 组装 Main Agent 完整系统提示（使用 PARENT_TOOLS）
└── sub_build()
    └── 组装 Sub Agent 完整系统提示（使用 CHILD_TOOLS）
```

---

## s10 新增内容详解（按代码执行顺序）

### 第 1 阶段：配置参数变更

#### 上下文管理参数

```python
CONTEXT_LIMIT = 100000              # s09: 80000
PERSIST_THRESHOLD = 60000           # s09: 40000
PREVIEW_CHARS = 20000               # s09: 10000
PLAN_REMINDER_INTERVAL = 5          # s09: 3
KEEP_RECENT_TOOL_RESULTS = 5        # s09: 3
```

参数调整适应更复杂的长上下文场景，提高工具结果保留数量和计划提醒间隔。

| 参数 | s09 值 | s10 值 | 用途 |
|------|--------|--------|------|
| CONTEXT_LIMIT | 80000 | 100000 | 触发自动压缩的上下文大小阈值 |
| PERSIST_THRESHOLD | 40000 | 60000 | 工具输出持久化到文件的阈值 |
| PREVIEW_CHARS | 10000 | 20000 | 持久化输出时保留的预览字符数 |
| PLAN_REMINDER_INTERVAL | 3 | 5 | 连续多少轮未更新计划后触发提醒 |
| KEEP_RECENT_TOOL_RESULTS | 3 | 5 | 微型压缩时保留的最近工具结果数量 |

---

### 第 2 阶段：SystemPromptBuilder 类

#### 初始化

```python
class SystemPromptBuilder:
    def __init__(self, workdir: Path = None, tools: list = None, sub_tools: list = None):
        self.workdir = workdir or WORKDIR
        self.tools = tools or []
        self.sub_tools = sub_tools or []
        self.skills_dir = self.workdir / "skills"
        self.memory_dir = self.workdir / ".memory"
```

初始化时设置工作目录、主 Agent 工具列表、子 Agent 工具列表、技能目录路径、记忆目录路径。tools 参数传入 PARENT_TOOLS，sub_tools 参数传入 CHILD_TOOLS。

#### _build_core() 方法 - Section 1

```python
def _build_core(self) -> str:
    return (
        f"You are a coding agent operating in {self.workdir}.\n"
        "Use the provided tools to explore, read, write, and edit files.\n"
        "Always verify before assuming. Prefer reading files over guessing.\n"
        "The user controls permissions. Some tool calls may be denied.\n"
    )
```

生成核心指令部分，包含 Agent 身份声明、基本行为准则、权限说明。返回固定格式的字符串。

#### _build_tool_listing() 方法 - Section 2

```python
def _build_tool_listing(self, obj_tools: list = None) -> str:
    if not obj_tools:
        return ""
    
    lines = ["# Available tools"]
    for tool in obj_tools:
        func = tool.get("function", {})
        name = func.get("name", "")
        desc = func.get("description", "")
        props = func.get("parameters", {}).get("properties", {})
        params = ", ".join(props.keys())
        lines.append(f"- {name}({params}): {desc}")
    
    return "\n".join(lines)
```

遍历工具列表，从 OpenAI 格式的工具定义中提取工具名称、描述、参数列表，生成 Markdown 格式的工具说明。参数从 `parameters.properties` 中提取键名。

**输出示例**：
```markdown
# Available tools
- read_file(path, limit): Read file contents.
- task(prompt, description): Spawn a subagent with fresh context to finish.
- todo(items): Rewrite the current session plan for multi-step work.
- compact(focus): Summarize earlier conversation so work can continue in a smaller context.
- save_memory(name, description, type, content): Save a persistent memory that survives across sessions.
```

#### _build_skill_listing() 方法 - Section 3

```python
def _build_skill_listing(self) -> str:
    if not self.skills_dir.exists():
        return ""
    skills = []
    for skill_dir in sorted(self.skills_dir.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        text = skill_md.read_text()
        match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        if not match:
            continue
        meta = {}
        for line in match.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        name = meta.get("name", skill_dir.name)
        desc = meta.get("description", "")
        skills.append(f"- {name}: {desc}")
    if not skills:
        return ""
    return "# Available skills\n" + "\n".join(skills)
```

扫描 `skills/` 目录下所有包含 `SKILL.md` 文件的子目录，解析 frontmatter 提取技能名称和描述，生成技能列表。技能按目录名排序。

**输出示例**：
```markdown
# Available skills
- jsonl_handler: Best practices and code patterns for processing JSONL files in Python.
- pdf_handler: Comprehensive best practices and code patterns for reading, editing, and generating PDF files in Python.
```

#### _build_memory_section() 方法 - Section 4

```python
def _build_memory_section(self) -> str:
    if not self.memory_dir.exists():
        return ""
    memories = []
    for md_file in sorted(self.memory_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue
        text = md_file.read_text()
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if not match:
            continue
        header, body = match.group(1), match.group(2).strip()
        meta = {}
        for line in header.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        name = meta.get("name", md_file.stem)
        mem_type = meta.get("type", "project")
        desc = meta.get("description", "")
        memories.append(f"[{mem_type}] {name}: {desc}\n{body}")
    if not memories:
        return ""
    return "# Memories (persistent)\n\n" + "\n\n".join(memories)
```

扫描 `.memory/` 目录下所有 `.md` 文件（排除 `MEMORY.md` 索引），解析 frontmatter 提取记忆元数据，生成记忆内容部分。每条记忆包含类型、名称、描述和正文内容。

**输出示例**：
```markdown
# Memories (persistent)

[user] prefer_tabs: 用户偏好使用 tabs 而非 spaces
Use tabs for indentation in all Python files.

[project] payment_legacy: 支付模块必须保留旧接口
The legacy API must remain untouched for backward compatibility.
```

#### _build_claude_md() 方法 - Section 5

```python
def _build_claude_md(self) -> str:
    sources = []
    # User-global
    user_claude = Path.home() / ".claude" / "CLAUDE.md"
    if user_claude.exists():
        sources.append(("user global (~/.claude/CLAUDE.md)", user_claude.read_text()))
    # Project root
    project_claude = self.workdir / "CLAUDE.md"
    if project_claude.exists():
        sources.append(("project root (CLAUDE.md)", project_claude.read_text()))
    # Subdirectory
    cwd = Path.cwd()
    if cwd != self.workdir:
        subdir_claude = cwd / "CLAUDE.md"
        if subdir_claude.exists():
            sources.append((f"subdir ({cwd.name}/CLAUDE.md)", subdir_claude.read_text()))
    if not sources:
        return ""
    parts = ["# CLAUDE.md instructions"]
    for label, content in sources:
        parts.append(f"## From {label}")
        parts.append(content.strip())
    return "\n\n".join(parts)
```

按优先级加载 CLAUDE.md 文件：用户全局（`~/.claude/CLAUDE.md`）→ 项目根目录（`CLAUDE.md`）→ 当前子目录（`cwd/CLAUDE.md`）。当前版本中此方法已实现但未在 main_build() 中激活（代码被注释）。

#### _build_dynamic_context() 方法 - Section 6

```python
def _build_dynamic_context(self) -> str:
    lines = [
        f"Current date: {datetime.date.today().isoformat()}",
        f"Working directory: {self.workdir}",
        f"Model: {MODEL}",
    ]
    return "# Dynamic context\n" + "\n".join(lines)
```

生成动态上下文部分，包含当前日期、工作目录、模型名称。这部分内容在每次会话中可能变化，因此与静态部分通过 `DYNAMIC_BOUNDARY` 分隔。

**输出示例**：
```markdown
# Dynamic context
Current date: 2026-04-21
Working directory: <PROJECT_ROOT>
Model: Qwen3_5-397B-A17B
```

#### main_build() 方法 - 主 Agent 提示词构建

```python
def main_build(self) -> str:
    sections = []
    core = self._build_core()
    if core:
        sections.append(core)
    tools = self._build_tool_listing(self.tools)
    if tools:
        sections.append(tools)
    skills = self._build_skill_listing()
    if skills:
        sections.append(skills)
    memory = self._build_memory_section()
    if memory:
        sections.append(memory)
    # claude_md = self._build_claude_md()
    # if claude_md:
    #     sections.append(claude_md)
    sections.append(DYNAMIC_BOUNDARY)
    dynamic = self._build_dynamic_context()
    if dynamic:
        sections.append(dynamic)
    return "\n\n".join(sections)
```

按顺序组装 6 个部分：Core → Tools（使用 `self.tools` 即 PARENT_TOOLS）→ Skills → Memory →（CLAUDE.md 预留）→ DYNAMIC_BOUNDARY → Dynamic。每部分非空时才添加，各部分之间用双换行符连接。

**完整输出示例**：
```markdown
You are a coding agent operating in <PROJECT_ROOT>.
Use the provided tools to explore, read, write, and edit files.
Always verify before assuming. Prefer reading files over guessing.
The user controls permissions. Some tool calls may be denied.

# Available tools
- read_file(path, limit): Read file contents.
- task(prompt, description): Spawn a subagent with fresh context to finish.
- todo(items): Rewrite the current session plan for multi-step work.
- compact(focus): Summarize earlier conversation so work can continue in a smaller context.
- save_memory(name, description, type, content): Save a persistent memory that survives across sessions.

# Available skills
- jsonl_handler: Best practices and code patterns for processing JSONL files in Python.
- pdf_handler: Comprehensive best practices and code patterns for reading, editing, and generating PDF files in Python.

# Memories (persistent)

[user] prefer_tabs: 用户偏好使用 tabs 而非 spaces
Use tabs for indentation in all Python files.

=== DYNAMIC_BOUNDARY ===

# Dynamic context
Current date: 2026-04-21
Working directory: <PROJECT_ROOT>
Model: Qwen3_5-397B-A17B
```

#### sub_build() 方法 - 子 Agent 提示词构建

```python
def sub_build(self) -> str:
    sections = []
    core = self._build_core()
    if core:
        sections.append(core)
    tools = self._build_tool_listing(self.sub_tools)
    if tools:
        sections.append(tools)
    skills = self._build_skill_listing()
    if skills:
        sections.append(skills)
    memory = self._build_memory_section()
    if memory:
        sections.append(memory)
    sections.append(DYNAMIC_BOUNDARY)
    dynamic = self._build_dynamic_context()
    if dynamic:
        sections.append(dynamic)
    return "\n\n".join(sections)
```

与 main_build() 结构相同，区别在于工具列表使用 `self.sub_tools` 即 CHILD_TOOLS（不包含 task、todo、save_memory 等主 Agent 专用工具）。

**主/子 Agent 工具差异**：

| 工具 | Main Agent | Sub Agent |
|------|------------|-----------|
| read_file | ✓ | ✓ |
| bash | ✗ | ✓ |
| write_file | ✗ | ✓ |
| edit_file | ✗ | ✓ |
| load_skill | ✗ | ✓ |
| task | ✓ | ✗ |
| todo | ✓ | ✗ |
| compact | ✓ | ✓ |
| save_memory | ✓ | ✗ |

---

### 第 3 阶段：DYNAMIC_BOUNDARY 标记

#### 常量定义

```python
DYNAMIC_BOUNDARY = "=== DYNAMIC_BOUNDARY ==="
```

静态提示词与动态上下文的分隔标记。设计意图是在后续版本中缓存静态部分（Section 1-5），仅在动态内容变化时重新生成 Section 6，节省 token 消耗。当前版本中每次迭代仍重新构建完整提示词。

---

### 第 4 阶段：提示词构建器实例化

#### 全局实例创建

```python
prompt_builder = SystemPromptBuilder(workdir=WORKDIR, tools=PARENT_TOOLS, sub_tools=CHILD_TOOLS)
```

在模块级别创建 SystemPromptBuilder 单例，传入工作目录、主 Agent 工具列表、子 Agent 工具列表。该实例在后续代码中被多次调用。

---

### 第 5 阶段：run_subagent() 方法变更

#### 子 Agent 系统提示构建

**s09 方式**：
```python
sub_messages = [{"role": "system", "content": SUBAGENT_SYSTEM}, ...]
```

**s10 方式**：
```python
sub_messages = [{"role": "system", "content": prompt_builder.sub_build()}, ...]
```

子 Agent 的系统提示从硬编码的 SUBAGENT_SYSTEM 常量改为动态构建的提示词，包含工具列表、技能列表、记忆内容等完整上下文。

---

### 第 6 阶段：agent_loop() 方法变更

#### 主 Agent 系统提示构建

**s09 方式**：
```python
state.messages = [{"role": "system", "content": build_system_prompt(SYSTEM)},] + state.messages[1:]
```

**s10 方式**：
```python
state.messages = [{"role": "system", "content": prompt_builder.main_build()},] + state.messages[1:]
```

主 Agent 的系统提示从简单的字符串拼接改为使用 SystemPromptBuilder.main_build() 构建的完整结构化提示词。

---

### 第 7 阶段：PermissionManager 初始化变更

#### 交互式 Mode 选择

**s09 初始化**：
```python
def __init__(self, mode: str = "default", rules: list = None):
    import os
    if mode is None:
        mode = os.environ.get("PERMISSION_MODE", "auto")
    mode = mode.strip().lower() or "auto"
```

**s10 初始化**：
```python
def __init__(self, rules: list = None):
    print("Permission modes: default, plan, auto")
    mode = input("Mode (default): ").strip().lower() or "default"
```

s10 改为启动时交互式输入权限模式，不再从环境变量读取。这使每次会话可以明确选择权限模式，但降低了自动化程度。

---

### 第 8 阶段：保留功能（从 s09 继承）

以下功能在 s10 中完整保留，逻辑无变化：

| 组件 | 用途 | 状态 |
|------|------|------|
| MemoryManager | 持久化记忆管理（加载、保存、索引重建） | 完整保留 |
| DreamConsolidator | 后台记忆合并机制（待激活） | 完整保留 |
| HookManager | 外部钩子加载和执行 | 完整保留 |
| PermissionManager | 权限检查管线 | 逻辑保留（初始化方式变更） |
| BashSecurityValidator | Bash 命令安全验证 | 完整保留 |
| SkillRegistry | 技能文档加载和管理 | 完整保留 |
| TodoManager | 任务计划管理 | 完整保留 |
| micro_compact | 微型上下文压缩 | 完整保留 |
| compact_history | 全局上下文压缩 | 完整保留 |
| save_memory 工具 | 记忆保存接口 | 完整保留 |
| /memories 命令 | 查看记忆列表 | 完整保留 |
| /mode, /rules, /allow 命令 | 权限管理命令 | 完整保留 |

详细内容请参阅 v1_task_manager/chapter_9/s09_memory_system_文档.md。

---

## 目录结构依赖

| 目录/文件 | 用途 | 创建方式 |
|-----------|------|----------|
| `skills/` | 存储技能文档（SKILL.md） | 手动创建或通过工具创建 |
| `skills/*/SKILL.md` | 独立技能定义文件 | 手动创建或通过工具创建 |
| `.memory/` | 存储持久化记忆文件 | MemoryManager.save_memory() 自动创建 |
| `.memory/MEMORY.md` | 记忆索引文件（最多 200 行） | MemoryManager._rebuild_index() 自动重建 |
| `.memory/*.md` | 独立记忆文件 | MemoryManager.save_memory() 创建 |
| `.memory/.dream_lock` | DreamConsolidator 的 PID 锁文件 | DreamConsolidator._acquire_lock() 创建 |
| `.transcripts/` | 存储会话转录文件 | write_transcript() 自动创建 |
| `.task_outputs/tool-results/` | 存储大型工具输出 | persist_large_output() 自动创建 |
| `.claude/.claude_trusted` | 工作区信任标记 | 手动创建 |
| `.hooks.json` | 外部钩子配置文件 | 手动创建 |

### 技能文件格式（skills/*/SKILL.md）

```markdown
---
name: jsonl_handler
description: Best practices and code patterns for processing JSONL files in Python.
---
# JSONL Handler Skill

This skill provides guidelines for working with JSONL files...
```

| 字段 | 必填 | 说明 |
|------|------|------|
| name | 是 | 技能唯一标识符 |
| description | 是 | 一行摘要，出现在技能列表中 |
| 正文 | 否 | 技能详细内容 |

### 记忆文件格式（.memory/*.md）

参见 s09 文档，格式保持不变。

---

## 完整框架流程图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         会话启动                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  prompt_builder = SystemPromptBuilder(WORKDIR, PARENT_TOOLS, CHILD_TOOLS)│
│  memory_mgr.load_all()                                                  │
│  perms = PermissionManager() (交互式选择 mode)                           │
│  hooks = HookManager(perms)                                             │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  main_system = prompt_builder.main_build()                              │
│  - _build_core()                                                        │
│  - _build_tool_listing(PARENT_TOOLS)                                    │
│  - _build_skill_listing()                                               │
│  - _build_memory_section()                                              │
│  - _build_claude_md() (预留，当前未激活)                                 │
│  - DYNAMIC_BOUNDARY                                                     │
│  - _build_dynamic_context()                                             │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  用户输入 query                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  agent_loop(state, compact_state)                                       │
│  - state.messages[0] = {"role": "system", "content": main_system}       │
│  - micro_compact()                                                      │
│  - 检查 CONTEXT_LIMIT → compact_history()                               │
│  - run_one_turn() → LLM 调用                                            │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │  LLM 返回 tool_calls?       │
                    └──────────────┬──────────────┘
                          是       │       否
                                   │               │
                                   ▼               │
┌─────────────────────────────────────────────────────────────────────────┐
│  execute_tool_calls()                                                   │
│  - hooks.run_pre_tool_use() (Ring 0 + Ring 1)                           │
│  - 如 blocked → 返回错误消息                                            │
│  - 执行 TOOL_HANDLERS[f_name](**args)                                   │
│  - hooks.run_post_tool_use()                                            │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │  工具类型？                  │
                    └──────────────┬──────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
┌─────────────────┐    ┌─────────────────────┐    ┌─────────────────┐
│ task            │    │ 其他工具            │    │ compact         │
│ - 调用          │    │ - 正常执行          │    │ - 手动压缩      │
│   run_subagent()│    │ - 返回结果          │    │ - 设置标志      │
│ - 传递          │    │                     │    │                 │
│   sub_build()   │    │                     │    │                 │
└─────────────────┘    └─────────────────────┘    └─────────────────┘
          │                        │                        │
          └────────────────────────┴────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  返回 tool results → LLM 继续对话                                       │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  Subagent 执行流程 (run_subagent)                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  sub_messages = [                                                       │
│    {"role": "system", "content": prompt_builder.sub_build()},           │
│    {"role": "user", "content": prompt}                                  │
│  ]                                                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  子 Agent 循环 (最多 30 步)                                              │
│  - micro_compact()                                                      │
│  - 检查 CONTEXT_LIMIT → compact_history()                               │
│  - LLM 调用 (使用 CHILD_TOOLS)                                          │
│  - execute_tool_calls() (共享 TOOL_HANDLERS)                            │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  返回子 Agent 总结                                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 设计点总结

### 核心设计机制 1：模块化提示词构建

SystemPromptBuilder 将系统提示词拆分为 6 个独立部分，每部分有单一职责。这使提示词更易理解、测试和扩展。新增功能时只需添加对应的方法，无需修改现有代码。

### 核心设计机制 2：静态/动态分离

DYNAMIC_BOUNDARY 标记分隔静态提示词（Section 1-5）和动态上下文（Section 6）。设计意图是在后续版本中缓存静态部分，仅在动态内容变化时重新生成 Section 6，节省 token 消耗。当前版本中每次迭代仍重新构建完整提示词。

### 核心设计机制 3：主/子 Agent 差异化提示

main_build() 和 sub_build() 方法使用不同的工具列表（PARENT_TOOLS vs CHILD_TOOLS），使主 Agent 和子 Agent 获得差异化的能力描述。主 Agent 有 task、todo、save_memory 等管理工具，子 Agent 有 bash、write_file、edit_file 等执行工具。

### 核心设计机制 4：工具列表自动提取

_build_tool_listing() 方法从 OpenAI 格式的工具定义中自动提取工具名称、参数、描述，无需手动维护工具说明。工具定义变更时，提示词自动同步更新。

### 核心设计机制 5：技能和记忆动态加载

_build_skill_listing() 和 _build_memory_section() 方法在运行时扫描文件系统和记忆目录，动态加载技能和记忆内容。新增技能或记忆无需修改代码，下次会话自动生效。

### 核心设计机制 6：CLAUDE.md 链预留

_build_claude_md() 方法已实现但未激活，为后续版本预留接口。完整实现后将支持三层 CLAUDE.md 加载：用户全局 → 项目根目录 → 当前子目录。

---

## 整体设计思想总结

1. **模块化优于硬编码**：将系统提示词从硬编码字符串升级为模块化构建器，每个部分独立可维护，便于扩展和调试。

2. **静态/动态分离**：通过 DYNAMIC_BOUNDARY 标记分隔不变的核心指令和变化的动态上下文，为后续缓存优化预留接口。

3. **差异化能力描述**：主 Agent 和子 Agent 使用不同的工具列表构建提示词，使各自明确自己的能力边界，避免子 Agent 尝试调用不存在的 task 或 todo 工具。

4. **自动同步工具定义**：工具列表从 OpenAI 格式的工具定义自动提取，工具变更时无需手动更新提示词模板，减少维护成本。

5. **运行时动态加载**：技能和记忆在运行时动态加载，新增内容无需修改代码，下次会话自动生效，支持渐进式知识积累。

6. **渐进式功能扩展**：CLAUDE.md 链等功能已实现但未激活，采用预留接口的方式支持后续版本迭代，不破坏现有代码结构。

---

## 与 s09 的关系

### 保留内容（无变化）

s10 完整保留了 s09 的所有核心功能，以下组件逻辑完全相同：

- **MemoryManager 类**：加载、保存、索引重建逻辑不变
- **DreamConsolidator 类**：7 道门检查 + 4 阶段合并流程不变（待激活状态）
- **HookManager 类**：加载和执行钩子的逻辑不变
- **PermissionManager 类**：权限检查管线不变（初始化方式变更）
- **BashSecurityValidator**：危险命令验证不变
- **双层拦截管线**：Ring 0 + Ring 1 架构不变
- **命令行支持**：/mode, /rules, /allow, /memories 命令不变
- **上下文压缩**：micro_compact、compact_history 逻辑不变
- **技能注册**：SkillRegistry 加载逻辑不变
- **任务管理**：TodoManager 逻辑不变

详细内容请参阅 v1_task_manager/chapter_9/s09_memory_system_文档.md。

### 新增内容

| 组件 | 用途 |
|------|------|
| SystemPromptBuilder 类 | 结构化系统提示词构建器 |
| main_build() 方法 | 主 Agent 完整提示词构建 |
| sub_build() 方法 | 子 Agent 完整提示词构建 |
| DYNAMIC_BOUNDARY 常量 | 静态/动态提示词分隔标记 |
| _build_core() | Section 1: 核心指令 |
| _build_tool_listing() | Section 2: 工具列表 |
| _build_skill_listing() | Section 3: 技能元数据 |
| _build_memory_section() | Section 4: 记忆内容 |
| _build_claude_md() | Section 5: CLAUDE.md 链（预留） |
| _build_dynamic_context() | Section 6: 动态上下文 |

### 简化对比

| 特性 | s09 | s10 |
|------|-----|-----|
| 提示词构建方式 | 字符串拼接 | 模块化构建器 |
| 提示词结构 | 3 部分 | 6 层 |
| 静态/动态分隔 | 无 | DYNAMIC_BOUNDARY |
| 主/子 Agent 提示差异 | 独立常量 | 统一构建器 + 不同工具列表 |
| 工具列表维护 | 手动 | 自动提取 |
| 配置参数 | 基础值 | 全面提升 |
| 权限模式选择 | 环境变量 | 交互式输入 |

---

## 实践指南

### 运行方法

```bash
cd v1_task_manager/chapter_10
python s10_build_system.py
```

启动时：
1. 交互式选择权限模式（default/plan/auto）
2. 加载 `.memory/` 目录中的已有记忆
3. 加载 `skills/` 目录中的技能文档
4. 构建完整系统提示词

### 测试示例

#### 1. 查看生成的系统提示词

在代码中添加临时打印：

```python
if __name__ == "__main__":
    prompt_builder = SystemPromptBuilder(workdir=WORKDIR, tools=PARENT_TOOLS, sub_tools=CHILD_TOOLS)
    print("=" * 80)
    print("Main Agent System Prompt:")
    print("=" * 80)
    print(prompt_builder.main_build())
    print("=" * 80)
    print("Sub Agent System Prompt:")
    print("=" * 80)
    print(prompt_builder.sub_build())
    quit()
```

#### 2. 验证技能加载

创建测试技能：

```bash
mkdir -p skills/test_skill
cat > skills/test_skill/SKILL.md << 'EOF'
---
name: test_skill
description: A test skill for demonstration
---
This is a test skill body.
EOF
```

运行后系统提示词中将包含：
```markdown
# Available skills
- test_skill: A test skill for demonstration
```

#### 3. 验证记忆加载

```bash
python -c "
from pathlib import Path
from v1_task_manager.chapter_10.s10_build_system import memory_mgr

memory_mgr.memory_dir = Path('.memory')
memory_mgr.load_all()
print(memory_mgr.load_memory_prompt())
"
```

#### 4. 主/子 Agent 工具差异验证

```bash
python -c "
from v1_task_manager.chapter_10.s10_build_system import prompt_builder

print('Main Agent Tools:')
print(prompt_builder._build_tool_listing(prompt_builder.tools))
print()
print('Sub Agent Tools:')
print(prompt_builder._build_tool_listing(prompt_builder.sub_tools))
"
```

输出差异：
- Main Agent 包含：read_file, task, todo, compact, save_memory
- Sub Agent 包含：bash, read_file, write_file, edit_file, load_skill, compact

---

## 总结

### 核心设计思想

s10 通过引入 SystemPromptBuilder 类，将系统提示词从硬编码字符串升级为模块化、可扩展的构建器。核心设计原则是**单一职责**和**静态/动态分离**：每个部分独立可维护，静态内容可与动态内容分离以支持后续缓存优化。

### 核心机制

1. **6 层结构化 Pipeline**：Core → Tools → Skills → Memory → CLAUDE.md → Dynamic，每层有独立方法负责构建
2. **主/子 Agent 差异化**：main_build() 和 sub_build() 使用不同工具列表，实现能力边界隔离
3. **自动工具提取**：从 OpenAI 格式工具定义自动提取说明，减少手动维护
4. **动态内容加载**：技能和记忆在运行时扫描加载，支持渐进式知识积累
5. **DYNAMIC_BOUNDARY 标记**：分隔静态和动态部分，为缓存优化预留接口
6. **预留扩展接口**：CLAUDE.md 链等功能已实现但未激活，支持后续迭代

### 版本说明

- **文件路径**：v1_task_manager/chapter_10/s10_build_system.py
- **核心创新**：SystemPromptBuilder 类（6 层结构化提示词构建）
- **继承内容**：s09 的记忆系统、Hook 系统、权限系统完整保留
- **配置变更**：CONTEXT_LIMIT、PERSIST_THRESHOLD 等参数全面提升
- **初始化变更**：PermissionManager 改为交互式选择权限模式

---
*文档版本：v1.0*
*基于代码：v1_task_manager/chapter_10/s10_build_system.py*
