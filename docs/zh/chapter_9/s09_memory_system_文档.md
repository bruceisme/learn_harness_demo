# s09: Memory System (记忆系统) - 代码文档

## 概述

s09 在 s08 Hook 系统的基础上引入了**持久化记忆系统**。核心改进是从单会话上下文扩展到跨会话知识持久化，使 Agent 能够记住用户偏好、项目约定和外部资源位置。

### 核心改进

1. **MemoryManager 类** - 管理记忆的加载、存储和索引重建
2. **DreamConsolidator 类** - 自动合并和清理记忆的后台机制（待激活，未整合到主流程）
3. **四种记忆类型** - user（用户偏好）、feedback（纠正反馈）、project（项目约定）、reference（外部资源）
4. **记忆注入系统提示** - build_system_prompt() 将记忆内容注入每次对话
5. **save_memory 工具** - Agent 可调用的持久化存储接口
6. **/memories 命令** - 用户查看当前记忆列表

### 设计思想

```
┌─────────────────────────────────────────────────────────────────┐
│                      新会话启动                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  MemoryManager.load_all()                                       │
│  - 扫描 .memory/*.md 文件                                        │
│  - 解析 frontmatter (name, description, type, content)           │
│  - 构建内存索引 {name -> {description, type, content}}           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  build_system_prompt(SYSTEM)                                    │
│  - 原始 SYSTEM 提示                                               │
│  - + load_memory_prompt() (按类型分组的记忆内容)                  │
│  - + MEMORY_GUIDANCE (何时保存/不保存的指导)                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Agent 对话执行                               │
│  - Agent 可调用 save_memory 工具保存新记忆                         │
│  - 用户可使用 /memories 命令查看记忆列表                           │
└─────────────────────────────────────────────────────────────────┘
```

### 代码文件路径

- **源代码**：v1_task_manager/chapter_9/s09_memory_system.py
- **记忆目录**：`.memory/`（工作区根目录下的隐藏目录）
- **索引文件**：`.memory/MEMORY.md`（自动生成）
- **钩子配置**：`.hooks.json`（工作区根目录下的钩子拦截管线配置文件）
- **Claude 信任标记**：`.claude/.claude_trusted`（工作区根目录下的隐藏目录，用于标识受信任的工作区）

---

## 与 s08 的对比

### 变更总览

| 组件 | s08 | s09 |
|------|-----|-----|
| 持久化存储 | 无 | MemoryManager + .memory 目录 |
| 记忆类型 | 无 | user, feedback, project, reference |
| 系统提示注入 | 无 | build_system_prompt() |
| 记忆保存工具 | 无 | save_memory |
| 记忆查看命令 | 无 | /memories |
| 自动合并机制 | 无 | DreamConsolidator (7 道门 +4 阶段，待激活) |
| Hook 系统 | 完整实现 | 完整保留（无变化） |
| 权限系统 | PermissionManager | 完整保留（无变化） |

### 新增组件架构

```
s09_memory_system.py
├── MEMORY_TYPES                   # ("user", "feedback", "project", "reference")
├── MEMORY_DIR                     # WORKDIR / ".memory"
├── MEMORY_INDEX                   # MEMORY_DIR / "MEMORY.md"
├── MemoryManager
│   ├── __init__()                 # 初始化 memory_dir 和 memories 字典
│   ├── load_all()                 # 加载 MEMORY.md 索引和所有记忆文件
│   ├── load_memory_prompt()       # 构建注入系统提示的记忆内容
│   ├── save_memory()              # 保存记忆到磁盘并更新索引
│   ├── _rebuild_index()           # 重建 MEMORY.md 索引文件
│   └── _parse_frontmatter()       # 解析 Markdown frontmatter
├── DreamConsolidator
│   ├── should_consolidate()       # 7 道门检查
│   ├── consolidate()              # 4 阶段合并流程
│   ├── _acquire_lock()            # PID 锁获取
│   └── _release_lock()            # PID 锁释放
├── build_system_prompt()          # 组装含记忆的系统提示
├── MEMORY_GUIDANCE                # 何时保存/不保存记忆的指导
├── save_memory 工具               # TOOL_HANDLERS 集成
├── /memories 命令                 # 主循环中处理
└── [s08 内容完整保留]
    ├── HookManager
    ├── PermissionManager
    ├── BashSecurityValidator
    └── 命令行 (/mode, /rules, /allow)
```

