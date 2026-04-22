# s14_cron_scheduler: 定时任务调度系统（双事件源架构）

## 概述

s14 在 s13 后台任务系统的基础上进行了**定时任务调度能力增强**。核心改动是新增 CronScheduler 定时任务调度器，支持 5 字段 cron 表达式，并升级事件驱动架构从单事件源到双事件源。

### 核心改进

1. **CronScheduler 类** - 定时任务调度器，支持 5 字段 cron 表达式（min hour dom month dow）
2. **cron_create/delete/list 工具** - 主代理管理定时任务的接口
3. **cron_watcher 线程** - 专职监听 cron 通知并注入事件队列
4. **事件驱动架构升级** - 从单事件源（用户输入）到双事件源（用户输入 + cron 定时任务）
5. **_Tee 类** - 会话日志功能，同时输出到终端和文件
6. **线程安全修复** - BUG-1（BackgroundManager 写锁）、BUG-2（CronScheduler RLock）、BUG-17（子 agent 通知窃取）

### 代码文件路径

- **源代码**：v1_task_manager/chapter_14/s14_cron_scheduler.py
- **参考文档**：v1_task_manager/chapter_13/s13_v2_backtask_文档.md
- **参考代码**：v1_task_manager/chapter_13/s13_v2_backtask.py
- **定时任务持久化文件**：`.claude/scheduled_tasks.json`
- **会话日志目录**：`logs/`
- **后台任务目录**：`.runtime-tasks/`
- **任务目录**：`.tasks/`
- **记忆目录**：`.memory/`
- **技能目录**：`skills/`
- **钩子配置**：`.hooks.json`
- **Claude 信任标记**：`.claude/.claude_trusted`

---

## 与 s13 的对比（变更总览）

| 组件 | s13_v2 | s14_cron_scheduler | 变化说明 |
|------|--------|-------------------|----------|
| 定时任务调度 | 无 | CronScheduler | 新增 5 字段 cron 表达式支持 |
| 主代理工具集 | background_task + check_background | + cron_create/delete/list | 新增定时任务管理工具 |
| 事件源 | 单事件源（用户输入） | 双事件源（用户输入 + cron） | 新增 cron_watcher 线程 |
| 事件处理 | agent_loop 直接处理用户输入 | 统一事件队列驱动 | input_reader + cron_watcher 共同注入 |
| 会话日志 | 无 | _Tee 类 | 新增同时输出到终端和文件 |
| BackgroundManager 线程安全 | 无锁写 self.tasks | _execute 加锁写 + 锁外持久化 | 修复 BUG-1 数据竞态 |
| CronScheduler 线程安全 | 无锁访问 self.tasks | RLock 保护所有访问 | 修复 BUG-2 数据竞态 |
| 子 agent 工具集 | background_run + check_background | 移除后台工具 | 修复 BUG-17 通知窃取 |
| 上下文限制 | 100000 chars | 800000 chars | 适配 260k token 模型 |
| 持久化阈值 | 60000 chars | 150000 chars | 减少文件持久化频率 |

---

## s14 新增内容详解（按代码执行顺序）

### CronScheduler 类（定时任务调度器，5 字段 cron 表达式）

```python
class CronScheduler:
    """
    管理定时任务并在后台线程中检查触发条件。
    触发时将 prompt 推入通知队列，agent_loop 在每轮 LLM 调用前 drain。
    """
    def __init__(self):
        self.tasks = []
        self.queue = Queue()
        self._lock = threading.RLock()  # RLock：允许同线程重入
        self._stop_event = threading.Event()
        self._thread = None
        self._last_check_minute = -1
```

**核心属性**：

| 属性 | 类型 | 用途 |
|------|------|------|
| tasks | list | 定时任务列表，每项包含 id/cron/prompt/recurring/durable 等字段 |
| queue | Queue | 线程安全的通知队列，触发的任务 prompt 推入此队列 |
| _lock | RLock | 可重入锁，保护 tasks 列表的并发访问 |
| _stop_event | Event | 停止信号，用于优雅关闭后台线程 |
| _thread | Thread | 后台检查线程，每秒检查一次任务是否触发 |
| _last_check_minute | int | 上次检查的分钟数，避免同一分钟内重复触发 |

**核心方法**：

| 方法 | 功能 | 返回值 | 线程安全 |
|------|------|--------|----------|
| `start()` | 加载持久任务并启动后台检查线程 | 无 | 是（锁内读取 count） |
| `stop()` | 设置停止信号并等待线程退出 | 无 | 是 |
| `create()` | 创建定时任务 | task_id 字符串 | 是（锁内 append + 持久化） |
| `delete()` | 删除定时任务 | 删除结果字符串 | 是（锁内过滤 + 持久化） |
| `list_tasks()` | 列出所有定时任务 | 格式化字符串 | 是（锁内取快照） |
| `drain_notifications()` | 返回并清除所有触发通知 | list[str] | 是（Queue 线程安全） |
| `_check_loop()` | 后台线程主循环，每秒检查一次 | 无（线程目标函数） | 是 |
| `_check_tasks()` | 检查当前分钟是否有任务触发 | 无 | 是（锁内遍历 + 更新） |
| `_load_durable()` | 从磁盘加载持久化任务 | 无 | 是（启动时调用） |
| `_save_durable()` | 保存持久化任务到磁盘 | 无 | 是（锁内调用） |
| `detect_missed_tasks()` | 检测会话关闭期间错过的触发 | list[dict] | 是（锁内取快照） |

