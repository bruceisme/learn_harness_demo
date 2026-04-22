# s18_v2_singleagent_worktree_task_isolation: Worktree 任务隔离系统

## 概述

s18_v2 在 s14 定时任务调度系统的基础上进行了**任务执行环境隔离能力增强**。核心改动是新增 WorktreeManager 类和 EventBus 类，支持 git worktree 全生命周期管理，实现任务的物理隔离执行环境。

### 特殊版本说明

**chapter_18_2 是特殊章节**，代码基于 chapter_14 的 s14_cron_scheduler.py 直接修改，而非按顺序从 chapter_15/16/17 演进。这是一个**并行开发分支**，用于实验 worktree 任务隔离功能。

### 核心改进

1. **detect_repo_root() 函数** - 自动检测 git 仓库根目录，为 worktree 支持提供路径基础
2. **EventBus 类** - 追加写入的 worktree 生命周期事件日志（`.worktrees/events.jsonl`）
3. **WorktreeManager 类** - git worktree 全生命周期管理（create/enter/run/list/status/closeout/keep/remove）
4. **TaskManager 扩展** - 新增 worktree 相关字段（worktree、worktree_state、last_worktree）和绑定方法
5. **worktree_* 工具集** - 主代理可调用的 worktree 管理工具（task_bind_worktree、worktree_create、worktree_run 等）
6. **.worktrees/ 目录结构** - worktree 配置和事件存储（index.json、events.jsonl、worktrees/）

### 代码文件路径

- **源代码**：v1_task_manager/chapter_18_2/s18_v2_singleagent_worktree_task_isolation.py
- **参考文档**：v1_task_manager/chapter_14/s14_cron_scheduler_文档.md
- **参考代码**：v1_task_manager/chapter_14/s14_cron_scheduler.py
- **Worktree 索引文件**：`.worktrees/index.json`
- **事件日志文件**：`.worktrees/events.jsonl`
- **Worktree 目录**：`.worktrees/{worktree_name}/`
- **定时任务持久化文件**：`.claude/scheduled_tasks.json`
- **会话日志目录**：`logs/`
- **后台任务目录**：`.runtime-tasks/`
- **任务目录**：`.tasks/`
- **记忆目录**：`.memory/`
- **技能目录**：`skills/`

---

## 与 s14 的对比（变更总览）

| 组件 | s14_cron_scheduler | s18_v2_singleagent_worktree_task_isolation | 变化说明 |
|------|-------------------|-------------------------------------------|----------|
| Git 仓库检测 | 无 | detect_repo_root() | 新增自动检测 git 仓库根目录 |
| 事件日志 | 无 | EventBus 类 | 新增 worktree 生命周期事件日志 |
| Worktree 管理 | 无 | WorktreeManager 类 | 新增 git worktree 全生命周期管理 |
| TaskManager 字段 | 基础字段 | + worktree/worktree_state/last_worktree | 新增 worktree 绑定字段 |
| TaskManager 方法 | 基础 CRUD | + bind_worktree/unbind_worktree/record_closeout/exists | 新增 worktree 绑定方法 |
| 主代理工具集 | cron_* + task_* + background_* | + worktree_* 工具集 | 新增 9 个 worktree 管理工具 |
| 系统提示 | 无 worktree 规则 | + WORKTREES 规则 + 动态 worktree 列表 | 新增 worktree 使用说明 |
| 目录结构 | 无 .worktrees/ | + .worktrees/ 目录 | 新增 worktree 配置和事件存储 |
| 启动时信息 | 无 worktree 信息 | + Repo root 和 worktree 列表 | 新增启动时 worktree 状态显示 |

---

## s18_v2 新增内容详解（按代码执行顺序）

### detect_repo_root() 函数（自动检测 git 仓库根目录）

**实现代码**：
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

**核心机制**：

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1 | 执行 `git rev-parse --show-toplevel` | 获取 git 仓库根目录 |
| 2 | 检查 returncode == 0 | 确认在 git 仓库内 |
| 3 | 检查路径存在 | 确认根目录有效 |
| 4 | 返回根目录或 WORKDIR | 非 git 仓库时使用当前目录 |

**用途**：
- 为 worktree 管理提供统一的根目录路径
- 确保 `.worktrees/` 目录创建在 git 仓库根目录
- 非 git 仓库环境下降级为当前工作目录

---

### EventBus 类（worktree 生命周期事件日志）

**实现代码**：
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

**核心属性**：

| 属性 | 类型 | 用途 |
|------|------|------|
| path | Path | 事件日志文件路径（`.worktrees/events.jsonl`） |

**核心方法**：

| 方法 | 功能 | 返回值 | 说明 |
|------|------|--------|------|
| `__init__()` | 初始化事件日志路径 | 无 | 自动创建父目录和空文件 |
| `emit()` | 追加写入事件 | 无 | JSONL 格式，每行一个事件 |
| `list_recent()` | 列出最近事件 | JSON 字符串 | 默认 20 条，最大 200 条 |

