# s12: Task System (持久化任务系统)

## 概述

s12 在 s11 错误恢复机制的基础上进行了**任务管理系统升级**。核心改动是将内存中的 Todo 系统替换为基于文件持久化的 Task 系统，支持跨会话任务追踪、任务依赖关系管理和主/子代理职责分离。

### 核心改进

1. **TaskManager 类** - 核心改动，实现持久化任务 CRUD（存储在 `.tasks/` 目录）
2. **任务数据结构升级** - 从 PlanItem 升级为 TaskRecord（id, subject, description, status, blockedBy, blocks, owner 等）
3. **主/子代理职责分离** - Main Planner Agent 负责规划委派，Executing Subagent 负责执行
4. **工具集重构** - 移除 todo 工具，新增 task_create、task_update、task_list、task_get
5. **s11 功能完整保留** - 三层错误恢复、SystemPromptBuilder、MemoryManager 等核心组件无变化

### 代码文件路径

- **源代码**：v1_task_manager/chapter_12/s12_task_system.py
- **参考文档**：v1_task_manager/chapter_11/s11_Resume_system_文档.md
- **参考代码**：v1_task_manager/chapter_11/s11_Resume_system.py
- **任务目录**：`.tasks/`（工作区根目录下的隐藏目录）
- **记忆目录**：`.memory/`（工作区根目录下的隐藏目录）
- **技能目录**：`skills/`（工作区根目录下）
- **钩子配置**：`.hooks.json`（工作区根目录下的钩子拦截管线配置文件）
- **Claude 信任标记**：`.claude/.claude_trusted`（工作区根目录下的隐藏目录，用于标识受信任的工作区）

---

## s12 新增内容详解（按代码执行顺序）

### TaskManager 类（持久化任务 CRUD）

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

**核心方法**：

| 方法 | 功能 | 返回值 |
|------|------|--------|
| `get_items()` | 获取所有任务（列表） | list[dict] |
| `_max_id()` | 获取最大任务 ID | int |
| `_load(task_id)` | 加载单个任务 | dict |
| `_save(task)` | 保存任务到文件 | None |
| `create(subject, description)` | 创建新任务 | JSON 字符串 |
| `get(task_id)` | 获取任务详情 | JSON 字符串 |
| `update(task_id, ...)` | 更新任务状态/依赖 | JSON 字符串 |
| `list_all()` | 列出所有任务（格式化） | 格式化字符串 |
| `_clear_dependency(completed_id)` | 清除已完成任务的依赖 | None |

**存储结构**：
- 目录：`.tasks/`
- 文件命名：`task_<id>.json`
- 文件格式：JSON（带缩进，中文字符可见）

---

### 任务数据结构

**s11 PlanItem**：
```python
@dataclass
class PlanItem: 
    id: str                     # 标记任务 id
    content: str                # 这一步要做什么
    status: str = "pending"     # pending | in_progress | completed
    active_form: str = ""       # 进行时描述
```

**s12 TaskRecord**：
```python
task = {
    "id": int,                  # 任务 ID（自增整数）
    "subject": str,             # 任务主题（简短标题）
    "description": str,         # 任务详细描述
    "status": str,              # pending | in_progress | completed | deleted
    "blockedBy": list[int],     # 阻塞当前任务的任务 ID 列表
    "blocks": list[int],        # 被当前任务阻塞的任务 ID 列表
    "owner": str,               # 任务负责人
    "claim_role": str,          # 认领角色（可选）
    "worktree": str,            # 工作树状态（可选）
    "worktree_state": str,      # 工作树状态值（可选）
    "last_worktree": str,       # 上一个工作树（可选）
    "closeout": dict            # 关闭信息（可选）
}
```

**状态枚举**：
| 状态 | 标记 | 含义 |
|------|------|------|
| pending | `[ ]` | 等待执行 |
| in_progress | `[>]` | 正在执行 |
| completed | `[x]` | 已完成 |
| deleted | `[-]` | 已删除 |

