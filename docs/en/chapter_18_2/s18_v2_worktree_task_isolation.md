# s18_v2_singleagent_worktree_task_isolation: Worktree Task Isolation System

## Overview

s18_v2 enhances the **task execution environment isolation capability** based on s14's scheduled task scheduling system. The core changes are the addition of the WorktreeManager class and EventBus class, supporting full lifecycle management of git worktree, and implementing physically isolated execution environments for tasks.

### Special Version Note

**chapter_18_2 is a special chapter**. The code is directly modified from s14_cron_scheduler.py in chapter_14, rather than evolving sequentially from chapter_15/16/17. This is a **parallel development branch** used to experiment with worktree task isolation functionality.

### Core Improvements

1. **detect_repo_root() function** - Automatically detects git repository root directory, providing path foundation for worktree support
2. **EventBus class** - Append-written worktree lifecycle event logs (`.worktrees/events.jsonl`)
3. **WorktreeManager class** - Full lifecycle management of git worktree (create/enter/run/list/status/closeout/keep/remove)
4. **TaskManager extension** - New worktree-related fields (worktree, worktree_state, last_worktree) and binding methods
5. **worktree_* toolset** - Worktree management tools callable by the main agent (task_bind_worktree, worktree_create, worktree_run, etc.)
6. **`.worktrees/` directory structure** - Worktree configuration and event storage (index.json, events.jsonl, worktrees/)

### Code File Paths

- **Source code**: v1_task_manager/chapter_18_2/s18_v2_singleagent_worktree_task_isolation.py
- **Reference document**: v1_task_manager/chapter_14/s14_cron_scheduler_文档.md
- **Reference code**: v1_task_manager/chapter_14/s14_cron_scheduler.py
- **Worktree index file**: `.worktrees/index.json`
- **Event log file**: `.worktrees/events.jsonl`
- **Worktree directory**: `.worktrees/{worktree_name}/`
- **Scheduled task persistence file**: `.claude/scheduled_tasks.json`
- **Session log directory**: `logs/`
- **Background task directory**: `.runtime-tasks/`
- **Task directory**: `.tasks/`
- **Memory directory**: `.memory/`
- **Skills directory**: `skills/`

---

## Comparison with s14 (Change Overview)

| Component | s14_cron_scheduler | s18_v2_singleagent_worktree_task_isolation | Change Description |
|-----------|-------------------|-------------------------------------------|-------------------|
| Git repository detection | None | detect_repo_root() | New automatic git repository root detection |
| Event logging | None | EventBus class | New worktree lifecycle event logging |
| Worktree management | None | WorktreeManager class | New full lifecycle git worktree management |
| TaskManager fields | Basic fields | + worktree/worktree_state/last_worktree | New worktree binding fields |
| TaskManager methods | Basic CRUD | + bind_worktree/unbind_worktree/record_closeout/exists | New worktree binding methods |
| Main agent toolset | cron_* + task_* + background_* | + worktree_* toolset | New 9 worktree management tools |
| System prompt | No worktree rules | + WORKTREES rules + dynamic worktree list | New worktree usage instructions |
| Directory structure | No .worktrees/ | + .worktrees/ directory | New worktree configuration and event storage |
| Startup information | No worktree information | + Repo root and worktree list | New worktree status display at startup |

---

## s18_v2 New Content Details (in Code Execution Order)

### detect_repo_root() Function (Automatic Git Repository Root Detection)

**Implementation Code**:
```python
def detect_repo_root(cwd: Path) -> "Path | None":
    """Detect git repo root for worktree support. Returns None if not in a repo."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        root = Path(r.stdout.strip())
        return root if r.returncode == 0 and root.exists() else None
    except Exception:
        return None

REPO_ROOT = detect_repo_root(WORKDIR) or WORKDIR
```

**Core Mechanism**:

| Step | Operation | Description |
|------|-----------|-------------|
| 1 | Execute `git rev-parse --show-toplevel` | Get git repository root directory |
| 2 | Check returncode == 0 | Confirm inside git repository |
| 3 | Check path exists | Confirm root directory is valid |
| 4 | Return root directory or WORKDIR | Use current directory if not in git repository |

**Usage**:
- Provide unified root directory path for worktree management
- Ensure `.worktrees/` directory is created at git repository root
- Degrade to current working directory in non-git-repository environments

---

### EventBus Class (Worktree Lifecycle Event Logging)

**Implementation Code**:
```python
class EventBus:
    def __init__(self, event_log_path: Path):
        self.path = event_log_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("")
    
    def emit(self, event: str, task_id=None, wt_name=None, error=None, **extra):
        payload = {"event": event, "ts": time.time()}
        if task_id is not None:
            payload["task_id"] = task_id
        if wt_name:
            payload["worktree"] = wt_name
        if error:
            payload["error"] = error
        payload.update(extra)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    
    def list_recent(self, limit: int = 20) -> str:
        n = max(1, min(int(limit or 20), 200))
        lines = self.path.read_text(encoding="utf-8").splitlines()
        items = []
        for line in lines[-n:]:
            try:
                items.append(json.loads(line))
            except Exception:
                items.append({"event": "parse_error", "raw": line})
        return json.dumps(items, indent=2)
```

**Core Attributes**:

| Attribute | Type | Usage |
|-----------|------|-------|
| path | Path | Event log file path (`.worktrees/events.jsonl`) |

**Core Methods**:

| Method | Function | Return Value | Description |
|--------|----------|--------------|-------------|
| `__init__()` | Initialize event log path | None | Automatically create parent directory and empty file |
| `emit()` | Append write event | None | JSONL format, one event per line |
| `list_recent()` | List recent events | JSON string | Default 20 items, maximum 200 items |

