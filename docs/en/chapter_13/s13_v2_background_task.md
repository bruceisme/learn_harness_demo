# s13_v2: Background Task System (Asynchronous Parallel Sub-agent Execution)

## Overview

s13_v2 builds upon the s12 persistent task system with **enhanced background task capabilities**. The core changes include a new background task execution framework supporting asynchronous parallel sub-agent execution, priority notification queues, and background task lifecycle management.

### Core Improvements

1. **NotificationQueue class** - Priority notification queue with same-key message folding
2. **BackgroundManager class** - Background task lifecycle management (shell commands + sub-agents)
3. **run_subagent_background() function** - Asynchronous parallel sub-agent execution
4. **Tool set refactoring** - task → background_task + check_background + background_run
5. **s12 functionality fully preserved** - TaskManager, three-layer error recovery, SystemPromptBuilder, and other core components remain unchanged

### Code File Paths

- **Source code**: v1_task_manager/chapter_13/s13_v2_backtask.py
- **Reference documentation**: v1_task_manager/chapter_12/s12_task_system_文档.md
- **Reference code**: v1_task_manager/chapter_12/s12_task_system.py
- **Task directory**: `.tasks/` (hidden directory under workspace root)
- **Background task directory**: `.runtime-tasks/` (hidden directory under workspace root, new in s13)
- **Memory directory**: `.memory/` (hidden directory under workspace root)
- **Skills directory**: `skills/` (under workspace root)
- **Hook configuration**: `.hooks.json` (hook interception pipeline configuration file under workspace root)
- **Claude trust marker**: `.claude/.claude_trusted` (hidden directory under workspace root)

---

## Comparison with s12 (Change Summary)

| Component | s12 | s13_v2 | Change Description |
|------|-----|--------|----------|
| Sub-agent execution | run_subagent() synchronous blocking | run_subagent_background() asynchronous non-blocking | New parallel capability |
| Notification mechanism | None | NotificationQueue | New priority queue + message folding |
| Background management | None | BackgroundManager | New lifecycle management |
| Tool set (main agent) | task (synchronous) | background_task + check_background | Synchronous → Asynchronous |
| Tool set (sub-agent) | No background tools | background_run + check_background | New background shell capability |
| Storage directory | .tasks/ | .tasks/ + .runtime-tasks/ | New background task storage |
| agent_loop | No notification handling | Drain background notifications each round | New notification injection mechanism |
| SystemPromptBuilder | task tool description | background_task tool description | Prompt updated |

---

## s13 New Content Details (Organized by Code Execution Order)

### NotificationQueue Class (Priority Notification Queue with Same-key Message Folding)

```python
class NotificationQueue:
    """
    Priority-based notification queue with same-key folding.
    Folding means a newer message can replace an older message with the
    same key, so the context is not flooded with stale updates.
    """
    PRIORITIES = {"immediate": 0, "high": 1, "medium": 2, "low": 3}
    def __init__(self):
        self._queue = []  # list of (priority, key, message)
        self._lock = threading.Lock()
    def push(self, message: str, priority: str = "medium", key: str = None):
        """Add a message to the queue, folding if key matches an existing entry."""
        with self._lock:
            if key:
                self._queue = [(p, k, m) for p, k, m in self._queue if k != key]
            self._queue.append((self.PRIORITIES.get(priority, 2), key, message))
            self._queue.sort(key=lambda x: x[0])
    def drain(self) -> list:
        """Return all pending messages in priority order and clear the queue."""
        with self._lock:
            messages = [m for _, _, m in self._queue]
            self._queue.clear()
            return messages
```

**Core Mechanisms**:

| Feature | Implementation | Purpose |
|------|----------|------|
| Priority queue | PRIORITIES dictionary mapping, lower number = higher priority | Important notifications processed first |
| Message folding | Check key on push, remove old messages with same key | Avoid duplicate notifications flooding context |
| Thread safety | threading.Lock protects queue operations | Support multi-threaded concurrent access |
| Batch retrieval | drain() returns all messages and clears | Batch injection each agent_loop round |

**Priority Definitions**:
| Priority | Value | Usage Scenario |
|--------|-----|----------|
| immediate | 0 | Urgent notifications (not used in current code) |
| high | 1 | High priority notifications (not used in current code) |
| medium | 2 | Default priority (background task completion notifications) |
| low | 3 | Low priority notifications (not used in current code) |

