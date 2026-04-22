# s09: Memory System - Code Documentation

## Overview

s09 introduces a **persistent memory system** built on top of the s08 Hook system. The core improvement is extending from single-session context to cross-session knowledge persistence, enabling the Agent to remember user preferences, project conventions, and external resource locations.

### Core Improvements

1. **MemoryManager class** - Manages memory loading, storage, and index rebuilding
2. **DreamConsolidator class** - Background mechanism for automatic memory merging and cleanup (pending activation, not integrated into main flow)
3. **Four memory types** - user (user preferences), feedback (correction feedback), project (project conventions), reference (external resources)
4. **Memory injection system prompt** - build_system_prompt() injects memory content into every conversation
5. **save_memory tool** - Persistent storage interface callable by the Agent
6. **/memories command** - User command to view current memory list

### Design Philosophy

```
┌─────────────────────────────────────────────────────────────────┐
│                      New Session Start                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  MemoryManager.load_all()                                       │
│  - Scan .memory/*.md files                                       │
│  - Parse frontmatter (name, description, type, content)          │
│  - Build memory index {name -> {description, type, content}}     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  build_system_prompt(SYSTEM)                                    │
│  - Original SYSTEM prompt                                        │
│  - + load_memory_prompt() (memory content grouped by type)       │
│  - + MEMORY_GUIDANCE (guidance on when to save/not save)         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Agent Conversation Execution                │
│  - Agent can call save_memory tool to save new memories          │
│  - User can use /memories command to view memory list            │
└─────────────────────────────────────────────────────────────────┘
```

### Code File Paths

- **Source code**: v1_task_manager/chapter_9/s09_memory_system.py
- **Memory directory**: `.memory/` (hidden directory under workspace root)
- **Index file**: `.memory/MEMORY.md` (auto-generated)
- **Hook configuration**: `.hooks.json` (hook interception pipeline configuration file under workspace root)
- **Claude trust marker**: `.claude/.claude_trusted` (hidden directory under workspace root, used to identify trusted workspaces)

---

## Comparison with s08

### Change Overview

| Component | s08 | s09 |
|------|-----|-----|
| Persistent storage | None | MemoryManager + .memory directory |
| Memory types | None | user, feedback, project, reference |
| System prompt injection | None | build_system_prompt() |
| Memory save tool | None | save_memory |
| Memory view command | None | /memories |
| Auto-merge mechanism | None | DreamConsolidator (7 gates + 4 phases, pending activation) |
| Hook system | Full implementation | Fully retained (no changes) |
| Permission system | PermissionManager | Fully retained (no changes) |

### New Component Architecture

```
s09_memory_system.py
├── MEMORY_TYPES                   # ("user", "feedback", "project", "reference")
├── MEMORY_DIR                     # WORKDIR / ".memory"
├── MEMORY_INDEX                   # MEMORY_DIR / "MEMORY.md"
├── MemoryManager
│   ├── __init__()                 # Initialize memory_dir and memories dict
│   ├── load_all()                 # Load MEMORY.md index and all memory files
│   ├── load_memory_prompt()       # Build memory content for system prompt injection
│   ├── save_memory()              # Save memory to disk and update index
│   ├── _rebuild_index()           # Rebuild MEMORY.md index file
│   └── _parse_frontmatter()       # Parse Markdown frontmatter
├── DreamConsolidator
│   ├── should_consolidate()       # 7 gates check
│   ├── consolidate()              # 4-phase merge flow
│   ├── _acquire_lock()            # PID lock acquisition
│   └── _release_lock()            # PID lock release
├── build_system_prompt()          # Assemble system prompt with memories
├── MEMORY_GUIDANCE                # Guidance on when to save/not save memories
├── save_memory tool               # TOOL_HANDLERS integration
├── /memories command              # Handled in main loop
└── [s08 content fully retained]
    ├── HookManager
    ├── PermissionManager
    ├── BashSecurityValidator
    └── Command line (/mode, /rules, /allow)
```

---

## New Content Details (in code execution order)

### Phase 1: Memory Configuration and Type Definitions

#### MEMORY_TYPES Tuple

```python
MEMORY_TYPES = ("user", "feedback", "project", "reference")
```

Defines four memory types, each with different purposes:

| Type | Purpose | Example |
|------|------|------|
| user | User personal preferences | "Prefers tabs over spaces" |
| feedback | User corrections to Agent | "Do not use asyncio, project requires synchronous code" |
| project | Project-specific conventions (not easily derivable from code) | "Payment module must retain old interface for downstream compatibility" |
| reference | External resource locations | "Jira board URL: http://jira.example.com/projects/ABC" |

#### Path Configuration

```python
MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
MAX_INDEX_LINES = 200
```

Memories are stored in the `.memory` hidden directory under the working directory. `MEMORY.md` is a compact index file, limited to maximum 200 lines.

