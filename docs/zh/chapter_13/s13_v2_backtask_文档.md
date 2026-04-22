# s13_v2: 后台任务系统（异步并行子 agent 执行）

## 概述

s13_v2 在 s12 持久化任务系统的基础上进行了**后台任务能力增强**。核心改动是新增后台任务执行框架，支持子 agent 异步并行执行、优先级通知队列和后台任务生命周期管理。

### 核心改进

1. **NotificationQueue 类** - 优先级通知队列，支持同 key 消息折叠
2. **BackgroundManager 类** - 后台任务生命周期管理（shell 命令 + 子 agent）
3. **run_subagent_background() 函数** - 异步并行子 agent 执行
4. **工具集重构** - task → background_task + check_background + background_run
5. **s12 功能完整保留** - TaskManager、三层错误恢复、SystemPromptBuilder 等核心组件无变化

### 代码文件路径

- **源代码**：v1_task_manager/chapter_13/s13_v2_backtask.py
- **参考文档**：v1_task_manager/chapter_12/s12_task_system_文档.md
- **参考代码**：v1_task_manager/chapter_12/s12_task_system.py
- **任务目录**：`.tasks/`（工作区根目录下的隐藏目录）
- **后台任务目录**：`.runtime-tasks/`（工作区根目录下的隐藏目录，s13 新增）
- **记忆目录**：`.memory/`（工作区根目录下的隐藏目录）
- **技能目录**：`skills/`（工作区根目录下）
- **钩子配置**：`.hooks.json`（工作区根目录下的钩子拦截管线配置文件）
- **Claude 信任标记**：`.claude/.claude_trusted`（工作区根目录下的隐藏目录）

---

## 与 s12 的对比（变更总览）

| 组件 | s12 | s13_v2 | 变化说明 |
|------|-----|--------|----------|
| 子 agent 执行 | run_subagent() 同步阻塞 | run_subagent_background() 异步非阻塞 | 新增并行能力 |
| 通知机制 | 无 | NotificationQueue | 新增优先级队列 + 消息折叠 |
| 后台管理 | 无 | BackgroundManager | 新增生命周期管理 |
| 工具集（主代理） | task（同步） | background_task + check_background | 同步 → 异步 |
| 工具集（子代理） | 无后台工具 | background_run + check_background | 新增后台 shell 能力 |
| 存储目录 | .tasks/ | .tasks/ + .runtime-tasks/ | 新增后台任务存储 |
| agent_loop | 无通知处理 | 每轮 drain 后台通知 | 新增通知注入机制 |
| SystemPromptBuilder | task 工具描述 | background_task 工具描述 | 提示词更新 |

---

## s13 新增内容详解（按代码执行顺序）

### NotificationQueue 类（优先级通知队列，同 key 消息折叠）

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

**核心机制**：

| 特性 | 实现方式 | 作用 |
|------|----------|------|
| 优先级队列 | PRIORITIES 字典映射，数字越小优先级越高 | 重要通知优先处理 |
| 消息折叠 | push 时检查 key，移除同 key 旧消息 | 避免重复通知淹没上下文 |
| 线程安全 | threading.Lock 保护队列操作 | 支持多线程并发访问 |
| 批量获取 | drain() 返回所有消息并清空 | 每轮 agent_loop 批量注入 |

**优先级定义**：
| 优先级 | 值 | 使用场景 |
|--------|-----|----------|
| immediate | 0 | 紧急通知（未在当前代码中使用） |
| high | 1 | 高优先级通知（未在当前代码中使用） |
| medium | 2 | 默认优先级（后台任务完成通知） |
| low | 3 | 低优先级通知（未在当前代码中使用） |

**消息折叠示例**：
```python
# 第一次推送
queue.push("Task A: 50% complete", key="task_a")
# 队列：[(2, "task_a", "Task A: 50% complete")]

# 第二次推送（同 key）
queue.push("Task A: 100% complete", key="task_a")
# 队列：[(2, "task_a", "Task A: 100% complete")]  # 旧消息被移除
```