**Message Folding Example**:
```python
# First push
queue.push("Task A: 50% complete", key="task_a")
# Queue: [(2, "task_a", "Task A: 50% complete")]

# Second push (same key)
queue.push("Task A: 100% complete", key="task_a")
# Queue: [(2, "task_a", "Task A: 100% complete")]  # Old message removed
```

---

### BackgroundManager Class (Background Task Lifecycle Management)

```python
class BackgroundManager:
    def __init__(self):
        self.dir = RUNTIME_DIR
        self.tasks = {}  # task_id -> {status, result, command, started_at}
        self._notification_queue = []  # completed task results
        self._lock = threading.Lock()
```

**Core Methods**:

| Method | Function | Return Value | Usage Scenario |
|------|------|--------|----------|
| `run(command)` | Start background shell command thread | task_id string | Main agent calls background_run |
| `_execute(task_id, command)` | Thread target function: execute subprocess | None (writes to file + pushes notification) | Internal thread call |
| `check(task_id)` | Query single or all background task status | JSON string or formatted list | Main agent calls check_background |
| `drain_notifications()` | Return and clear all completion notifications | list[dict] | agent_loop calls each round |
| `detect_stalled()` | Detect timed-out tasks (>45 seconds) | list[task_id] | Monitor long-running tasks |
| `_persist_task(task_id)` | Persist task status to JSON file | None | Called when task status changes |

**Task Status Enum**:
| Status | Marker | Meaning |
|------|------|------|
| running | - | Currently executing |
| completed | - | Successfully completed |
| timeout | - | Timed out (300 seconds) |
| error | - | Execution error |

**Storage Structure**:
- Directory: `.runtime-tasks/`
- Record file naming: `{task_id}.json`
- Log file naming: `{task_id}.log`
- File format: JSON (with indentation, Chinese characters visible)

**Task Record Structure**:
```json
{
  "id": "sub_abc12345",
  "status": "completed",
  "result": "Task execution result summary",
  "command": "[subagent] Detailed sub-agent task prompt...",
  "started_at": 1234567890.123,
  "finished_at": 1234567895.456,
  "result_preview": "Result preview (first 500 characters)",
  "output_file": ".runtime-tasks/sub_abc12345.log"
}
```

**Background Shell Command Execution Flow**:
```python
def run(self, command: str) -> str:
    """Start a background thread, return task_id immediately."""
    task_id = str(uuid.uuid4())[:8]
    output_file = self._output_path(task_id)
    self.tasks[task_id] = {
        "id": task_id,
        "status": "running",
        "result": None,
        "command": command,
        "started_at": time.time(),
        "finished_at": None,
        "result_preview": "",
        "output_file": str(output_file.relative_to(WORKDIR)),
    }
    self._persist_task(task_id)
    thread = threading.Thread(
        target=self._execute, args=(task_id, command), daemon=True
    )
    thread.start()
    return f"Background task {task_id} started: {command[:80]} ..."
```

---

### run_subagent_background() Function (Asynchronous Parallel Sub-agent Execution)

```python
def run_subagent_background(prompt: str) -> str:
    """Spawn a subagent in a background thread. Returns task_id immediately.
    The subagent result is pushed to BG notification queue when done.
    task_id format: sub_xxxxxxxx
    """
    task_id = "sub_" + str(uuid.uuid4())[:8]
    with BG._lock:
        BG.tasks[task_id] = {
            "id": task_id,
            "status": "running",
            "result": None,
            "command": f"[subagent] {prompt[:80]}",
            "started_at": time.time(),
            "finished_at": None,
            "result_preview": "",
            "output_file": "",
        }
    
    def _run():
        try:
            result = run_subagent(prompt)
            status = "completed"
        except Exception as e:
            result = f"Subagent error: {e}"
            status = "error"
        preview = " ".join(result.split())[:500]
        with BG._lock:
            BG.tasks[task_id]["status"] = status
            BG.tasks[task_id]["result"] = result
            BG.tasks[task_id]["finished_at"] = time.time()
            BG.tasks[task_id]["result_preview"] = preview
            BG._notification_queue.append({
                "task_id": task_id,
                "status": status,
                "command": f"[subagent] {prompt[:80]}",
                "preview": preview,
                "output_file": "",
            })

    threading.Thread(target=_run, daemon=True).start()
    return f"Background subagent {task_id} started: {prompt[:80]}"
```