---

### Phase 2: MemoryManager Class

#### Initialization

```python
class MemoryManager:
    def __init__(self, memory_dir: Path = None):
        self.memory_dir = memory_dir or MEMORY_DIR
        self.memories = {}  # name -> {description, type, content}
```

Sets memory directory and memory dictionary on initialization. The memories dict key is memory name, value contains description, type, content, and file fields.

#### load_all() Method

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

Checks if memory directory exists, iterates through all `.md` files (excluding `MEMORY.md` index file itself), uses `_parse_frontmatter()` to parse each file's frontmatter, extracts name, description, type, content fields into memory dictionary. Files are loaded after `sorted()` to ensure deterministic order.

#### load_memory_prompt() Method

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

Returns empty string if no memories, groups by MEMORY_TYPES order (user → feedback → project → reference), generates Markdown-formatted headers and content for each group, returns concatenated complete string for system prompt injection.

#### save_memory() Method

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

Validates mem_type is legal, converts memory name to safe filename (keeping only letters, digits, underscores, hyphens), creates memory directory (if not exists), writes Markdown file with frontmatter, updates memory dictionary, rebuilds index file, returns status message.

#### _rebuild_index() Method

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

Generates index file header `# Memory Index`, iterates through all memories to generate lines in `- name: description [type]` format, truncates at 200 lines with a prompt, writes to `MEMORY.md` file.

#### _parse_frontmatter() Method

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

Uses regex to match `---` delimited frontmatter and body, parses `key: value` lines in frontmatter, returns dict containing all fields, content is the body part.

---

### Phase 3: DreamConsolidator Class

**Current status**: DreamConsolidator class is not yet integrated into the Agent main flow. The design goal of this class is to serve as an optional background mechanism to periodically automatically merge and clean up the memory library, but this feature is pending activation in the current version.

#### Configuration Parameters

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

- Cooldown time: At least 24 hours between two consolidations
- Scan throttle: At least 10 minutes between two scan attempts
- Minimum session count: At least 5 session data required before consolidation
- Lock expiration time: PID lock considered stale after 1 hour
- 4 merge phases: Orient → Gather → Consolidate → Prune

#### should_consolidate() Method - 7 Gates Check

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

Checks 7 conditions in order, returns `(True, "All 7 gates passed")` only if all pass. Returns `(False, failure reason)` immediately if any gate fails.

| Gate | Check item | Failure reason |
|----|--------|----------|
| Gate 1 | enabled flag | consolidation is disabled |
| Gate 2 | memory directory exists and has files | directory does not exist / no memory files found |
| Gate 3 | non-plan mode | plan mode does not allow consolidation |
| Gate 4 | 24-hour cooldown | cooldown active, Xs remaining |
| Gate 5 | 10-minute scan throttle | scan throttle active, Xs remaining |
| Gate 6 | at least 5 sessions | only X sessions, need 5 |
| Gate 7 | no active lock | lock held by another process |

#### consolidate() Method - 4-Phase Merge

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

Current version is a teaching implementation, only prints phase descriptions. Full implementation requires LLM involvement for merge logic.

| Phase | Name | Description |
|------|------|------|
| Phase 1 | Orient | Scan MEMORY.md index to understand structure and categories |
| Phase 2 | Gather | Read all individual memory files to get full content |
| Phase 3 | Consolidate | Merge related memories, remove stale entries |
| Phase 4 | Prune | Enforce 200-line limit on MEMORY.md index |

#### _acquire_lock() and _release_lock() Methods

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

Lock file format: `PID:timestamp` (e.g., `12345:1698765432.123`). Checks if lock is stale (over 1 hour), checks if owner process is alive (`os.kill(pid, 0)`), verifies PID matches when releasing lock.

---

### Phase 4: Memory Injection System Prompt

#### MEMORY_GUIDANCE Constant

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

Guides the Agent on when to save memories and when not to. Clearly distinguishes applicable scenarios for the four types.

#### build_system_prompt() Function

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

Original system prompt (SYSTEM constant), memory content (generated via `load_memory_prompt()`, if memories exist), memory save guidance (MEMORY_GUIDANCE) - three parts connected with double newlines. Rebuilds system prompt every time `agent_loop()` is called, ensuring newly saved memories are immediately visible in the next conversation round.

---

### Phase 5: save_memory Tool Integration

#### Tool Handler

```python
def run_save_memory(name: str, description: str, mem_type: str, content: str) -> str:
    return memory_mgr.save_memory(name, description, mem_type, content)
```

Simple wrapper, calls MemoryManager.save_memory() method.

#### TOOL_HANDLERS Registration

```python
TOOL_HANDLERS = {
    # ... other tools ...
    "save_memory":  lambda **kw: run_save_memory(kw["name"], kw["description"], kw["type"], kw["content"]),
}
```