**Event Types**:

| Event Name | Trigger Timing | Included Fields |
|------------|---------------|-----------------|
| `worktree.create.before` | Before worktree creation | task_id, worktree |
| `worktree.create.after` | After worktree creation | task_id, worktree |
| `worktree.create.failed` | Worktree creation failed | task_id, worktree, error |
| `worktree.enter` | Enter worktree | task_id, worktree, path |
| `worktree.run.before` | Before command execution | task_id, worktree, command |
| `worktree.run.after` | After command execution | task_id, worktree |
| `worktree.run.timeout` | Command execution timeout | task_id, worktree |
| `worktree.remove.before` | Before worktree removal | task_id, worktree |
| `worktree.remove.after` | After worktree removal | task_id, worktree |
| `worktree.remove.failed` | Worktree removal failed | task_id, worktree, error |
| `worktree.keep` | Worktree kept | task_id, worktree |
| `worktree.closeout.keep` | Closeout keep | task_id, worktree, reason |
| `worktree.closeout.remove` | Closeout remove | worktree, reason |
| `task.completed` | Task completed | task_id, worktree |

**Event Record Format**:
```jsonl
{"event": "worktree.create.before", "ts": 1713678901.123, "task_id": 1, "worktree": "wt-feature-1"}
{"event": "worktree.create.after", "ts": 1713678902.456, "task_id": 1, "worktree": "wt-feature-1"}
{"event": "worktree.run.before", "ts": 1713678910.789, "task_id": 1, "worktree": "wt-feature-1", "command": "git status"}
{"event": "worktree.run.after", "ts": 1713678911.012, "task_id": 1, "worktree": "wt-feature-1"}
```

---

### WorktreeManager Class (Full Lifecycle Git Worktree Management)

**Implementation Code**:
```python
class WorktreeManager:
    def __init__(self, repo_root: Path, tasks: TaskManager, events: EventBus):
        self.repo_root = repo_root
        self.tasks = tasks
        self.events = events
        self.dir = repo_root / ".worktrees"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / "index.json"
        if not self.index_path.exists():
            self.index_path.write_text(json.dumps({"worktrees": []}, indent=2))
        self.git_available = self._check_git()
```

**Core Attributes**:

| Attribute | Type | Usage |
|-----------|------|-------|
| repo_root | Path | Git repository root directory |
| tasks | TaskManager | Task manager instance (for worktree binding) |
| events | EventBus | Event bus instance (for event logging) |
| dir | Path | .worktrees/ directory path |
| index_path | Path | index.json file path (worktree index) |
| git_available | bool | Whether git is available |

**Core Methods**:

| Method | Function | Parameters | Return Value | Description |
|--------|----------|------------|--------------|-------------|
| `_check_git()` | Check git availability | None | bool | Execute `git rev-parse --is-inside-work-tree` |
| `_run_git()` | Execute git command | args: list | str | Timeout 120 seconds, return stdout+stderr |
| `_load_index()` | Load worktree index | None | dict | Read index.json |
| `_save_index()` | Save worktree index | data: dict | None | Write index.json |
| `_find()` | Find worktree | name: str | dict | Return worktree entry or None |
| `_update_entry()` | Update worktree entry | name, **changes | dict | Return updated entry |
| `_validate_name()` | Validate worktree name | name: str | None | 1-40 characters, alphanumeric._- |
| `create()` | Create worktree | name, task_id, base_ref | str | Create git worktree and bind task |
| `list_all()` | List all worktrees | None | str | Formatted list |
| `status()` | View worktree status | name: str | str | Execute git status |
| `enter()` | Enter worktree | name: str | str | Record last_entered_at |
| `run()` | Run command in worktree | name, command | str | Execute command and log event |
| `remove()` | Remove worktree | name, force, complete_task, reason | str | Remove worktree and update task |
| `keep()` | Keep worktree | name: str | str | Mark as kept status |
| `closeout()` | Close worktree | name, action, reason, force, complete_task | str | keep or remove |

**Worktree Entry Structure**:
```python
entry = {
    "name": "wt-feature-1",           # worktree name
    "path": "/path/to/.worktrees/wt-feature-1",  # worktree directory path
    "branch": "wt/wt-feature-1",      # Associated git branch
    "task_id": 1,                     # Bound task ID (optional)
    "status": "active",               # Status: active/kept/removed
    "created_at": 1713678901.123,     # Creation timestamp
    "last_entered_at": 1713678910.456, # Last entered timestamp (optional)
    "last_command_at": 1713678920.789, # Last command execution timestamp (optional)
    "last_command_preview": "git status", # Last command preview (optional)
    "closeout": {                     # Closeout information (optional)
        "action": "remove",
        "reason": "Task completed",
        "at": 1713679000.012
    }
}
```

**create() Method Details**:
```python
def create(self, name: str, task_id: int = None, base_ref: str = "HEAD") -> str:
    self._validate_name(name)
    if self._find(name):
        raise ValueError(f"Worktree '{name}' already exists")
    if task_id is not None and not self.tasks.exists(task_id):
        raise ValueError(f"Task {task_id} not found")
    path = self.dir / name
    branch = f"wt/{name}"
    self.events.emit("worktree.create.before", task_id=task_id, wt_name=name)
    try:
        self._run_git(["worktree", "add", "-b", branch, str(path), base_ref])
        entry = {
            "name": name, "path": str(path), "branch": branch,
            "task_id": task_id, "status": "active", "created_at": time.time(),
        }
        idx = self._load_index()
        idx["worktrees"].append(entry)
        self._save_index(idx)
        if task_id is not None:
            self.tasks.bind_worktree(task_id, name)
        self.events.emit("worktree.create.after", task_id=task_id, wt_name=name)
        return json.dumps(entry, indent=2)
    except Exception as e:
        self.events.emit("worktree.create.failed", task_id=task_id, wt_name=name, error=str(e))
        raise
```