**任务结构**：
```python
task = {
    "id": "abc12345",           # 8 字符 UUID
    "cron": "*/5 * * * *",      # 5 字段 cron 表达式
    "prompt": "执行的任务提示词",
    "recurring": True,          # 是否重复执行
    "durable": True,            # 是否持久化到磁盘
    "createdAt": 1234567890.123, # 创建时间戳
    "jitter_offset": 2,         # jitter 偏移（仅 recurring 任务）
    "last_fired": 1234567920.456, # 上次触发时间戳
}
```

---

### 5 字段 Cron 表达式格式和用法

**字段定义**：
```
+-------+-------+-------+-------+-------+
| min   | hour  | dom   | month | dow   |
| 0-59  | 0-23  | 1-31  | 1-23  | 0-6   |
+-------+-------+-------+-------+-------+
  分钟    小时    日期    月份    星期
```

**支持的语法**：

| 语法 | 示例 | 含义 |
|------|------|------|
| `*` | `* * * * *` | 每（每分钟/每小时/每天...） |
| `,` | `0,30 * * * *` | 枚举值（0 点和 30 点） |
| `-` | `0 9-17 * * 1-5` | 范围（9 点到 17 点，周一到周五） |
| `/` | `*/15 * * * *` | 步长（每 15 分钟） |
| 组合 | `0,30 9-17 * * 1-5` | 组合使用（工作日 9-17 点的 0 分和 30 分） |

**cron_matches() 函数实现**：
```python
def cron_matches(expr: str, now: "dt") -> bool:
    """
    检查 5 字段 cron 表达式是否与指定时间匹配。
    字段：分 时 日 月 周（0=周日）
    支持 * / N N-M N,M 语法，无外部依赖。
    """
    fields = expr.strip().split()
    if len(fields) != 5:
        return False
    cron_dow = (now.weekday() + 1) % 7  # Python 0=周一 → cron 0=周日
    values = [now.minute, now.hour, now.day, now.month, cron_dow]
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    for field, value, (lo, hi) in zip(fields, values, ranges):
        if not _field_matches(field, value, lo, hi):
            return False
    return True
```

**星期转换说明**：
- Python 的 `weekday()`：0=周一，6=周日
- Cron 标准：0=周日，6=周六
- 转换公式：`cron_dow = (now.weekday() + 1) % 7`

**cron 表达式示例**：

| 表达式 | 含义 | 使用场景 |
|--------|------|----------|
| `*/5 * * * *` | 每 5 分钟 | 高频监控任务 |
| `0 * * * *` | 每小时整点 | 每小时数据同步 |
| `0 9 * * *` | 每天 9:00 | 每日晨报生成 |
| `30 14 * * *` | 每天 14:30 | 每日下午任务 |
| `0 9 * * 1` | 周一 9:00 | 每周例会提醒 |
| `0 9 * * 1-5` | 工作日 9:00 | 工作日晨报 |
| `0,30 9-17 * * 1-5` | 工作日 9-17 点的 0 分和 30 分 | 工作时段每 30 分钟检查 |
| `0 0 1 * *` | 每月 1 日 0:00 | 月度报告生成 |

---

### cron_create/delete/list 工具（主代理管理定时任务）

**工具定义**：

```python
# [s14 新增] cron 定时任务工具
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

**工具处理器**：
```python
TOOL_HANDLERS = {
    # ... 其他工具
    "cron_create": lambda **kw: scheduler.create(
        kw["cron"], kw["prompt"],
        kw.get("recurring", True), kw.get("durable", False)
    ),
    "cron_delete": lambda **kw: scheduler.delete(kw["id"]),
    "cron_list":   lambda **kw: scheduler.list_tasks(),
}
```

**使用示例**：

```python
# 创建每 5 分钟执行的重复任务
cron_create(cron="*/5 * * * *", prompt="检查后台任务状态", recurring=True, durable=False)
# 返回：Created task abc12345 (recurring, session-only): cron=*/5 * * * *

# 创建每天 9:00 执行的持久化任务
cron_create(cron="0 9 * * *", prompt="生成每日晨报", recurring=True, durable=True)
# 返回：Created task def67890 (recurring, durable): cron=0 9 * * *

# 创建一次性任务
cron_create(cron="30 14 * * *", prompt="执行下午检查", recurring=False, durable=False)
# 返回：Created task ghi11111 (one-shot, session-only): cron=30 14 * * *

# 列出所有定时任务
cron_list()
# 返回：
#   abc12345  */5 * * * *  [recurring/session] (0.5h old): 检查后台任务状态
#   def67890  0 9 * * *  [recurring/durable] (1.2h old): 生成每日晨报

# 删除定时任务
cron_delete(id="abc12345")
# 返回：Deleted task abc12345
```

---

### cron_watcher 线程（专职监听 cron 通知并注入事件队列）

**实现代码**：
```python
def cron_watcher(event_queue: Queue, stop_event: threading.Event) -> None:
    """
    [s14_v2 新增] 专职监听 scheduler.queue 的后台线程。
    每秒 drain 一次，将触发的 cron 通知以 ("cron", note) 放入 event_queue。
    stop_event 置位后退出。
    由于 agent_loop 内部已不再 drain scheduler.queue，
    所有 cron 通知都经由此线程 → event_queue → 主循环统一处理，无竞争。
    """
    while not stop_event.is_set():
        notes = scheduler.drain_notifications()
        for note in notes:
            print(f"\n[Cron notification] {note[:100]}")
            event_queue.put(("cron", note))
        stop_event.wait(timeout=1)