Registers save_memory in the tool mapping dictionary, enabling the Agent to save memories via tool calls.

#### PARENT_TOOLS Definition

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

Defines JSON Schema for save_memory tool, containing 4 required parameters. save_memory is defined only in PARENT_TOOLS, not available to sub-Agents.

---

### Phase 6: /memories Command

#### Command Handling

```python
if query.strip() == "/memories":
    if memory_mgr.memories:
        for name, mem in memory_mgr.memories.items():
            print(f"  [{mem['type']}] {name}: {mem['description']}")
    else:
        print("  (no memories)")
    continue
```

When user inputs `/memories`, iterates through memory dictionary and prints type, name, and description of all memories.

**Output format**:
```
  [user] prefer_tabs: User prefers tabs over spaces
  [project] payment_legacy_api: Payment module must retain old interface
  [reference] jira_board: Jira board URL
```

---

### Phase 7: Main Program Initialization

#### Load Memories on Startup

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

Calls `memory_mgr.load_all()` on startup to load existing memories, prints count of loaded memories, system prompt is built using `build_system_prompt(SYSTEM)` (including memory content).

---

## Directory Structure Dependencies

| Directory/File | Purpose | Creation method |
|-----------|------|----------|
| `.memory/` | Store persistent memory files | Auto-created by MemoryManager.save_memory() |
| `.memory/MEMORY.md` | Memory index file (max 200 lines) | Auto-rebuilt by MemoryManager._rebuild_index() |
| `.memory/*.md` | Individual memory files | Created by MemoryManager.save_memory() |
| `.memory/.dream_lock` | PID lock file for DreamConsolidator | Created by DreamConsolidator._acquire_lock() |

### Individual Memory File Format

Each memory is stored as a separate Markdown file using frontmatter metadata:

```markdown
---
name: prefer_tabs
description: User prefers tabs over spaces
type: user
---
Use tabs for indentation in all Python files.
The user explicitly stated this preference in session #3.
```

| Field | Required | Description |
|------|------|------|
| name | Yes | Unique memory identifier (used for filename and reference) |
| description | Yes | One-line summary, appears in index |
| type | Yes | Memory type (user/feedback/project/reference) |
| Body | No | Detailed memory content (can be empty) |

### MEMORY.md Index Format

```markdown
# Memory Index

- prefer_tabs: User prefers tabs over spaces [user]
- payment_legacy_api: Payment module must retain old interface [project]
- jira_board: Jira board URL [reference]
```

Index file is auto-generated, format is `- name: description [type]`. Truncated at 200 lines.

---

