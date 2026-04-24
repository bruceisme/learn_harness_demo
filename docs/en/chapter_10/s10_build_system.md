# s10: System Prompt Rebuild

## Overview

s10 builds upon the s09 memory system with a **structured system prompt reconstruction**. The core improvement is upgrading from hard-coded system prompt strings to a modular, extensible prompt builder, making each component of the system prompt independently maintainable.

### Core Improvements

1. **SystemPromptBuilder Class** - Core change, implements a 6-layer structured prompt construction pipeline
2. **main_build() / sub_build() Methods** - Build differentiated system prompts for Main Agent and Sub Agent respectively
3. **DYNAMIC_BOUNDARY Marker** - Separates static prompts from dynamic context, reserving interface for subsequent cache optimization
4. **Comprehensive Configuration Parameters** - Adapted for more complex long-context scenarios
5. **s09 Functionality Fully Preserved** - Core components like MemoryManager, HookManager, PermissionManager remain unchanged

### Design Philosophy

```
┌─────────────────────────────────────────────────────────────────┐
│                    s10 System Prompt Architecture               │
├─────────────────────────────────────────────────────────────────┤
│  Section 1: Core instructions                                   │
│  Section 2: Tool listing                                        │
│  Section 3: Skill metadata                                      │
│  Section 4: Memory section                                      │
│  Section 5: CLAUDE.md chain [Reserved]                          │
│  === DYNAMIC_BOUNDARY ===                                       │
│  Section 6: Dynamic context                                     │
└─────────────────────────────────────────────────────────────────┘
```

### Code File Paths

- **Source Code**: v1_task_manager/chapter_10/s10_build_system.py
- **Reference Documentation**: v1_task_manager/chapter_09/s09_memory_system_文档.md
- **Memory Directory**: `.memory/` (hidden directory under workspace root)
- **Skills Directory**: `skills/` (under workspace root)
- **Hook Configuration**: `.hooks.json` (hook interception pipeline configuration file under workspace root)
- **Claude Trust Marker**: `.claude/.claude_trusted` (hidden directory under workspace root, used to identify trusted workspaces)

---

## Comparison with s09

### Change Overview

| Component | s09 | s10 |
|------|-----|-----|
| System Prompt Construction | `build_system_prompt()` function string concatenation | `SystemPromptBuilder` class modular construction |
| Prompt Structure | 3 parts: SYSTEM + Memory + Guidance | 6 layers: Core → Tools → Skills → Memory → CLAUDE.md → Dynamic |
| Main Agent Prompt | `build_system_prompt(SYSTEM)` | `prompt_builder.main_build()` |
| Sub Agent Prompt | `SUBAGENT_SYSTEM` constant | `prompt_builder.sub_build()` |
| Static/Dynamic Separation | None | `DYNAMIC_BOUNDARY` marker |
| CONTEXT_LIMIT | 80000 | 100000 |
| PERSIST_THRESHOLD | 40000 | 60000 |
| PREVIEW_CHARS | 10000 | 20000 |
| PLAN_REMINDER_INTERVAL | 3 | 5 |
| KEEP_RECENT_TOOL_RESULTS | 3 | 5 |
| PermissionManager Initialization | Get mode from environment variable or parameter | Interactive mode input |
| MemoryManager | Full implementation | Fully preserved (no changes) |
| DreamConsolidator | Pending activation | Fully preserved (no changes) |
| HookManager | Full implementation | Fully preserved (no changes) |
| PermissionManager | Full implementation | Fully preserved (initialization method changed) |
| BashSecurityValidator | Full implementation | Fully preserved (no changes) |

### SystemPromptBuilder Class Architecture

```
SystemPromptBuilder
├── __init__(workdir, tools, sub_tools)
│   └── Initialize working directory, main/sub Agent tool lists, skills directory, memory directory
├── _build_core()
│   └── Section 1: Core instructions (Agent identity, basic behavior guidelines)
├── _build_tool_listing(obj_tools)
│   └── Section 2: Tool listing (extracted from OpenAI format tool definitions)
├── _build_skill_listing()
│   └── Section 3: Skill metadata (scans SKILL.md under skills/ directory)
├── _build_memory_section()
│   └── Section 4: Memory content (scans memory files under .memory/ directory)
├── _build_claude_md()
│   └── Section 5: CLAUDE.md chain (reserved, not activated in current version)
├── _build_dynamic_context()
│   └── Section 6: Dynamic context (date, working directory, model information)
├── main_build()
│   └── Assemble complete Main Agent system prompt (uses PARENT_TOOLS)
└── sub_build()
    └── Assemble complete Sub Agent system prompt (uses CHILD_TOOLS)
```