```

**工作机制**：

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1 | 每秒唤醒一次 | `stop_event.wait(timeout=1)` |
| 2 | drain scheduler.queue | 获取所有触发的 cron 通知 |
| 3 | 打印通知到终端 | 用户可见的触发日志 |
| 4 | 注入事件队列 | `event_queue.put(("cron", note))` |
| 5 | 主循环处理 | 从 event_queue 获取并注入历史 |

**与 s13 的对比**：

| 特性 | s13_v2 | s14_cron_scheduler |
|------|--------|-------------------|
| 事件源 | 仅用户输入（input_reader） | 用户输入 + cron_watcher |
| 通知处理 | agent_loop 内 drain BG 通知 | cron_watcher 统一注入事件队列 |
| 事件队列 | 无 | Queue 统一调度 |
| 阻塞方式 | input() 阻塞 | event_queue.get() 阻塞 |

**事件注入流程**：
```
CronScheduler 检测到触发
        │
        ▼
scheduler.queue.put(notification)
        │
        ▼
cron_watcher 每秒 drain
        │
        ▼
event_queue.put(("cron", note))
        │
        ▼
主循环 event_queue.get() 唤醒
        │
        ▼
history.append(<cron-notification>...)
        │
        ▼
agent_loop(state, compact_state)
```

---

### 事件驱动架构升级（从单事件源到双事件源）

**s13 单事件源架构**：
```
用户输入 ──► input() 阻塞 ──► agent_loop ──► 工具执行 ──► 循环
```

**s14 双事件源架构**：
```
                    ┌─────────────────────────────────────┐
                    │           事件队列 (Queue)          │
                    │  ┌───────────┐  ┌───────────────┐  │
用户输入 ──► input_reader ──►│ ("user", query) │  │               │
                    │  └───────────┘  └───────────────┘  │
                    │                                     │
cron 触发 ──► cron_watcher ──►│ ("cron", note)  │  │               │
                    │  └───────────┘  └───────────────┘  │
                    └─────────────────┬───────────────────┘
                                      │
                                      ▼
                            event_queue.get() 阻塞
                                      │
                                      ▼
                              根据 event_type 分发
                            ┌─────────┴─────────┐
                            │                   │
                      event_type="user"   event_type="cron"
                            │                   │
                            ▼                   ▼
                      正常对话流程      注入<cron-notification>
                            │                   │
                            └─────────┬─────────┘
                                      │
                                      ▼
                                agent_loop
```

**主循环实现**：
```python
while True:
    event_type, content = _event_queue.get()  # 任意事件到来即唤醒

    # ── quit ────────────────────────────────────────────────────
    if event_type == "quit":
        _stop_cron_watcher.set()
        scheduler.stop()
        break

    # ── cron 触发：无需用户输入，直接注入历史并运行 agent_loop ──
    if event_type == "cron":
        print()
        history.append({
            "role": "user",
            "content": f"<cron-notification>\n{content}\n</cron-notification>",
        })
        state = LoopState(messages=history)
        agent_loop(state, compact_state)
        history = state.messages
        # ... 处理回复 ...
        _input_ready.set()   # 恢复提示符
        continue

    # ── user 输入 ────────────────────────────────────────────────
    query = content
    # ... 处理用户输入（斜杠命令、正常对话等）...
```

**双事件源的优势**：

| 特性 | 说明 |
|------|------|
| 自主触发 | cron 任务触发无需用户输入，系统自动执行 |
| 统一调度 | 所有事件通过单一队列调度，避免竞争 |
| 解耦设计 | input_reader 和 cron_watcher 独立运行，互不干扰 |
| 可扩展 | 可轻松添加新的事件源（如 webhook、文件监控等） |

---

### _Tee 类（会话日志功能）

**实现代码**：
```python
class _Tee:
    """
    代理 sys.stdout / sys.stderr：
    - 终端侧：原样输出（保留 ANSI 颜色）
    - 文件侧：去除 ANSI 转义码、readline 标记（\x01/\x02）和单独的 \r，输出可读文本
    fileno() 代理到原始终端 fd，保证 readline / termios 正常工作。
    """
    _ANSI_RE = re.compile(r'\x1b\[[0-9;]*[mKJHABCDEFGfrsulh]|\x01|\x02')

    def __init__(self, terminal, logfile):
        self._terminal = terminal
        self._logfile  = logfile

    def write(self, data: str):
        self._terminal.write(data)
        clean = self._ANSI_RE.sub('', data)
        # 将单独的 \r（不跟 \n）转成空串，避免日志里行被覆盖
        clean = re.sub(r'\r(?!\n)', '', clean)
        if clean:
            try:
                self._logfile.write(clean)
            except Exception as e:
                self._terminal.write(f"\n[_Tee] 日志写入失败，本次丢弃：{e}\n")

    def flush(self):
        self._terminal.flush()
        try:
            self._logfile.flush()
        except Exception as e:
            self._terminal.write(f"\n[_Tee] 日志 flush 失败，本次丢弃：{e}\n")

    def isatty(self):
        return self._terminal.isatty()

    def fileno(self):
        return self._terminal.fileno()