---

## 新增内容详解（按代码执行顺序）

### 第 1 阶段：记忆配置与类型定义

#### MEMORY_TYPES 元组

```python
MEMORY_TYPES = ("user", "feedback", "project", "reference")
```

定义四种记忆类型，每种类型有不同用途：

| 类型 | 用途 | 示例 |
|------|------|------|
| user | 用户个人偏好 | "偏好使用 tabs 而非 spaces" |
| feedback | 用户对 Agent 的纠正 | "不要使用 asyncio，项目要求同步代码" |
| project | 项目特定约定（不易从代码推导） | "支付模块必须保留旧接口以兼容下游系统" |
| reference | 外部资源位置 | "Jira 看板地址：http://jira.example.com/projects/ABC" |

#### 路径配置

```python
MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
MAX_INDEX_LINES = 200
```

记忆存储在工作目录下的 `.memory` 隐藏目录中。`MEMORY.md` 是紧凑的索引文件，限制最多 200 行。

---

### 第 2 阶段：MemoryManager 类

#### 初始化

```python
class MemoryManager:
    def __init__(self, memory_dir: Path = None):
        self.memory_dir = memory_dir or MEMORY_DIR
        self.memories = {}  # name -> {description, type, content}
```

初始化时设置记忆目录和内存字典。memories 字典的 key 是记忆名称，value 包含 description、type、content 和 file 字段。

#### load_all() 方法

```python
def load_all(self):
    """Load MEMORY.md index and all individual memory files."""
    self.memories = {}
    if not self.memory_dir.exists():
        return
    for md_file in sorted(self.memory_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue
        parsed = self._parse_frontmatter(md_file.read_text())
        if parsed:
            name = parsed.get("name", md_file.stem)
            self.memories[name] = {
                "description": parsed.get("description", ""),
                "type": parsed.get("type", "project"),
                "content": parsed.get("content", ""),
                "file": md_file.name,
            }
    count = len(self.memories)
    if count > 0:
        print(f"[Memory loaded: {count} memories from {self.memory_dir}]")
```

检查记忆目录是否存在，遍历所有 `.md` 文件（排除 `MEMORY.md` 索引文件本身），使用 `_parse_frontmatter()` 解析每个文件的 frontmatter，提取 name、description、type、content 字段存入内存字典。文件按 `sorted()` 排序后加载，确保确定性顺序。

#### load_memory_prompt() 方法

```python
def load_memory_prompt(self) -> str:
    """Build a memory section for injection into the system prompt."""
    if not self.memories:
        return ""
    sections = []
    sections.append("# Memories (persistent across sessions)")
    sections.append("")
    for mem_type in MEMORY_TYPES:
        typed = {k: v for k, v in self.memories.items() if v["type"] == mem_type}
        if not typed:
            continue
        sections.append(f"## [{mem_type}]")
        for name, mem in typed.items():
            sections.append(f"### {name}: {mem['description']}")
            if mem["content"].strip():
                sections.append(mem["content"].strip())
            sections.append("")
    return "\n".join(sections)
```

如无记忆则返回空字符串，按 MEMORY_TYPES 顺序分组（user → feedback → project → reference），每组生成 Markdown 格式的标题和内容，返回拼接后的完整字符串用于注入系统提示。

#### save_memory() 方法

```python
def save_memory(self, name: str, description: str, mem_type: str, content: str) -> str:
    if mem_type not in MEMORY_TYPES:
        return f"Error: type must be one of {MEMORY_TYPES}"
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower())
    if not safe_name:
        return "Error: invalid memory name"
    self.memory_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = (
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"type: {mem_type}\n"
        f"---\n"
        f"{content}\n"
    )
    file_name = f"{safe_name}.md"
    file_path = self.memory_dir / file_name
    file_path.write_text(frontmatter)
    self.memories[name] = {
        "description": description,
        "type": mem_type,
        "content": content,
        "file": file_name,
    }
    self._rebuild_index()
    return f"Saved memory '{name}' [{mem_type}] to {file_path.relative_to(WORKDIR)}"
```

