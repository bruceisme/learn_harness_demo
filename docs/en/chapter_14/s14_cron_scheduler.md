# s14_cron_scheduler: Cron Task Scheduling System (Dual Event Source Architecture)

## Overview

s14 enhances **cron task scheduling capabilities** on top of the s13 background task system. The core changes include adding the CronScheduler cron task scheduler with support for 5-field cron expressions, and upgrading the event-driven architecture from single event source to dual event source.

### Core Improvements

1. **CronScheduler class** - Cron task scheduler supporting 5-field cron expressions (min hour dom month dow)
2. **cron_create/delete/list tools** - Main agent interface for managing cron tasks
3. **cron_watcher thread** - Dedicated thread for listening to cron notifications and injecting into event queue
4. **Event-driven architecture upgrade** - From single event source (user input) to dual event source (user input + cron cron tasks)
5. **_Tee class** - Session logging functionality, outputting to both terminal and file simultaneously
6. **Thread safety fixes** - BUG-1 (BackgroundManager lock), BUG-2 (CronScheduler RLock), BUG-17 (subagent notification stealing)

### Code File Paths

- **Source code**: v1_task_manager/chapter_14/s14_cron_scheduler.py
- **Reference documentation**: v1_task_manager/chapter_13/s13_v2_backtask_文档.md
- **Reference code**: v1_task_manager/chapter_13/s13_v2_backtask.py
- **Cron task persistence file**: `.claude/scheduled_tasks.json`
- **Session log directory**: `logs/`
- **Background task directory**: `.runtime-tasks/`
- **Task directory**: `.tasks/`
- **Memory directory**: `.memory/`
- **Skills directory**: `skills/`
- **Hook configuration**: `.hooks.json`
- **Claude trust marker**: `.claude/.claude_trusted`

---

## Comparison with s13 (Change Summary)

| Component | s13_v2 | s14_cron_scheduler | Change Description |
|------|--------|-------------------|----------|
| Cron task scheduling | None | CronScheduler | New 5-field cron expression support |
| Main agent toolset | background_task + check_background | + cron_create/delete/list | New cron task management tools |
| Event source | Single event source (user input) | Dual event source (user input + cron) | New cron_watcher thread |
| Event processing | agent_loop directly processes user input | Unified event queue driven | input_reader + cron_watcher jointly inject |
| Session logging | None | _Tee class | New simultaneous output to terminal and file |
| BackgroundManager thread safety | No lock on self.tasks writes | _execute with lock writes + lock-outside persistence | Fix BUG-1 data race |
| CronScheduler thread safety | No lock on self.tasks access | RLock protects all access | Fix BUG-2 data race |
| Subagent toolset | background_run + check_background | Remove background tools | Fix BUG-17 notification stealing |
| Context limit | 100000 chars | 800000 chars | Adapt to 260k token models |
| Persistence threshold | 60000 chars | 150000 chars | Reduce file persistence frequency |

---

## s14 New Content Details (by Code Execution Order)

### CronScheduler Class (Cron Task Scheduler, 5-field cron expressions)

```python
class CronScheduler:
    """
    Manages cron tasks and checks trigger conditions in a background thread.
    When triggered, pushes prompt to notification queue, agent_loop drains before each LLM call.
    """
    def __init__(self):
        self.tasks = []
        self.queue = Queue()
        self._lock = threading.RLock()  # RLock: allows same-thread reentrancy
        self._stop_event = threading.Event()
        self._thread = None
        self._last_check_minute = -1
```

**Core Attributes**:

| Attribute | Type | Purpose |
|------|------|------|
| tasks | list | Cron task list, each item contains id/cron/prompt/recurring/durable fields |
| queue | Queue | Thread-safe notification queue, triggered task prompts pushed here |
| _lock | RLock | Reentrant lock, protects concurrent access to tasks list |
| _stop_event | Event | Stop signal, used for graceful background thread shutdown |
| _thread | Thread | Background check thread, checks task triggers every second |
| _last_check_minute | int | Last checked minute, avoids repeated triggers within same minute |

**Core Methods**:

