# s12: Task System (Persistent Task System)

## Overview

s12 builds upon s11's error recovery mechanism with a **task management system upgrade**. The core change is replacing the in-memory Todo system with a file-based persistent Task system, supporting cross-session task tracking, task dependency management, and Main/Subagent responsibility separation.

### Core Improvements

1. **TaskManager class** - Core change, implements persistent task CRUD (stored in `.tasks/` directory)
2. **Task data structure upgrade** - Upgraded from PlanItem to TaskRecord (id, subject, description, status, blockedBy, blocks, owner, etc.)
3. **Main/Subagent responsibility separation** - Main Planner Agent handles planning and delegation, Executing Subagent handles execution
4. **Toolset refactoring** - Removed todo tool, added task_create, task_update, task_list, task_get
5. **s11 functionality fully preserved** - Three-layer error recovery, SystemPromptBuilder, MemoryManager, and other core components unchanged

### Code File Paths

- **Source code**: v1_task_manager/chapter_12/s12_task_system.py
- **Reference documentation**: v1_task_manager/chapter_11/s11_Resume_system_文档.md
- **Reference code**: v1_task_manager/chapter_11/s11_Resume_system.py
- **Task directory**: `.tasks/` (hidden directory under workspace root)
- **Memory directory**: `.memory/` (hidden directory under workspace root)
- **Skills directory**: `skills/` (under workspace root)
- **Hook configuration**: `.hooks.json` (hook interception pipeline configuration file under workspace root)
- **Claude trust marker**: `.claude/.claude_trusted` (hidden directory under workspace root, used to identify trusted workspaces)

---

## s12 New Content Details (in code execution order)

### TaskManager Class (Persistent Task CRUD)

```python
class TaskManager:
    """Persistent TaskRecord store.
    Think "work graph on disk", not "currently running worker".
    """
    def __init__(self, tasks_dir: Path):
        self.dir = tasks_dir
        self.dir.mkdir(exist_ok=True)
        self._next_id = self._max_id() + 1
        self.rounds_since_update = 0
```

**Core Methods**:

| Method | Function | Return Value |
|--------|----------|--------------|
| `get_items()` | Get all tasks (list) | list[dict] |
| `_max_id()` | Get maximum task ID | int |
| `_load(task_id)` | Load single task | dict |
| `_save(task)` | Save task to file | None |
| `create(subject, description)` | Create new task | JSON string |
| `get(task_id)` | Get task details | JSON string |
| `update(task_id, ...)` | Update task status/dependencies | JSON string |
| `list_all()` | List all tasks (formatted) | Formatted string |
| `_clear_dependency(completed_id)` | Clear dependencies for completed task | None |

**Storage Structure**:
- Directory: `.tasks/`
- File naming: `task_<id>.json`
- File format: JSON (with indentation, Chinese characters visible)

---

### Task Data Structure

**s11 PlanItem**:
```python
@dataclass
class PlanItem: 
    id: str                     # Task id marker
    content: str                # What to do in this step
    status: str = "pending"     # pending | in_progress | completed
    active_form: str = ""       # In-progress description
```

**s12 TaskRecord**:
```python
task = {
    "id": int,                  # Task ID (auto-incrementing integer)
    "subject": str,             # Task subject (short title)
    "description": str,         # Task detailed description
    "status": str,              # pending | in_progress | completed | deleted
    "blockedBy": list[int],     # List of task IDs blocking current task
    "blocks": list[int],        # List of task IDs blocked by current task
    "owner": str,               # Task owner
    "claim_role": str,          # Claim role (optional)
    "worktree": str,            # Worktree state (optional)
    "worktree_state": str,      # Worktree state value (optional)
    "last_worktree": str,       # Previous worktree (optional)
    "closeout": dict            # Closeout information (optional)
}
```

**Status Enum**:
| Status | Marker | Meaning |
|--------|--------|---------|
| pending | `[ ]` | Waiting for execution |
| in_progress | `[>]` | In progress |
| completed | `[x]` | Completed |
| deleted | `[-]` | Deleted |

**Task Dependencies**:
- `blockedBy`: Which tasks block the current task (predecessor tasks)
- `blocks`: Which tasks are blocked by the current task (successor tasks)
- Bidirectional association: Setting `blocks` automatically updates corresponding task's `blockedBy`
- Auto cleanup: When task completes, remove from all tasks' `blockedBy`