验证 mem_type 是否合法，将记忆名称转换为安全文件名（只保留字母数字下划线连字符），创建记忆目录（如不存在），写入带 frontmatter 的 Markdown 文件，更新内存字典，重建索引文件，返回状态消息。

#### _rebuild_index() 方法

```python
def _rebuild_index(self):
    """Rebuild MEMORY.md from current in-memory state, capped at 200 lines."""
    lines = ["# Memory Index", ""]
    for name, mem in self.memories.items():
        lines.append(f"- {name}: {mem['description']} [{mem['type']}]")
        if len(lines) >= MAX_INDEX_LINES:
            lines.append(f"... (truncated at {MAX_INDEX_LINES} lines)")
            break
    self.memory_dir.mkdir(parents=True, exist_ok=True)
    MEMORY_INDEX.write_text("\n".join(lines) + "\n")
```

生成索引文件头部 `# Memory Index`，遍历所有记忆生成 `- name: description [type]` 格式的行，达到 200 行限制时截断并添加提示，写入 `MEMORY.md` 文件。

#### _parse_frontmatter() 方法

```python
def _parse_frontmatter(self, text: str) -> dict | None:
    """Parse --- delimited frontmatter + body content."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        return None
    header, body = match.group(1), match.group(2)
    result = {"content": body.strip()}
    for line in header.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result
```

使用正则匹配 `---` 分隔的 frontmatter 和正文，解析 frontmatter 中的 `key: value` 行，返回包含所有字段的字典，content 为正文部分。

---

### 第 3 阶段：DreamConsolidator 类

**当前状态**：DreamConsolidator 类尚未整合到 Agent 主流程中。该类的设计目标是作为可选的后台机制，定期自动合并和清理记忆库，但当前版本中此功能处于待激活状态。

#### 配置参数

```python
class DreamConsolidator:
    COOLDOWN_SECONDS = 86400       # 24 hours between consolidations
    SCAN_THROTTLE_SECONDS = 600    # 10 minutes between scan attempts
    MIN_SESSION_COUNT = 5          # need enough data to consolidate
    LOCK_STALE_SECONDS = 3600      # PID lock considered stale after 1 hour
    PHASES = [
        "Orient: scan MEMORY.md index for structure and categories",
        "Gather: read individual memory files for full content",
        "Consolidate: merge related memories, remove stale entries",
        "Prune: enforce 200-line limit on MEMORY.md index",
    ]
```

- 冷却时间：两次合并之间至少间隔 24 小时
- 扫描节流：两次扫描尝试之间至少间隔 10 分钟
- 最小会话数：至少需要 5 次会话数据才进行合并
- 锁过期时间：PID 锁超过 1 小时视为过期
- 4 个合并阶段：Orient → Gather → Consolidate → Prune

#### should_consolidate() 方法 - 7 道门检查

```python
def should_consolidate(self) -> tuple[bool, str]:
    import time
    now = time.time()
    if not self.enabled:
        return False, "Gate 1: consolidation is disabled"
    if not self.memory_dir.exists():
        return False, "Gate 2: memory directory does not exist"
    memory_files = list(self.memory_dir.glob("*.md"))
    memory_files = [f for f in memory_files if f.name != "MEMORY.md"]
    if not memory_files:
        return False, "Gate 2: no memory files found"
    if self.mode == "plan":
        return False, "Gate 3: plan mode does not allow consolidation"
    time_since_last = now - self.last_consolidation_time
    if time_since_last < self.COOLDOWN_SECONDS:
        remaining = int(self.COOLDOWN_SECONDS - time_since_last)
        return False, f"Gate 4: cooldown active, {remaining}s remaining"
    time_since_scan = now - self.last_scan_time
    if time_since_scan < self.SCAN_THROTTLE_SECONDS:
        remaining = int(self.SCAN_THROTTLE_SECONDS - time_since_scan)
        return False, f"Gate 5: scan throttle active, {remaining}s remaining"
    if self.session_count < self.MIN_SESSION_COUNT:
        return False, f"Gate 6: only {self.session_count} sessions, need {self.MIN_SESSION_COUNT}"
    if not self._acquire_lock():
        return False, "Gate 7: lock held by another process"
    return True, "All 7 gates passed"
```

按顺序检查 7 个条件，全部通过才返回 `(True, "All 7 gates passed")`。任意一门失败立即返回 `(False, 失败原因)`。