**任务依赖关系**：
- `blockedBy`: 当前任务被哪些任务阻塞（前置任务）
- `blocks`: 当前任务阻塞哪些任务（后置任务）
- 双向关联：设置 `blocks` 时自动更新对应任务的 `blockedBy`
- 自动清理：任务完成时从所有任务的 `blockedBy` 中移除

---

### 主/子代理职责分离

**Main Planner Agent 核心指令**（`_build_core()`）：
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

**Executing Subagent 核心指令**（`_build_sub_core()`）：
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

**职责对比**：
| 职责 | Main Planner Agent | Executing Subagent |
|------|-------------------|-------------------|
| 任务规划 | ✓ | ✗ |
| 任务委派 | ✓ | ✗ |
| 结果验证 | ✓ | ✗ |
| 代码编写 | ✗ | ✓ |
| 文件编辑 | ✗ | ✓ |
| Shell 命令 | ✗ | ✓ |
| 上下文隔离 | 完整会话历史 | 独立新鲜上下文 |

---

### 工具集重构

**s11 工具集**：
| 工具 | 功能 |
|------|------|
| todo | 更新会话计划（内存） |
| task | 委派子代理 |
| read_file | 读取文件 |
| bash | 执行 Shell 命令 |
| write_file | 写入文件 |
| edit_file | 编辑文件 |
| load_skill | 加载技能 |
| compact | 压缩上下文 |
| save_memory | 保存记忆 |

**s12 工具集**：
| 工具 | 功能 | 变化 |
|------|------|------|
| task_create | 创建新任务 | 新增 |
| task_update | 更新任务状态/依赖 | 新增 |
| task_list | 列出所有任务 | 新增 |
| task_get | 获取任务详情 | 新增 |
| task | 委派子代理 | 保留 |
| read_file | 读取文件 | 保留 |
| bash | 执行 Shell 命令 | 保留（主代理无） |
| write_file | 写入文件 | 保留（主代理无） |
| edit_file | 编辑文件 | 保留（主代理无） |
| load_skill | 加载技能 | 保留 |
| compact | 压缩上下文 | 保留 |
| save_memory | 保存记忆 | 保留 |
| todo | 更新会话计划 | 移除 |

**PARENT_TOOLS（主代理工具）**：
```python
PARENT_TOOLS = [
    {"name": "read_file", ...},
    {"name": "task", ...},           # 委派子代理
    {"name": "compact", ...},
    {"name": "save_memory", ...},
    {"name": "task_create", ...},    # 新增
    {"name": "task_update", ...},    # 新增
    {"name": "task_list", ...},      # 新增
    {"name": "task_get", ...},       # 新增
]
```

**CHILD_TOOLS（子代理工具）**：
```python
CHILD_TOOLS = [
    {"name": "bash", ...},
    {"name": "read_file", ...},
    {"name": "write_file", ...},
    {"name": "edit_file", ...},
    {"name": "load_skill", ...},
    {"name": "compact", ...},
    # 无 task_* 工具（子代理不管理任务）
]
```

---

### 任务依赖关系管理