---

### Main/Subagent Responsibility Separation

**Main Planner Agent Core Instructions** (`_build_core()`):
```
You are the Main Planner Agent operating in {workdir}.
Your primary role is to orchestrate complex tasks, delegate execution, and verify results. 
You do NOT write code or execute shell commands directly.

1. TASK PLANNING: Break down user requests using the task management tools. 
   Keep exactly ONE task 'in_progress' at a time.
2. DELEGATION: You must use the `task` tool to spawn a subagent to perform 
   the actual coding, file editing, or shell commands.
3. STRICT VERIFICATION: Never blindly trust a subagent's claim of success. 
   Use `read_file` to verify their work. If flawed, explain the issue and 
   spawn a new subagent to fix it.
4. FRESH STARTS: When the user issues a completely new request, gracefully 
   update old pending/in_progress tasks to 'deleted' or 'completed' before 
   creating a new plan.
5. CONTEXT: Use `compact` if your conversation history grows too long.
6. PERMISSIONS: The user controls execution. Respect denied tool calls and 
   adapt your plan.
```

**Executing Subagent Core Instructions** (`_build_sub_core()`):
```
You are an Executing Subagent operating in {workdir}.
Your role is to strictly complete the specific task delegated to you by the Main Agent.

1. EXECUTION: Use your available tools (`bash`, `read_file`, `write_file`, 
   `edit_file`) to actively solve the task step-by-step.
2. NO GUESSING: Always verify file paths and read existing code before 
   attempting to modify files.
3. KNOWLEDGE: Use `load_skill` if you need specialized instructions or 
   framework conventions before you act.
4. CONTEXT: Use `compact` if your local sub-conversation gets too long.
5. HANDOVER REPORT: When finishing a task, you MUST provide a detailed final 
   summary including: (1) Files created/modified, (2) Key logic implemented, 
   and (3) Output of any verification commands you ran.
6. PERMISSIONS: The user controls execution. If a tool call is denied, think 
   of an alternative approach.
```

**Responsibility Comparison**:
| Responsibility | Main Planner Agent | Executing Subagent |
|----------------|-------------------|-------------------|
| Task Planning | ✓ | ✗ |
| Task Delegation | ✓ | ✗ |
| Result Verification | ✓ | ✗ |
| Code Writing | ✗ | ✓ |
| File Editing | ✗ | ✓ |
| Shell Commands | ✗ | ✓ |
| Context Isolation | Full session history | Independent fresh context |

---

### Toolset Refactoring

**s11 Toolset**:
| Tool | Function |
|------|----------|
| todo | Update session plan (in-memory) |
| task | Delegate subagent |
| read_file | Read file |
| bash | Execute shell command |
| write_file | Write file |
| edit_file | Edit file |
| load_skill | Load skill |
| compact | Compact context |
| save_memory | Save memory |

**s12 Toolset**:
| Tool | Function | Change |
|------|----------|--------|
| task_create | Create new task | Added |
| task_update | Update task status/dependencies | Added |
| task_list | List all tasks | Added |
| task_get | Get task details | Added |
| task | Delegate subagent | Preserved |
| read_file | Read file | Preserved |
| bash | Execute shell command | Preserved (not in main agent) |
| write_file | Write file | Preserved (not in main agent) |
| edit_file | Edit file | Preserved (not in main agent) |
| load_skill | Load skill | Preserved |
| compact | Compact context | Preserved |
| save_memory | Save memory | Preserved |
| todo | Update session plan | Removed |

**PARENT_TOOLS (Main Agent Tools)**:
```python
PARENT_TOOLS = [
    {"name": "read_file", ...},
    {"name": "task", ...},           # Delegate subagent
    {"name": "compact", ...},
    {"name": "save_memory", ...},
    {"name": "task_create", ...},    # Added
    {"name": "task_update", ...},    # Added
    {"name": "task_list", ...},      # Added
    {"name": "task_get", ...},       # Added
]
```

**CHILD_TOOLS (Subagent Tools)**:
```python
CHILD_TOOLS = [
    {"name": "bash", ...},
    {"name": "read_file", ...},
    {"name": "write_file", ...},
    {"name": "edit_file", ...},
    {"name": "load_skill", ...},
    {"name": "compact", ...},
    # No task_* tools (subagent does not manage tasks)
]
```