| 门 | 检查项 | 失败原因 |
|----|--------|----------|
| Gate 1 | enabled 标志 | consolidation is disabled |
| Gate 2 | 记忆目录存在且有文件 | directory does not exist / no memory files found |
| Gate 3 | 非 plan 模式 | plan mode does not allow consolidation |
| Gate 4 | 24 小时冷却时间 | cooldown active, Xs remaining |
| Gate 5 | 10 分钟扫描节流 | scan throttle active, Xs remaining |
| Gate 6 | 至少 5 次会话 | only X sessions, need 5 |
| Gate 7 | 无活跃锁 | lock held by another process |

#### consolidate() 方法 - 4 阶段合并

```python
def consolidate(self) -> list[str]:
    import time
    can_run, reason = self.should_consolidate()
    if not can_run:
        print(f"[Dream] Cannot consolidate: {reason}")
        return []
    print("[Dream] Starting consolidation...")
    self.last_scan_time = time.time()
    completed_phases = []
    for i, phase in enumerate(self.PHASES, 1):
        print(f"[Dream] Phase {i}/4: {phase}")
        completed_phases.append(phase)
    self.last_consolidation_time = time.time()
    self._release_lock()
    print(f"[Dream] Consolidation complete: {len(completed_phases)} phases executed")
    return completed_phases
```

当前版本为教学实现，仅打印阶段描述。完整实现需要 LLM 参与合并逻辑。

| 阶段 | 名称 | 描述 |
|------|------|------|
| Phase 1 | Orient | 扫描 MEMORY.md 索引了解结构和分类 |
| Phase 2 | Gather | 读取所有独立记忆文件获取完整内容 |
| Phase 3 | Consolidate | 合并相关记忆，移除过时条目 |
| Phase 4 | Prune | 强制执行 MEMORY.md 的 200 行限制 |

#### _acquire_lock() 和 _release_lock() 方法

```python
def _acquire_lock(self) -> bool:
    import time
    if self.lock_file.exists():
        try:
            lock_data = self.lock_file.read_text().strip()
            pid_str, timestamp_str = lock_data.split(":", 1)
            pid = int(pid_str)
            lock_time = float(timestamp_str)
            if (time.time() - lock_time) > self.LOCK_STALE_SECONDS:
                print(f"[Dream] Removing stale lock from PID {pid}")
                self.lock_file.unlink()
            else:
                try:
                    os.kill(pid, 0)
                    return False  # process alive, lock is valid
                except OSError:
                    print(f"[Dream] Removing lock from dead PID {pid}")
                    self.lock_file.unlink()
        except (ValueError, OSError):
            self.lock_file.unlink(missing_ok=True)
    try:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file.write_text(f"{os.getpid()}:{time.time()}")
        return True
    except OSError:
        return False

def _release_lock(self):
    try:
        if self.lock_file.exists():
            lock_data = self.lock_file.read_text().strip()
            pid_str = lock_data.split(":")[0]
            if int(pid_str) == os.getpid():
                self.lock_file.unlink()
    except (ValueError, OSError):
        pass
```

锁文件格式：`PID:timestamp`（如 `12345:1698765432.123`）。检查锁是否过期（超过 1 小时），检查拥有进程是否存活（`os.kill(pid, 0)`），释放锁时验证 PID 匹配。

---

### 第 4 阶段：记忆注入系统提示

#### MEMORY_GUIDANCE 常量

```python
MEMORY_GUIDANCE = """
When to save memories:
- User states a preference ("I like tabs", "always use pytest") -> type: user
- User corrects you ("don't do X", "that was wrong because...") -> type: feedback
- You learn a project fact that is not easy to infer from current code alone
  (for example: a rule exists because of compliance, or a legacy module must
  stay untouched for business reasons) -> type: project
- You learn where an external resource lives (ticket board, dashboard, docs URL)
  -> type: reference
When NOT to save:
- Anything easily derivable from code (function signatures, file structure, directory layout)
- Temporary task state (current branch, open PR numbers, current TODOs)
- Secrets or credentials (API keys, passwords)
"""
```

指导 Agent 何时应该保存记忆、何时不应该保存。明确区分四种类型的适用场景。

#### build_system_prompt() 函数