**Execution Flow**:
1. Generate task_id (format: `sub_xxxxxxxx`)
2. Create task record in BG.tasks
3. Start daemon thread to execute sub-agent
4. Return task_id immediately (non-blocking)
5. Push notification to BG._notification_queue when sub-agent completes

**Comparison with run_subagent()**:

| Feature | run_subagent() | run_subagent_background() |
|------|----------------|---------------------------|
| Execution mode | Synchronous blocking | Asynchronous non-blocking (background thread) |
| Return value | Execution summary string | task_id string |
| Tool exposure | s12 task tool | s13 background_task tool |
| Main agent behavior | Waits for completion | Can continue dispatching other tasks |
| Parallel capability | Not supported | Supports multiple sub-agents in parallel |
| Result retrieval | Direct return | Via check_background or notifications |

**Parallel Execution Example**:
```python
# Main agent can continuously dispatch multiple background sub-agents
task1 = background_task(prompt="Analyze module A")  # Returns immediately: sub_abc12345
task2 = background_task(prompt="Analyze module B")  # Returns immediately: sub_def67890
task3 = background_task(prompt="Analyze module C")  # Returns immediately: sub_ghi11111

# Three sub-agents execute in parallel
# Main agent can continue processing other tasks or wait for results
```

---

### Tool Set Refactoring (task → background_task + Other Tools)

**s12 Main Agent Tool Set**:
| Tool | Function | Blocking |
|------|------|------|
| task | Synchronously execute sub-agent | Yes |
| task_create | Create task | No |
| task_update | Update task | No |
| task_list | List tasks | No |
| task_get | Get task details | No |

**s13_v2 Main Agent Tool Set**:
| Tool | Function | Blocking | Change |
|------|------|------|------|
| background_task | Asynchronously execute sub-agent | No | New |
| check_background | Query background task status | No | New |
| task_create | Create task | No | Preserved |
| task_update | Update task | No | Preserved |
| task_list | List tasks | No | Preserved |
| task_get | Get task details | No | Preserved |
| task | Synchronously execute sub-agent | Yes | Removed |

**s13_v2 Sub-agent Tool Set (New Background Capability)**:
| Tool | Function | Change |
|------|------|------|
| background_run | Asynchronously execute shell command | New |
| check_background | Query background task status | New |

**PARENT_TOOLS Definition (s13_v2)**:
```python
PARENT_TOOLS = [
    {"type": "function", "function": {"name": "read_file", ...}},
    {"type": "function", "function": {"name": "compact", ...}},
    {"type": "function", "function": {"name": "save_memory", ...}},
    {"type": "function", "function": {"name": "task_create", ...}},
    {"type": "function", "function": {"name": "task_update", ...}},
    {"type": "function", "function": {"name": "task_list", ...}},
    {"type": "function", "function": {"name": "task_get", ...}},
    # [s13_v2 New] Parallel sub-agent tools
    {"type": "function", "function": {"name": "background_task",
        "description": "Spawn a subagent in the background...",
        "parameters": {"prompt": "..."}
    }},
    {"type": "function", "function": {"name": "check_background",
        "description": "Check status of a background subagent...",
        "parameters": {"task_id": "..."}
    }},
]
```

**TOOL_HANDLERS Mapping (s13_v2)**:
```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"], kw["tool_call_id"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw["tool_call_id"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_REGISTRY.load_full_text(kw["name"]),
    "compact":    lambda **kw: f"Compacting conversation...",
    "save_memory":  lambda **kw: run_save_memory(kw["name"], kw["description"], kw["type"], kw["content"]),
    "task_create": lambda **kw: TASKS.create(kw["subject"], kw.get("description", "")),
    "task_update": lambda **kw: TASKS.update(kw["task_id"], kw.get("status"), kw.get("owner"), kw.get("addBlockedBy"), kw.get("addBlocks")),
    "task_list":   lambda **kw: TASKS.list_all(),
    "task_get":    lambda **kw: TASKS.get(kw["task_id"]),
    "background_run":   lambda **kw: BG.run(kw["command"]),
    "check_background": lambda **kw: BG.check(kw.get("task_id")),
    "background_task":  lambda **kw: run_subagent_background(kw["prompt"]),  # [s13_v2 New]
}
```