**事件类型**：

| 事件名 | 触发时机 | 包含字段 |
|--------|----------|----------|
| `worktree.create.before` | worktree 创建前 | task_id, worktree |
| `worktree.create.after` | worktree 创建后 | task_id, worktree |
| `worktree.create.failed` | worktree 创建失败 | task_id, worktree, error |
| `worktree.enter` | 进入 worktree | task_id, worktree, path |
| `worktree.run.before` | 命令执行前 | task_id, worktree, command |
| `worktree.run.after` | 命令执行后 | task_id, worktree |
| `worktree.run.timeout` | 命令执行超时 | task_id, worktree |
| `worktree.remove.before` | worktree 删除前 | task_id, worktree |
| `worktree.remove.after` | worktree 删除后 | task_id, worktree |
| `worktree.remove.failed` | worktree 删除失败 | task_id, worktree, error |
| `worktree.keep` | worktree 保留 | task_id, worktree |
| `worktree.closeout.keep` | closeout 保留 | task_id, worktree, reason |
| `worktree.closeout.remove` | closeout 删除 | worktree, reason |
| `task.completed` | 任务完成 | task_id, worktree |

**事件记录格式**：
```jsonl
{"event": "worktree.create.before", "ts": 1713678901.123, "task_id": 1, "worktree": "wt-feature-1"}
{"event": "worktree.create.after", "ts": 1713678902.456, "task_id": 1, "worktree": "wt-feature-1"}
{"event": "worktree.run.before", "ts": 1713678910.789, "task_id": 1, "worktree": "wt-feature-1", "command": "git status"}
{"event": "worktree.run.after", "ts": 1713678911.012, "task_id": 1, "worktree": "wt-feature-1"}
```

---

### WorktreeManager 类（git worktree 全生命周期管理）

**实现代码**：
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

**核心属性**：

| 属性 | 类型 | 用途 |
|------|------|------|
| repo_root | Path | git 仓库根目录 |
| tasks | TaskManager | 任务管理器实例（用于绑定 worktree） |
| events | EventBus | 事件总线实例（用于记录事件） |
| dir | Path | .worktrees/ 目录路径 |
| index_path | Path | index.json 文件路径（worktree 索引） |
| git_available | bool | git 是否可用 |

**核心方法**：

| 方法 | 功能 | 参数 | 返回值 | 说明 |
|------|------|------|--------|------|
| `_check_git()` | 检查 git 可用性 | 无 | bool | 执行 `git rev-parse --is-inside-work-tree` |
| `_run_git()` | 执行 git 命令 | args: list | str | 超时 120 秒，返回 stdout+stderr |
| `_load_index()` | 加载 worktree 索引 | 无 | dict | 读取 index.json |
| `_save_index()` | 保存 worktree 索引 | data: dict | 无 | 写入 index.json |
| `_find()` | 查找 worktree | name: str | dict | 返回 worktree 条目或 None |
| `_update_entry()` | 更新 worktree 条目 | name, **changes | dict | 返回更新后的条目 |
| `_validate_name()` | 验证 worktree 名称 | name: str | 无 | 1-40 字符，字母数字._- |
| `create()` | 创建 worktree | name, task_id, base_ref | str | 创建 git worktree 并绑定任务 |
| `list_all()` | 列出所有 worktrees | 无 | str | 格式化列表 |
| `status()` | 查看 worktree 状态 | name: str | str | 执行 git status |
| `enter()` | 进入 worktree | name: str | str | 记录 last_entered_at |
| `run()` | 在 worktree 中运行命令 | name, command | str | 执行命令并记录事件 |
| `remove()` | 删除 worktree | name, force, complete_task, reason | str | 删除 worktree 并更新任务 |
| `keep()` | 保留 worktree | name: str | str | 标记为 kept 状态 |
| `closeout()` | 关闭 worktree | name, action, reason, force, complete_task | str | keep 或 remove |

**Worktree 条目结构**：
```python
entry = {
    "name": "wt-feature-1",           # worktree 名称
    "path": "/path/to/.worktrees/wt-feature-1",  # worktree 目录路径
    "branch": "wt/wt-feature-1",      # 关联的 git 分支
    "task_id": 1,                     # 绑定的任务 ID（可选）
    "status": "active",               # 状态：active/kept/removed
    "created_at": 1713678901.123,     # 创建时间戳
    "last_entered_at": 1713678910.456, # 最后进入时间戳（可选）
    "last_command_at": 1713678920.789, # 最后执行命令时间戳（可选）
    "last_command_preview": "git status", # 最后执行命令预览（可选）
    "closeout": {                     # closeout 信息（可选）
        "action": "remove",
        "reason": "任务完成",
        "at": 1713679000.012
    }
}
```

**create() 方法详解**：
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

**工作流程**：
1. 验证 worktree 名称格式
2. 检查是否已存在同名 worktree
3. 检查关联的任务是否存在
4. 创建新分支 `wt/{name}`
5. 执行 `git worktree add -b branch path base_ref`
6. 创建 worktree 条目并保存到 index.json
7. 绑定任务到 worktree（如果有 task_id）
8. 记录创建事件