```python
def build_system_prompt(sys_p) -> str:
    """Assemble system prompt with memory content included."""
    parts = [sys_p]
    memory_section = memory_mgr.load_memory_prompt()
    if memory_section:
        parts.append(memory_section)
    parts.append(MEMORY_GUIDANCE)
    return "\n\n".join(parts)
```

原始系统提示（SYSTEM 常量）、记忆内容（通过 `load_memory_prompt()` 生成，如有记忆）、记忆保存指导（MEMORY_GUIDANCE）三部分用双换行符连接。每次 `agent_loop()` 调用时重建系统提示，确保新保存的记忆在下一轮对话中立即可见。

---

### 第 5 阶段：save_memory 工具集成

#### 工具处理器

```python
def run_save_memory(name: str, description: str, mem_type: str, content: str) -> str:
    return memory_mgr.save_memory(name, description, mem_type, content)
```

简单包装器，调用 MemoryManager.save_memory() 方法。

#### TOOL_HANDLERS 注册

```python
TOOL_HANDLERS = {
    # ... 其他工具 ...
    "save_memory":  lambda **kw: run_save_memory(kw["name"], kw["description"], kw["type"], kw["content"]),
}
```

在工具映射字典中注册 save_memory，使 Agent 可通过工具调用保存记忆。

#### PARENT_TOOLS 定义

```python
{"type": "function","function": {"name": "save_memory",
        "description": "Save a persistent memory that survives across sessions.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string", 
                    "description": "Short identifier (e.g. prefer_tabs, db_schema)"
                },
                "description": {
                    "type": "string", 
                    "description": "One-line summary of what this memory captures"
                },
                "type": {
                    "type": "string", 
                    "enum": ["user", "feedback", "project", "reference"],
                    "description": "user=preferences, feedback=corrections, project=non-obvious project conventions or decision reasons, reference=external resource pointers"
                },
                "content": {
                    "type": "string", 
                    "description": "Full memory content (multi-line OK)"
                }
            },
            "required": ["name", "description", "type", "content"]
        }
    }
}
```

定义 save_memory 工具的 JSON Schema，包含 4 个必填参数。save_memory 仅在 PARENT_TOOLS 中定义，子 Agent 不可用。

---

### 第 6 阶段：/memories 命令

#### 命令处理

```python
if query.strip() == "/memories":
    if memory_mgr.memories:
        for name, mem in memory_mgr.memories.items():
            print(f"  [{mem['type']}] {name}: {mem['description']}")
    else:
        print("  (no memories)")
    continue
```

用户输入 `/memories` 时，遍历内存字典打印所有记忆的类型、名称和描述。

**输出格式**：
```
  [user] prefer_tabs: 用户偏好使用 tabs 而非 spaces
  [project] payment_legacy_api: 支付模块必须保留旧接口
  [reference] jira_board: Jira 看板地址
```

---

### 第 7 阶段：主程序初始化

#### 启动时加载记忆

```python
if __name__ == "__main__":
    compact_state = CompactState()
    memory_mgr.load_all()
    mem_count = len(memory_mgr.memories)
    if mem_count:
        print(f"[{mem_count} memories loaded into context]")
    else:
        print("[No existing memories. The agent can create them with save_memory.]")
    
    start_result = hooks._run_external_hooks("SessionStart", {"trigger": True})
    for msg in start_result.get("messages", []):
        print(f"\033[35m👋 [SessionStart Hook]: {msg}\033[0m")
    
    history = [{"role": "system", "content": build_system_prompt(SYSTEM)},]
```

启动时调用 `memory_mgr.load_all()` 加载已有记忆，打印加载的记忆数量，系统提示使用 `build_system_prompt(SYSTEM)` 构建（包含记忆内容）。

---

## 目录结构依赖

| 目录/文件 | 用途 | 创建方式 |
|-----------|------|----------|
| `.memory/` | 存储持久化记忆文件 | MemoryManager.save_memory() 自动创建 |
| `.memory/MEMORY.md` | 记忆索引文件（最多 200 行） | MemoryManager._rebuild_index() 自动重建 |
| `.memory/*.md` | 独立记忆文件 | MemoryManager.save_memory() 创建 |
| `.memory/.dream_lock` | DreamConsolidator 的 PID 锁文件 | DreamConsolidator._acquire_lock() 创建 |