---

### .runtime-tasks/ Directory (Background Task Status and Log Storage)

**Directory Structure**:
```
.workdir/
├── .runtime-tasks/
│   ├── sub_abc12345.json       # Task status record
│   ├── sub_abc12345.log        # Task output log
│   ├── sub_def67890.json
│   ├── sub_def67890.log
│   └── ...
├── .tasks/
├── .memory/
└── ...
```

**File Purposes**:

| File Type | Naming Rule | Content | Creation Time |
|----------|----------|------|----------|
| Status record | `{task_id}.json` | Task metadata (status, command, timestamps, etc.) | When task starts + when status changes |
| Output log | `{task_id}.log` | Complete output (stdout + stderr) | When task completes |

**Status Record Fields**:
```json
{
  "id": "sub_abc12345",
  "status": "completed",
  "result": "Complete execution result",
  "command": "[subagent] First 80 characters of task prompt",
  "started_at": 1234567890.123,
  "finished_at": 1234567895.456,
  "result_preview": "Result preview (first 500 characters, whitespace compressed)",
  "output_file": ".runtime-tasks/sub_abc12345.log"
}
```

**Persistence Mechanism**:
```python
def _persist_task(self, task_id: str):
    record = dict(self.tasks[task_id])
    self._record_path(task_id).write_text(
        json.dumps(record, indent=2, ensure_ascii=False)
    )
```

**Log Truncation**:
```python
# Output log limited to 50000 characters to prevent excessive size
output = (r.stdout + r.stderr).strip()[:50000]
```

---

### Preserved Features (Inherited from s12)

| Component | Status | Description |
|------|------|------|
| TaskManager | Fully preserved | Persistent task CRUD (stored in `.tasks/` directory) |
| Three-layer error recovery | Fully preserved | max_tokens, prompt_too_long, API errors |
| SystemPromptBuilder | Preserved (core instructions updated) | 6-layer structured build, main agent core instructions updated to background_task |
| MemoryManager | Fully preserved | Persistent memory management |
| DreamConsolidator | Fully preserved (pending activation) | Automatic memory consolidation |
| HookManager | Fully preserved | Hook interception pipeline |
| PermissionManager | Fully preserved | Permission management |
| BashSecurityValidator | Fully preserved | Bash security validation |
| SkillRegistry | Fully preserved | Skill registry |
| Context compression | Fully preserved | micro_compact, compact_history |
| Transcript saving | Fully preserved | write_transcript |

---

## Directory Structure Dependencies

| Directory/File | Purpose | Creation Method | Version |
|-----------|------|----------|------|
| `.tasks/` | Persistent task storage | TaskManager auto-creates | s12 preserved |
| `.tasks/task_*.json` | Single task file | TaskManager._save() creates | s12 preserved |
| `.runtime-tasks/` | Background task status and logs | BackgroundManager auto-creates | s13 new |
| `.runtime-tasks/{task_id}.json` | Background task status record | BG._persist_task() creates | s13 new |
| `.runtime-tasks/{task_id}.log` | Background task output log | BG._execute() creates | s13 new |
| `skills/` | Skill documents | Manually created | s11 preserved |
| `.memory/` | Persistent memory | MemoryManager auto-creates | s09 preserved |
| `.memory/MEMORY.md` | Memory index | _rebuild_index() rebuilds | s09 preserved |
| `.memory/*.md` | Single memory file | save_memory() creates | s09 preserved |
| `.transcripts/` | Session transcripts | write_transcript() creates | s11 preserved |
| `.task_outputs/tool-results/` | Large tool outputs | persist_large_output() creates | s12 preserved |
| `.hooks.json` | Hook configuration | Manually created | s08 preserved |
| `.claude/.claude_trusted` | Workspace trust marker | Manually created | s08 preserved |

---

## Complete Framework Flowchart