**update() 方法中的依赖处理**：
```python
def update(self, task_id: int, status: str = None, owner: str = None,
           add_blocked_by: list = None, add_blocks: list = None) -> str:
    task = self._load(task_id)
    
    # 更新状态
    if status:
        task["status"] = status
        # 任务完成时，从所有其他任务的 blockedBy 中移除
        if status == "completed":
            self._clear_dependency(task_id)
    
    # 添加前置依赖
    if add_blocked_by:
        task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
    
    # 添加后置依赖（双向更新）
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

**依赖清除机制**：
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

### 保留功能（从 s11 继承）

| 组件 | 状态 | 说明 |
|------|------|------|
| 三层错误恢复 | 完整保留 | max_tokens、prompt_too_long、API 错误 |
| SystemPromptBuilder | 保留（核心指令更新） | 6 层结构化构建，主/子代理不同核心指令 |
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

| 目录/文件 | 用途 | 创建方式 |
|-----------|------|----------|
| `.tasks/` | 持久化任务存储 | TaskManager 自动创建 |
| `.tasks/task_*.json` | 单个任务文件 | TaskManager._save() 创建 |
| `skills/` | 技能文档 | 手动创建 |
| `.memory/` | 持久化记忆 | MemoryManager 自动创建 |
| `.memory/MEMORY.md` | 记忆索引 | _rebuild_index() 重建 |
| `.memory/*.md` | 单个记忆文件 | save_memory() 创建 |
| `.transcripts/` | 会话转录 | write_transcript() 创建 |
| `.task_outputs/tool-results/` | 大型工具输出 | persist_large_output() 创建 |
| `.hooks.json` | 钩子配置 | 手动创建 |
| `.claude/.claude_trusted` | 工作区信任标记 | 手动创建 |

---

## 完整框架流程图

```
会话启动
    │
    ▼
加载组件
├── MemoryManager.load_all()
├── TaskManager(TASKS_DIR)
├── HookManager(perms)
└── SystemPromptBuilder
    │
    ▼
用户输入
    │
    ▼
agent_loop(state, compact_state)
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
│   │   │   ├── task_create -> TASKS.create()
│   │   │   ├── task_update -> TASKS.update()
│   │   │   ├── task_list -> TASKS.list_all()
│   │   │   ├── task_get -> TASKS.get()
│   │   │   ├── task -> run_subagent()
│   │   │   ├── read_file -> run_read()
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
run_subagent() (当调用 task 工具时)
│   - 构建子代理系统提示 (sub_build)
│   - 独立消息历史
│   - 独立循环 (最多 30 步)
│   - 返回执行摘要
    │
    ▼
循环继续或退出


任务管理数据流
┌─────────────────────────────────────────────────────────────┐
│                      .tasks/ 目录                           │
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
│                    依赖关系图                                │
│                    Task1 → Task2 → Task3                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 设计点总结

### 核心设计机制 1：持久化任务存储

| 特性 | 实现方式 |
|------|----------|
| 存储介质 | 文件系统（`.tasks/` 目录） |
| 文件格式 | JSON（每个任务独立文件） |
| ID 生成 | 自增整数（基于已有文件最大 ID） |
| 跨会话 | 支持（文件持久化） |
| 并发安全 | 单进程场景（无文件锁） |

### 核心设计机制 2：任务依赖图

| 关系类型 | 字段 | 更新方式 |
|----------|------|----------|
| 前置依赖 | blockedBy | 添加时单向更新 |
| 后置依赖 | blocks | 添加时双向更新 |
| 自动清理 | - | 任务完成时清除所有 blockedBy 引用 |

### 核心设计机制 3：主/子代理分离

| 维度 | Main Planner Agent | Executing Subagent |
|------|-------------------|-------------------|
| 系统提示 | main_build() | sub_build() |
| 工具集 | PARENT_TOOLS | CHILD_TOOLS |
| 上下文 | 完整会话历史 | 独立新鲜上下文 |
| 职责 | 规划、委派、验证 | 执行、编码、操作 |
| 任务管理 | 有（task_* 工具） | 无 |

### 核心设计机制 4：工具权限分离

| 工具类别 | 主代理 | 子代理 |
|----------|--------|--------|
| 任务管理 | ✓ | ✗ |
| 文件读取 | ✓ | ✓ |
| 文件写入 | ✗ | ✓ |
| Shell 命令 | ✗ | ✓ |
| 技能加载 | ✗ | ✓ |

### 核心设计机制 5：任务提醒机制

```python
# 工具使用后检测
if used_task_manager:
    TASKS.rounds_since_update = 0
    reminder = None
else:
    TASKS.rounds_since_update += 1
    if TASKS.rounds_since_update >= PLAN_REMINDER_INTERVAL:
        reminder = "Refresh your current task list (task_list) or update task statuses before continuing."
```

---

## 整体设计思想总结

1. **持久化优先**：任务状态存储于文件系统，支持跨会话追踪。

2. **职责分离**：主代理负责规划验证，子代理负责执行操作。

3. **依赖显式化**：任务依赖关系通过 blockedBy/blocks 字段明确表达。

4. **工具集分层**：主/子代理使用不同工具集，防止职责混淆。

5. **状态可追踪**：任务 ID 自增、状态枚举、依赖关系图。

6. **渐进式升级**：在 s11 错误恢复机制基础上增加任务管理，保留所有核心组件。

---

## 与 s11 的关系

### 继承内容

s12 完整保留 s11 的核心组件：
- 三层错误恢复机制（max_tokens、prompt_too_long、API 错误）
- SystemPromptBuilder 6 层结构化构建
- MemoryManager 持久化记忆管理
- HookManager 拦截管线
- PermissionManager 权限管理
- BashSecurityValidator 安全验证
- 上下文压缩机制（micro_compact、compact_history）

### 变更内容

| 组件 | s11 | s12 |
|------|-----|-----|
| 任务管理 | TodoManager (内存会话级) | TaskManager (持久化跨会话) |
| 工具集 | todo | task_create/update/list/get |
| 代理模型 | 通用 coding agent | Main Planner + Executing Subagent |

### 详细说明对比

关于 s11 错误恢复机制的详细说明，参考：v1_task_manager/chapter_11/s11_Resume_system_文档.md

---

## 实践指南

### 运行方法

```bash
cd v1_task_manager/chapter_12
python s12_task_system.py
```

### 任务管理示例

#### 1. 创建任务

```
/task_create subject="编写文档" description="为 s12 创建 Markdown 文档"
```

返回：
```json
{
  "id": 1,
  "subject": "编写文档",
  "description": "为 s12 创建 Markdown 文档",
  "status": "pending",
  "blockedBy": [],
  "blocks": [],
  "owner": ""
}
```

#### 2. 更新任务状态

```
/task_update task_id=1 status="in_progress" owner="Hestal"
```

返回：
```json
{
  "id": 1,
  "subject": "编写文档",
  "description": "为 s12 创建 Markdown 文档",
  "status": "in_progress",
  "blockedBy": [],
  "blocks": [],
  "owner": "Hestal"
}
```

#### 3. 设置任务依赖

```
/task_update task_id=2 addBlockedBy=[1]
```

Task2 被 Task1 阻塞，Task1 完成后 Task2 才能开始。

#### 4. 列出所有任务

```
/task_list
```

返回：
```
[>] #1: 编写文档 owner=Hestal
[ ] #2: 验证文档格式 (blocked by: [1])
```

#### 5. 委派子代理

```
/task prompt="读取 s12_task_system.py 并分析 TaskManager 类的实现"
```

---

### 测试示例

#### 1. 验证持久化

```bash
# 创建任务后检查 .tasks/ 目录
ls -la .tasks/
# 输出：task_1.json

# 重启程序后任务仍存在
python s12_task_system.py
/task_list
# 输出：之前的任务列表
```

#### 2. 验证依赖关系

```bash
# 创建 Task1 和 Task2
/task_create subject="Task1"
/task_create subject="Task2"

# 设置依赖：Task2 被 Task1 阻塞
/task_update task_id=1 addBlocks=[2]

# 检查 Task2
/task_get task_id=2
# 输出包含："blockedBy": [1]
```

#### 3. 验证主/子代理分离

观察日志输出：
- 主代理调用：`[Tool: task_create]`、`[Tool: task_update]`
- 子代理调用：`[Tool: write_file]`、`[Tool: bash]`
- 子代理启动：`> Spawning Subagent : ...`

---

## 总结

### 核心设计思想

s12 通过将内存 Todo 系统升级为持久化 Task 系统，实现了跨会话任务追踪和任务依赖关系管理。设计原则是**持久化存储**、**职责分离**和**依赖显式化**。

### 核心机制

1. TaskManager 持久化 CRUD
2. 任务依赖图（blockedBy/blocks）
3. 主/子代理职责分离
4. 工具集分层
5. 任务提醒机制

### 版本说明

- **文件路径**：v1_task_manager/chapter_12/s12_task_system.py
- **核心改动**：持久化任务系统（TaskManager）
- **继承内容**：s11 核心组件完整保留（错误恢复、Memory、Hook 等）
- **主题**：持久化任务系统

---

*文档版本：v1.0*
*基于代码：v1_task_manager/chapter_12/s12_task_system.py*