| Method | Function | Return Value | Thread Safe |
|------|------|--------|----------|
| `start()` | Load persistent tasks and start background check thread | None | Yes (lock-protected count read) |
| `stop()` | Set stop signal and wait for thread exit | None | Yes |
| `create()` | Create cron task | task_id string | Yes (lock-protected append + persistence) |
| `delete()` | Delete cron task | Deletion result string | Yes (lock-protected filter + persistence) |
| `list_tasks()` | List all cron tasks | Formatted string | Yes (lock-protected snapshot) |
| `drain_notifications()` | Return and clear all triggered notifications | list[str] | Yes (Queue is thread-safe) |
| `_check_loop()` | Background thread main loop, checks every second | None (thread target function) | Yes |
| `_check_tasks()` | Check if any tasks trigger in current minute | None | Yes (lock-protected traversal + update) |
| `_load_durable()` | Load persistent tasks from disk | None | Yes (called at startup) |
| `_save_durable()` | Save persistent tasks to disk | None | Yes (lock-protected call) |
| `detect_missed_tasks()` | Detect missed triggers during session close | list[dict] | Yes (lock-protected snapshot) |

**Task Structure**:
```python
task = {
    "id": "abc12345",           # 8-char UUID
    "cron": "*/5 * * * *",      # 5-field cron expression
    "prompt": "Task prompt to execute",
    "recurring": True,          # Whether to repeat execution
    "durable": True,            # Whether to persist to disk
    "createdAt": 1234567890.123, # Creation timestamp
    "jitter_offset": 2,         # jitter offset (recurring tasks only)
    "last_fired": 1234567920.456, # Last trigger timestamp
}
```

---

## 5-field Cron Expression Format and Usage

**Field Definition**:
```
+-------+-------+-------+-------+-------+
| min   | hour  | dom   | month | dow   |
| 0-59  | 0-23  | 1-31  | 1-23  | 0-6   |
+-------+-------+-------+-------+-------+
  minute  hour    day     month   weekday
```

**Supported Syntax**:

| Syntax | Example | Meaning |
|------|------|------|
| `*` | `* * * * *` | Every (every minute/hour/day...) |
| `,` | `0,30 * * * *` | Enumerated values (0 and 30) |
| `-` | `0 9-17 * * 1-5` | Range (9 to 17, Monday to Friday) |
| `/` | `*/15 * * * *` | Step (every 15 minutes) |
| Combined | `0,30 9-17 * * 1-5` | Combined usage (0 and 30 minutes, 9-17 on weekdays) |

**cron_matches() Function Implementation**:
```python
def cron_matches(expr: str, now: "dt") -> bool:
    """
    Check if 5-field cron expression matches specified time.
    Fields: minute hour day month weekday (0=Sunday)
    Supports * / N N-M N,M syntax, no external dependencies.
    """
    fields = expr.strip().split()
    if len(fields) != 5:
        return False
    cron_dow = (now.weekday() + 1) % 7  # Python 0=Monday → cron 0=Sunday
    values = [now.minute, now.hour, now.day, now.month, cron_dow]
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    for field, value, (lo, hi) in zip(fields, values, ranges):
        if not _field_matches(field, value, lo, hi):
            return False
    return True
```

**Weekday Conversion Explanation**:
- Python's `weekday()`: 0=Monday, 6=Sunday
- Cron standard: 0=Sunday, 6=Saturday
- Conversion formula: `cron_dow = (now.weekday() + 1) % 7`

**Cron Expression Examples**:

| Expression | Meaning | Use Case |
|--------|------|----------|
| `*/5 * * * *` | Every 5 minutes | High-frequency monitoring tasks |
| `0 * * * *` | Every hour on the hour | Hourly data sync |
| `0 9 * * *` | Daily at 9:00 | Daily morning report generation |
| `30 14 * * *` | Daily at 14:30 | Daily afternoon tasks |
| `0 9 * * 1` | Monday at 9:00 | Weekly meeting reminder |
| `0 9 * * 1-5` | Weekdays at 9:00 | Weekday morning report |
| `0,30 9-17 * * 1-5` | 0 and 30 minutes, 9-17 on weekdays | Every 30 minutes during work hours |
| `0 0 1 * *` | 1st of month at 0:00 | Monthly report generation |

---

### cron_create/delete/list Tools (Main Agent Manages Cron Tasks)

**Tool Definitions**:

```python
# [s14 new] cron cron task tools
{"type": "function","function": {"name": "cron_create",
        "description": "Schedule a recurring or one-shot task with a cron expression. The task prompt will be injected into the conversation when the schedule fires.",
        "parameters": {
            "type": "object",
            "properties": {
                "cron": {"type": "string", "description": "5-field cron expression: 'min hour dom month dow'. Example: '*/5 * * * *' for every 5 minutes."},
                "prompt": {"type": "string", "description": "The prompt to inject into the conversation when the task fires."},
                "recurring": {"type": "boolean", "description": "true=repeat until deleted or 7-day expiry, false=fire once then auto-delete. Default true."},
                "durable": {"type": "boolean", "description": "true=persist to disk (.claude/scheduled_tasks.json), false=session-only. Default false."},
            },
            "required": ["cron", "prompt"]
        }}},
{"type": "function","function": {"name": "cron_delete",
        "description": "Delete a scheduled cron task by its ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "The task ID to delete (8-char hex string)."},
            },
            "required": ["id"]
        }}},
{"type": "function","function": {"name": "cron_list",
        "description": "List all currently scheduled cron tasks with their status, cron expression, and prompt.",
        "parameters": {
            "type": "object",
            "properties": {}
        }}},
```

**Tool Handlers**:
```python
TOOL_HANDLERS = {
    # ... other tools
    "cron_create": lambda **kw: scheduler.create(
        kw["cron"], kw["prompt"],
        kw.get("recurring", True), kw.get("durable", False)
    ),
    "cron_delete": lambda **kw: scheduler.delete(kw["id"]),
    "cron_list":   lambda **kw: scheduler.list_tasks(),
}
```

**Usage Examples**:

```python
# Create recurring task every 5 minutes
cron_create(cron="*/5 * * * *", prompt="Check background task status", recurring=True, durable=False)
# Returns: Created task abc12345 (recurring, session-only): cron=*/5 * * * *

# Create persistent task daily at 9:00
cron_create(cron="0 9 * * *", prompt="Generate daily morning report", recurring=True, durable=True)
# Returns: Created task def67890 (recurring, durable): cron=0 9 * * *

# Create one-shot task
cron_create(cron="30 14 * * *", prompt="Execute afternoon check", recurring=False, durable=False)
# Returns: Created task ghi11111 (one-shot, session-only): cron=30 14 * * *

# List all cron tasks
cron_list()
# Returns:
#   abc12345  */5 * * * *  [recurring/session] (0.5h old): Check background task status
#   def67890  0 9 * * *  [recurring/durable] (1.2h old): Generate daily morning report

# Delete cron task
cron_delete(id="abc12345")
# Returns: Deleted task abc12345
```

---

### cron_watcher Thread (Dedicated Listener for Cron Notifications Injecting into Event Queue)

**Implementation Code**:
```python
def cron_watcher(event_queue: Queue, stop_event: threading.Event) -> None:
    """
    [s14_v2 new] Background thread dedicated to listening to scheduler.queue.
    Drains every second, pushes triggered cron notifications as ("cron", note) to event_queue.
    Exits after stop_event is set.
    Since agent_loop no longer drains scheduler.queue internally,
    all cron notifications go through this thread → event_queue → main loop unified processing, no race.
    """
    while not stop_event.is_set():
        notes = scheduler.drain_notifications()
        for note in notes:
            print(f"\n[Cron notification] {note[:100]}")
            event_queue.put(("cron", note))
        stop_event.wait(timeout=1)
```

**Working Mechanism**:

| Step | Operation | Description |
|------|------|------|
| 1 | Wake up every second | `stop_event.wait(timeout=1)` |
| 2 | drain scheduler.queue | Get all triggered cron notifications |
| 3 | Print notification to terminal | User-visible trigger log |
| 4 | Inject into event queue | `event_queue.put(("cron", note))` |
| 5 | Main loop processes | Get from event_queue and inject into history |

**Comparison with s13**:

| Feature | s13_v2 | s14_cron_scheduler |
|------|--------|-------------------|
| Event source | User input only (input_reader) | User input + cron_watcher |
| Notification processing | agent_loop drains BG notifications internally | cron_watcher uniformly injects into event queue |
| Event queue | None | Queue unified scheduling |
| Blocking method | input() blocking | event_queue.get() blocking |

**Event Injection Flow**:
```
CronScheduler detects trigger
        │
        ▼
scheduler.queue.put(notification)
        │
        ▼
cron_watcher drains every second
        │
        ▼
event_queue.put(("cron", note))
        │
        ▼
Main loop event_queue.get() wakes
        │
        ▼
history.append(<cron-notification>...)
        │
        ▼
agent_loop(state, compact_state)
```