---

## s10 New Content Details (in code execution order)

### Phase 1: Configuration Parameter Changes

#### Context Management Parameters

```python
CONTEXT_LIMIT = 100000              # s09: 80000
PERSIST_THRESHOLD = 60000           # s09: 40000
PREVIEW_CHARS = 20000               # s09: 10000
PLAN_REMINDER_INTERVAL = 5          # s09: 3
KEEP_RECENT_TOOL_RESULTS = 5        # s09: 3
```

Parameter adjustments adapt to more complex long-context scenarios, increasing tool result retention count and plan reminder interval.

| Parameter | s09 Value | s10 Value | Purpose |
|------|--------|--------|------|
| CONTEXT_LIMIT | 80000 | 100000 | Context size threshold triggering automatic compression |
| PERSIST_THRESHOLD | 40000 | 60000 | Threshold for persisting tool output to files |
| PREVIEW_CHARS | 10000 | 20000 | Preview character count retained during persistence |
| PLAN_REMINDER_INTERVAL | 3 | 5 | Number of consecutive rounds without plan update before triggering reminder |
| KEEP_RECENT_TOOL_RESULTS | 3 | 5 | Number of recent tool results retained during micro-compression |

---

### Phase 2: SystemPromptBuilder Class

#### Initialization

```python
class SystemPromptBuilder:
    def __init__(self, workdir: Path = None, tools: list = None, sub_tools: list = None):
        self.workdir = workdir or WORKDIR
        self.tools = tools or []
        self.sub_tools = sub_tools or []
        self.skills_dir = self.workdir / "skills"
        self.memory_dir = self.workdir / ".memory"
```

Initialization sets working directory, Main Agent tool list, Sub Agent tool list, skills directory path, and memory directory path. The `tools` parameter receives PARENT_TOOLS, and `sub_tools` parameter receives CHILD_TOOLS.

#### _build_core() Method - Section 1

```python
def _build_core(self) -> str:
    return (
        f"You are a coding agent operating in {self.workdir}.\n"
        "Use the provided tools to explore, read, write, and edit files.\n"
        "Always verify before assuming. Prefer reading files over guessing.\n"
        "The user controls permissions. Some tool calls may be denied.\n"
    )
```

Generates the core instructions section, containing Agent identity declaration, basic behavior guidelines, and permission instructions. Returns a fixed-format string.

#### _build_tool_listing() Method - Section 2

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

Iterates through the tool list, extracts tool name, description, and parameter list from OpenAI format tool definitions, generating Markdown-formatted tool documentation. Parameters are extracted from `parameters.properties` keys.

**Output Example**:
```markdown
# Available tools
- read_file(path, limit): Read file contents.
- task(prompt, description): Spawn a subagent with fresh context to finish.
- todo(items): Rewrite the current session plan for multi-step work.
- compact(focus): Summarize earlier conversation so work can continue in a smaller context.
- save_memory(name, description, type, content): Save a persistent memory that survives across sessions.
```

#### _build_skill_listing() Method - Section 3

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

Scans all subdirectories under `skills/` containing `SKILL.md` files, parses frontmatter to extract skill name and description, generating a skill list. Skills are sorted by directory name.

**Output Example**:
```markdown
# Available skills
- jsonl_handler: Best practices and code patterns for processing JSONL files in Python.
- pdf_handler: Comprehensive best practices and code patterns for reading, editing, and generating PDF files in Python.
```

#### _build_memory_section() Method - Section 4

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

Scans all `.md` files under `.memory/` directory (excluding `MEMORY.md` index), parses frontmatter to extract memory metadata, generating the memory content section. Each memory includes type, name, description, and body content.

**Output Example**:
```markdown
# Memories (persistent)

[user] prefer_tabs: User prefers tabs over spaces
Use tabs for indentation in all Python files.

[project] payment_legacy: Payment module must retain legacy interface
The legacy API must remain untouched for backward compatibility.
```

#### _build_claude_md() Method - Section 5

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