**Workflow**:
1. Validate worktree name format
2. Check if worktree with same name already exists
3. Check if associated task exists
4. Create new branch `wt/{name}`
5. Execute `git worktree add -b branch path base_ref`
6. Create worktree entry and save to index.json
7. Bind task to worktree (if task_id provided)
8. Log creation event

---

### worktree_* Toolset (Worktree Management Tools Callable by Main Agent)

**Tool Definitions**:

```python
# [s18_v2 New] worktree tools
{"type": "function","function": {"name": "task_bind_worktree",
        "description": "Bind a task to a worktree name, setting its worktree_state to 'active'.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "ID of the task to bind."},
                "worktree": {"type": "string", "description": "Name of the worktree to bind the task to."},
                "owner": {"type": "string", "description": "Optional owner name for the task."}
            },
            "required": ["task_id", "worktree"]
        }}},
{"type": "function","function": {"name": "worktree_create",
        "description": "Create a git worktree execution lane and optionally bind it to a task. Use for parallel or risky work.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Worktree name (1-40 chars: letters, digits, ., _, -)."},
                "task_id": {"type": "integer", "description": "Optional task ID to bind."},
                "base_ref": {"type": "string", "description": "Git ref to branch from (default: HEAD)."}
            },
            "required": ["name"]
        }}},
{"type": "function","function": {"name": "worktree_list",
        "description": "List worktrees tracked in .worktrees/index.json.",
        "parameters": {"type": "object", "properties": {}}}},
{"type": "function","function": {"name": "worktree_enter",
        "description": "Enter or reopen a worktree lane before working in it. Records last_entered_at.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Worktree name."}
            },
            "required": ["name"]
        }}},
{"type": "function","function": {"name": "worktree_status",
        "description": "Show git status for one worktree.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Worktree name."}
            },
            "required": ["name"]
        }}},
{"type": "function","function": {"name": "worktree_run",
        "description": "Run a shell command inside a named worktree directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Worktree name."},
                "command": {"type": "string", "description": "Shell command to run in the worktree."}
            },
            "required": ["name", "command"]
        }}},
{"type": "function","function": {"name": "worktree_closeout",
        "description": "Close out a worktree lane by keeping it for follow-up or removing it. Optionally mark its bound task completed.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Worktree name."},
                "action": {"type": "string", "enum": ["keep", "remove"], "description": "'keep' retains the lane; 'remove' deletes it."},
                "reason": {"type": "string", "description": "Optional reason for this closeout."},
                "force": {"type": "boolean", "description": "Force remove even if worktree has uncommitted changes."},
                "complete_task": {"type": "boolean", "description": "Mark bound task as completed during closeout."}
            },
            "required": ["name", "action"]
        }}},
{"type": "function","function": {"name": "worktree_keep",
        "description": "Mark a worktree as kept without removing it.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Worktree name."}
            },
            "required": ["name"]
        }}},
{"type": "function","function": {"name": "worktree_remove",
        "description": "Remove a worktree directory. Optionally mark its bound task completed.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Worktree name."},
                "force": {"type": "boolean", "description": "Force remove even with uncommitted changes."},
                "complete_task": {"type": "boolean", "description": "Mark bound task as completed."},
                "reason": {"type": "string", "description": "Reason for removal."}
            },
            "required": ["name"]
        }}},
{"type": "function","function": {"name": "worktree_events",
        "description": "List recent worktree lifecycle events from .worktrees/events.jsonl.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of recent events to return (default 20, max 200)."}
            }
        }}},
```

**Tool Handlers**:
```python
TOOL_HANDLERS = {
    # ... other tools
    # [s18_v2 New] worktree tools
    "task_bind_worktree": lambda **kw: TASKS.bind_worktree(kw["task_id"], kw["worktree"], kw.get("owner", "")),
    "worktree_create":    lambda **kw: WORKTREES.create(kw["name"], kw.get("task_id"), kw.get("base_ref", "HEAD")),
    "worktree_list":      lambda **kw: WORKTREES.list_all(),
    "worktree_enter":     lambda **kw: WORKTREES.enter(kw["name"]),
    "worktree_status":    lambda **kw: WORKTREES.status(kw["name"]),
    "worktree_run":       lambda **kw: WORKTREES.run(kw["name"], kw["command"]),
    "worktree_closeout":  lambda **kw: WORKTREES.closeout(kw["name"], kw["action"], kw.get("reason", ""), kw.get("force", False), kw.get("complete_task", False)),
    "worktree_keep":      lambda **kw: WORKTREES.keep(kw["name"]),
    "worktree_remove":    lambda **kw: WORKTREES.remove(kw["name"], kw.get("force", False), kw.get("complete_task", False), kw.get("reason", "")),
    "worktree_events":    lambda **kw: EVENTS.list_recent(kw.get("limit", 20)),
}
```

**Usage Examples**:

```python
# Create worktree and bind task
worktree_create(name="wt-feature-1", task_id=1, base_ref="HEAD")
# Returns: {"name": "wt-feature-1", "path": "/path/to/.worktrees/wt-feature-1", "branch": "wt/wt-feature-1", "task_id": 1, "status": "active", "created_at": 1713678901.123}

# List all worktrees
worktree_list()
# Returns:
# [active] wt-feature-1 -> /path/to/.worktrees/wt-feature-1 (wt/wt-feature-1) task=1

# Enter worktree
worktree_enter(name="wt-feature-1")
# Returns: Updated worktree entry (including last_entered_at)

# View worktree status
worktree_status(name="wt-feature-1")
# Returns: git status output

# Run command in worktree
worktree_run(name="wt-feature-1", command="git status")
# Returns: Command execution result

# Keep worktree
worktree_keep(name="wt-feature-1")
# Returns: Updated worktree entry (status="kept")

# Remove worktree
worktree_remove(name="wt-feature-1", force=False, complete_task=True, reason="Task completed")
# Returns: "Removed worktree 'wt-feature-1'"

# Closeout worktree (comprehensive operation)
worktree_closeout(name="wt-feature-1", action="remove", reason="Task completed", force=False, complete_task=True)
# Returns: Execute keep or remove based on action

# View event log
worktree_events(limit=20)
# Returns: JSON list of recent 20 events
```

---

### TaskManager Enhancement (Worktree-Related Fields and Methods)

**New Fields**:

```python
# New fields in TaskManager.create()
task = {
    "id": self._next_id,
    "subject": subject,
    "description": description,
    "status": "pending",
    "blockedBy": [],
    "blocks": [],
    "owner": "",
    "worktree": "",              # [New] Currently bound worktree name
    "worktree_state": "unbound", # [New] Worktree status: unbound/active
    "last_worktree": "",         # [New] Last used worktree name
    "closeout": None,            # [New] Closeout information
}
```

**TaskRecord Field Description**:

| Field | Type | Meaning | Values |
|-------|------|---------|--------|
| worktree | str | Currently bound worktree name | Empty string or worktree name |
| worktree_state | str | Worktree binding status | unbound/active/kept/removed |
| last_worktree | str | Last used worktree name | Empty string or worktree name |
| closeout | dict | Closeout information | None or {"action": "keep/remove", "reason": "", "at": timestamp} |

**New Methods**:

```python
def exists(self, task_id: int) -> bool:
    """Check if task exists."""
    return (self.dir / f"task_{task_id}.json").exists()

def bind_worktree(self, task_id: int, worktree: str, owner: str = "") -> str:
    """Bind task to worktree."""
    task = self._load(task_id)
    task["worktree"] = worktree
    task["last_worktree"] = worktree
    task["worktree_state"] = "active"
    if owner:
        task["owner"] = owner
    if task["status"] == "pending":
        task["status"] = "in_progress"
    task["updated_at"] = time.time()
    self._save(task)
    return json.dumps(task, indent=2, ensure_ascii=False)

def unbind_worktree(self, task_id: int) -> str:
    """Unbind task's worktree."""
    task = self._load(task_id)
    task["worktree"] = ""
    task["worktree_state"] = "unbound"
    task["updated_at"] = time.time()
    self._save(task)
    return json.dumps(task, indent=2, ensure_ascii=False)

def record_closeout(self, task_id: int, action: str, reason: str = "", keep_binding: bool = False) -> str:
    """Record task's closeout information."""
    task = self._load(task_id)
    task["closeout"] = {
        "action": action,
        "reason": reason,
        "at": time.time(),
    }
    task["worktree_state"] = action
    if not keep_binding:
        task["worktree"] = ""
    task["updated_at"] = time.time()
    self._save(task)
    return json.dumps(task, indent=2, ensure_ascii=False)
```

**TaskManager Method Description**:

| Method | Function | Parameters | Return Value | Description |
|--------|----------|------------|--------------|-------------|
| `exists()` | Check if task exists | task_id: int | bool | Used to verify task before worktree creation |
| `bind_worktree()` | Bind task to worktree | task_id, worktree, owner | JSON string | Set worktree status to active |
| `unbind_worktree()` | Unbind worktree | task_id: int | JSON string | Set worktree status to unbound |
| `record_closeout()` | Record closeout | task_id, action, reason, keep_binding | JSON string | action=keep/remove |

**list_all() Output Enhancement**:
```python
# Add worktree information in list_all() output
marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]", "deleted": "[-]"}.get(t["status"], "[?]")
blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
owner = f" owner={t['owner']}" if t.get("owner") else ""
wt = f" wt={t['worktree']}" if t.get("worktree") else ""  # [New] Worktree information
lines.append(f"{marker} #{t['id']}: {t['subject']}{owner}{wt}{blocked}")
```

Output Example:
```
[>] #1: Implement feature A owner=ZhangSan wt=wt-feature-1
[ ] #2: Implement feature B
[x] #3: Implement feature C wt=wt-feature-2
```

---

### .worktrees/ Directory Structure (Worktree Configuration and Event Storage)

**Directory Structure**:
```
.worktrees/
├── index.json          # Worktree index (all worktree entries)
├── events.jsonl        # Worktree lifecycle event log (JSONL format)
└── worktrees/          # Actual worktree directories (created by git worktree add)
    ├── wt-feature-1/   # Worktree 1
    ├── wt-feature-2/   # Worktree 2
    └── ...
```

**index.json Format**:
```json
{
  "worktrees": [
    {
      "name": "wt-feature-1",
      "path": "/path/to/.worktrees/wt-feature-1",
      "branch": "wt/wt-feature-1",
      "task_id": 1,
      "status": "active",
      "created_at": 1713678901.123,
      "last_entered_at": 1713678910.456,
      "last_command_at": 1713678920.789,
      "last_command_preview": "git status"
    },
    {
      "name": "wt-feature-2",
      "path": "/path/to/.worktrees/wt-feature-2",
      "branch": "wt/wt-feature-2",
      "task_id": 2,
      "status": "kept",
      "created_at": 1713679000.000,
      "closeout": {
        "action": "keep",
        "reason": "Needs follow-up",
        "at": 1713679500.000
      }
    }
  ]
}
```