---

### Event-Driven Architecture Upgrade (From Single Event Source to Dual Event Source)

**s13 Single Event Source Architecture**:
```
User Input ──► input() blocking ──► agent_loop ──► Tool Execution ──► Loop
```

**s14 Dual Event Source Architecture**:
```
                    ┌─────────────────────────────────────┐
                    │           Event Queue (Queue)       │
                    │  ┌───────────┐  ┌───────────────┐  │
User Input ──► input_reader ──►│ ("user", query) │  │               │
                    │  └───────────┘  └───────────────┘  │
                    │                                     │
cron trigger ──► cron_watcher ──►│ ("cron", note)  │  │               │
                    │  └───────────┘  └───────────────┘  │
                    └─────────────────┬───────────────────┘
                                      │
                                      ▼
                            event_queue.get() blocking
                                      │
                                      ▼
                              Dispatch by event_type
                            ┌─────────┴─────────┐
                            │                   │
                      event_type="user"   event_type="cron"
                            │                   │
                            ▼                   ▼
                      Normal dialogue    Inject <cron-notification>
                            │                   │
                            └─────────┬─────────┘
                                      │
                                      ▼
                                agent_loop
```

**Main Loop Implementation**:
```python
while True:
    event_type, content = _event_queue.get()  # Wakes on any event

    # ── quit ────────────────────────────────────────────────────
    if event_type == "quit":
        _stop_cron_watcher.set()
        scheduler.stop()
        break

    # ── cron trigger: no user input needed, inject into history and run agent_loop directly ──
    if event_type == "cron":
        print()
        history.append({
            "role": "user",
            "content": f"<cron-notification>\n{content}\n</cron-notification>",
        })
        state = LoopState(messages=history)
        agent_loop(state, compact_state)
        history = state.messages
        # ... process reply ...
        _input_ready.set()   # Restore prompt
        continue

    # ── user input ────────────────────────────────────────────────
    query = content
    # ... process user input (slash commands, normal dialogue, etc.) ...
```

**Advantages of Dual Event Source**:

| Feature | Description |
|------|------|
| Autonomous trigger | cron task triggers without user input, system executes automatically |
| Unified scheduling | All events scheduled through single queue, avoids races |
| Decoupled design | input_reader and cron_watcher run independently, no interference |
| Extensible | Easy to add new event sources (webhooks, file monitoring, etc.) |

---

### _Tee Class (Session Logging Functionality)

**Implementation Code**:
```python
class _Tee:
    """
    Proxies sys.stdout / sys.stderr:
    - Terminal side: outputs as-is (preserves ANSI colors)
    - File side: removes ANSI escape codes, readline markers (\x01/\x02) and standalone \r, outputs readable text
    fileno() proxies to original terminal fd, ensures readline / termios work correctly.
    """
    _ANSI_RE = re.compile(r'\x1b\[[0-9;]*[mKJHABCDEFGfrsulh]|\x01|\x02')

    def __init__(self, terminal, logfile):
        self._terminal = terminal
        self._logfile  = logfile

    def write(self, data: str):
        self._terminal.write(data)
        clean = self._ANSI_RE.sub('', data)
        # Convert standalone \r (not followed by \n) to empty string, avoids line overwriting in log
        clean = re.sub(r'\r(?!\n)', '', clean)
        if clean:
            try:
                self._logfile.write(clean)
            except Exception as e:
                self._terminal.write(f"\n[_Tee] Log write failed, discarding: {e}\n")

    def flush(self):
        self._terminal.flush()
        try:
            self._logfile.flush()
        except Exception as e:
            self._terminal.write(f"\n[_Tee] Log flush failed, discarding: {e}\n")

    def isatty(self):
        return self._terminal.isatty()

    def fileno(self):
        return self._terminal.fileno()
```

**Core Mechanism**:

| Method | Function | Description |
|------|------|------|
| `__init__()` | Save terminal and log file references | Proxy object initialization |
| `write()` | Dual-path writing | Terminal outputs as-is, file removes ANSI codes |
| `flush()` | Dual-path flush | Ensures logs written to disk promptly |
| `isatty()` | Proxy terminal check | Maintains terminal feature detection |
| `fileno()` | Proxy file descriptor | Ensures readline/termios work correctly |