Loads CLAUDE.md files by priority: user global (`~/.claude/CLAUDE.md`) → project root (`CLAUDE.md`) → current subdirectory (`cwd/CLAUDE.md`). In the current version, this method is implemented but not activated in main_build() (code is commented out).

#### _build_dynamic_context() Method - Section 6

```python
def _build_dynamic_context(self) -> str:
    lines = [
        f"Current date: {datetime.date.today().isoformat()}",
        f"Working directory: {self.workdir}",
        f"Model: {MODEL}",
    ]
    return "# Dynamic context\n" + "\n".join(lines)
```

Generates the dynamic context section, containing current date, working directory, and model name. This content may vary in each session, so it is separated from the static part via `DYNAMIC_BOUNDARY`.

**Output Example**:
```markdown
# Dynamic context
Current date: 2026-04-21
Working directory: <PROJECT_ROOT>
Model: Qwen3_5-397B-A17B
```

#### main_build() Method - Main Agent Prompt Construction

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

Assembles 6 sections in order: Core → Tools (uses `self.tools` i.e., PARENT_TOOLS) → Skills → Memory → (CLAUDE.md reserved) → DYNAMIC_BOUNDARY → Dynamic. Each section is added only if non-empty, with sections connected by double newlines.

**Complete Output Example**:
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

[user] prefer_tabs: User prefers tabs over spaces
Use tabs for indentation in all Python files.

=== DYNAMIC_BOUNDARY ===

# Dynamic context
Current date: 2026-04-21
Working directory: <PROJECT_ROOT>
Model: Qwen3_5-397B-A17B
```

#### sub_build() Method - Sub Agent Prompt Construction

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

Same structure as main_build(), the difference is the tool list uses `self.sub_tools` i.e., CHILD_TOOLS (does not include task, todo, save_memory and other Main Agent-exclusive tools).

**Main/Sub Agent Tool Differences**:

| Tool | Main Agent | Sub Agent |
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

### Phase 3: DYNAMIC_BOUNDARY Marker

#### Constant Definition

```python
DYNAMIC_BOUNDARY = "=== DYNAMIC_BOUNDARY ==="
```

Separator marker between static prompts and dynamic context. The design intent is to cache the static part (Section 1-5) in subsequent versions, regenerating Section 6 only when dynamic content changes, saving token consumption. In the current version, the complete prompt is still rebuilt in each iteration.

---

### Phase 4: Prompt Builder Instantiation

#### Global Instance Creation

```python
prompt_builder = SystemPromptBuilder(workdir=WORKDIR, tools=PARENT_TOOLS, sub_tools=CHILD_TOOLS)
```

Creates a SystemPromptBuilder singleton at module level, passing in working directory, Main Agent tool list, and Sub Agent tool list. This instance is called multiple times in subsequent code.

---

### Phase 5: run_subagent() Method Changes

#### Sub Agent System Prompt Construction

**s09 Approach**:
```python
sub_messages = [{"role": "system", "content": SUBAGENT_SYSTEM}, ...]
```

**s10 Approach**:
```python
sub_messages = [{"role": "system", "content": prompt_builder.sub_build()}, ...]
```

Sub Agent's system prompt changes from hard-coded SUBAGENT_SYSTEM constant to dynamically constructed prompt containing complete context like tool list, skill list, memory content, etc.

---

### Phase 6: agent_loop() Method Changes

#### Main Agent System Prompt Construction

**s09 Approach**:
```python
state.messages = [{"role": "system", "content": build_system_prompt(SYSTEM)},] + state.messages[1:]
```

**s10 Approach**:
```python
state.messages = [{"role": "system", "content": prompt_builder.main_build()},] + state.messages[1:]
```

Main Agent's system prompt changes from simple string concatenation to complete structured prompt built using SystemPromptBuilder.main_build().

---

### Phase 7: PermissionManager Initialization Changes

#### Interactive Mode Selection

**s09 Initialization**:
```python
def __init__(self, mode: str = "default", rules: list = None):
    import os
    if mode is None:
        mode = os.environ.get("PERMISSION_MODE", "auto")
    mode = mode.strip().lower() or "auto"
```

**s10 Initialization**:
```python
def __init__(self, rules: list = None):
    print("Permission modes: default, plan, auto")
    mode = input("Mode (default): ").strip().lower() or "default"