---

### Task Dependency Management

**Dependency Handling in update() Method**:
```python
def update(self, task_id: int, status: str = None, owner: str = None,
           add_blocked_by: list = None, add_blocks: list = None) -> str:
    task = self._load(task_id)
    
    # Update status
    if status:
        task["status"] = status
        # When task completes, remove from all other tasks' blockedBy
        if status == "completed":
            self._clear_dependency(task_id)
    
    # Add predecessor dependencies
    if add_blocked_by:
        task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
    
    # Add successor dependencies (bidirectional update)
    if add_blocks:
        task["blocks"] = list(set(task["blocks"] + add_blocks))
        for blocked_id in add_blocks:
            try:
                blocked = self._load(blocked_id)
                if task_id not in blocked["blockedBy"]:
                    blocked["blockedBy"].append(task_id)
                    self._save(blocked)
            except ValueError:
                pass
    
    self._save(task)
    return json.dumps(task, indent=2, ensure_ascii=False)
```

**Dependency Cleanup Mechanism**:
```python
def _clear_dependency(self, completed_id: int):
    """Remove completed_id from all other tasks' blockedBy lists."""
    for f in self.dir.glob("task_*.json"):
        task = json.loads(f.read_text())
        if completed_id in task.get("blockedBy", []):
            task["blockedBy"].remove(completed_id)
            self._save(task)
```

---

### Preserved Features (Inherited from s11)

| Component | Status | Description |
|-----------|--------|-------------|
| Three-layer error recovery | Fully preserved | max_tokens, prompt_too_long, API errors |
| SystemPromptBuilder | Preserved (core instructions updated) | 6-layer structured build, different core instructions for main/subagent |
| MemoryManager | Fully preserved | Persistent memory management |
| DreamConsolidator | Fully preserved (pending activation) | Automatic memory consolidation |
| HookManager | Fully preserved | Hook interception pipeline |
| PermissionManager | Fully preserved | Permission management |
| BashSecurityValidator | Fully preserved | Bash security validation |
| SkillRegistry | Fully preserved | Skill registry |
| Context compaction | Fully preserved | micro_compact, compact_history |
| Transcript saving | Fully preserved | write_transcript |

---

## Directory Structure Dependencies

| Directory/File | Purpose | Creation Method |
|----------------|---------|-----------------|
| `.tasks/` | Persistent task storage | Auto-created by TaskManager |
| `.tasks/task_*.json` | Single task file | Created by TaskManager._save() |
| `skills/` | Skill documents | Manually created |
| `.memory/` | Persistent memory | Auto-created by MemoryManager |
| `.memory/MEMORY.md` | Memory index | Rebuilt by _rebuild_index() |
| `.memory/*.md` | Single memory file | Created by save_memory() |
| `.transcripts/` | Session transcripts | Created by write_transcript() |
| `.task_outputs/tool-results/` | Large tool outputs | Created by persist_large_output() |
| `.hooks.json` | Hook configuration | Manually created |
| `.claude/.claude_trusted` | Workspace trust marker | Manually created |

---

## Complete Framework Flowchart