---

### BackgroundManager 类（后台任务生命周期管理）

```python
class BackgroundManager:
    def __init__(self):
        self.dir = RUNTIME_DIR
        self.tasks = {}  # task_id -> {status, result, command, started_at}
        self._notification_queue = []  # completed task results
        self._lock = threading.Lock()
```

**核心方法**：

| 方法 | 功能 | 返回值 | 使用场景 |
|------|------|--------|----------|
| `run(command)` | 启动后台 shell 命令线程 | task_id 字符串 | 主代理调用 background_run |
| `_execute(task_id, command)` | 线程目标函数：执行 subprocess | 无（写入文件 + 推送通知） | 内部线程调用 |
| `check(task_id)` | 查询单个或所有后台任务状态 | JSON 字符串或格式化列表 | 主代理调用 check_background |
| `drain_notifications()` | 返回并清除所有完成通知 | list[dict] | agent_loop 每轮调用 |
| `detect_stalled()` | 检测超时任务（>45 秒） | list[task_id] | 监控长时间运行任务 |
| `_persist_task(task_id)` | 持久化任务状态到 JSON 文件 | 无 | 任务状态变更时调用 |

**任务状态枚举**：
| 状态 | 标记 | 含义 |
|------|------|------|
| running | - | 正在执行 |
| completed | - | 正常完成 |
| timeout | - | 超时（300 秒） |
| error | - | 执行出错 |

**存储结构**：
- 目录：`.runtime-tasks/`
- 记录文件命名：`{task_id}.json`
- 日志文件命名：`{task_id}.log`
- 文件格式：JSON（带缩进，中文字符可见）

**任务记录结构**：
```json
{
  "id": "sub_abc12345",
  "status": "completed",
  "result": "任务执行结果摘要",
  "command": "[subagent] 详细的子 agent 任务提示...",
  "started_at": 1234567890.123,
  "finished_at": 1234567895.456,
  "result_preview": "结果预览（前 500 字符）",
  "output_file": ".runtime-tasks/sub_abc12345.log"
}
```

**后台 shell 命令执行流程**：
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

### run_subagent_background() 函数（异步并行子 agent 执行）

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

**执行流程**：
1. 生成 task_id（格式：`sub_xxxxxxxx`）
2. 在 BG.tasks 中创建任务记录
3. 启动守护线程执行子 agent
4. 立即返回 task_id（非阻塞）
5. 子 agent 完成后推送通知到 BG._notification_queue

**与 run_subagent() 的对比**：

| 特性 | run_subagent() | run_subagent_background() |
|------|----------------|---------------------------|
| 执行方式 | 同步阻塞 | 异步非阻塞（后台线程） |
| 返回值 | 执行摘要字符串 | task_id 字符串 |
| 工具暴露 | s12 的 task 工具 | s13 的 background_task 工具 |
| 主代理行为 | 等待完成 | 可继续派发其他任务 |
| 并行能力 | 不支持 | 支持多个子 agent 并行 |
| 结果获取 | 直接返回 | 通过 check_background 或通知 |

**并行执行示例**：
```python
# 主代理可以连续派发多个后台子 agent
task1 = background_task(prompt="分析模块 A")  # 立即返回 sub_abc12345
task2 = background_task(prompt="分析模块 B")  # 立即返回 sub_def67890
task3 = background_task(prompt="分析模块 C")  # 立即返回 sub_ghi11111

# 三个子 agent 并行执行
# 主代理可继续处理其他事务或等待结果
```

---

### 工具集重构（task → background_task + 其他工具）

**s12 主代理工具集**：
| 工具 | 功能 | 阻塞 |
|------|------|------|
| task | 同步执行子 agent | 是 |
| task_create | 创建任务 | 否 |
| task_update | 更新任务 | 否 |
| task_list | 列出任务 | 否 |
| task_get | 获取任务详情 | 否 |