```

**核心机制**：

| 方法 | 功能 | 说明 |
|------|------|------|
| `__init__()` | 保存终端和日志文件引用 | 代理对象初始化 |
| `write()` | 双路写入 | 终端原样输出，文件去除 ANSI 码 |
| `flush()` | 双路刷新 | 保证日志及时写入磁盘 |
| `isatty()` | 代理终端检查 | 保持终端特性检测 |
| `fileno()` | 代理文件描述符 | 保证 readline/termios 正常工作 |

**日志文件处理**：
- **目录**：`logs/`
- **命名**：`session_{timestamp}.log`
- **内容**：去除 ANSI 转义码、readline 标记、单独的回车符
- **编码**：UTF-8

**初始化代码**：
```python
_log_dir = WORKDIR / "logs"
_log_dir.mkdir(exist_ok=True)
_log_path = _log_dir / f"session_{int(time.time())}.log"
_log_file = open(_log_path, "w", buffering=1, encoding="utf-8")
sys.stdout = _Tee(sys.__stdout__, _log_file)
sys.stderr = _Tee(sys.__stderr__, _log_file)
print(f"[Session log: {_log_path}]")
```

**日志内容示例**：
```
[Session log: logs/session_1713678901.log]
[Cron scheduler running. Background checks every second.]
[5 memories loaded into context]
[s14_v2] Event-driven loop started. Cron tasks will fire without user input.

[最终回复] 已为您创建定时任务 abc12345，每 5 分钟执行一次。
```

---

### 线程安全修复（BUG-1、BUG-2、BUG-17 数据竞态问题）

#### BUG-1：BackgroundManager._execute 写 self.tasks 加锁

**问题描述**：
```python
# 修复前（s13）：4 个字段赋值无锁写
self.tasks[task_id]["status"] = status
self.tasks[task_id]["result"] = final_output
self.tasks[task_id]["finished_at"] = time.time()
self.tasks[task_id]["result_preview"] = preview
self._notification_queue.append({...})
self._persist_task(task_id)
```

**数据竞态场景**：
- 后台线程 `_execute()` 写 self.tasks[task_id] 的 4 个字段
- 主线程 `check()` 或 `detect_stalled()` 同时读 self.tasks[task_id]
- 可能读到部分更新的中间状态

**修复方案**：
```python
# 修复后（s14）：4 个字段赋值和通知入队合并进同一个 with self._lock: 块
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
self._persist_task(task_id)  # 锁外执行文件 I/O，避免持锁期间阻塞
```

**修复要点**：
- 4 个字段赋值和通知入队在同一个锁内完成
- `_persist_task()` 移到锁外，避免持锁期间阻塞其他线程

---

#### BUG-2：CronScheduler 全部 self.tasks 访问加 RLock 保护

**问题描述**：
```python
# 修复前（s14_v3）：_check_tasks 后台线程和主线程的 create/delete/list_tasks
# 并发读写 self.tasks 列表，没有任何同步
```

**数据竞态场景**：
- 后台线程 `_check_tasks()` 遍历 self.tasks 并修改（删除过期任务）
- 主线程 `create()` 或 `delete()` 同时修改 self.tasks 列表
- 可能导致 `RuntimeError: list changed size during iteration` 或数据丢失

**修复方案**：
```python
class CronScheduler:
    def __init__(self):
        self.tasks = []
        self.queue = Queue()
        self._lock = threading.RLock()  # RLock：允许同线程重入
        # ...
```

**加锁方法**：
```python
# start() → count = len(self.tasks) 加锁
def start(self):
    self._load_durable()
    self._thread = threading.Thread(target=self._check_loop, daemon=True)
    self._thread.start()
    with self._lock:
        count = len(self.tasks)
    if count:
        print(f"[Cron] 已加载 {count} 个定时任务")

# create() → append + _save_durable 加锁
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

# delete() → 整体加锁
def delete(self, task_id: str) -> str:
    with self._lock:
        before = len(self.tasks)
        self.tasks = [t for t in self.tasks if t["id"] != task_id]
        if len(self.tasks) < before:
            self._save_durable()
            return f"Deleted task {task_id}"
    return f"Task {task_id} not found"

# list_tasks() → 锁内取快照，锁外迭代
def list_tasks(self) -> str:
    with self._lock:
        snapshot = list(self.tasks)
    if not snapshot:
        return "No scheduled tasks."
    lines = []
    for t in snapshot:
        # ... 锁外迭代，避免持锁时间过长

# _check_tasks() → 整体加锁
def _check_tasks(self, now: "dt"):
    expired = []
    fired_oneshots = []
    with self._lock:
        for task in self.tasks:
            # ... 遍历和修改都在锁内
        if expired or fired_oneshots:
            remove_ids = set(expired) | set(fired_oneshots)
            self.tasks = [t for t in self.tasks if t["id"] not in remove_ids]
            # ...
            self._save_durable()  # RLock 允许重入调用

# detect_missed_tasks() → 锁内取快照，锁外迭代
def detect_missed_tasks(self) -> list:
    now = dt.now()
    missed = []
    with self._lock:
        snapshot = list(self.tasks)
    for task in snapshot:
        # ... 锁外迭代
    return missed