```
Session Start
    │
    ▼
Load Components
├── MemoryManager.load_all()
├── TaskManager(TASKS_DIR)
├── HookManager(perms)
└── SystemPromptBuilder
    │
    ▼
User Input
    │
    ▼
agent_loop(state, compact_state)
│   - Update system prompt (main_build)
│   - micro_compact()
│   - estimate_context_size() > CONTEXT_LIMIT? -> compact_history()
    │
    ▼
run_one_turn(state, compact_state)
│   Layer 1: LLM Call (for attempt in range(4))
│   │   try: response = client.chat.completions.create()
│   │   except:
│   │       context_length_exceeded? -> Strategy 2 + continue
│   │       attempt < 3? -> Strategy 3 + continue
│   │       else -> return False
│   │
│   Layer 2: finish_reason Check
│   │   finish_reason == "length"?
│   │       -> max_output_recovery_count += 1
│   │       -> count <= 3? -> Strategy 1 + return True
│   │       -> else -> return False
│   │
│   Layer 3: Tool Execution
│       tool_calls? -> execute_tool_calls() + return True
│       else -> return False
    │
    ▼
execute_tool_calls()
│   for each tool_call:
│   │   PreToolUse Hook Pipeline
│   │   │   ├── PermissionManager.check()
│   │   │   └── HookManager._run_external_hooks()
│   │   │
│   │   Tool Execution
│   │   │   ├── task_create -> TASKS.create()
│   │   │   ├── task_update -> TASKS.update()
│   │   │   ├── task_list -> TASKS.list_all()
│   │   │   ├── task_get -> TASKS.get()
│   │   │   ├── task -> run_subagent()
│   │   │   ├── read_file -> run_read()
│   │   │   └── ...
│   │   │
│   │   PostToolUse Hook Pipeline
│   │
│   Task Tool Usage Detection
│   │   used_task_manager? -> TASKS.rounds_since_update = 0
│   │   else -> TASKS.rounds_since_update += 1
│   │           >= PLAN_REMINDER_INTERVAL? -> Insert reminder
    │
    ▼
run_subagent() (when task tool is called)
│   - Build subagent system prompt (sub_build)
│   - Independent message history
│   - Independent loop (max 30 steps)
│   - Return execution summary
    │
    ▼
Loop continues or exits


Task Management Data Flow
┌─────────────────────────────────────────────────────────────┐
│                      .tasks/ Directory                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ task_1.json │  │ task_2.json │  │ task_3.json │  ...    │
│  │             │  │             │  │             │         │
│  │ id: 1       │  │ id: 2       │  │ id: 3       │         │
│  │ subject: .. │  │ subject: .. │  │ subject: .. │         │
│  │ status: ..  │  │ status: ..  │  │ status: ..  │         │
│  │ blockedBy:  │  │ blockedBy:  │  │ blockedBy:  │         │
│  │   [1]       │  │   []        │  │   [1,2]     │         │
│  │ blocks: [2] │  │ blocks: [3] │  │ blocks: []  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│         │                │                │                 │
│         └────────────────┼────────────────┘                 │
│                          │                                  │
│                    Dependency Graph                         │
│                    Task1 → Task2 → Task3                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Design Point Summary

### Core Design Mechanism 1: Persistent Task Storage

| Feature | Implementation |
|---------|----------------|
| Storage medium | File system (`.tasks/` directory) |
| File format | JSON (each task as independent file) |
| ID generation | Auto-incrementing integer (based on maximum ID from existing files) |
| Cross-session | Supported (file persistence) |
| Concurrency safety | Single-process scenario (no file locking) |

### Core Design Mechanism 2: Task Dependency Graph

| Relationship Type | Field | Update Method |
|-------------------|-------|---------------|
| Predecessor dependency | blockedBy | Single-direction update on add |
| Successor dependency | blocks | Bidirectional update on add |
| Auto cleanup | - | Clear all blockedBy references when task completes |

### Core Design Mechanism 3: Main/Subagent Separation

| Dimension | Main Planner Agent | Executing Subagent |
|-----------|-------------------|-------------------|
| System prompt | main_build() | sub_build() |
| Toolset | PARENT_TOOLS | CHILD_TOOLS |
| Context | Full session history | Independent fresh context |
| Responsibility | Planning, delegation, verification | Execution, coding, operations |
| Task management | Yes (task_* tools) | No |

### Core Design Mechanism 4: Tool Permission Separation

| Tool Category | Main Agent | Subagent |
|---------------|------------|----------|
| Task management | ✓ | ✗ |
| File reading | ✓ | ✓ |
| File writing | ✗ | ✓ |
| Shell commands | ✗ | ✓ |
| Skill loading | ✗ | ✓ |

### Core Design Mechanism 5: Task Reminder Mechanism

```python
# Tool usage detection
if used_task_manager:
    TASKS.rounds_since_update = 0
    reminder = None
else:
    TASKS.rounds_since_update += 1
    if TASKS.rounds_since_update >= PLAN_REMINDER_INTERVAL:
        reminder = "Refresh your current task list (task_list) or update task statuses before continuing."