**s13_v2 主代理工具集**：
| 工具 | 功能 | 阻塞 | 变化 |
|------|------|------|------|
| background_task | 异步执行子 agent | 否 | 新增 |
| check_background | 查询后台任务状态 | 否 | 新增 |
| task_create | 创建任务 | 否 | 保留 |
| task_update | 更新任务 | 否 | 保留 |
| task_list | 列出任务 | 否 | 保留 |
| task_get | 获取任务详情 | 否 | 保留 |
| task | 同步执行子 agent | 是 | 移除 |

**s13_v2 子代理工具集（新增后台能力）**：
| 工具 | 功能 | 变化 |
|------|------|------|
| background_run | 异步执行 shell 命令 | 新增 |
| check_background | 查询后台任务状态 | 新增 |

**PARENT_TOOLS 定义（s13_v2）**：
```python
PARENT_TOOLS = [
    {"type": "function", "function": {"name": "read_file", ...}},
    {"type": "function", "function": {"name": "compact", ...}},
    {"type": "function", "function": {"name": "save_memory", ...}},
    {"type": "function", "function": {"name": "task_create", ...}},
    {"type": "function", "function": {"name": "task_update", ...}},
    {"type": "function", "function": {"name": "task_list", ...}},
    {"type": "function", "function": {"name": "task_get", ...}},
    # [s13_v2 新增] 并行子 agent 工具
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

**TOOL_HANDLERS 映射（s13_v2）**：
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
    "background_task":  lambda **kw: run_subagent_background(kw["prompt"]),  # [s13_v2 新增]
}
```

---

### .runtime-tasks/ 目录（后台任务状态和日志存储）

**目录结构**：
```
.workdir/
├── .runtime-tasks/
│   ├── sub_abc12345.json       # 任务状态记录
│   ├── sub_abc12345.log        # 任务输出日志
│   ├── sub_def67890.json
│   ├── sub_def67890.log
│   └── ...
├── .tasks/
├── .memory/
└── ...
```

**文件用途**：

| 文件类型 | 命名规则 | 内容 | 创建时机 |
|----------|----------|------|----------|
| 状态记录 | `{task_id}.json` | 任务元数据（状态、命令、时间戳等） | 任务启动时 + 状态变更时 |
| 输出日志 | `{task_id}.log` | 完整输出（stdout + stderr） | 任务完成时 |

**状态记录字段**：
```json
{
  "id": "sub_abc12345",
  "status": "completed",
  "result": "完整执行结果",
  "command": "[subagent] 任务提示词前 80 字符",
  "started_at": 1234567890.123,
  "finished_at": 1234567895.456,
  "result_preview": "结果预览（前 500 字符，空格压缩）",
  "output_file": ".runtime-tasks/sub_abc12345.log"
}
```

**持久化机制**：
```python
def _persist_task(self, task_id: str):
    record = dict(self.tasks[task_id])
    self._record_path(task_id).write_text(
        json.dumps(record, indent=2, ensure_ascii=False)
    )
```

**日志截断**：
```python
# 输出日志限制为 50000 字符，防止过大
output = (r.stdout + r.stderr).strip()[:50000]
```

---

### 保留功能（从 s12 继承）

| 组件 | 状态 | 说明 |
|------|------|------|
| TaskManager | 完整保留 | 持久化任务 CRUD（存储在 `.tasks/` 目录） |
| 三层错误恢复 | 完整保留 | max_tokens、prompt_too_long、API 错误 |
| SystemPromptBuilder | 保留（核心指令更新） | 6 层结构化构建，主代理核心指令更新 background_task |
| MemoryManager | 完整保留 | 持久化记忆管理 |
| DreamConsolidator | 完整保留（待激活） | 记忆自动整合 |
| HookManager | 完整保留 | 钩子拦截管线 |
| PermissionManager | 完整保留 | 权限管理 |
| BashSecurityValidator | 完整保留 | Bash 安全验证 |
| SkillRegistry | 完整保留 | 技能注册表 |
| 上下文压缩 | 完整保留 | micro_compact、compact_history |
| 转录保存 | 完整保留 | write_transcript |