```
Session Start
    │
    ▼
Load Components
├── MemoryManager.load_all()
├── TaskManager(TASKS_DIR)
├── BackgroundManager()  # [s13 New]
├── HookManager(perms)
└── SystemPromptBuilder
    │
    ▼
User Input
    │
    ▼
agent_loop(state, compact_state)
│   [s13 New] Drain BG notifications
│   │   notifs = BG.drain_notifications()
│   │   if notifs:
│   │       Inject <background-results> into state.messages
│   │
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
│   │   │   ├── background_task -> run_subagent_background()  # [s13 New]
│   │   │   ├── check_background -> BG.check()                # [s13 New]
│   │   │   ├── background_run -> BG.run()                    # [s13 New]
│   │   │   ├── task_create -> TASKS.create()
│   │   │   ├── task_update -> TASKS.update()
│   │   │   ├── task_list -> TASKS.list_all()
│   │   │   ├── task_get -> TASKS.get()
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
run_subagent_background() (When background_task tool is called)  # [s13 New]
│   - Generate task_id (sub_xxxxxxxx)
│   - Create task record in BG.tasks
│   - Start daemon thread
│   │   └── Call run_subagent(prompt)
│   │       └── Independent sub-agent loop (max 30 steps)
│   │
│   - Return task_id immediately (non-blocking)
│   - When sub-agent completes:
│       ├── Update BG.tasks[task_id] status
│       └── Push notification to BG._notification_queue
    │
    ▼
Loop Continue or Exit
│   - No tool calls and no running background tasks -> Exit
│   - Has running background tasks -> Wait for notifications -> Continue loop


Background Task Execution Flow
┌─────────────────────────────────────────────────────────────────┐
│                    .runtime-tasks/ Directory                     │
│  ┌──────────────────────┐  ┌──────────────────────┐            │
│  │ sub_abc12345.json    │  │ sub_abc12345.log     │            │
│  │                      │  │                      │            │
│  │ id: sub_abc12345     │  │ Complete output log  │            │
│  │ status: completed    │  │ (stdout + stderr)    │            │
│  │ command: [subagent]..│  │                      │            │
│  │ started_at: ...      │  │                      │            │
│  │ finished_at: ...     │  │                      │            │
│  │ result_preview: ...  │  │                      │            │
│  │ output_file: ...     │  │                      │            │
│  └──────────────────────┘  └──────────────────────┘            │
│            │                                                       │
│            ▼                                                       │
│  BackgroundManager Lifecycle Management                            │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │  BG.tasks Dictionary (Memory)                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐                │   │
│  │  │ task_1   │  │ task_2   │  │ task_3   │  ...           │   │
│  │  │ running  │  │ completed│  │ error    │                │   │
│  │  └──────────┘  └──────────┘  └──────────┘                │   │
│  │                                                           │   │
│  │  BG._notification_queue (Completion Notifications)        │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ [{task_id, status, preview, output_file}, ...]   │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  └───────────────────────────────────────────────────────────┘   │
│            │                                                       │
│            ▼                                                       │
│  agent_loop Drains Notifications Each Round and Injects to Context│
│  <background-results>                                              │
│  [bg:sub_abc12345] completed: Result preview (output_file=...)    │
│  </background-results>                                             │
└─────────────────────────────────────────────────────────────────┘


Parallel Sub-agent Execution Timeline
Main Agent                   Background Thread 1       Background Thread 2       Background Thread 3
  │                              │                        │                        │
  ├─ background_task("Task A") ──┼────────────────────────┼────────────────────────┤
  │  Returns sub_abc12345        │                        │                        │
  │                              │                        │                        │
  ├─ background_task("Task B") ──┼────────────────────────┼────────────────────────┤
  │  Returns sub_def67890        │                        │                        │
  │                              │                        │                        │
  ├─ background_task("Task C") ──┼────────────────────────┼────────────────────────┤
  │  Returns sub_ghi11111        │                        │                        │
  │                              │                        │                        │
  │  Continue processing other tasks...                  │                        │
  │                              │                        │                        │
  │                              ├─ run_subagent("A")     │                        │
  │                              │  Execute 30-step loop  │                        │
  │                              │                        │                        │
  │                              │                        ├─ run_subagent("B")     │
  │                              │                        │  Execute 30-step loop  │
  │                              │                        │                        │
  │                              │                        │                        ├─ run_subagent("C")
  │                              │                        │                        │  Execute 30-step loop
  │                              │                        │                        │
  │                              ├─ Complete, push notification ────────────────────┤
  │                              │                        │                        │
  │                              │                        ├─ Complete, push notification ───────────┤
  │                              │                        │                        │
  │                              │                        │                        ├─ Complete, push notification
  │                              │                        │                        │
  │  agent_loop drain notifications ◄─────────────────────┴────────────────────────┴────────────────┤
  │  Inject <background-results> into context                                                       │
  │                                                                                                 │
```