```

**RLock 选择原因**：
- `_check_tasks()` 持锁时调用 `_save_durable()`
- `_save_durable()` 可能间接调用其他加锁方法
- RLock 允许同一线程重入获取锁，避免死锁

---

#### BUG-17：背景任务结果注入的数据竞态

**问题描述**：
```python
# 修复前（s14_v3）：run_subagent 里调用 drain_notifications()
def run_subagent(prompt: str) -> str:
    # ...
    # 子 agent 运行在后台 daemon 线程
    # 调用全局 BG.drain_notifications() 会从主 agent 的通知队列中偷走通知
```

**数据竞态场景**：
- 子 agent 运行在后台线程，与主 agent 共享全局 BG 实例
- 子 agent 调用 `BG.drain_notifications()` 时，会取走主 agent 的通知
- 多并行子 agent 时，通知可能被错误的线程消费

**修复方案**：
```python
# 修复 1：移除 run_subagent 里的 drain_notifications() 调用
# 修复 2：从 CHILD_TOOLS 中移除 background_run 和 check_background
CHILD_TOOLS = [
    {"type": "function", "function": {"name": "read_file", ...}},
    {"type": "function", "function": {"name": "bash", ...}},
    # background_run / check_background intentionally omitted
]
```

**修复说明**：
- 子 agent 已经是后台线程，不应再嵌套后台任务
- 子 agent 需要运行 shell 命令时改用同步 bash 工具
- 所有 BG 通知由主 agent 的 agent_loop 统一处理

---

### 保留功能（从 s13 继承）

| 组件 | 状态 | 说明 |
|------|------|------|
| BackgroundManager | 完整保留（修复 BUG-1） | 后台任务生命周期管理（shell 命令） |
| NotificationQueue | 完整保留 | 优先级通知队列（当前未使用） |
| TaskManager | 完整保留 | 持久化任务 CRUD（存储在 `.tasks/` 目录） |
| 三层错误恢复 | 完整保留 | max_tokens、prompt_too_long、API 错误 |
| SystemPromptBuilder | 完整保留（核心指令更新） | 6 层结构化构建，主代理核心指令更新 background_task |
| MemoryManager | 完整保留 | 持久化记忆管理 |
| DreamConsolidator | 完整保留（待激活） | 记忆自动整合 |
| HookManager | 完整保留 | 钩子拦截管线 |
| PermissionManager | 完整保留 | 权限管理 |
| BashSecurityValidator | 完整保留 | Bash 安全验证 |
| SkillRegistry | 完整保留 | 技能注册表 |
| 上下文压缩 | 完整保留（阈值调整） | micro_compact、compact_history，CONTEXT_LIMIT 调整为 800000 |
| 转录保存 | 完整保留 | write_transcript |
| run_subagent_background() | 完整保留 | 异步并行子 agent 执行 |

**配置参数调整**：

| 参数 | s13_v2 | s14_cron_scheduler | 调整原因 |
|------|--------|-------------------|----------|
| CONTEXT_LIMIT | 100000 chars | 800000 chars | 适配 260k token 模型（最大输入） |
| PERSIST_THRESHOLD | 60000 chars | 150000 chars | 减少文件持久化频率 |
| PREVIEW_CHARS | 20000 chars | 80000 chars | 增加预览长度 |
| PLAN_REMINDER_INTERVAL | 5 | 8 | 减少提醒频率 |
| KEEP_RECENT_TOOL_RESULTS | 5 | 20 | 保留更多工具结果 |

---

## 目录结构依赖

| 目录/文件 | 用途 | 创建方式 | 版本 |
|-----------|------|----------|------|
| `.tasks/` | 持久化任务存储 | TaskManager 自动创建 | s12 保留 |
| `.tasks/task_*.json` | 单个任务文件 | TaskManager._save() 创建 | s12 保留 |
| `.runtime-tasks/` | 后台任务状态和日志 | BackgroundManager 自动创建 | s13 保留 |
| `.runtime-tasks/{task_id}.json` | 后台任务状态记录 | BG._persist_task() 创建 | s13 保留 |
| `.runtime-tasks/{task_id}.log` | 后台任务输出日志 | BG._execute() 创建 | s13 保留 |
| `.claude/scheduled_tasks.json` | 定时任务持久化 | CronScheduler._save_durable() 创建 | s14 新增 |
| `.claude/cron.lock` | cron 任务锁文件（未使用） | CronLock.acquire() 创建 | s14 新增 |
| `logs/` | 会话日志目录 | main 函数初始化创建 | s14 新增 |
| `logs/session_{timestamp}.log` | 会话日志文件 | _Tee 类写入 | s14 新增 |
| `skills/` | 技能文档 | 手动创建 | s11 保留 |
| `.memory/` | 持久化记忆 | MemoryManager 自动创建 | s09 保留 |
| `.memory/MEMORY.md` | 记忆索引 | _rebuild_index() 重建 | s09 保留 |
| `.memory/*.md` | 单个记忆文件 | save_memory() 创建 | s09 保留 |
| `.transcripts/` | 会话转录 | write_transcript() 创建 | s11 保留 |
| `.task_outputs/tool-results/` | 大型工具输出 | persist_large_output() 创建 | s12 保留 |
| `.hooks.json` | 钩子配置 | 手动创建 | s08 保留 |
| `.claude/.claude_trusted` | 工作区信任标记 | 手动创建 | s08 保留 |

---

## 完整框架流程图

```
会话启动
    │
    ▼
初始化组件
├── MemoryManager.load_all()
├── TaskManager(TASKS_DIR)
├── BackgroundManager()
├── CronScheduler()
├── HookManager(perms)
└── SystemPromptBuilder
    │
    ▼
启动后台线程
├── scheduler.start()
│   ├── _load_durable()  # 加载 .claude/scheduled_tasks.json
│   └── _check_loop 线程  # 每秒检查任务触发
├── cron_watcher 线程  # 监听 scheduler.queue → event_queue
└── input_reader 线程  # 监听用户输入 → event_queue
    │
    ▼
事件驱动主循环
    │
    ┌─────────────────────────────────────────────────────────────┐
    │                    event_queue.get() 阻塞                    │
    └──────────────────────────┬──────────────────────────────────┘
                               │
         ┌─────────────────────┴─────────────────────┐
         │                                           │
   ("user", query)                             ("cron", note)
         │                                           │
         ▼                                           ▼
    用户输入处理                              cron 触发处理
    - 斜杠命令检查                            - 注入<cron-notification>
    - quit/exit 检查                          - agent_loop(state)
    - 正常对话                                - 恢复提示符
         │                                           │
         └─────────────────────┬─────────────────────┘
                               │
                               ▼
                        agent_loop(state, compact_state)
                        │
                        ├─ 更新系统提示 (main_build)
                        ├─ micro_compact()
                        ├─ estimate_context_size() > CONTEXT_LIMIT?
                        │     └── compact_history()
                        │
                        ▼
                    run_one_turn()
                        │
                        ├─ Layer 1: LLM 调用
                        ├─ Layer 2: finish_reason 检查
                        └─ Layer 3: 工具执行
                                │
                                ▼
                        execute_tool_calls()
                            │
                            ├─ PreToolUse Hook 管线
                            ├─ 工具执行
                            │   ├── background_task → run_subagent_background()
                            │   ├── check_background → BG.check()
                            │   ├── cron_create → scheduler.create()
                            │   ├── cron_delete → scheduler.delete()
                            │   ├── cron_list → scheduler.list_tasks()
                            │   └── ...
                            └─ PostToolUse Hook 管线


定时任务调度流程
┌─────────────────────────────────────────────────────────────────┐
│                    CronScheduler 后台线程                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  _check_loop() 每秒检查一次                                │   │
│  │      │                                                   │   │
│  │      ▼                                                   │   │
│  │  current_minute != _last_check_minute?                   │   │
│  │      │                                                   │   │
│  │      ▼                                                   │   │
│  │  _check_tasks(now)                                       │   │
│  │      │                                                   │   │
│  │      ├── 遍历 self.tasks（锁内）                          │   │
│  │      ├── cron_matches(cron, now)?                        │   │
│  │      │     │                                             │   │
│  │      │     ▼                                             │   │
│  │      ├── scheduler.queue.put(notification)              │   │
│  │      │     │                                             │   │
│  │      │     ▼                                             │   │
│  │      ├── 标记 last_fired                                 │   │
│  │      │     │                                             │   │
│  │      │     ▼                                             │   │
│  │      └── 非 recurring 任务 → fired_oneshots              │   │
│  │                                                           │   │
│  │  清理过期/一次性任务（>7 天或 one-shot fired）             │   │
│  │      │                                                   │   │
│  │      ▼                                                   │   │
│  │  _save_durable() 持久化                                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│            │                                                   │
│            ▼                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  cron_watcher 线程（每秒）                                 │   │
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
│  │  主循环 event_queue.get()                                │   │
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
│  │  agent_loop(state)  # 自主执行，无需用户输入               │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘


双事件源时序图
主循环                      input_reader 线程          cron_watcher 线程        CronScheduler 线程
  │                              │                        │                        │
  │  event_queue.get() 阻塞 ◄────┼────────────────────────┼────────────────────────┤
  │                              │                        │                        │
  │                              ├─ 用户输入 "hello"      │                        │
  │                              │                        │                        │
  │                              ├─ event_queue.put(      │                        │
  │                              │   ("user", "hello")    │                        │
  │                              │  )                    │                        │
  │                              │                        │                        │
  │◄─────────────────────────────┴────────────────────────┼────────────────────────┤
  │  唤醒：("user", "hello")      │                        │                        │
  │                              │                        │                        │
  │  处理用户输入...              │                        │                        │
  │  agent_loop(state)           │                        │                        │
  │                              │                        │                        │
  │                              │                        │                        │
  │  event_queue.get() 阻塞 ◄────┼────────────────────────┼────────────────────────┤
  │                              │                        │                        │
  │                              │                        │ 每秒检查               │
  │                              │                        │                        │
  │                              │                        ├─ scheduler 检测到触发  │
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
  │  唤醒：("cron", note)        │                        │                        │
  │                              │                        │                        │
  │  注入<cron-notification>     │                        │                        │
  │  agent_loop(state)  # 自主执行                         │                        │
  │                              │                        │                        │
```

---

## 设计点总结

### 核心设计机制 1：定时任务调度器

| 特性 | 实现方式 |
|------|----------|
| cron 表达式解析 | 5 字段解析，支持 */N/N-M/N,M 语法 |
| 触发检查 | 后台线程每秒检查，避免同一分钟重复触发 |
| 通知队列 | Queue 线程安全，cron_watcher 统一注入事件队列 |
| 持久化 | durable=True 时写入 .claude/scheduled_tasks.json |
| 自动过期 | recurring 任务超过 7 天自动删除 |
| 一次性任务 | recurring=False 触发后自动删除 |
| Jitter 偏移 | 避免整点触发集中，0/30 分钟的任务随机偏移 1-4 分钟 |
| 线程安全 | RLock 保护所有 self.tasks 访问 |