**Log File Processing**:
- **Directory**: `logs/`
- **Naming**: `session_{timestamp}.log`
- **Content**: ANSI escape codes, readline markers, standalone carriage returns removed
- **Encoding**: UTF-8

**Initialization Code**:
```python
_log_dir = WORKDIR / "logs"
_log_dir.mkdir(exist_ok=True)
_log_path = _log_dir / f"session_{int(time.time())}.log"
_log_file = open(_log_path, "w", buffering=1, encoding="utf-8")
sys.stdout = _Tee(sys.__stdout__, _log_file)
sys.stderr = _Tee(sys.__stderr__, _log_file)
print(f"[Session log: {_log_path}]")
```

**Log Content Example**:
```
[Session log: logs/session_1713678901.log]
[Cron scheduler running. Background checks every second.]
[5 memories loaded into context]
[s14_v2] Event-driven loop started. Cron tasks will fire without user input.

[Final reply] Cron task abc12345 created, executes every 5 minutes.
```

---

### Thread Safety Fixes (BUG-1, BUG-2, BUG-17 Data Race Issues)

#### BUG-1: BackgroundManager._execute Writes to self.tasks with Lock

**Problem Description**:
```python
# Before fix (s13): 4 field assignments without lock
self.tasks[task_id]["status"] = status
self.tasks[task_id]["result"] = final_output
self.tasks[task_id]["finished_at"] = time.time()
self.tasks[task_id]["result_preview"] = preview
self._notification_queue.append({...})
self._persist_task(task_id)
```

**Data Race Scenario**:
- Background thread `_execute()` writes 4 fields of self.tasks[task_id]
- Main thread `check()` or `detect_stalled()` reads self.tasks[task_id] simultaneously
- May read partially updated intermediate state

**Fix Solution**:
```python
# After fix (s14): 4 field assignments and notification enqueue merged into single with self._lock: block
with self._lock:
    self.tasks[task_id]["status"] = status
    self.tasks[task_id]["result"] = final_output
    self.tasks[task_id]["finished_at"] = time.time()
    self.tasks[task_id]["result_preview"] = preview
    self._notification_queue.append({
        "task_id": task_id,
        "status": status,
        "command": command[:80],
        "preview": preview,
        "output_file": str(output_path.relative_to(WORKDIR)),
    })
self._persist_task(task_id)  # Execute file I/O outside lock, avoids blocking other threads while holding lock
```

**Fix Key Points**:
- 4 field assignments and notification enqueue completed within same lock
- `_persist_task()` moved outside lock, avoids blocking other threads during file I/O

---

#### BUG-2: CronScheduler All self.tasks Access Protected by RLock

**Problem Description**:
```python
# Before fix (s14_v3): _check_tasks background thread and main thread's create/delete/list_tasks
# Concurrent read/write to self.tasks list, no synchronization
```

**Data Race Scenario**:
- Background thread `_check_tasks()` traverses self.tasks and modifies (deletes expired tasks)
- Main thread `create()` or `delete()` modifies self.tasks list simultaneously
- May cause `RuntimeError: list changed size during iteration` or data loss

**Fix Solution**:
```python
class CronScheduler:
    def __init__(self):
        self.tasks = []
        self.queue = Queue()
        self._lock = threading.RLock()  # RLock: allows same-thread reentrancy
        # ...
```