---

## Design Point Summary

### Core Design Mechanism 1: Priority Notification Queue

| Feature | Implementation |
|------|----------|
| Priority sorting | PRIORITIES dictionary mapping, sort(key=lambda x: x[0]) |
| Message folding | Check key on push, filter old messages with same key |
| Thread safety | threading.Lock protects queue operations |
| Batch consumption | drain() returns all messages and clears |

### Core Design Mechanism 2: Background Task Lifecycle Management

| Phase | Operation |
|------|------|
| Creation | Generate task_id, initialize BG.tasks record, persist JSON |
| Execution | Start daemon thread, execute subprocess or run_subagent |
| Completion | Update status, result, timestamps, push notification to queue |
| Query | check() returns in-memory task status |
| Monitoring | detect_stalled() checks timed-out tasks (>45 seconds) |

### Core Design Mechanism 3: Asynchronous Parallel Sub-agent Execution

| Dimension | run_subagent() | run_subagent_background() |
|------|----------------|---------------------------|
| Execution model | Synchronous blocking | Asynchronous non-blocking (background thread) |
| Main agent behavior | Waits for completion | Can continue dispatching other tasks |
| Parallel capability | Not supported | Supports multiple sub-agents in parallel |
| Result retrieval | Direct return | Via notifications or check_background |

### Core Design Mechanism 4: Layered Tool Set

| Tool Category | Main Agent | Sub-agent |
|----------|--------|--------|
| Task management | ✓ (task_*) | ✗ |
| Background tasks | ✓ (background_task, check_background) | ✓ (background_run, check_background) |
| File reading | ✓ | ✓ |
| File writing | ✗ | ✓ |
| Shell commands | ✗ | ✓ (bash, background_run) |

### Core Design Mechanism 5: Notification Injection Mechanism

```python
# Drain notifications before each LLM call in agent_loop
notifs = BG.drain_notifications()
if notifs and state.messages:
    notif_text = "\n".join(
        f"[bg:{n['task_id']}] {n['status']}: {n['preview']}"
        for n in notifs
    )
    state.messages.append({
        "role": "user",
        "content": f"<background-results>\n{notif_text}\n</background-results>"
    })
```

---

## Overall Design Philosophy Summary

1. **Asynchronous Parallelism**: Background threads execute sub-agents, main agent can dispatch multiple independent tasks in parallel.

2. **Notification-Driven**: Priority queue + message folding mechanism prevents notifications from flooding context.

3. **Traceable Lifecycle**: Background task status persisted to .runtime-tasks/ directory, supporting query and audit.

4. **Tool Set Extension**: background_task + check_background + background_run form complete background capability.

5. **Incremental Upgrade**: Adds background execution on top of s12 persistent task system, preserving all core components.

6. **Non-Blocking Design**: Main agent not blocked by long-running tasks, can continue processing other tasks or dispatch new ones.

---

## Relationship with s12

### Inherited Content

s13_v2 fully preserves s12's core components:
- TaskManager persistent task CRUD
- Three-layer error recovery mechanism (max_tokens, prompt_too_long, API errors)
- SystemPromptBuilder 6-layer structured build (core instructions updated)
- MemoryManager persistent memory management
- HookManager interception pipeline
- PermissionManager permission management
- BashSecurityValidator security validation
- Context compression mechanism (micro_compact, compact_history)

### Changed Content

| Component | s12 | s13_v2 |
|------|-----|--------|
| Sub-agent execution | run_subagent() synchronous | run_subagent_background() asynchronous |
| Main agent tools | task | background_task + check_background |
| Sub-agent tools | No background tools | background_run + check_background |
| Storage directory | .tasks/ | .tasks/ + .runtime-tasks/ |
| agent_loop | No notification handling | Drain BG notifications each round |

### Detailed Comparison

For detailed documentation on s12 persistent task system, refer to: v1_task_manager/chapter_12/s12_task_system_文档.md

---

## Practice Guide

### Running Method

```bash
cd v1_task_manager/chapter_13
python s13_v2_backtask.py
```

### Background Task Usage Examples