---

## 目录结构依赖

| 目录/文件 | 用途 | 创建方式 | 版本 |
|-----------|------|----------|------|
| `.tasks/` | 持久化任务存储 | TaskManager 自动创建 | s12 保留 |
| `.tasks/task_*.json` | 单个任务文件 | TaskManager._save() 创建 | s12 保留 |
| `.runtime-tasks/` | 后台任务状态和日志 | BackgroundManager 自动创建 | s13 新增 |
| `.runtime-tasks/{task_id}.json` | 后台任务状态记录 | BG._persist_task() 创建 | s13 新增 |
| `.runtime-tasks/{task_id}.log` | 后台任务输出日志 | BG._execute() 创建 | s13 新增 |
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
加载组件
├── MemoryManager.load_all()
├── TaskManager(TASKS_DIR)
├── BackgroundManager()  # [s13 新增]
├── HookManager(perms)
└── SystemPromptBuilder
    │
    ▼
用户输入
    │
    ▼
agent_loop(state, compact_state)
│   [s13 新增] Drain BG 通知
│   │   notifs = BG.drain_notifications()
│   │   if notifs:
│   │       注入 <background-results> 到 state.messages
│   │
│   - 更新系统提示 (main_build)
│   - micro_compact()
│   - estimate_context_size() > CONTEXT_LIMIT? -> compact_history()
    │
    ▼
run_one_turn(state, compact_state)
│   Layer 1: LLM 调用 (for attempt in range(4))
│   │   try: response = client.chat.completions.create()
│   │   except:
│   │       context_length_exceeded? -> Strategy 2 + continue
│   │       attempt < 3? -> Strategy 3 + continue
│   │       else -> return False
│   │
│   Layer 2: finish_reason 检查
│   │   finish_reason == "length"?
│   │       -> max_output_recovery_count += 1
│   │       -> count <= 3? -> Strategy 1 + return True
│   │       -> else -> return False
│   │
│   Layer 3: 工具执行
│       tool_calls? -> execute_tool_calls() + return True
│       else -> return False
    │
    ▼
execute_tool_calls()
│   for each tool_call:
│   │   PreToolUse Hook 管线
│   │   │   ├── PermissionManager.check()
│   │   │   └── HookManager._run_external_hooks()
│   │   │
│   │   工具执行
│   │   │   ├── background_task -> run_subagent_background()  # [s13 新增]
│   │   │   ├── check_background -> BG.check()                # [s13 新增]
│   │   │   ├── background_run -> BG.run()                    # [s13 新增]
│   │   │   ├── task_create -> TASKS.create()
│   │   │   ├── task_update -> TASKS.update()
│   │   │   ├── task_list -> TASKS.list_all()
│   │   │   ├── task_get -> TASKS.get()
│   │   │   └── ...
│   │   │
│   │   PostToolUse Hook 管线
│   │
│   任务工具使用检测
│   │   used_task_manager? -> TASKS.rounds_since_update = 0
│   │   else -> TASKS.rounds_since_update += 1
│   │           >= PLAN_REMINDER_INTERVAL? -> 插入提醒
    │
    ▼
run_subagent_background() (当调用 background_task 工具时)  # [s13 新增]
│   - 生成 task_id (sub_xxxxxxxx)
│   - 创建任务记录到 BG.tasks
│   - 启动守护线程
│   │   └── 调用 run_subagent(prompt)
│   │       └── 独立子 agent 循环（最多 30 步）
│   │
│   - 立即返回 task_id（非阻塞）
│   - 子 agent 完成后：
│       ├── 更新 BG.tasks[task_id] 状态
│       └── 推送通知到 BG._notification_queue
    │
    ▼