```

---

## Overall Design Philosophy Summary

1. **Persistence first**: Task state stored in file system, supporting cross-session tracking.

2. **Responsibility separation**: Main agent handles planning and verification, subagent handles execution and operations.

3. **Explicit dependencies**: Task dependencies explicitly expressed through blockedBy/blocks fields.

4. **Layered toolset**: Main/subagent use different toolsets to prevent responsibility confusion.

5. **Traceable state**: Auto-incrementing task IDs, status enums, dependency graphs.

6. **Progressive upgrade**: Added task management on top of s11 error recovery mechanism, preserving all core components.

---

## Relationship with s11

### Inherited Content

s12 fully preserves s11's core components:
- Three-layer error recovery mechanism (max_tokens, prompt_too_long, API errors)
- SystemPromptBuilder 6-layer structured build
- MemoryManager persistent memory management
- HookManager interception pipeline
- PermissionManager permission management
- BashSecurityValidator security validation
- Context compaction mechanism (micro_compact, compact_history)

### Changed Content

| Component | s11 | s12 |
|-----------|-----|-----|
| Task management | TodoManager (in-memory session-level) | TaskManager (persistent cross-session) |
| Toolset | todo | task_create/update/list/get |
| Agent model | Universal coding agent | Main Planner + Executing Subagent |

### Detailed Comparison

For detailed explanation of s11 error recovery mechanism, refer to: v1_task_manager/chapter_11/s11_Resume_system_文档.md

---

## Practice Guide

### Running Method

```bash
cd v1_task_manager/chapter_12
python s12_task_system.py
```

### Task Management Examples

#### 1. Create Task

```
/task_create subject="Write documentation" description="Create Markdown documentation for s12"
```

Returns:
```json
{
  "id": 1,
  "subject": "Write documentation",
  "description": "Create Markdown documentation for s12",
  "status": "pending",
  "blockedBy": [],
  "blocks": [],
  "owner": ""
}
```

#### 2. Update Task Status

```
/task_update task_id=1 status="in_progress" owner="Hestal"
```

Returns:
```json
{
  "id": 1,
  "subject": "Write documentation",
  "description": "Create Markdown documentation for s12",
  "status": "in_progress",
  "blockedBy": [],
  "blocks": [],
  "owner": "Hestal"
}
```

#### 3. Set Task Dependency

```
/task_update task_id=2 addBlockedBy=[1]
```

Task2 is blocked by Task1, Task2 can only start after Task1 completes.

#### 4. List All Tasks

```
/task_list
```

Returns:
```
[>] #1: Write documentation owner=Hestal
[ ] #2: Verify documentation format (blocked by: [1])
```

#### 5. Delegate Subagent

```
/task prompt="Read s12_task_system.py and analyze the TaskManager class implementation"
```

---

### Test Examples

#### 1. Verify Persistence

```bash
# Check .tasks/ directory after creating task
ls -la .tasks/
# Output: task_1.json

# Task still exists after restarting program
python s12_task_system.py
/task_list
# Output: Previous task list
```

#### 2. Verify Dependency Relationship

```bash
# Create Task1 and Task2
/task_create subject="Task1"
/task_create subject="Task2"

# Set dependency: Task2 blocked by Task1
/task_update task_id=1 addBlocks=[2]

# Check Task2
/task_get task_id=2
# Output contains: "blockedBy": [1]
```

#### 3. Verify Main/Subagent Separation

Observe log output:
- Main agent calls: `[Tool: task_create]`, `[Tool: task_update]`
- Subagent calls: `[Tool: write_file]`, `[Tool: bash]`
- Subagent spawn: `> Spawning Subagent : ...`

---

## Summary

### Core Design Philosophy

s12 achieves cross-session task tracking and task dependency management by upgrading the in-memory Todo system to a persistent Task system. Design principles are **persistent storage**, **responsibility separation**, and **explicit dependencies**.

### Core Mechanisms

1. TaskManager persistent CRUD
2. Task dependency graph (blockedBy/blocks)
3. Main/Subagent responsibility separation
4. Layered toolset
5. Task reminder mechanism

### Version Information

- **File path**: v1_task_manager/chapter_12/s12_task_system.py
- **Core change**: Persistent task system (TaskManager)
- **Inherited content**: s11 core components fully preserved (error recovery, Memory, Hook, etc.)
- **Theme**: Persistent task system

---

*Document version: v1.0*
*Based on code: v1_task_manager/chapter_12/s12_task_system.py*