#### 1. Dispatch Background Sub-agent

```
/background_task prompt="Read s13_v2_backtask.py and analyze the BackgroundManager class implementation"
```

Returns:
```
Background subagent sub_abc12345 started: Read s13_v2_backtask.py and analyze the BackgroundManager class implementation
```

#### 2. Query Background Task Status

```
/check_background task_id="sub_abc12345"
```

Returns (running):
```json
{
  "id": "sub_abc12345",
  "status": "running",
  "command": "[subagent] Read s13_v2_backtask.py and analyze the BackgroundManager class implementation",
  "result_preview": "",
  "output_file": ""
}
```

Returns (completed):
```json
{
  "id": "sub_abc12345",
  "status": "completed",
  "command": "[subagent] Read s13_v2_backtask.py and analyze the BackgroundManager class implementation",
  "result_preview": "BackgroundManager class is responsible for background task lifecycle management...",
  "output_file": ""
}
```

#### 3. List All Background Tasks

```
/check_background
```

Returns:
```
sub_abc12345: [completed] [subagent] Read s13_v2_backtask.py -> BackgroundManager class is responsible for...
sub_def67890: [running] [subagent] Analyze tool set changes -> (running)
```

#### 4. Dispatch Background Shell Command (Sub-agent)

```
/background_run command="find . -name '*.py' | head -20"
```

Returns:
```
Background task abc12345 started: find . -name '*.py' | head -20 (output_file=.runtime-tasks/abc12345.log)
```

#### 5. Dispatch Multiple Background Sub-agents in Parallel

```
/background_task prompt="Analyze module A code structure"
/background_task prompt="Analyze module B code structure"
/background_task prompt="Analyze module C code structure"
```

Three sub-agents execute in parallel, main agent can continue processing other tasks.

---

### Test Examples

#### 1. Verify Parallel Execution

```bash
# Start program
python s13_v2_backtask.py

# Continuously dispatch three background sub-agents
/background_task prompt="sleep 5 && echo 'Task A completed'"
/background_task prompt="sleep 5 && echo 'Task B completed'"
/background_task prompt="sleep 5 && echo 'Task C completed'"

# Query status immediately (should all be running)
/check_background

# Query again after waiting 6 seconds (should all be completed)
/check_background
```

#### 2. Verify Notification Injection

Observe log output:
- Main agent drains background notifications each loop iteration
- Completion notifications injected into context with `<background-results>` tags
- Format: `[bg:sub_abc12345] completed: Result preview (output_file=...)`

#### 3. Verify Persistence

```bash
# Check .runtime-tasks/ directory after executing background task
ls -la .runtime-tasks/
# Output: sub_abc12345.json, sub_abc12345.log

# View task status record
cat .runtime-tasks/sub_abc12345.json
# Output: Contains id, status, command, started_at, finished_at, etc.

# View task output log
cat .runtime-tasks/sub_abc12345.log
# Output: Complete stdout + stderr
```

#### 4. Verify Message Folding

```python
# NotificationQueue message folding test
queue = NotificationQueue()
queue.push("Task A: 50%", key="task_a")
queue.push("Task A: 75%", key="task_a")
queue.push("Task A: 100%", key="task_a")

# drain should only return the last message
messages = queue.drain()
# messages = ["Task A: 100%"]
```

---

## Summary

### Core Design Philosophy

s13_v2 implements asynchronous parallel sub-agent execution capability by introducing a background task execution framework. Design principles are **asynchronous parallelism**, **notification-driven**, and **traceable lifecycle**.

### Core Mechanisms

1. NotificationQueue priority queue + message folding
2. BackgroundManager background task lifecycle management
3. run_subagent_background() asynchronous parallel sub-agent execution
4. Tool set refactoring (background_task + check_background + background_run)
5. .runtime-tasks/ directory persistence
6. agent_loop notification injection mechanism

### Version Information

- **File path**: v1_task_manager/chapter_13/s13_v2_backtask.py
- **Core changes**: Background task system (asynchronous parallel sub-agent execution)
- **Inherited content**: s12 core components fully preserved (TaskManager, error recovery, Memory, Hook, etc.)
- **Theme**: Background task system enhancement

---

*Document version: v1.0*
*Based on code: v1_task_manager/chapter_13/s13_v2_backtask.py*