循环继续或退出
│   - 无工具调用且无运行中后台任务 -> 退出
│   - 有运行中后台任务 -> 等待通知 -> 继续循环


后台任务执行流程
┌─────────────────────────────────────────────────────────────────┐
│                    .runtime-tasks/ 目录                          │
│  ┌──────────────────────┐  ┌──────────────────────┐            │
│  │ sub_abc12345.json    │  │ sub_abc12345.log     │            │
│  │                      │  │                      │            │
│  │ id: sub_abc12345     │  │ 完整输出日志          │            │
│  │ status: completed    │  │ (stdout + stderr)    │            │
│  │ command: [subagent]..│  │                      │            │
│  │ started_at: ...      │  │                      │            │
│  │ finished_at: ...     │  │                      │            │
│  │ result_preview: ...  │  │                      │            │
│  │ output_file: ...     │  │                      │            │
│  └──────────────────────┘  └──────────────────────┘            │
│            │                                                       │
│            ▼                                                       │
│  BackgroundManager 生命周期管理                                      │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │  BG.tasks 字典（内存）                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐                │   │
│  │  │ task_1   │  │ task_2   │  │ task_3   │  ...           │   │
│  │  │ running  │  │ completed│  │ error    │                │   │
│  │  └──────────┘  └──────────┘  └──────────┘                │   │
│  │                                                           │   │
│  │  BG._notification_queue（完成通知）                        │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ [{task_id, status, preview, output_file}, ...]   │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  └───────────────────────────────────────────────────────────┘   │
│            │                                                       │
│            ▼                                                       │
│  agent_loop 每轮 drain 通知注入上下文                                 │
│  <background-results>                                              │
│  [bg:sub_abc12345] completed: 结果预览 (output_file=...)          │
│  </background-results>                                             │
└─────────────────────────────────────────────────────────────────┘


并行子 agent 执行时序
主 Agent                      后台线程 1                后台线程 2                后台线程 3
  │                              │                        │                        │
  ├─ background_task("任务 A") ──┼────────────────────────┼────────────────────────┤
  │  返回 sub_abc12345           │                        │                        │
  │                              │                        │                        │
  ├─ background_task("任务 B") ──┼────────────────────────┼────────────────────────┤
  │  返回 sub_def67890           │                        │                        │
  │                              │                        │                        │
  ├─ background_task("任务 C") ──┼────────────────────────┼────────────────────────┤
  │  返回 sub_ghi11111           │                        │                        │
  │                              │                        │                        │
  │  继续处理其他事务...          │                        │                        │
  │                              │                        │                        │
  │                              ├─ run_subagent("A")     │                        │
  │                              │  执行 30 步循环          │                        │
  │                              │                        │                        │
  │                              │                        ├─ run_subagent("B")     │
  │                              │                        │  执行 30 步循环          │
  │                              │                        │                        │
  │                              │                        │                        ├─ run_subagent("C")
  │                              │                        │                        │  执行 30 步循环
  │                              │                        │                        │
  │                              ├─ 完成，推送通知 ────────┼────────────────────────┤
  │                              │                        │                        │
  │                              │                        ├─ 完成，推送通知 ────────┤
  │                              │                        │                        │
  │                              │                        │                        ├─ 完成，推送通知
  │                              │                        │                        │
  │  agent_loop drain 通知 ◄─────┴────────────────────────┴────────────────────────┤
  │  注入 <background-results> 到上下文                                              │
  │                                                                                │