---

### worktree_* 工具集（主代理可调用的 worktree 管理工具）

**工具定义**：

```python
# [s18_v2 新增] worktree 工具
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

**工具处理器**：
```python
TOOL_HANDLERS = {
    # ... 其他工具
    # [s18_v2 新增] worktree 工具
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

**使用示例**：

```python
# 创建 worktree 并绑定任务
worktree_create(name="wt-feature-1", task_id=1, base_ref="HEAD")
# 返回：{"name": "wt-feature-1", "path": "/path/to/.worktrees/wt-feature-1", "branch": "wt/wt-feature-1", "task_id": 1, "status": "active", "created_at": 1713678901.123}

# 列出所有 worktrees
worktree_list()
# 返回：
# [active] wt-feature-1 -> /path/to/.worktrees/wt-feature-1 (wt/wt-feature-1) task=1

# 进入 worktree
worktree_enter(name="wt-feature-1")
# 返回：更新后的 worktree 条目（包含 last_entered_at）

# 查看 worktree 状态
worktree_status(name="wt-feature-1")
# 返回：git status 输出

# 在 worktree 中运行命令
worktree_run(name="wt-feature-1", command="git status")
# 返回：命令执行结果

# 保留 worktree
worktree_keep(name="wt-feature-1")
# 返回：更新后的 worktree 条目（status="kept"）

# 删除 worktree
worktree_remove(name="wt-feature-1", force=False, complete_task=True, reason="任务完成")
# 返回："Removed worktree 'wt-feature-1'"

# closeout worktree（综合操作）
worktree_closeout(name="wt-feature-1", action="remove", reason="任务完成", force=False, complete_task=True)
# 返回：根据 action 执行 keep 或 remove

# 查看事件日志
worktree_events(limit=20)
# 返回：最近 20 条事件的 JSON 列表
```

---

### TaskManager 增强（worktree 相关字段和方法）

**新增字段**：

```python
# TaskManager.create() 中新增的字段
task = {
    "id": self._next_id,
    "subject": subject,
    "description": description,
    "status": "pending",
    "blockedBy": [],
    "blocks": [],
    "owner": "",
    "worktree": "",              # [新增] 当前绑定的 worktree 名称
    "worktree_state": "unbound", # [新增] worktree 状态：unbound/active
    "last_worktree": "",         # [新增] 最后使用的 worktree 名称
    "closeout": None,            # [新增] closeout 信息
}
```

**TaskRecord 字段说明**：

| 字段 | 类型 | 含义 | 取值 |
|------|------|------|------|
| worktree | str | 当前绑定的 worktree 名称 | 空字符串或 worktree 名称 |
| worktree_state | str | worktree 绑定状态 | unbound（未绑定）/active（已绑定）/kept（保留）/removed（已删除） |
| last_worktree | str | 最后使用的 worktree 名称 | 空字符串或 worktree 名称 |
| closeout | dict | closeout 信息 | None 或 {"action": "keep/remove", "reason": "", "at": timestamp} |

**新增方法**：

```python
def exists(self, task_id: int) -> bool:
    """检查任务是否存在。"""
    return (self.dir / f"task_{task_id}.json").exists()

def bind_worktree(self, task_id: int, worktree: str, owner: str = "") -> str:
    """绑定任务到 worktree。"""
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
    """解绑任务的 worktree。"""
    task = self._load(task_id)
    task["worktree"] = ""
    task["worktree_state"] = "unbound"
    task["updated_at"] = time.time()
    self._save(task)
    return json.dumps(task, indent=2, ensure_ascii=False)

def record_closeout(self, task_id: int, action: str, reason: str = "", keep_binding: bool = False) -> str:
    """记录任务的 closeout 信息。"""
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

**TaskManager 方法说明**：

| 方法 | 功能 | 参数 | 返回值 | 说明 |
|------|------|------|--------|------|
| `exists()` | 检查任务是否存在 | task_id: int | bool | 用于 worktree 创建前验证任务 |
| `bind_worktree()` | 绑定任务到 worktree | task_id, worktree, owner | JSON 字符串 | 设置 worktree 状态为 active |
| `unbind_worktree()` | 解绑 worktree | task_id: int | JSON 字符串 | 设置 worktree 状态为 unbound |
| `record_closeout()` | 记录 closeout | task_id, action, reason, keep_binding | JSON 字符串 | action=keep/remove |

**list_all() 输出增强**：
```python
# list_all() 输出中增加 worktree 信息
marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]", "deleted": "[-]"}.get(t["status"], "[?]")
blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
owner = f" owner={t['owner']}" if t.get("owner") else ""
wt = f" wt={t['worktree']}" if t.get("worktree") else ""  # [新增] worktree 信息
lines.append(f"{marker} #{t['id']}: {t['subject']}{owner}{wt}{blocked}")
```

输出示例：
```
[>] #1: 实现功能 A owner=张三 wt=wt-feature-1
[ ] #2: 实现功能 B
[x] #3: 实现功能 C wt=wt-feature-2
```

---

### .worktrees/ 目录结构（worktree 配置和事件存储）

**目录结构**：
```
.worktrees/
├── index.json          # worktree 索引（所有 worktree 条目）
├── events.jsonl        # worktree 生命周期事件日志（JSONL 格式）
└── worktrees/          # 实际 worktree 目录（由 git worktree add 创建）
    ├── wt-feature-1/   # worktree 1
    ├── wt-feature-2/   # worktree 2
    └── ...