```

s10 changes to interactive permission mode input at startup, no longer reading from environment variables. This allows explicit permission mode selection for each session but reduces automation level.

---

### Phase 8: Preserved Functionality (Inherited from s09)

The following functionality is fully preserved in s10 with no logic changes:

| Component | Purpose | Status |
|------|------|------|
| MemoryManager | Persistent memory management (loading, saving, index rebuilding) | Fully preserved |
| DreamConsolidator | Background memory consolidation mechanism (pending activation) | Fully preserved |
| HookManager | External hook loading and execution | Fully preserved |
| PermissionManager | Permission check pipeline | Logic preserved (initialization method changed) |
| BashSecurityValidator | Bash command security validation | Fully preserved |
| SkillRegistry | Skill document loading and management | Fully preserved |
| TodoManager | Task plan management | Fully preserved |
| micro_compact | Micro context compression | Fully preserved |
| compact_history | Global context compression | Fully preserved |
| save_memory Tool | Memory save interface | Fully preserved |
| /memories Command | View memory list | Fully preserved |
| /mode, /rules, /allow Commands | Permission management commands | Fully preserved |

For detailed content, please refer to v1_task_manager/chapter_09/s09_memory_system_文档.md.

---

## Directory Structure Dependencies

| Directory/File | Purpose | Creation Method |
|-----------|------|----------|
| `skills/` | Store skill documents (SKILL.md) | Manually created or via tools |
| `skills/*/SKILL.md` | Independent skill definition files | Manually created or via tools |
| `.memory/` | Store persistent memory files | Automatically created by MemoryManager.save_memory() |
| `.memory/MEMORY.md` | Memory index file (max 200 lines) | Automatically rebuilt by MemoryManager._rebuild_index() |
| `.memory/*.md` | Independent memory files | Created by MemoryManager.save_memory() |
| `.memory/.dream_lock` | PID lock file for DreamConsolidator | Created by DreamConsolidator._acquire_lock() |
| `.transcripts/` | Store session transcript files | Automatically created by write_transcript() |
| `.task_outputs/tool-results/` | Store large tool outputs | Automatically created by persist_large_output() |
| `.claude/.claude_trusted` | Workspace trust marker | Manually created |
| `.hooks.json` | External hook configuration file | Manually created |

### Skill File Format (skills/*/SKILL.md)

```markdown
---
name: jsonl_handler
description: Best practices and code patterns for processing JSONL files in Python.
---
# JSONL Handler Skill

This skill provides guidelines for working with JSONL files...
```

| Field | Required | Description |
|------|------|------|
| name | Yes | Skill unique identifier |
| description | Yes | One-line summary, appears in skill list |
| Body | No | Detailed skill content |

### Memory File Format (.memory/*.md)

See s09 documentation, format remains unchanged.

---

## Complete Framework Flowchart

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Session Startup                                 │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  prompt_builder = SystemPromptBuilder(WORKDIR, PARENT_TOOLS, CHILD_TOOLS)│
│  memory_mgr.load_all()                                                  │
│  perms = PermissionManager() (interactive mode selection)                │
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
│  - _build_claude_md() (reserved, not activated currently)               │
│  - DYNAMIC_BOUNDARY                                                     │
│  - _build_dynamic_context()                                             │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  User inputs query                                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  agent_loop(state, compact_state)                                       │
│  - state.messages[0] = {"role": "system", "content": main_system}       │
│  - micro_compact()                                                      │
│  - Check CONTEXT_LIMIT → compact_history()                              │
│  - run_one_turn() → LLM call                                            │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │  LLM returns tool_calls?    │
                    └──────────────┬──────────────┘
                          Yes      │       No
                                   │               │
                                   ▼               │
┌─────────────────────────────────────────────────────────────────────────┐
│  execute_tool_calls()                                                   │
│  - hooks.run_pre_tool_use() (Ring 0 + Ring 1)                           │
│  - If blocked → return error message                                    │
│  - Execute TOOL_HANDLERS[f_name](**args)                                │
│  - hooks.run_post_tool_use()                                            │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │  Tool type?                 │
                    └──────────────┬──────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