```

---

## 设计点总结

### 核心设计机制 1：优先级通知队列

| 特性 | 实现方式 |
|------|----------|
| 优先级排序 | PRIORITIES 字典映射，sort(key=lambda x: x[0]) |
| 消息折叠 | push 时检查 key，过滤同 key 旧消息 |
| 线程安全 | threading.Lock 保护队列操作 |
| 批量消费 | drain() 返回所有消息并清空 |

### 核心设计机制 2：后台任务生命周期管理

| 阶段 | 操作 |
|------|------|
| 创建 | 生成 task_id，初始化 BG.tasks 记录，持久化 JSON |
| 执行 | 启动守护线程，执行 subprocess 或 run_subagent |
| 完成 | 更新状态、结果、时间戳，推送通知到队列 |
| 查询 | check() 返回内存中的任务状态 |
| 监控 | detect_stalled() 检查超时任务（>45 秒） |

### 核心设计机制 3：异步并行子 agent 执行

| 维度 | run_subagent() | run_subagent_background() |
|------|----------------|---------------------------|
| 执行模型 | 同步阻塞 | 异步非阻塞（后台线程） |
| 主代理行为 | 等待完成 | 可继续派发其他任务 |
| 并行能力 | 不支持 | 支持多个子 agent 并行 |
| 结果获取 | 直接返回 | 通过通知或 check_background |

### 核心设计机制 4：工具集分层

| 工具类别 | 主代理 | 子代理 |
|----------|--------|--------|
| 任务管理 | ✓ (task_*) | ✗ |
| 后台任务 | ✓ (background_task, check_background) | ✓ (background_run, check_background) |
| 文件读取 | ✓ | ✓ |
| 文件写入 | ✗ | ✓ |
| Shell 命令 | ✗ | ✓ (bash, background_run) |

### 核心设计机制 5：通知注入机制

```python
# agent_loop 中每轮 LLM 调用前 drain 通知
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

## 整体设计思想总结

1. **异步并行**：后台线程执行子 agent，主代理可并行派发多个独立任务。

2. **通知驱动**：优先级队列 + 消息折叠机制，避免通知淹没上下文。

3. **生命周期可追踪**：后台任务状态持久化到 .runtime-tasks/ 目录，支持查询和审计。

4. **工具集扩展**：background_task + check_background + background_run 形成完整后台能力。

5. **渐进式升级**：在 s12 持久化任务系统基础上增加后台执行，保留所有核心组件。

6. **非阻塞设计**：主代理不被长时间任务阻塞，可继续处理其他事务或派发新任务。

---

## 与 s12 的关系

### 继承内容

s13_v2 完整保留 s12 的核心组件：
- TaskManager 持久化任务 CRUD
- 三层错误恢复机制（max_tokens、prompt_too_long、API 错误）
- SystemPromptBuilder 6 层结构化构建（核心指令更新）
- MemoryManager 持久化记忆管理
- HookManager 拦截管线
- PermissionManager 权限管理
- BashSecurityValidator 安全验证
- 上下文压缩机制（micro_compact、compact_history）

### 变更内容

| 组件 | s12 | s13_v2 |
|------|-----|--------|
| 子 agent 执行 | run_subagent() 同步 | run_subagent_background() 异步 |
| 主代理工具 | task | background_task + check_background |
| 子代理工具 | 无后台工具 | background_run + check_background |
| 存储目录 | .tasks/ | .tasks/ + .runtime-tasks/ |
| agent_loop | 无通知处理 | 每轮 drain BG 通知 |

### 详细说明对比

关于 s12 持久化任务系统的详细说明，参考：v1_task_manager/chapter_12/s12_task_system_文档.md

---

## 实践指南

### 运行方法

```bash
cd v1_task_manager/chapter_13
python s13_v2_backtask.py
```

### 后台任务使用示例

#### 1. 派发后台子 agent

```
/background_task prompt="读取 s13_v2_backtask.py 并分析 BackgroundManager 类的实现"
```

返回：
```
Background subagent sub_abc12345 started: 读取 s13_v2_backtask.py 并分析 BackgroundManager 类的实现
```

#### 2. 查询后台任务状态

```
/check_background task_id="sub_abc12345"
```