## Complete Framework Flowchart

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Session Start                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  memory_mgr.load_all()                                                  │
│  - Scan .memory/*.md                                                    │
│  - Parse frontmatter → memories dict                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  User inputs query                                                      │
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
│ save_memory     │    │ Other tools         │    │ compact         │
│ - Write .md file│    │ - Normal execution  │    │ - Manual comp.  │
│ - Rebuild index │    │ - Return result     │    │ - Set flag      │
│ - Return success│    │                     │    │                 │
└─────────────────┘    └─────────────────────┘    └─────────────────┘
          │                        │                        │
          └────────────────────────┴────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Return tool results → LLM continues conversation                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Design Point Summary

### Core Design Mechanism 1: Explicit Persistence

The memory system adopts an explicit persistence strategy. Only cross-session, non-rederivable knowledge from current work is worth entering memory. MemoryManager class uniformly manages memory loading, saving, and index rebuilding.

### Core Design Mechanism 2: Four Memory Types

MEMORY_TYPES tuple defines four types: user (user preferences), feedback (correction feedback), project (project conventions), reference (external resources). Each type has different purposes, grouped by type in load_memory_prompt() for system prompt injection.

### Core Design Mechanism 3: Dynamic System Prompt Injection

build_system_prompt() function rebuilds system prompt on every agent_loop() call, injecting existing memory content. Ensures newly saved memories are immediately visible in the next conversation round, without requiring Agent to actively recall.

### Core Design Mechanism 4: DreamConsolidator Background Merge (Pending Activation)

DreamConsolidator is a designed background merge mechanism (currently not integrated into main flow), controls execution conditions through 7 gates check, merges, deduplicates, and prunes memories through 4-phase flow (Orient → Gather → Consolidate → Prune), preventing memory library bloat.

### Core Design Mechanism 5: save_memory Tool Interface

save_memory tool enables the Agent to programmatically save memories. Tool is defined only in PARENT_TOOLS, not available to sub-Agents, ensuring memory saving is controlled by the main Agent.

---

## Overall Design Philosophy Summary

1. **Cross-session context extension**: Extends Agent's context scope from single-session conversation history to cross-session knowledge persistence, enabling the Agent to remember user preferences and project conventions.

2. **Explicit storage strategy**: Only information that cannot be re-derived from code and is valid across sessions is stored in memory. File structure, function signatures, etc. that can be read from code are not stored.

3. **Type separation**: Four memory types clearly distinguish purposes, facilitating management and retrieval. user and feedback are typically private, project and reference can be team-shared.

4. **Auto-injection**: Memory content is automatically injected into system prompt, without requiring Agent to actively recall. Every conversation automatically includes existing memories, reducing Agent cognitive load.

5. **Optional merge mechanism**: DreamConsolidator is a designed background task (currently not activated), ensures merge executes at appropriate timing through 7 gates check, preventing memory library from becoming杂乱.

6. **Simple file format**: Each memory is one Markdown file using frontmatter metadata. Index file is compact and auto-rebuilt, facilitating manual reading and debugging.

---

## Relationship with s08

### Retained Content (No Changes)

s09 fully retains all functionality from s08, the following component logic is identical:

- **HookManager class**: Logic for loading and executing hooks unchanged
- **PermissionManager class**: Permission check pipeline unchanged
- **BashSecurityValidator**: Dangerous command validation unchanged
- **Dual-layer interception pipeline**: Ring 0 + Ring 1 architecture unchanged
- **Command line support**: /mode, /rules, /allow commands unchanged
- **.hooks.json configuration**: External hook configuration mechanism unchanged

See s08 documentation for details.

### New Content

| Component | Purpose |
|------|------|
| MemoryManager | Persistent memory management |
| DreamConsolidator | Background memory merge (pending activation) |
| save_memory tool | Memory save interface |
| build_system_prompt() | Memory injection into system prompt |
| /memories command | View memory list |
| MEMORY_TYPES | Four memory types definition |
| MEMORY_GUIDANCE | Memory save guidance |

### Simplified Comparison

| Feature | s08 | s09 |
|------|-----|-----|
| Context scope | Single-session | Cross-session (memory persistence) |
| Knowledge storage | Only conversation history | Conversation history + .memory directory |
| System prompt | Static | Dynamically injects memory content |
| User commands | /mode, /rules, /allow | + /memories |
| Agent tools | Basic toolset | + save_memory |

---

## Practice Guide

### Running Method

```bash
cd v1_task_manager/chapter_9
python s09_memory_system.py
```

Automatically loads existing memories from `.memory/` directory on startup. Creates empty memory system if no memory directory exists.

### Test Examples

#### 1. Save Memory

Agent calls save_memory tool:

```json
{
  "name": "save_memory",
  "arguments": {
    "name": "prefer_pytest",
    "description": "User prefers pytest over unittest",
    "type": "user",
    "content": "Always use pytest for testing. The user prefers pytest's fixture system and parametrize features over unittest."
  }
}
```

Return result:
```
Saved memory 'prefer_pytest' [user] to .memory/prefer_pytest.md
```

#### 2. View Memory List

User inputs command:

```
s01 >> /memories
  [user] prefer_tabs: User prefers tabs over spaces
  [feedback] no_async_code: Project requires synchronous code
  [project] payment_legacy_api: Payment module must retain old interface
  [reference] jira_board: Jira board URL
```

#### 3. Verify Memory File

```bash
cat .memory/prefer_pytest.md
```

Output:
```markdown
---
name: prefer_pytest
description: User prefers pytest over unittest
type: user
---
Always use pytest for testing. The user prefers pytest's fixture system and parametrize features over unittest.
```

#### 4. Verify Index File

```bash
cat .memory/MEMORY.md
```

Output:
```markdown
# Memory Index

- prefer_pytest: User prefers pytest over unittest [user]
- prefer_tabs: User prefers tabs over spaces [user]
```

---

## Summary

### Core Design Philosophy

s09 extends the Agent's context scope from single-session to cross-session by introducing the memory system. The core design principle is **explicit persistence**: only cross-session, non-rederivable knowledge from current work is worth entering memory.

### Core Mechanisms

1. **MemoryManager**: Explicitly manages memory lifecycle (loading, saving, index rebuilding)
2. **Four types**: user/feedback/project/reference clearly distinguish memory purposes
3. **System prompt injection**: Automatically includes existing memories in every conversation, without requiring Agent to actively recall
4. **DreamConsolidator**: Designed background merge mechanism (currently not activated), prevents memory library bloat
5. **save_memory tool**: Agent can programmatically save memories, supporting automated knowledge accumulation

### Version Information

- **File path**: v1_task_manager/chapter_9/s09_memory_system.py
- **Memory directory**: `.memory/` (under workspace root)
- **Index file**: `.memory/MEMORY.md` (auto-generated)
- **Inherited content**: s08's Hook system and permission system fully retained

---
*Document version: v1.0*
*Based on code: v1_task_manager/chapter_9/s09_memory_system.py*