**Lock-Protected Methods**:
```python
# start() → count = len(self.tasks) with lock
def start(self):
    self._load_durable()
    self._thread = threading.Thread(target=self._check_loop, daemon=True)
    self._thread.start()
    with self._lock:
        count = len(self.tasks)
    if count:
        print(f"[Cron] Loaded {count} cron tasks")

# create() → append + _save_durable with lock
def create(self, cron_expr: str, prompt: str, recurring: bool = True, durable: bool = False) -> str:
    task_id = str(uuid.uuid4())[:8]
    now = time.time()
    task = {
        "id": task_id,
        "cron": cron_expr,
        "prompt": prompt,
        "recurring": recurring,
        "durable": durable,
        "createdAt": now,
    }
    if recurring:
        task["jitter_offset"] = self._compute_jitter(cron_expr)
    with self._lock:
        self.tasks.append(task)
        if durable:
            self._save_durable()
    # ...

# delete() → fully locked
def delete(self, task_id: str) -> str:
    with self._lock:
        before = len(self.tasks)
        self.tasks = [t for t in self.tasks if t["id"] != task_id]
        if len(self.tasks) < before:
            self._save_durable()
            return f"Deleted task {task_id}"
    return f"Task {task_id} not found"

# list_tasks() → snapshot inside lock, iterate outside
def list_tasks(self) -> str:
    with self._lock:
        snapshot = list(self.tasks)
    if not snapshot:
        return "No scheduled tasks."
    lines = []
    for t in snapshot:
        # ... iterate outside lock, avoids holding lock too long

# _check_tasks() → fully locked
def _check_tasks(self, now: "dt"):
    expired = []
    fired_oneshots = []
    with self._lock:
        for task in self.tasks:
            # ... traversal and modification both inside lock
        if expired or fired_oneshots:
            remove_ids = set(expired) | set(fired_oneshots)
            self.tasks = [t for t in self.tasks if t["id"] not in remove_ids]
            # ...
            self._save_durable()  # RLock allows reentrant call

# detect_missed_tasks() → snapshot inside lock, iterate outside
def detect_missed_tasks(self) -> list:
    now = dt.now()
    missed = []
    with self._lock:
        snapshot = list(self.tasks)
    for task in snapshot:
        # ... iterate outside lock
    return missed
```

**RLock Selection Reason**:
- `_check_tasks()` holds lock while calling `_save_durable()`
- `_save_durable()` may indirectly call other lock-protected methods
- RLock allows same thread to reentrantly acquire lock, avoids deadlock

---

#### BUG-17: Data Race in Background Task Result Injection

**Problem Description**:
```python
# Before fix (s14_v3): drain_notifications() called in run_subagent
def run_subagent(prompt: str) -> str:
    # ...
    # Subagent runs in background daemon thread
    # Calling global BG.drain_notifications() steals notifications from main agent's notification queue
```

**Data Race Scenario**:
- Subagent runs in background thread, shares global BG instance with main agent
- When subagent calls `BG.drain_notifications()`, it takes main agent's notifications
- With multiple parallel subagents, notifications may be consumed by wrong thread

**Fix Solution**:
```python
# Fix 1: Remove drain_notifications() call from run_subagent
# Fix 2: Remove background_run and check_background from CHILD_TOOLS
CHILD_TOOLS = [
    {"type": "function", "function": {"name": "read_file", ...}},
    {"type": "function", "function": {"name": "bash", ...}},
    # background_run / check_background intentionally omitted
]
```

**Fix Explanation**:
- Subagent is already background thread, should not nest background tasks
- When subagent needs to run shell commands, use synchronous bash tool instead
- All BG notifications handled uniformly by main agent's agent_loop

---

### Retained Features (Inherited from s13)

| Component | Status | Description |
|------|------|------|
| BackgroundManager | Fully retained (BUG-1 fixed) | Background task lifecycle management (shell commands) |
| NotificationQueue | Fully retained | Priority notification queue (not currently used) |
| TaskManager | Fully retained | Persistent task CRUD (stored in `.tasks/` directory) |
| Three-layer error recovery | Fully retained | max_tokens, prompt_too_long, API errors |
| SystemPromptBuilder | Fully retained (core instructions updated) | 6-layer structured build, main agent core instructions updated background_task |
| MemoryManager | Fully retained | Persistent memory management |
| DreamConsolidator | Fully retained (pending activation) | Automatic memory consolidation |
| HookManager | Fully retained | Hook interception pipeline |
| PermissionManager | Fully retained | Permission management |
| BashSecurityValidator | Fully retained | Bash security validation |
| SkillRegistry | Fully retained | Skill registry |
| Context compaction | Fully retained (threshold adjusted) | micro_compact, compact_history, CONTEXT_LIMIT adjusted to 800000 |
| Transcript saving | Fully retained | write_transcript |
| run_subagent_background() | Fully retained | Asynchronous parallel subagent execution |

**Configuration Parameter Adjustments**:

| Parameter | s13_v2 | s14_cron_scheduler | Adjustment Reason |
|------|--------|-------------------|----------|
| CONTEXT_LIMIT | 100000 chars | 800000 chars | Adapt to 260k token models (max input) |
| PERSIST_THRESHOLD | 60000 chars | 150000 chars | Reduce file persistence frequency |
| PREVIEW_CHARS | 20000 chars | 80000 chars | Increase preview length |
| PLAN_REMINDER_INTERVAL | 5 | 8 | Reduce reminder frequency |
| KEEP_RECENT_TOOL_RESULTS | 5 | 20 | Retain more tool results |

---

## Directory Structure Dependencies

| Directory/File | Purpose | Creation Method | Version |
|-----------|------|----------|------|
| `.tasks/` | Persistent task storage | TaskManager auto-creates | s12 retained |
| `.tasks/task_*.json` | Single task file | TaskManager._save() creates | s12 retained |
| `.runtime-tasks/` | Background task state and logs | BackgroundManager auto-creates | s13 retained |
| `.runtime-tasks/{task_id}.json` | Background task state record | BG._persist_task() creates | s13 retained |
| `.runtime-tasks/{task_id}.log` | Background task output log | BG._execute() creates | s13 retained |
| `.claude/scheduled_tasks.json` | Cron task persistence | CronScheduler._save_durable() creates | s14 new |
| `.claude/cron.lock` | Cron task lock file (unused) | CronLock.acquire() creates | s14 new |
| `logs/` | Session log directory | main function initialization creates | s14 new |
| `logs/session_{timestamp}.log` | Session log file | _Tee class writes | s14 new |
| `skills/` | Skill documentation | Manually created | s11 retained |
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
Session Startup
    │
    ▼
Initialize Components
├── MemoryManager.load_all()
├── TaskManager(TASKS_DIR)
├── BackgroundManager()
├── CronScheduler()
├── HookManager(perms)
└── SystemPromptBuilder
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
    User Input Processing                      Cron Trigger Processing
    - Slash command check                       - Inject <cron-notification>
    - quit/exit check                           - agent_loop(state)
    - Normal dialogue                           - Restore prompt
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
                            │   ├── background_task → run_subagent_background()
                            │   ├── check_background → BG.check()
                            │   ├── cron_create → scheduler.create()
                            │   ├── cron_delete → scheduler.delete()
                            │   ├── cron_list → scheduler.list_tasks()
                            │   └── ...
                            └─ PostToolUse Hook pipeline


Cron Task Scheduling Flow
┌─────────────────────────────────────────────────────────────────┐
│                    CronScheduler Background Thread               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  _check_loop() checks every second                       │   │
│  │      │                                                   │   │
│  │      ▼                                                   │   │
│  │  current_minute != _last_check_minute?                   │   │
│  │      │                                                   │   │
│  │      ▼                                                   │   │
│  │  _check_tasks(now)                                       │   │
│  │      │                                                   │   │
│  │      ├── Traverse self.tasks (inside lock)               │   │
│  │      ├── cron_matches(cron, now)?                        │   │
│  │      │     │                                             │   │
│  │      │     ▼                                             │   │
│  │      ├── scheduler.queue.put(notification)              │   │
│  │      │     │                                             │   │
│  │      │     ▼                                             │   │
│  │      ├── Mark last_fired                                 │   │
│  │      │     │                                             │   │
│  │      │     ▼                                             │   │
│  │      └── Non-recurring tasks → fired_oneshots            │   │
│  │                                                           │   │
│  │  Clean expired/one-shot tasks (>7 days or one-shot fired)│   │
│  │      │                                                   │   │
│  │      ▼                                                   │   │
│  │  _save_durable() persist                                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│            │                                                   │
│            ▼                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  cron_watcher thread (every second)                      │   │
│  │      │                                                   │   │
│  │      ▼                                                   │   │
│  │  notes = scheduler.drain_notifications()                │   │
│  │      │                                                   │   │
│  │      ▼                                                   │   │
│  │  for note in notes:                                      │   │
│  │      event_queue.put(("cron", note))                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│            │                                                   │
│            ▼                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Main loop event_queue.get()                             │   │
│  │      │                                                   │   │
│  │      ▼                                                   │   │
│  │  event_type == "cron"                                    │   │
│  │      │                                                   │   │
│  │      ▼                                                   │   │
│  │  history.append({                                        │   │
│  │      "role": "user",                                     │   │
│  │      "content": "<cron-notification>...</cron-notification>" │
│  │  })                                                      │   │
│  │      │                                                   │   │
│  │      ▼                                                   │   │
│  │  agent_loop(state)  # Autonomous execution, no user input │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘


Dual Event Source Sequence Diagram
Main Loop                      input_reader Thread          cron_watcher Thread        CronScheduler Thread
  │                              │                        │                        │
  │  event_queue.get() blocking ◄┼────────────────────────┼────────────────────────┤
  │                              │                        │                        │
  │                              ├─ User input "hello"    │                        │
  │                              │                        │                        │
  │                              ├─ event_queue.put(      │                        │
  │                              │   ("user", "hello")    │                        │
  │                              │  )                    │                        │
  │                              │                        │                        │
  │◄─────────────────────────────┴────────────────────────┼────────────────────────┤
  │  Wake: ("user", "hello")     │                        │                        │
  │                              │                        │                        │
  │  Process user input...       │                        │                        │
  │  agent_loop(state)           │                        │                        │
  │                              │                        │                        │
  │                              │                        │                        │
  │  event_queue.get() blocking ◄┼────────────────────────┼────────────────────────┤
  │                              │                        │                        │
  │                              │                        │ Check every second     │
  │                              │                        │                        │
  │                              │                        ├─ scheduler detects trigger │
  │                              │                        │                        │
  │                              │                        │  scheduler.queue.put() │
  │                              │                        │                        │
  │                              │                        │                        │
  │                              │                        ├─ drain_notifications() │
  │                              │                        │                        │
  │                              │                        ├─ event_queue.put(      │
  │                              │                        │   ("cron", note)       │
  │                              │                        │  )                     │
  │                              │                        │                        │
  │◄─────────────────────────────┴────────────────────────┼────────────────────────┤
  │  Wake: ("cron", note)       │                        │                        │
  │                              │                        │                        │
  │  Inject <cron-notification> │                        │                        │
  │  agent_loop(state)  # Autonomous execution            │                        │
  │                              │                        │                        │
```

---

## Design Point Summary

### Core Design Mechanism 1: Cron Task Scheduler

| Feature | Implementation |
|------|----------|
| Cron expression parsing | 5-field parsing, supports */N/N-M/N,M syntax |
| Trigger checking | Background thread checks every second, avoids repeated triggers within same minute |
| Notification queue | Queue thread-safe, cron_watcher uniformly injects into event queue |
| Persistence | durable=True writes to .claude/scheduled_tasks.json |
| Auto-expiry | Recurring tasks auto-delete after 7 days |
| One-shot tasks | Auto-delete after trigger when recurring=False |
| Jitter offset | Avoids concentrated triggers on the hour, 0/30 minute tasks randomly offset 1-4 minutes |
| Thread safety | RLock protects all self.tasks access |

### Core Design Mechanism 2: Dual Event Source Architecture

| Event Source | Thread | Injection Method | Processing Flow |
|--------|------|----------|----------|
| User input | input_reader | event_queue.put(("user", query)) | Slash command check → Normal dialogue |
| Cron trigger | cron_watcher | event_queue.put(("cron", note)) | Inject <cron-notification> → agent_loop |

**Event Queue Advantages**:
- Unified scheduling: All events processed through single queue
- Decoupled design: Event producers and consumers decoupled
- Extensible: Easy to add new event sources

### Core Design Mechanism 3: Session Logging

| Feature | Implementation |
|------|----------|
| Dual-path output | Terminal outputs as-is (preserves ANSI), file removes ANSI codes |
| Readability processing | Remove readline markers (\x01/\x02) and standalone carriage returns |
| Terminal compatibility | fileno() proxies to original terminal fd, ensures readline/termios work correctly |
| Error handling | Output error message to terminal on write failure, doesn't interrupt program |

### Core Design Mechanism 4: Thread Safety Fixes

| BUG | Problem | Fix Solution |
|-----|------|----------|
| BUG-1 | BackgroundManager._execute writes self.tasks without lock | 4 field assignments and notification enqueue merged into with self._lock block, persistence moved outside lock |
| BUG-2 | CronScheduler accesses self.tasks without lock | RLock protects all methods, _check_tasks can reentrantly call _save_durable while holding lock |
| BUG-17 | Subagent steals main agent notifications | Remove drain_notifications() from run_subagent, remove background_run/check_background from CHILD_TOOLS |

### Core Design Mechanism 5: Toolset Layering

| Tool Category | Main Agent |