返回（运行中）：
```json
{
  "id": "sub_abc12345",
  "status": "running",
  "command": "[subagent] 读取 s13_v2_backtask.py 并分析 BackgroundManager 类的实现",
  "result_preview": "",
  "output_file": ""
}
```

返回（已完成）：
```json
{
  "id": "sub_abc12345",
  "status": "completed",
  "command": "[subagent] 读取 s13_v2_backtask.py 并分析 BackgroundManager 类的实现",
  "result_preview": "BackgroundManager 类负责后台任务的生命周期管理...",
  "output_file": ""
}
```

#### 3. 列出所有后台任务

```
/check_background
```

返回：
```
sub_abc12345: [completed] [subagent] 读取 s13_v2_backtask.py -> BackgroundManager 类负责...
sub_def67890: [running] [subagent] 分析工具集变化 -> (running)
```

#### 4. 派发后台 shell 命令（子代理）

```
/background_run command="find . -name '*.py' | head -20"
```

返回：
```
Background task abc12345 started: find . -name '*.py' | head -20 (output_file=.runtime-tasks/abc12345.log)
```

#### 5. 并行派发多个后台子 agent

```
/background_task prompt="分析模块 A 的代码结构"
/background_task prompt="分析模块 B 的代码结构"
/background_task prompt="分析模块 C 的代码结构"
```

三个子 agent 并行执行，主代理可继续处理其他事务。

---

### 测试示例

#### 1. 验证并行执行

```bash
# 启动程序
python s13_v2_backtask.py

# 连续派发三个后台子 agent
/background_task prompt="sleep 5 && echo 'Task A completed'"
/background_task prompt="sleep 5 && echo 'Task B completed'"
/background_task prompt="sleep 5 && echo 'Task C completed'"

# 立即查询状态（应该都是 running）
/check_background

# 等待 6 秒后再次查询（应该都是 completed）
/check_background
```

#### 2. 验证通知注入

观察日志输出：
- 主代理每轮循环会 drain 后台通知
- 完成通知以 `<background-results>` 标签注入上下文
- 格式：`[bg:sub_abc12345] completed: 结果预览 (output_file=...)`

#### 3. 验证持久化

```bash
# 执行后台任务后检查 .runtime-tasks/ 目录
ls -la .runtime-tasks/
# 输出：sub_abc12345.json, sub_abc12345.log

# 查看任务状态记录
cat .runtime-tasks/sub_abc12345.json
# 输出：包含 id, status, command, started_at, finished_at 等字段

# 查看任务输出日志
cat .runtime-tasks/sub_abc12345.log
# 输出：完整的 stdout + stderr
```

#### 4. 验证消息折叠

```python
# NotificationQueue 消息折叠测试
queue = NotificationQueue()
queue.push("Task A: 50%", key="task_a")
queue.push("Task A: 75%", key="task_a")
queue.push("Task A: 100%", key="task_a")

# drain 应该只返回最后一条消息
messages = queue.drain()
# messages = ["Task A: 100%"]
```

---

## 总结

### 核心设计思想

s13_v2 通过引入后台任务执行框架，实现了子 agent 的异步并行执行能力。设计原则是**异步并行**、**通知驱动**和**生命周期可追踪**。

### 核心机制

1. NotificationQueue 优先级队列 + 消息折叠
2. BackgroundManager 后台任务生命周期管理
3. run_subagent_background() 异步并行子 agent 执行
4. 工具集重构（background_task + check_background + background_run）
5. .runtime-tasks/ 目录持久化
6. agent_loop 通知注入机制

### 版本说明

- **文件路径**：v1_task_manager/chapter_13/s13_v2_backtask.py
- **核心改动**：后台任务系统（异步并行子 agent 执行）
- **继承内容**：s12 核心组件完整保留（TaskManager、错误恢复、Memory、Hook 等）
- **主题**：后台任务系统增强

---

*文档版本：v1.0*
*基于代码：v1_task_manager/chapter_13/s13_v2_backtask.py*