**events.jsonl Format**:
```jsonl
{"event": "worktree.create.before", "ts": 1713678901.123, "task_id": 1, "worktree": "wt-feature-1"}
{"event": "worktree.create.after", "ts": 1713678902.456, "task_id": 1, "worktree": "wt-feature-1"}
{"event": "worktree.enter", "ts": 1713678910.456, "task_id": 1, "worktree": "wt-feature-1", "path": "/path/to/.worktrees/wt-feature-1"}
{"event": "worktree.run.before", "ts": 1713678920.789, "task_id": 1, "worktree": "wt-feature-1", "command": "git status"}
{"event": "worktree.run.after", "ts": 1713678921.012, "task_id": 1, "worktree": "wt-feature-1"}
{"event": "worktree.closeout.keep", "ts": 1713679500.000, "task_id": 1, "worktree": "wt-feature-1", "reason": "Needs follow-up"}
```

**File Usage**:

| File | Usage | Update Timing | Format |
|------|-------|---------------|--------|
| index.json | Worktree index | When worktree is created/updated/deleted | JSON |
| events.jsonl | Lifecycle event log | During all worktree operations | JSONL (one JSON object per line) |
| worktrees/*/ | Actual worktree directories | Created by git worktree add | git worktree |

---

### Retained Features (Inherited from s14)

| Component | Status | Description |
|-----------|--------|-------------|
| CronScheduler | Fully retained | Scheduled task scheduler (5-field cron expression) |
| BackgroundManager | Fully retained | Background task lifecycle management (shell commands) |
| NotificationQueue | Fully retained | Priority notification queue |
| TaskManager | Enhanced (new worktree fields) | Persistent task CRUD |
| Three-layer error recovery | Fully retained | max_tokens, prompt_too_long, API errors |
| SystemPromptBuilder | Enhanced (new worktree rules) | 6-layer structured building |
| MemoryManager | Fully retained | Persistent memory management |
| DreamConsolidator | Fully retained (pending activation) | Automatic memory consolidation |
| HookManager | Fully retained | Hook interception pipeline |
| PermissionManager | Fully retained | Permission management |
| BashSecurityValidator | Fully retained | Bash security validation |
| SkillRegistry | Fully retained | Skill registry |
| Context compression | Fully retained | micro_compact, compact_history |
| Transcript saving | Fully retained | write_transcript |
| run_subagent_background() | Fully retained | Asynchronous parallel sub-agent execution |
| Event-driven architecture | Fully retained | input_reader + cron_watcher |
| _Tee session log | Fully retained | Output to both terminal and file simultaneously |

**SystemPromptBuilder Enhancement**:

s18_v2 adds worktree-related instructions in the `_build_core()` method of SystemPromptBuilder:

```python
def _build_core(self) -> str:
    return (
        f"You are the Main Planner Agent operating in {self.workdir}.\n"
        # ... other core instructions ...
        "7. WORKTREES: For parallel or risky work, create tasks then use `worktree_create` to allocate isolated git worktree lanes. "
        "Run commands via `worktree_run`. When done, use `worktree_closeout` (action='keep' or 'remove') to close the lane.\n"
    )
```

**Dynamic Context Enhancement**:

The `_build_dynamic_context()` method adds worktree list display:

```python
def _build_dynamic_context(self) -> str:
    lines = [
        f"Current date: {datetime.date.today().isoformat()}",
        f"Working directory: {self.workdir}",
        f"Model: {MODEL}",
    ]
    try:
        wt_info = WORKTREES.list_all()
        lines.append(f"Worktrees:\n{wt_info}")
    except Exception:
        pass
    return "# Dynamic context\n" + "\n".join(lines)
```

**Startup Information Enhancement**:

```python
# [s18_v2] Display worktree and repo root information at startup
print(f"[Repo root: {REPO_ROOT}]")
if not WORKTREES.git_available:
    print("[Note: Not in a git repo. worktree_* tools will return errors.]")
else:
    wt_list = WORKTREES.list_all()
    print(f"[Worktrees: {wt_list}]")
```

---

## Directory Structure Dependencies

| Directory/File | Usage | Creation Method | Version |
|----------------|-------|-----------------|---------|
| `.worktrees/` | Worktree configuration and event storage root | WorktreeManager.__init__() auto-creates | s18_v2 new |
| `.worktrees/index.json` | Worktree index | WorktreeManager init/update | s18_v2 new |
| `.worktrees/events.jsonl` | Worktree lifecycle event log | EventBus append-write | s18_v2 new |
| `.worktrees/worktrees/` | Actual worktree directories | git worktree add creates | s18_v2 new |
| `.worktrees/worktrees/{name}/` | Single worktree directory | WorktreeManager.create() | s18_v2 new |
| `.tasks/` | Persistent task storage | TaskManager auto-creates | s12 retained |
| `.tasks/task_*.json` | Single task file | TaskManager._save() creates | s12 retained (s18_v2 enhanced fields) |
| `.runtime-tasks/` | Background task status and logs | BackgroundManager auto-creates | s13 retained |
| `.runtime-tasks/{task_id}.json` | Background task status record | BG._persist_task() creates | s13 retained |
| `.runtime-tasks/{task_id}.log` | Background task output log | BG._execute() creates | s13 retained |
| `.claude/scheduled_tasks.json` | Scheduled task persistence | CronScheduler._save_durable() creates | s14 retained |
| `logs/` | Session log directory | main function init creates | s14 retained |
| `logs/session_{timestamp}.log` | Session log file | _Tee class writes | s14 retained |
| `skills/` | Skill documents | Manually created | s11 retained |
| `.memory/` | Persistent memory | MemoryManager auto-creates | s09 retained |
| `.memory/MEMORY.md` | Memory index | _rebuild_index() rebuilds | s09 retained |
| `.memory/*.md` | Single memory file | save_memory() creates | s09 retained |
| `.transcripts/` | Session transcripts | write_transcript() creates | s11 retained |
| `.task_outputs/tool-results/` | Large tool outputs | persist_large_output() creates | s12 retained |
| `.hooks.json` | Hook configuration | Manually created | s08 retained |
| `.claude/.claude_trusted` | Workspace trust marker | Manually created | s08 retained |

---

## Complete Framework Flowchart

```
Session Start
    │
    ▼
Initialize Components
├── detect_repo_root()  # Detect git repository root
├── MemoryManager.load_all()
├── TaskManager(TASKS_DIR)
├── EventBus(REPO_ROOT / ".worktrees" / "events.jsonl")
├── WorktreeManager(REPO_ROOT, TASKS, EVENTS)
├── BackgroundManager()
├── CronScheduler()
├── HookManager(perms)
└── SystemPromptBuilder
    │
    ▼
Display Worktree Information at Startup
├── print(f"[Repo root: {REPO_ROOT}]")
├── Check git availability
└── List existing worktrees
    │
    ▼
Start Background Threads
├── scheduler.start()
│   ├── _load_durable()  # Load .claude/scheduled_tasks.json
│   └── _check_loop thread  # Check task triggers every second
├── cron_watcher thread  # Listen scheduler.queue → event_queue
└── input_reader thread  # Listen user input → event_queue
    │
    ▼
Event-Driven Main Loop
    │
    ┌─────────────────────────────────────────────────────────────┐
    │                    event_queue.get() blocking                │
    └──────────────────────────┬──────────────────────────────────┘
                               │
         ┌─────────────────────┴─────────────────────┐
         │                                           │
   ("user", query)                             ("cron", note)
         │                                           │
         ▼                                           ▼
    User Input Processing                     Cron Trigger Processing
    - Slash command check                     - Inject <cron-notification>
    - quit/exit check                         - agent_loop(state)
    - Normal conversation                     - Restore prompt
         │                                           │
         └─────────────────────┬─────────────────────┘
                               │
                               ▼
                        agent_loop(state, compact_state)
                        │
                        ├─ Update system prompt (main_build)
                        ├─ micro_compact()
                        ├─ estimate_context_size() > CONTEXT_LIMIT?
                        │     └── compact_history()
                        │
                        ▼
                    run_one_turn()
                        │
                        ├─ Layer 1: LLM call
                        ├─ Layer 2: finish_reason check
                        └─ Layer 3: Tool execution
                                │
                                ▼
                        execute_tool_calls()
                            │
                            ├─ PreToolUse Hook pipeline
                            ├─ Tool execution
                            │   ├── worktree_create → WORKTREES.create()
                            │   ├── worktree_list → WORKTREES.list_all()
                            │   ├── worktree_enter → WORKTREES.enter()
                            │   ├── worktree_status → WORKTREES.status()
                            │   ├── worktree_run → WORKTREES.run()
                            │   ├── worktree_closeout → WORKTREES.closeout()
                            │   ├── worktree_keep → WORKTREES.keep()
                            │   ├── worktree_remove → WORKTREES.remove()
                            │   ├── worktree_events → EVENTS.list_recent()
                            │   ├── task_bind_worktree → TASKS.bind_worktree()
                            │   ├── background_task → run_subagent_background()
                            │   ├── check_background → BG.check()
                            │   ├── cron_create → scheduler.create()
                            │   └── ...
                            └─ PostToolUse Hook pipeline
```

---

## Design Point Summary

### Core Design Mechanism 1: Full Lifecycle Git Worktree Management

| Feature | Implementation |
|---------|---------------|
| Create | `git worktree add -b {branch} {path} {base_ref}` |
| Enter | Record last_entered_at timestamp |
| Run command | subprocess.run(command, cwd=worktree_path) |
| List | Read index.json return all entries |
| Status | Execute `git status --short --branch` |
| Keep | Update status="kept", record closeout information |
| Remove | `git worktree remove {path}`, update task and index |
| Closeout | Comprehensive operation, supports keep/remove two actions |

### Core Design Mechanism 2: EventBus Event Logging

| Feature | Implementation |
|---------|---------------|
| Format | JSONL (one JSON object per line) |
| Append write | `with path.open("a")` append mode |
| Timestamp | time.time() float timestamp |
| Event types | 14 worktree lifecycle events |
| Query | list_recent(limit) return recent N items |
| Fault tolerance | Return {"event": "parse_error", "raw": line} on parse failure |

### Core Design Mechanism 3: TaskManager Worktree Binding

| Field | Usage | State Flow |
|-------|-------|------------|
| worktree | Currently bound worktree name | Empty string ↔ worktree name |
| worktree_state | Worktree binding status | unbound → active → kept/removed |
| last_worktree | Last used worktree name | Record history, no unbind |
| closeout | Closeout information | None → {"action", "reason", "at"} |

### Core Design Mechanism 4: .worktrees/ Directory Structure

| File | Usage | Update Frequency |
|------|-------|------------------|
| index.json | Worktree index | Every worktree create/update/delete |
| events.jsonl | Lifecycle event log | Every worktree operation |
| worktrees/{name}/ | Actual worktree directory | git worktree add/remove |

### Core Design Mechanism 5: Worktree Toolset Layering

| Tool Category | Tool Name | Usage |
|---------------|-----------|-------|
| Create | worktree_create | Create worktree and optionally bind task |
| Query | worktree_list | List all worktrees |
| Query | worktree_status | View single worktree git status |
| Enter | worktree_enter | Enter worktree (record timestamp) |
| Execute | worktree_run | Run command in worktree |
| Bind | task_bind_worktree | Bind task to worktree |
| Close | worktree_closeout | Comprehensive closeout operation (keep/remove) |
| Close | worktree_keep | Keep worktree |
| Close | worktree_remove | Remove worktree |
| Audit | worktree_events | View event log |

### Core Design Mechanism 6: Thread Safety and Concurrency

| Component | Thread Safety Measure |
|-----------|----------------------|
| WorktreeManager | Single-threaded call (main agent tools) |
| EventBus | Append write (atomic operation) |
| TaskManager | File-level atomic write (_save direct overwrite) |
| index.json | Read-modify-write mode (no lock, single-threaded call) |

---

## Overall Design Philosophy Summary

1. **Physical Isolation Execution Environment**: Provide independent filesystem views for each task through git worktree, avoiding file conflicts between parallel tasks.

2. **Traceable Lifecycle**: EventBus records complete event logs of all worktree operations, facilitating auditing and troubleshooting.

3. **Task-Worktree Binding**: TaskManager extends worktree-related fields, establishing association between tasks and execution environments.

4. **Progressive Upgrade**: Add worktree support on top of s14 scheduled task scheduling system, retaining all core components (CronScheduler, BackgroundManager, TaskManager, etc.).

5. **Toolset Completeness**: Provide 9 worktree management tools, covering full lifecycle operations: create/list/enter/run/status/closeout/keep/remove/events.

6. **Parallel Development Branch**: chapter_18_2 is a parallel branch based on s14, used to experiment with worktree task isolation functionality, rather than evolving sequentially from chapter_15/16/17.

---

## Relationship with s14

### Special Version Note

**chapter_18_2 is a special chapter**. The code is directly modified from s14_cron_scheduler.py in chapter_14, rather than evolving sequentially from chapter_15/16/17. This is a **parallel development branch** used to experiment with worktree task isolation functionality.

### Inherited Content

s18_v2 fully retains s14's core components:
- CronScheduler scheduled task scheduler (5-field cron expression)
- BackgroundManager background task lifecycle management
- TaskManager persistent task CRUD (enhanced worktree fields)
- Three-layer error recovery mechanism (max_tokens, prompt_too_long, API errors)
- SystemPromptBuilder 6-layer structured building (enhanced worktree rules)
- MemoryManager persistent memory management
- HookManager interception pipeline
- PermissionManager permission management
- BashSecurityValidator security validation
- Context compression mechanism (micro_compact, compact_history)
- run_subagent_background() asynchronous parallel sub-agent execution
- Event-driven architecture (input_reader + cron_watcher)
- _Tee session log

### Change Content

| Component | s14_cron_scheduler | s18_v2_singleagent_worktree_task_isolation |
|-----------|-------------------|-------------------------------------------|
| Git repository detection | None | detect_repo_root() |
| Event logging | None | EventBus class |
| Worktree management | None | WorktreeManager class |
| TaskManager fields | Basic fields | + worktree/worktree_state/last_worktree/closeout |
| TaskManager methods | Basic CRUD | + bind_worktree/unbind_worktree/record_closeout/exists |
| Main agent tools | cron_* + task_* + background_* | + 9 worktree_* tools |
| Directory structure | No .worktrees/ | + .worktrees/ directory |
| Startup information | No worktree information | + Repo root and worktree list |

### Detailed Comparison

For detailed description of s14 scheduled task scheduling system, refer to: v1_task_manager/chapter_14/s14_cron_scheduler_文档.md

---

## Practice Guide

### Running Method

```bash
cd v1_task_manager/chapter_18_2
python s18_v2_singleagent_worktree_task_isolation.py
```

### Worktree Usage Examples

#### 1. Create Worktree and Bind Task

```
/worktree_create name="wt-feature-1" task_id=1 base_ref="HEAD"
```

Returns:
```json
{
  "name": "wt-feature-1",
  "path": "/path/to/.worktrees/wt-feature-1",
  "branch": "wt/wt-feature-1",
  "task_id": 1,
  "status": "active",
  "created_at": 1713678901.123
}
```

#### 2. Create Task and Bind Worktree

```
/task_create subject="Implement feature A" description="Implement feature A in wt-feature-1"
/worktree_create name="wt-feature-2" task_id=2
/task_bind_worktree task_id=2 worktree="wt-feature-2" owner="ZhangSan"
```

#### 3. List All Worktrees

```
/worktree_list
```

Returns:
```
[active] wt-feature-1 -> /path/to/.worktrees/wt-feature-1 (wt/wt-feature-1) task=1
[active] wt-feature-2 -> /path/to/.worktrees/wt-feature-2 (wt/wt-feature-2) task=2
```

#### 4. Enter Worktree

```
/worktree_enter name="wt-feature-1"
```

Returns: Updated worktree entry (including last_entered_at)

#### 5. View Worktree Status

```
/worktree_status name="wt-feature-1"
```

Returns: git status output

#### 6. Run Command in Worktree

```
/worktree_run name="wt-feature-1" command="git status"
/worktree_run name="wt-feature-1" command="python -m pytest tests/"
```

Returns: Command execution result

#### 7. Keep Worktree

```
/worktree_keep name="wt-feature-1"
```

Returns: Updated worktree entry (status="kept")

#### 8. Remove Worktree

```
/worktree_remove name="wt-feature-1" force=False complete_task=True reason="Task completed"
```

Returns: `"Removed worktree 'wt-feature-1'"`

#### 9. Closeout Worktree (Comprehensive Operation)

```
/worktree_closeout name="wt-feature-1" action="remove" reason="Task completed" force=False complete_task=True
/worktree_closeout name="wt-feature-2" action="keep" reason="Needs follow-up"
```

#### 10. View Event Log

```
/worktree_events limit=20
```

Returns: JSON list of recent 20 events

---

### Test Examples

#### 1. Verify Worktree Creation

```bash
# Start program
python s18_v2_singleagent_worktree_task_isolation.py

# Create task
/task_create subject="Test feature" description="Test worktree functionality"

# Create worktree and bind task
/worktree_create name="wt-test-1" task_id=1 base_ref="HEAD"

# Check .worktrees/index.json
cat .worktrees/index.json

# Check .worktrees/events.jsonl
cat .worktrees/events.jsonl

# Check task file
cat .tasks/task_1.json
# Should contain worktree, worktree_state, last_worktree fields
```

#### 2. Verify Worktree Command Execution

```bash
# Run command in worktree
/worktree_run name="wt-test-1" command="git status"
/worktree_run name="wt-test-1" command="ls -la"

# View event log
/worktree_events limit=10
# Should contain worktree.run.before and worktree.run.after events
```

#### 3. Verify Worktree Closeout

```bash
# Closeout worktree
/worktree_closeout name="wt-test-1" action="remove" reason="Test completed" complete_task=True

# Check task status
/task_get task_id=1
# status should be "completed", closeout should have record

# Check event log
/worktree_events limit=5
# Should contain worktree.closeout.remove, worktree.remove.before, worktree.remove.after events
```

#### 4. Verify Non-Git-Repository Degradation

```bash
# Start in non-git-repository directory
mkdir /tmp/test-non-git
cd /tmp/test-non-git
python /path/to/s18_v2_singleagent_worktree_task_isolation.py

# Output should contain:
# [Repo root: /tmp/test-non-git]
# [Note: Not in a git repo. worktree_* tools will return errors.]

# Attempt to create worktree should return error
/worktree_create name="wt-test"
# Returns: "Not in a git repository."
```

#### 5. Verify Complete Workflow

```bash
# 1. Create task
/task_create subject="Implement feature A"

# 2. Create worktree
/worktree_create name="wt-feature-a" task_id=1

# 3. List tasks (verify worktree binding)
/task_list
# Output should contain: [>] #1: Implement feature A wt=wt-feature-a

# 4. Execute operations in worktree
/worktree_run name="wt-feature-a" command="echo 'Hello from worktree' > test.txt"
/worktree_run name="wt-feature-a" command="cat test.txt"

# 5. Closeout worktree
/worktree_closeout name="wt-feature-a" action="remove" reason="Feature completed" complete_task=True

# 6. Verify task completion
/task_list
# Output should contain: [x] #1: Implement feature A

# 7. View event log
/worktree_events limit=20
# Should contain complete lifecycle events
```

---

### Worktree Naming Conventions

| Rule | Description | Example |
|------|-------------|---------|
| Length | 1-40 characters | ✓ wt-feature-1, ✗ a...a (41 chars) |
| Character set | Letters, digits, ., _, - | ✓ wt_feature.1, ✗ wt@feature |
| Recommended prefix | wt- | wt-feature-1, wt-bugfix-123 |
| Recommended format | wt-{type}-{identifier} | wt-feature-login, wt-bugfix-456 |

---

### Common Workflow Patterns

#### Pattern 1: Single Task Single Worktree

```
/task_create subject="Feature A"
/worktree_create name="wt-feature-a" task_id=1
# ... work in worktree ...
/worktree_closeout name="wt-feature-a" action="remove" complete_task=True
```

#### Pattern 2: Multi-Task Parallel Worktree

```
/task_create subject="Feature A"
/task_create subject="Feature B"
/worktree_create name="wt-feature-a" task_id=1
/worktree_create name="wt-feature-b" task_id=2
# ... two worktrees work in parallel ...
/worktree_closeout name="wt-feature-a" action="remove" complete_task=True
/worktree_closeout name="wt-feature-b" action="remove" complete_task=True
```

#### Pattern 3: Keep Worktree for Follow-up

```
/task_create subject="Feature A"
/worktree_create name="wt-feature-a" task_id=1
# ...阶段性 work ...
/worktree_closeout name="wt-feature-a" action="keep" reason="Pending optimization"
# ... subsequent session ...
/worktree_enter name="wt-feature-a"
# ... continue work ...
/worktree_closeout name="wt-feature-a" action="remove" complete_task=True
```

---

## Summary

### Core Design Philosophy

s18_v2 implements task physical isolation execution environment based on git worktree by introducing WorktreeManager and EventBus. Design principles are **physical isolation**, **traceable lifecycle**, and **task-environment binding**.

### Core Mechanisms

1. detect_repo_root() automatically detects git repository root directory
2. EventBus worktree lifecycle event logging
3. WorktreeManager git worktree full lifecycle management (9 methods)
4. TaskManager worktree field extension (worktree, worktree_state, last_worktree, closeout)
5. worktree_* toolset (9 main agent tools)
6. .worktrees/ directory structure (index.json, events.jsonl, worktrees/)

### Version Notes

- **File path**: v1_task_manager/chapter_18_2/s18_v2_singleagent_worktree_task_isolation.py
- **Core changes**: worktree task isolation system
- **Inherited content**: s14 core components fully retained (CronScheduler, BackgroundManager, TaskManager enhanced, Memory, Hook, etc.)
- **Theme**: Task execution environment physical isolation
- **Version relationship**: Parallel development branch based on s14 (chapter_18_2 is special chapter)

---

*Document version: v1.0*
*Based on code: v1_task_manager/chapter_18_2/s18_v2_singleagent_worktree_task_isolation.py*