┌─────────────────┐    ┌─────────────────────┐    ┌─────────────────┐
│ task            │    │ Other tools         │    │ compact         │
│ - Call          │    │ - Normal execution  │    │ - Manual comp.  │
│   run_subagent()│    │ - Return result     │    │ - Set flag      │
│ - Pass          │    │                     │    │                 │
│   sub_build()   │    │                     │    │                 │
└─────────────────┘    └─────────────────────┘    └─────────────────┘
          │                        │                        │
          └────────────────────────┴────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Return tool results → LLM continues conversation                       │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  Subagent Execution Flow (run_subagent)                                 │
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
│  Sub Agent Loop (max 30 steps)                                          │
│  - micro_compact()                                                      │
│  - Check CONTEXT_LIMIT → compact_history()                              │
│  - LLM call (using CHILD_TOOLS)                                         │
│  - execute_tool_calls() (shared TOOL_HANDLERS)                          │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Return Sub Agent summary                                               │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Design Points Summary

### Core Design Mechanism 1: Modular Prompt Construction

SystemPromptBuilder splits system prompts into 6 independent parts, each with a single responsibility. This makes prompts easier to understand, test, and extend. When adding new features, only the corresponding method needs to be added without modifying existing code.

### Core Design Mechanism 2: Static/Dynamic Separation

DYNAMIC_BOUNDARY marker separates static prompts (Section 1-5) from dynamic context (Section 6). The design intent is to cache the static part in subsequent versions, regenerating Section 6 only when dynamic content changes, saving token consumption. In the current version, the complete prompt is still rebuilt in each iteration.

### Core Design Mechanism 3: Main/Sub Agent Differentiated Prompts

main_build() and sub_build() methods use different tool lists (PARENT_TOOLS vs CHILD_TOOLS), enabling Main Agent and Sub Agent to receive differentiated capability descriptions. Main Agent has management tools like task, todo, save_memory, while Sub Agent has execution tools like bash, write_file, edit_file.

### Core Design Mechanism 4: Automatic Tool List Extraction

_build_tool_listing() method automatically extracts tool name, parameters, and description from OpenAI format tool definitions, eliminating the need for manual tool documentation maintenance. When tool definitions change, prompts automatically sync updates.

### Core Design Mechanism 5: Dynamic Skill and Memory Loading

_build_skill_listing() and _build_memory_section() methods scan the filesystem and memory directory at runtime, dynamically loading skill and memory content. Adding new skills or memories requires no code changes, taking effect automatically in the next session.

### Core Design Mechanism 6: CLAUDE.md Chain Reservation

_build_claude_md() method is implemented but not activated, reserving an interface for subsequent versions. When fully implemented, it will support three-layer CLAUDE.md loading: user global → project root → current subdirectory.

---

## Overall Design Philosophy Summary

1. **Modularity Over Hard-coding**: Upgrades system prompts from hard-coded strings to modular builders, with each part independently maintainable, facilitating extension and debugging.

2. **Static/Dynamic Separation**: Uses DYNAMIC_BOUNDARY marker to separate invariant core instructions from changing dynamic context, reserving interface for subsequent cache optimization.

3. **Differentiated Capability Description**: Main Agent and Sub Agent use different tool lists to build prompts, enabling each to clearly understand their capability boundaries, preventing Sub Agent from attempting to call non-existent task or todo tools.

4. **Automatic Tool Definition Synchronization**: Tool lists are automatically extracted from OpenAI format tool definitions, eliminating manual prompt template updates when tools change, reducing maintenance costs.

5. **Runtime Dynamic Loading**: Skills and memories are dynamically loaded at runtime, new content requires no code changes, taking effect automatically in the next session, supporting progressive knowledge accumulation.

6. **Progressive Feature Extension**: Features like CLAUDE.md chain are implemented but not activated, using reserved interfaces to support subsequent version iterations without breaking existing code structure.

---

## Relationship with s09

### Preserved Content (No Changes)

s10 fully preserves all core functionality from s09, the following components have identical logic:

- **MemoryManager Class**: Loading, saving, index rebuilding logic unchanged
- **DreamConsolidator Class**: 7-door check + 4-stage consolidation flow unchanged (pending activation)
- **HookManager Class**: Hook loading and execution logic unchanged
- **PermissionManager Class**: Permission check pipeline unchanged (initialization method changed)
- **BashSecurityValidator**: Dangerous command validation unchanged
- **Dual-layer Interception Pipeline**: Ring 0 + Ring 1 architecture unchanged
- **Command-line Support**: /mode, /rules, /allow, /memories commands unchanged
- **Context Compression**: micro_compact, compact_history logic unchanged
- **Skill Registration**: SkillRegistry loading logic unchanged
- **Task Management**: TodoManager logic unchanged