### 核心设计机制 2：双事件源架构

| 事件源 | 线程 | 注入方式 | 处理流程 |
|--------|------|----------|----------|
| 用户输入 | input_reader | event_queue.put(("user", query)) | 斜杠命令检查 → 正常对话 |
| cron 触发 | cron_watcher | event_queue.put(("cron", note)) | 注入<cron-notification> → agent_loop |

**事件队列优势**：
- 统一调度：所有事件通过单一队列处理
- 解耦设计：事件生产者和消费者解耦
- 可扩展：可轻松添加新事件源

### 核心设计机制 3：会话日志

| 特性 | 实现方式 |
|------|----------|
| 双路输出 | 终端原样输出（保留 ANSI），文件去除 ANSI 码 |
| 可读性处理 | 去除 readline 标记（\x01/\x02）和单独的回车符 |
| 终端兼容 | fileno() 代理到原始终端 fd，保证 readline/termios 正常工作 |
| 错误处理 | 写入失败时终端输出错误信息，不中断程序 |

### 核心设计机制 4：线程安全修复

| BUG | 问题 | 修复方案 |
|-----|------|----------|
| BUG-1 | BackgroundManager._execute 无锁写 self.tasks | 4 字段赋值和通知入队合并进 with self._lock 块，持久化移到锁外 |
| BUG-2 | CronScheduler 无锁访问 self.tasks | RLock 保护所有方法，_check_tasks 持锁时可重入调用_save_durable |
| BUG-17 | 子 agent 窃取主 agent 通知 | 移除 run_subagent 中的 drain_notifications()，从 CHILD_TOOLS 移除 background_run/check_background |