```

**index.json 格式**：
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
        "reason": "需要后续跟进",
        "at": 1713679500.000
      }
    }
  ]
}
```

**events.jsonl 格式**：
```jsonl
{"event": "worktree.create.before", "ts": 1713678901.123, "task_id": 1, "worktree": "wt-feature-1"}
{"event": "worktree.create.after", "ts": 1713678902.456, "task_id": 1, "worktree": "wt-feature-1"}
{"event": "worktree.enter", "ts": 1713678910.456, "task_id": 1, "worktree": "wt-feature-1", "path": "/path/to/.worktrees/wt-feature-1"}
{"event": "worktree.run.before", "ts": 1713678920.789, "task_id": 1, "worktree": "wt-feature-1", "command": "git status"}
{"event": "worktree.run.after", "ts": 1713678921.012, "task_id": 1, "worktree": "wt-feature-1"}
{"event": "worktree.closeout.keep", "ts": 1713679500.000, "task_id": 1, "worktree": "wt-feature-1", "reason": "需要后续跟进"}
```

**文件用途**：

| 文件 | 用途 | 更新时机 | 格式 |
|------|------|----------|------|
| index.json | worktree 索引 | worktree 创建/更新/删除时 | JSON |
| events.jsonl | 生命周期事件日志 | 所有 worktree 操作时 | JSONL（每行一个 JSON 对象） |
| worktrees/*/ | 实际 worktree 目录 | git worktree add 创建 | git worktree |

---

### 保留功能（从 s14 继承）

| 组件 | 状态 | 说明 |
|------|------|------|
| CronScheduler | 完整保留 | 定时任务调度器（5 字段 cron 表达式） |
| BackgroundManager | 完整保留 | 后台任务生命周期管理（shell 命令） |
| NotificationQueue | 完整保留 | 优先级通知队列 |
| TaskManager | 增强（新增 worktree 字段） | 持久化任务 CRUD |
| 三层错误恢复 | 完整保留 | max_tokens、prompt_too_long、API 错误 |
| SystemPromptBuilder | 增强（新增 worktree 规则） | 6 层结构化构建 |
| MemoryManager | 完整保留 | 持久化记忆管理 |
| DreamConsolidator | 完整保留（待激活） | 记忆自动整合 |
| HookManager | 完整保留 | 钩子拦截管线 |
| PermissionManager | 完整保留 | 权限管理 |
| BashSecurityValidator | 完整保留 | Bash 安全验证 |
| SkillRegistry | 完整保留 | 技能注册表 |
| 上下文压缩 | 完整保留 | micro_compact、compact_history |
| 转录保存 | 完整保留 | write_transcript |
| run_subagent_background() | 完整保留 | 异步并行子 agent 执行 |
| 事件驱动架构 | 完整保留 | input_reader + cron_watcher |
| _Tee 会话日志 | 完整保留 | 同时输出到终端和文件 |

**SystemPromptBuilder 增强**：

s18_v2 在 SystemPromptBuilder 的 `_build_core()` 方法中增加了 worktree 相关说明：

```python
def _build_core(self) -> str:
    return (
        f"You are the Main Planner Agent operating in {self.workdir}.\n"
        # ... 其他核心指令 ...
        "7. WORKTREES: For parallel or risky work, create tasks then use `worktree_create` to allocate isolated git worktree lanes. "
        "Run commands via `worktree_run`. When done, use `worktree_closeout` (action='keep' or 'remove') to close the lane.\n"
    )
```

**动态上下文增强**：

`_build_dynamic_context()` 方法中增加了 worktree 列表显示：

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

**启动时信息增强**：

```python
# [s18_v2] 启动时显示 worktree 和 repo root 信息
print(f"[Repo root: {REPO_ROOT}]")
if not WORKTREES.git_available:
    print("[Note: Not in a git repo. worktree_* tools will return errors.]")
else:
    wt_list = WORKTREES.list_all()
    print(f"[Worktrees: {wt_list}]")
```

---

## 目录结构依赖

| 目录/文件 | 用途 | 创建方式 | 版本 |
|-----------|------|----------|------|
| `.worktrees/` | worktree 配置和事件存储根目录 | WorktreeManager.__init__() 自动创建 | s18_v2 新增 |
| `.worktrees/index.json` | worktree 索引 | WorktreeManager 初始化/更新 | s18_v2 新增 |
| `.worktrees/events.jsonl` | worktree 生命周期事件日志 | EventBus 追加写入 | s18_v2 新增 |
| `.worktrees/worktrees/` | 实际 worktree 目录 | git worktree add 创建 | s18_v2 新增 |
| `.worktrees/worktrees/{name}/` | 单个 worktree 目录 | WorktreeManager.create() | s18_v2 新增 |
| `.tasks/` | 持久化任务存储 | TaskManager 自动创建 | s12 保留 |
| `.tasks/task_*.json` | 单个任务文件 | TaskManager._save() 创建 | s12 保留（s18_v2 增强字段） |
| `.runtime-tasks/` | 后台任务状态和日志 | BackgroundManager 自动创建 | s13 保留 |
| `.runtime-tasks/{task_id}.json` | 后台任务状态记录 | BG._persist_task() 创建 | s13 保留 |
| `.runtime-tasks/{task_id}.log` | 后台任务输出日志 | BG._execute() 创建 | s13 保留 |
| `.claude/scheduled_tasks.json` | 定时任务持久化 | CronScheduler._save_durable() 创建 | s14 保留 |
| `logs/` | 会话日志目录 | main 函数初始化创建 | s14 保留 |
| `logs/session_{timestamp}.log` | 会话日志文件 | _Tee 类写入 | s14 保留 |
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
├── detect_repo_root()  # 检测 git 仓库根目录
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
启动时显示 worktree 信息
├── print(f"[Repo root: {REPO_ROOT}]")
├── 检查 git 可用性
└── 列出已有 worktrees
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
                            └─ PostToolUse Hook 管线


Worktree 任务隔离流程
┌─────────────────────────────────────────────────────────────────┐
│                    主代理任务规划                                │
│  1. task_create(subject="实现功能 A")                           │
│     │                                                          │
│     ▼                                                          │
│  2. worktree_create(name="wt-feature-1", task_id=1)            │
│     │                                                          │
│     ├──► WorktreeManager.create()                              │
│     │     ├── 验证名称格式                                     │
│     │     ├── 检查是否已存在                                   │
│     │     ├── 检查任务是否存在                                 │
│     │     ├── events.emit("worktree.create.before")            │
│     │     ├── git worktree add -b wt/wt-feature-1 path HEAD    │
│     │     ├── 创建 entry 并保存 index.json                     │
│     │     ├── TASKS.bind_worktree(1, "wt-feature-1")           │
│     │     └── events.emit("worktree.create.after")             │
│     │                                                          │
│     ▼                                                          │
│  3. background_task(prompt="在 wt-feature-1 中实现功能 A")      │
│     │                                                          │
│     └──► 子代理执行（使用 bash 工具在 worktree 目录中操作）     │
│                                                                  │
│  4. worktree_run(name="wt-feature-1", command="git status")    │
│     │                                                          │
│     ├──► WorktreeManager.run()                                 │
│     │     ├── 检查危险命令                                     │
│     │     ├── 查找 worktree                                    │
│     │     ├── events.emit("worktree.run.before")               │
│     │     ├── subprocess.run(command, cwd=worktree_path)       │
│     │     └── events.emit("worktree.run.after")                │
│     │                                                          │
│     ▼                                                          │
│  5. worktree_closeout(name="wt-feature-1", action="remove",    │
│                       complete_task=True)                      │
│     │                                                          │
│     ├──► WorktreeManager.closeout()                            │
│     │     ├── action="remove" → 调用 remove()                  │
│     │     ├── events.emit("worktree.remove.before")            │
│     │     ├── git worktree remove path                         │
│     │     ├── TASKS.update(1, status="completed")              │
│     │     ├── TASKS.record_closeout(1, "removed", ...)         │
│     │     ├── 更新 entry (status="removed")                    │
│     │     └── events.emit("worktree.remove.after")             │
│     │                                                          │
│     ▼                                                          │
│  任务完成，worktree 已清理                                      │
└─────────────────────────────────────────────────────────────────┘


Worktree 状态流转图
┌──────────────┐
│   unbound    │  任务初始状态
│  (未绑定)    │
└──────┬───────┘
       │
       │ task_bind_worktree() 或 worktree_create(task_id=X)
       ▼
┌──────────────┐
│    active    │  worktree 正在使用中
│  (活跃)      │
└──────┬───────┘
       │
       ├─────────────────────┐
       │                     │
       │ worktree_closeout   │ worktree_closeout
       │ action="keep"       │ action="remove"
       ▼                     ▼
┌──────────────┐     ┌──────────────┐
│    kept      │     │   removed    │
│  (保留)      │     │  (已删除)    │
└──────────────┘     └──────────────┘
       │                     │
       │ 可再次使用          │ 可从 index 清理
       │                     │
       └─────────────────────┘


事件日志记录时序
主代理                      WorktreeManager           EventBus                  index.json
  │                              │                         │                         │
  │  worktree_create(name="wt-1", task_id=1)              │                         │
  │                              │                         │                         │
  │                              ├─ events.emit("worktree.create.before")          │
  │                              │                         │                         │
  │                              │                         ├─ events.jsonl 追加     │
  │                              │                         │  {"event": "worktree.create.before", ...}
  │                              │                         │                         │
  │                              ├─ git worktree add ...   │                         │
  │                              │                         │                         │
  │                              ├─ 创建 entry             │                         │
  │                              │                         │                         │
  │                              │                         │                         ├─ 保存 worktree 条目
  │                              │                         │                         │
  │                              ├─ TASKS.bind_worktree(1, "wt-1")                  │
  │                              │                         │                         │
  │                              ├─ events.emit("worktree.create.after")            │
  │                              │                         │                         │
  │                              │                         ├─ events.jsonl 追加     │
  │                              │                         │  {"event": "worktree.create.after", ...}
  │                              │                         │                         │
  │  返回 worktree 条目          │                         │                         │
  │◄─────────────────────────────┴─────────────────────────┴─────────────────────────┤
```

---

## 设计点总结

### 核心设计机制 1：git worktree 全生命周期管理

| 特性 | 实现方式 |
|------|----------|
| 创建 | `git worktree add -b {branch} {path} {base_ref}` |
| 进入 | 记录 last_entered_at 时间戳 |
| 运行命令 | subprocess.run(command, cwd=worktree_path) |
| 列出 | 读取 index.json 返回所有条目 |
| 状态 | 执行 `git status --short --branch` |
| 保留 | 更新 status="kept"，记录 closeout 信息 |
| 删除 | `git worktree remove {path}`，更新任务和索引 |
| closeout | 综合操作，支持 keep/remove 两种动作 |

### 核心设计机制 2：EventBus 事件日志

| 特性 | 实现方式 |
|------|----------|
| 格式 | JSONL（每行一个 JSON 对象） |
| 追加写入 | `with path.open("a")` 追加模式 |
| 时间戳 | time.time() 浮点时间戳 |
| 事件类型 | 14 种 worktree 生命周期事件 |
| 查询 | list_recent(limit) 返回最近 N 条 |
| 容错 | 解析失败时返回 {"event": "parse_error", "raw": line} |

### 核心设计机制 3：TaskManager worktree 绑定

| 字段 | 用途 | 状态流转 |
|------|------|----------|
| worktree | 当前绑定的 worktree 名称 | 空字符串 ↔ worktree 名称 |
| worktree_state | worktree 绑定状态 | unbound → active → kept/removed |
| last_worktree | 最后使用的 worktree 名称 | 记录历史，不解绑 |
| closeout | closeout 信息 | None → {"action", "reason", "at"} |

### 核心设计机制 4：.worktrees/ 目录结构

| 文件 | 用途 | 更新频率 |
|------|------|----------|
| index.json | worktree 索引 | 每次 worktree 创建/更新/删除 |
| events.jsonl | 生命周期事件日志 | 每次 worktree 操作 |
| worktrees/{name}/ | 实际 worktree 目录 | git worktree add/remove |

### 核心设计机制 5：worktree 工具集分层

| 工具类别 | 工具名 | 用途 |
|----------|--------|------|
| 创建 | worktree_create | 创建 worktree 并可选绑定任务 |
| 查询 | worktree_list | 列出所有 worktrees |
| 查询 | worktree_status | 查看单个 worktree 的 git 状态 |
| 进入 | worktree_enter | 进入 worktree（记录时间戳） |
| 执行 | worktree_run | 在 worktree 中运行命令 |
| 绑定 | task_bind_worktree | 将任务绑定到 worktree |
| 关闭 | worktree_closeout | 综合 closeout 操作（keep/remove） |
| 关闭 | worktree_keep | 保留 worktree |
| 关闭 | worktree_remove | 删除 worktree |
| 审计 | worktree_events | 查看事件日志 |

### 核心设计机制 6：线程安全与并发

| 组件 | 线程安全措施 |
|------|--------------|
| WorktreeManager | 单线程调用（主代理工具） |
| EventBus | 追加写入（原子操作） |
| TaskManager | 文件级原子写（_save 直接覆盖） |
| index.json | 读 - 改 - 写模式（无锁，单线程调用） |

---

## 整体设计思想总结

1. **物理隔离执行环境**：通过 git worktree 为每个任务提供独立的文件系统视图，避免并行任务间的文件冲突。

2. **生命周期可追溯**：EventBus 记录所有 worktree 操作的完整事件日志，便于审计和问题排查。

3. **任务与 worktree 绑定**：TaskManager 扩展 worktree 相关字段，建立任务与执行环境的关联关系。

4. **渐进式升级**：在 s14 定时任务调度系统基础上增加 worktree 支持，保留所有核心组件（CronScheduler、BackgroundManager、TaskManager 等）。

5. **工具集完整性**：提供 9 个 worktree 管理工具，覆盖 create/list/enter/run/status/closeout/keep/remove/events 全生命周期操作。

6. **并行开发分支**：chapter_18_2 是基于 s14 的并行分支，用于实验 worktree 任务隔离功能，而非按顺序从 chapter_15/16/17 演进。

---

## 与 s14 的关系

### 特殊版本说明

**chapter_18_2 是特殊章节**，代码基于 chapter_14 的 s14_cron_scheduler.py 直接修改，而非按顺序从 chapter_15/16/17 演进。这是一个**并行开发分支**，用于实验 worktree 任务隔离功能。

### 继承内容

s18_v2 完整保留 s14 的核心组件：
- CronScheduler 定时任务调度器（5 字段 cron 表达式）
- BackgroundManager 后台任务生命周期管理
- TaskManager 持久化任务 CRUD（增强 worktree 字段）
- 三层错误恢复机制（max_tokens、prompt_too_long、API 错误）
- SystemPromptBuilder 6 层结构化构建（增强 worktree 规则）
- MemoryManager 持久化记忆管理
- HookManager 拦截管线
- PermissionManager 权限管理
- BashSecurityValidator 安全验证
- 上下文压缩机制（micro_compact、compact_history）
- run_subagent_background() 异步并行子 agent 执行
- 事件驱动架构（input_reader + cron_watcher）
- _Tee 会话日志

### 变更内容

| 组件 | s14_cron_scheduler | s18_v2_singleagent_worktree_task_isolation |
|------|-------------------|-------------------------------------------|
| Git 仓库检测 | 无 | detect_repo_root() |
| 事件日志 | 无 | EventBus 类 |
| Worktree 管理 | 无 | WorktreeManager 类 |
| TaskManager 字段 | 基础字段 | + worktree/worktree_state/last_worktree/closeout |
| TaskManager 方法 | 基础 CRUD | + bind_worktree/unbind_worktree/record_closeout/exists |
| 主代理工具 | cron_* + task_* + background_* | + 9 个 worktree_* 工具 |
| 目录结构 | 无 .worktrees/ | + .worktrees/ 目录 |
| 启动时信息 | 无 worktree 信息 | + Repo root 和 worktree 列表 |

### 详细说明对比

关于 s14 定时任务调度系统的详细说明，参考：v1_task_manager/chapter_14/s14_cron_scheduler_文档.md

---

## 实践指南

### 运行方法

```bash
cd v1_task_manager/chapter_18_2
python s18_v2_singleagent_worktree_task_isolation.py
```

### Worktree 使用示例

#### 1. 创建 worktree 并绑定任务

```
/worktree_create name="wt-feature-1" task_id=1 base_ref="HEAD"
```

返回：
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

#### 2. 创建任务并绑定 worktree

```
/task_create subject="实现功能 A" description="在 wt-feature-1 中实现功能 A"
/worktree_create name="wt-feature-2" task_id=2
/task_bind_worktree task_id=2 worktree="wt-feature-2" owner="张三"
```

#### 3. 列出所有 worktrees

```
/worktree_list
```

返回：
```
[active] wt-feature-1 -> /path/to/.worktrees/wt-feature-1 (wt/wt-feature-1) task=1
[active] wt-feature-2 -> /path/to/.worktrees/wt-feature-2 (wt/wt-feature-2) task=2
```

#### 4. 进入 worktree

```
/worktree_enter name="wt-feature-1"
```

返回：更新后的 worktree 条目（包含 last_entered_at）

#### 5. 查看 worktree 状态

```
/worktree_status name="wt-feature-1"
```

返回：git status 输出

#### 6. 在 worktree 中运行命令

```
/worktree_run name="wt-feature-1" command="git status"
/worktree_run name="wt-feature-1" command="python -m pytest tests/"
```

返回：命令执行结果

#### 7. 保留 worktree

```
/worktree_keep name="wt-feature-1"
```

返回：更新后的 worktree 条目（status="kept"）

#### 8. 删除 worktree

```
/worktree_remove name="wt-feature-1" force=False complete_task=True reason="任务完成"
```

返回：`"Removed worktree 'wt-feature-1'"`

#### 9. closeout worktree（综合操作）

```
/worktree_closeout name="wt-feature-1" action="remove" reason="任务完成" force=False complete_task=True
/worktree_closeout name="wt-feature-2" action="keep" reason="需要后续跟进"
```

#### 10. 查看事件日志

```
/worktree_events limit=20
```

返回：最近 20 条事件的 JSON 列表

---

### 测试示例

#### 1. 验证 worktree 创建

```bash
# 启动程序
python s18_v2_singleagent_worktree_task_isolation.py

# 创建任务
/task_create subject="测试功能" description="测试 worktree 功能"

# 创建 worktree 并绑定任务
/worktree_create name="wt-test-1" task_id=1 base_ref="HEAD"

# 检查 .worktrees/index.json
cat .worktrees/index.json

# 检查 .worktrees/events.jsonl
cat .worktrees/events.jsonl

# 检查任务文件
cat .tasks/task_1.json
# 应包含 worktree、worktree_state、last_worktree 字段
```

#### 2. 验证 worktree 命令执行

```bash
# 在 worktree 中运行命令
/worktree_run name="wt-test-1" command="git status"
/worktree_run name="wt-test-1" command="ls -la"

# 查看事件日志
/worktree_events limit=10
# 应包含 worktree.run.before 和 worktree.run.after 事件
```

#### 3. 验证 worktree 关闭

```bash
# closeout worktree
/worktree_closeout name="wt-test-1" action="remove" reason="测试完成" complete_task=True

# 检查任务状态
/task_get task_id=1
# status 应为 "completed"，closeout 应有记录

# 检查事件日志
/worktree_events limit=5
# 应包含 worktree.closeout.remove、worktree.remove.before、worktree.remove.after 事件
```

#### 4. 验证非 git 仓库降级

```bash
# 在非 git 仓库目录启动
mkdir /tmp/test-non-git
cd /tmp/test-non-git
python /path/to/s18_v2_singleagent_worktree_task_isolation.py

# 输出应包含：
# [Repo root: /tmp/test-non-git]
# [Note: Not in a git repo. worktree_* tools will return errors.]

# 尝试创建 worktree 应返回错误
/worktree_create name="wt-test"
# 返回："Not in a git repository."
```

#### 5. 验证完整工作流

```bash
# 1. 创建任务
/task_create subject="实现功能 A"

# 2. 创建 worktree
/worktree_create name="wt-feature-a" task_id=1

# 3. 列出任务（验证 worktree 绑定）
/task_list
# 输出应包含：[>] #1: 实现功能 A wt=wt-feature-a

# 4. 在 worktree 中执行操作
/worktree_run name="wt-feature-a" command="echo 'Hello from worktree' > test.txt"
/worktree_run name="wt-feature-a" command="cat test.txt"

# 5. closeout worktree
/worktree_closeout name="wt-feature-a" action="remove" reason="功能完成" complete_task=True

# 6. 验证任务完成
/task_list
# 输出应包含：[x] #1: 实现功能 A

# 7. 查看事件日志
/worktree_events limit=20
# 应包含完整的生命周期事件
```

---

### Worktree 命名规范

| 规则 | 说明 | 示例 |
|------|------|------|
| 长度 | 1-40 字符 | ✓ wt-feature-1, ✗ a...a (41 字符) |
| 字符集 | 字母、数字、.、_、- | ✓ wt_feature.1, ✗ wt@feature |
| 推荐前缀 | wt- | wt-feature-1, wt-bugfix-123 |
| 推荐格式 | wt-{类型}-{标识} | wt-feature-login, wt-bugfix-456 |

---

### 常见工作流模式

#### 模式 1：单任务单 worktree

```
/task_create subject="功能 A"
/worktree_create name="wt-feature-a" task_id=1
# ... 在 worktree 中工作 ...
/worktree_closeout name="wt-feature-a" action="remove" complete_task=True
```

#### 模式 2：多任务并行 worktree

```
/task_create subject="功能 A"
/task_create subject="功能 B"
/worktree_create name="wt-feature-a" task_id=1
/worktree_create name="wt-feature-b" task_id=2
# ... 两个 worktree 并行工作 ...
/worktree_closeout name="wt-feature-a" action="remove" complete_task=True
/worktree_closeout name="wt-feature-b" action="remove" complete_task=True
```

#### 模式 3：保留 worktree 后续跟进

```
/task_create subject="功能 A"
/worktree_create name="wt-feature-a" task_id=1
# ... 阶段性工作 ...
/worktree_closeout name="wt-feature-a" action="keep" reason="待后续优化"
# ... 后续会话 ...
/worktree_enter name="wt-feature-a"
# ... 继续工作 ...
/worktree_closeout name="wt-feature-a" action="remove" complete_task=True
```

---

## 总结

### 核心设计思想

s18_v2 通过引入 WorktreeManager 和 EventBus，实现了基于 git worktree 的任务物理隔离执行环境。设计原则是**物理隔离**、**生命周期可追溯**和**任务与环境绑定**。

### 核心机制

1. detect_repo_root() 自动检测 git 仓库根目录
2. EventBus worktree 生命周期事件日志
3. WorktreeManager git worktree 全生命周期管理（9 个方法）
4. TaskManager worktree 字段扩展（worktree、worktree_state、last_worktree、closeout）
5. worktree_* 工具集（9 个主代理工具）
6. .worktrees/ 目录结构（index.json、events.jsonl、worktrees/）

### 版本说明

- **文件路径**：v1_task_manager/chapter_18_2/s18_v2_singleagent_worktree_task_isolation.py
- **核心改动**：worktree 任务隔离系统
- **继承内容**：s14 核心组件完整保留（CronScheduler、BackgroundManager、TaskManager 增强、Memory、Hook 等）
- **主题**：任务执行环境物理隔离
- **版本关系**：基于 s14 的并行开发分支（chapter_18_2 是特殊章节）

---

*文档版本：v1.0*
*基于代码：v1_task_manager/chapter_18_2/s18_v2_singleagent_worktree_task_isolation.py*