For detailed content, please refer to v1_task_manager/chapter_09/s09_memory_system_文档.md.

### New Content

| Component | Purpose |
|------|------|
| SystemPromptBuilder Class | Structured system prompt builder |
| main_build() Method | Main Agent complete prompt construction |
| sub_build() Method | Sub Agent complete prompt construction |
| DYNAMIC_BOUNDARY Constant | Static/dynamic prompt separator marker |
| _build_core() | Section 1: Core instructions |
| _build_tool_listing() | Section 2: Tool listing |
| _build_skill_listing() | Section 3: Skill metadata |
| _build_memory_section() | Section 4: Memory content |
| _build_claude_md() | Section 5: CLAUDE.md chain (reserved) |
| _build_dynamic_context() | Section 6: Dynamic context |

### Simplified Comparison

| Feature | s09 | s10 |
|------|-----|-----|
| Prompt Construction Method | String concatenation | Modular builder |
| Prompt Structure | 3 parts | 6 layers |
| Static/Dynamic Separation | None | DYNAMIC_BOUNDARY |
| Main/Sub Agent Prompt Difference | Independent constants | Unified builder + different tool lists |
| Tool List Maintenance | Manual | Automatic extraction |
| Configuration Parameters | Basic values | Comprehensively upgraded |
| Permission Mode Selection | Environment variable | Interactive input |

---

## Practical Guide

### Running Method

```bash
cd v1_task_manager/chapter_10
python s10_build_system.py
```

At startup:
1. Interactively select permission mode (default/plan/auto)
2. Load existing memories from `.memory/` directory
3. Load skill documents from `skills/` directory
4. Build complete system prompt

### Test Examples

#### 1. View Generated System Prompt

Add temporary print in code:

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

#### 2. Verify Skill Loading

Create test skill:

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

After running, system prompt will contain:
```markdown
# Available skills
- test_skill: A test skill for demonstration
```

#### 3. Verify Memory Loading

```bash
python -c "
from pathlib import Path
from v1_task_manager.chapter_10.s10_build_system import memory_mgr

memory_mgr.memory_dir = Path('.memory')
memory_mgr.load_all()
print(memory_mgr.load_memory_prompt())
"
```

#### 4. Main/Sub Agent Tool Difference Verification

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

Output differences:
- Main Agent includes: read_file, task, todo, compact, save_memory
- Sub Agent includes: bash, read_file, write_file, edit_file, load_skill, compact

---

## Summary

### Core Design Philosophy

s10 introduces the SystemPromptBuilder class, upgrading system prompts from hard-coded strings to a modular, extensible builder. The core design principles are **single responsibility** and **static/dynamic separation**: each part is independently maintainable, and static content can be separated from dynamic content to support subsequent cache optimization.

### Core Mechanisms

1. **6-Layer Structured Pipeline**: Core → Tools → Skills → Memory → CLAUDE.md → Dynamic, each layer has an independent method responsible for construction
2. **Main/Sub Agent Differentiation**: main_build() and sub_build() use different tool lists, achieving capability boundary isolation
3. **Automatic Tool Extraction**: Automatically extracts descriptions from OpenAI format tool definitions, reducing manual maintenance
4. **Dynamic Content Loading**: Skills and memories are scanned and loaded at runtime, supporting progressive knowledge accumulation
5. **DYNAMIC_BOUNDARY Marker**: Separates static and dynamic parts, reserving interface for cache optimization
6. **Reserved Extension Interfaces**: Features like CLAUDE.md chain are implemented but not activated, supporting subsequent iterations

### Version Information

- **File Path**: v1_task_manager/chapter_10/s10_build_system.py
- **Core Change**: SystemPromptBuilder class (6-layer structured prompt construction)
- **Inherited Content**: s09's memory system, Hook system, permission system fully preserved
- **Configuration Changes**: CONTEXT_LIMIT, PERSIST_THRESHOLD and other parameters comprehensively upgraded
- **Initialization Change**: PermissionManager changed to interactive permission mode selection

---
*Document Version: v1.0*
*Based on Code: v1_task_manager/chapter_10/s10_build_system.py*