### 独立记忆文件格式

每个记忆存储为单独的 Markdown 文件，使用 frontmatter 元数据：

```markdown
---
name: prefer_tabs
description: 用户偏好使用 tabs 而非 spaces
type: user
---
Use tabs for indentation in all Python files.
The user explicitly stated this preference in session #3.
```

| 字段 | 必填 | 说明 |
|------|------|------|
| name | 是 | 记忆唯一标识符（用于文件名和引用） |
| description | 是 | 一行摘要，出现在索引中 |
| type | 是 | 记忆类型（user/feedback/project/reference） |
| 正文 | 否 | 记忆详细内容（可为空） |

### MEMORY.md 索引格式

```markdown
# Memory Index

- prefer_tabs: 用户偏好使用 tabs 而非 spaces [user]
- payment_legacy_api: 支付模块必须保留旧接口 [project]
- jira_board: Jira 看板地址 [reference]
```

索引文件自动生成，格式为 `- name: description [type]`。达到 200 行时截断。

---

## 完整框架流程图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         会话启动                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  memory_mgr.load_all()                                                  │
│  - 扫描 .memory/*.md                                                    │
│  - 解析 frontmatter → memories 字典                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  用户输入 query                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  build_system_prompt(SYSTEM)                                            │
│  - SYSTEM + load_memory_prompt() + MEMORY_GUIDANCE                      │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  agent_loop()                                                           │
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
│ save_memory     │    │ 其他工具            │    │ compact         │
│ - 写入.md 文件   │    │ - 正常执行          │    │ - 手动压缩      │
│ - 重建索引      │    │ - 返回结果          │    │ - 设置标志      │
│ - 返回成功消息  │    │                     │    │                 │
└─────────────────┘    └─────────────────────┘    └─────────────────┘
          │                        │                        │
          └────────────────────────┴────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  返回 tool results → LLM 继续对话                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 设计点总结

### 核心设计机制 1：显式持久化

记忆系统采用显式持久化策略。只有跨会话、无法从当前工作重新推导的知识才值得进入 memory。通过 MemoryManager 类统一管理记忆的加载、保存和索引重建。

### 核心设计机制 2：四种记忆类型

MEMORY_TYPES 元组定义四种类型：user（用户偏好）、feedback（纠正反馈）、project（项目约定）、reference（外部资源）。每种类型有不同用途，在 load_memory_prompt() 中按类型分组注入系统提示。

### 核心设计机制 3：系统提示动态注入

build_system_prompt() 函数在每次 agent_loop() 调用时重建系统提示，将已有记忆内容注入。确保新保存的记忆在下一轮对话中立即可见，无需 Agent 主动回忆。

### 核心设计机制 4：DreamConsolidator 后台合并（待激活）

DreamConsolidator 是设计中的后台合并机制（当前未整合到主流程），通过 7 道门检查控制执行条件，通过 4 阶段流程（Orient → Gather → Consolidate → Prune）合并、去重和修剪记忆，防止记忆库膨胀。

### 核心设计机制 5：save_memory 工具接口

save_memory 工具使 Agent 可 programmatically 保存记忆。工具仅在 PARENT_TOOLS 中定义，子 Agent 不可用，确保记忆保存由主 Agent 控制。

---

## 整体设计思想总结

1. **跨会话上下文扩展**：从单会话对话历史扩展到跨会话知识持久化，使 Agent 能够记住用户偏好和项目约定。

2. **显式存储策略**：只有无法从代码重新推导、跨会话有效的信息才存入 memory。文件结构、函数签名等可从代码读取的信息不存储。

3. **类型分离**：四种记忆类型明确区分用途，便于管理和检索。user 和 feedback 通常私有，project 和 reference 可团队共享。

4. **自动注入**：记忆内容自动注入系统提示，无需 Agent 主动回忆。每次对话自动包含已有记忆，降低 Agent 认知负担。

5. **可选合并机制**：DreamConsolidator 是设计中的后台任务（当前未激活），通过 7 道门检查确保合并在合适时机执行，防止记忆库杂乱。

6. **简单文件格式**：每条记忆一个 Markdown 文件，使用 frontmatter 元数据。索引文件紧凑且自动重建，便于人工阅读和调试。

---

## 与 s08 的关系

### 保留内容（无变化）

s09 完整保留了 s08 的所有功能，以下组件逻辑完全相同：

- **HookManager 类**：加载和执行钩子的逻辑不变
- **PermissionManager 类**：权限检查管线不变
- **BashSecurityValidator**：危险命令验证不变
- **双层拦截管线**：Ring 0 + Ring 1 架构不变
- **命令行支持**：/mode, /rules, /allow 命令不变
- **.hooks.json 配置**：外部钩子配置机制不变

详细内容请参阅 s08 文档。

### 新增内容

| 组件 | 用途 |
|------|------|
| MemoryManager | 持久化记忆管理 |
| DreamConsolidator | 后台记忆合并（待激活） |
| save_memory 工具 | 记忆保存接口 |
| build_system_prompt() | 记忆注入系统提示 |
| /memories 命令 | 查看记忆列表 |
| MEMORY_TYPES | 四种记忆类型定义 |
| MEMORY_GUIDANCE | 记忆保存指导 |

### 简化对比

| 特性 | s08 | s09 |
|------|-----|-----|
| 上下文范围 | 单会话 | 跨会话（记忆持久化） |
| 知识存储 | 仅对话历史 | 对话历史 + .memory 目录 |
| 系统提示 | 静态 | 动态注入记忆内容 |
| 用户命令 | /mode, /rules, /allow | + /memories |
| Agent 工具 | 基础工具集 | + save_memory |

---

## 实践指南

### 运行方法

```bash
cd v1_task_manager/chapter_9
python s09_memory_system.py
```

启动时自动加载 `.memory/` 目录中的已有记忆。如无记忆目录则创建空记忆系统。

### 测试示例

#### 1. 保存记忆

Agent 调用 save_memory 工具：

```json
{
  "name": "save_memory",
  "arguments": {
    "name": "prefer_pytest",
    "description": "用户偏好使用 pytest 而非 unittest",
    "type": "user",
    "content": "Always use pytest for testing. The user prefers pytest's fixture system and parametrize features over unittest."
  }
}
```

返回结果：
```
Saved memory 'prefer_pytest' [user] to .memory/prefer_pytest.md
```

#### 2. 查看记忆列表

用户输入命令：

```
s01 >> /memories
  [user] prefer_tabs: 用户偏好使用 tabs 而非 spaces
  [feedback] no_async_code: 项目要求使用同步代码
  [project] payment_legacy_api: 支付模块必须保留旧接口
  [reference] jira_board: Jira 看板地址
```

#### 3. 验证记忆文件

```bash
cat .memory/prefer_pytest.md
```

输出：
```markdown
---
name: prefer_pytest
description: 用户偏好使用 pytest 而非 unittest
type: user
---
Always use pytest for testing. The user prefers pytest's fixture system and parametrize features over unittest.
```

#### 4. 验证索引文件

```bash
cat .memory/MEMORY.md
```

输出：
```markdown
# Memory Index

- prefer_pytest: 用户偏好使用 pytest 而非 unittest [user]
- prefer_tabs: 用户偏好使用 tabs 而非 spaces [user]
```

---

## 总结

### 核心设计思想

s09 通过引入记忆系统，将 Agent 的上下文范围从单会话扩展到跨会话。核心设计原则是**显式持久化**：只有跨会话、无法从当前工作重新推导的知识才值得进入 memory。

### 核心机制

1. **MemoryManager**：显式管理记忆生命周期（加载、保存、索引重建）
2. **四种类型**：user/feedback/project/reference 明确区分记忆用途
3. **系统提示注入**：每次对话自动包含已有记忆，无需 Agent 主动回忆
4. **DreamConsolidator**：设计中的后台合并机制（当前未激活），防止记忆库膨胀
5. **save_memory 工具**：Agent 可编程保存记忆，支持自动化知识积累

### 版本说明

- **文件路径**：v1_task_manager/chapter_9/s09_memory_system.py
- **记忆目录**：`.memory/`（工作区根目录下）
- **索引文件**：`.memory/MEMORY.md`（自动生成）
- **继承内容**：s08 的 Hook 系统、权限系统完整保留

---
*文档版本：v1.0*
*基于代码：v1_task_manager/chapter_9/s09_memory_system.py*