### 核心设计机制 5：工具集分层

| 工具类别 | 主代理 | 子代理 |
|----------|--------|--------|
| 任务管理 | ✓ (task_*) | ✗ |
| 后台任务 | ✓ (background_task, check_background) | ✗（移除，修复 BUG-17） |
| 定时任务 | ✓ (cron_create, cron_delete, cron_list) | ✗ |
| 文件读取 | ✓ | ✓ |
| 文件写入 | ✗ | ✓ |
| Shell 命令 | ✗ | ✓ (bash) |

---

## 整体设计思想总结

1. **定时任务自主触发**：通过 cron 表达式定义执行时间，系统自动检测触发，无需用户干预。

2. **双事件源驱动**：用户输入和 cron 触发作为两个独立事件源，通过统一事件队列调度，实现自主执行能力。

3. **线程安全优先**：所有共享状态（self.tasks）的访问都加锁保护，使用 RLock 支持重入，避免数据竞态。

4. **解耦设计**：事件生产者（input_reader、cron_watcher）和消费者（主循环）解耦，便于扩展新事件源。

5. **渐进式升级**：在 s13 后台任务系统基础上增加定时任务调度，保留所有核心组件（TaskManager、BackgroundManager、MemoryManager 等）。

6. **可观测性增强**：_Tee 类实现会话日志功能，同时输出到终端和文件，便于调试和审计。

---

## 与 s13 的关系

### 继承内容

s14 完整保留 s13 的核心组件：
- BackgroundManager 后台任务生命周期管理（修复 BUG-1 线程安全）
- TaskManager 持久化任务 CRUD
- 三层错误恢复机制（max_tokens、prompt_too_long、API 错误）
- SystemPromptBuilder 6 层结构化构建
- MemoryManager 持久化记忆管理
- HookManager 拦截管线
- PermissionManager 权限管理
- BashSecurityValidator 安全验证
- 上下文压缩机制（micro_compact、compact_history，阈值调整）
- run_subagent_background() 异步并行子 agent 执行

### 变更内容

| 组件 | s13_v2 | s14_cron_scheduler |
|------|--------|-------------------|
| 定时任务调度 | 无 | CronScheduler |
| 主代理工具 | background_task + check_background | + cron_create/delete/list |
| 子代理工具 | background_run + check_background | 移除后台工具 |
| 事件源 | 单事件源（用户输入） | 双事件源（用户输入 + cron） |
| 事件处理 | input() 阻塞 | event_queue.get() 阻塞 |
| 会话日志 | 无 | _Tee 类 |
| 上下文限制 | 100000 chars | 800000 chars |

### 详细说明对比

关于 s13 后台任务系统的详细说明，参考：v1_task_manager/chapter_13/s13_v2_backtask_文档.md

---

## 实践指南

### 运行方法

```bash
cd v1_task_manager/chapter_14
python s14_cron_scheduler.py
```

### 定时任务使用示例

#### 1. 创建每 5 分钟执行的重复任务

```
/cron_create cron="*/5 * * * *" prompt="检查后台任务状态" recurring=true durable=false
```

返回：
```
Created task abc12345 (recurring, session-only): cron=*/5 * * * *
```

#### 2. 创建每天 9:00 执行的持久化任务

```
/cron_create cron="0 9 * * *" prompt="生成每日晨报" recurring=true durable=true
```

返回：
```
Created task def67890 (recurring, durable): cron=0 9 * * *
```

会话重启后任务会自动加载。

#### 3. 创建一次性任务

```
/cron_create cron="30 14 * * *" prompt="执行下午检查" recurring=false durable=false
```

返回：
```
Created task ghi11111 (one-shot, session-only): cron=30 14 * * *
```

任务触发后自动删除。

#### 4. 列出所有定时任务

```
/cron_list
```

返回：
```
  abc12345  */5 * * * *  [recurring/session] (0.5h old): 检查后台任务状态
  def67890  0 9 * * *  [recurring/durable] (1.2h old): 生成每日晨报
```

#### 5. 删除定时任务

```
/cron_delete id="abc12345"
```

返回：
```
Deleted task abc12345
```

#### 6. 测试 cron 触发

```
/test
```

返回：
```
[Test cron event enqueued.]
```

手动触发一个测试 cron 事件，验证 cron 通知处理流程。

---

### 测试示例

#### 1. 验证定时任务触发

```bash
# 启动程序
python s14_cron_scheduler.py

# 创建每 1 分钟执行的任务
/cron_create cron="* * * * *" prompt="每分钟检查" recurring=true durable=false

# 观察日志输出
# 每分钟会看到：
# [Cron] Fired: abc12345
# [Cron notification] [Scheduled task abc12345]: 每分钟检查

# 列出任务确认
/cron_list
```

#### 2. 验证持久化

```bash
# 创建持久化任务
/cron_create cron="0 9 * * *" prompt="每日晨报" recurring=true durable=true

# 检查持久化文件
cat .claude/scheduled_tasks.json

# 输出：
# [
#   {
#     "id": "def67890",
#     "cron": "0 9 * * *",
#     "prompt": "每日晨报",
#     "recurring": true,
#     "durable": true,
#     "createdAt": 1713678901.123,
#     "jitter_offset": 2
#   }
# ]

# 重启程序验证自动加载
python s14_cron_scheduler.py
# 输出：[Cron] 已加载 1 个定时任务
```

#### 3. 验证双事件源

```bash
# 启动程序
python s14_cron_scheduler.py

# 创建每 1 分钟执行的任务
/cron_create cron="* * * * *" prompt="自主执行检查" recurring=true durable=false

# 不输入任何内容，等待 cron 触发
# 观察到：
# [Cron] Fired: abc12345
# [Cron notification] [Scheduled task abc12345]: 自主执行检查
# agent_loop 自主执行，回复用户

# 验证无需用户输入即可触发执行
```

#### 4. 验证会话日志

```bash
# 启动程序
python s14_cron_scheduler.py

# 执行一些操作
/cron_list
/quit

# 检查日志文件
ls -la logs/
# 输出：session_1713678901.log

# 查看日志内容
cat logs/session_1713678901.log
# 输出：去除 ANSI 码的可读文本
```

#### 5. 验证线程安全

```python
# 多线程并发测试（需要另外编写测试脚本）
import threading
import time

def create_tasks():
    for i in range(10):
        scheduler.create(f"0 {i} * * *", f"Task {i}", recurring=True, durable=False)

def delete_tasks():
    time.sleep(0.1)
    for task in list(scheduler.tasks):
        scheduler.delete(task["id"])

# 并发创建和删除
t1 = threading.Thread(target=create_tasks)
t2 = threading.Thread(target=delete_tasks)
t1.start()
t2.start()
t1.join()
t2.join()

# 无 RuntimeError 或数据丢失
```

---

### Cron 表达式示例

| 表达式 | 含义 | 使用场景 |
|--------|------|----------|
| `*/5 * * * *` | 每 5 分钟 | 高频监控任务 |
| `0 * * * *` | 每小时整点 | 每小时数据同步 |
| `0 9 * * *` | 每天 9:00 | 每日晨报生成 |
| `30 14 * * *` | 每天 14:30 | 每日下午任务 |
| `0 9 * * 1` | 周一 9:00 | 每周例会提醒 |
| `0 9 * * 1-5` | 工作日 9:00 | 工作日晨报 |
| `0,30 9-17 * * 1-5` | 工作日 9-17 点的 0 分和 30 分 | 工作时段每 30 分钟检查 |
| `0 0 1 * *` | 每月 1 日 0:00 | 月度报告生成 |
| `0 0 * * 0` | 每周日 0:00 | 周度总结 |
| `*/15 * * * *` | 每 15 分钟 | 定期状态检查 |

---

## 总结

### 核心设计思想

s14 通过引入 CronScheduler 定时任务调度器，实现了定时任务的自主触发能力。设计原则是**定时自主触发**、**双事件源驱动**和**线程安全优先**。

### 核心机制

1. CronScheduler 定时任务调度器（5 字段 cron 表达式）
2. cron_create/delete/list 工具集
3. cron_watcher 线程（专职监听 cron 通知）
4. 事件驱动架构升级（双事件源）
5. _Tee 类会话日志
6. 线程安全修复（BUG-1、BUG-2、BUG-17）
7. .claude/scheduled_tasks.json 持久化
8. logs/ 目录会话日志存储

### 版本说明

- **文件路径**：v1_task_manager/chapter_14/s14_cron_scheduler.py
- **核心改动**：定时任务调度系统（双事件源架构）
- **继承内容**：s13 核心组件完整保留（BackgroundManager、TaskManager、Memory、Hook 等，部分修复线程安全）
- **主题**：定时任务调度系统增强

---

*文档版本：v1.0*
*基于代码：v1_task_manager/chapter_14/s14_cron_scheduler.py*