# s04: Todo Write (任务管理) - 代码文档

---

## 概述

### 核心改进

**从单步执行到多步骤任务规划**

s04 在 s03 的基础上引入了 **Todo 任务管理系统**，使模型能够规划和管理多步骤复杂任务。这解决了单次工具调用无法完成复杂需求的问题。

### 设计思想

> **"Plan complex tasks, track progress, and maintain state across turns."**

s04 的核心设计思想：**Task Decomposition + State Tracking（任务拆解 + 状态追踪）**。通过以下机制实现：

- **任务拆解**：模型使用 `todo` 工具将复杂需求分解为有序的步骤列表
- **状态追踪**：每个任务项有明确的状态（pending/in_progress/completed）
- **定期提醒**：系统定期提醒模型更新计划，保持计划的时效性
- **单一 in_progress 约束**：同一时间最多一个任务项处于进行中，确保焦点集中

### 代码文件路径

```
v1_task_manager/chapter_04/s04_todo_write.py
```

### 核心架构图（对比 s03）

**s03 架构（单步执行）**：
```
    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch    |
    |  prompt  |      |       |      | {bash, read,     |
    +----------+      +---+---+      |  write, edit,    |
                          ^          |  load_skill}     |
                          |          +------------------+
                          +-----------------+
                               tool_result
```

**s04 架构（任务规划 + 执行）**：
```
    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | 判断是否需要规划 |
    |  prompt  |      |       |      +--------+---------+
    +----------+      +---+---+               |
                          ^                   | 需要规划
                          |            +------v------+
                    +-----+-----+      |   todo      |
                    |  Reminder | <----|   Tool      |
                    |  (定期)   |      +------+------+
                    +-----+-----+             |
                          |                   | 创建/更新计划
                          |            +------v------+
                          |            | TodoManager |
                          |            |  state.items|
                          |            +------+------+
                          |                   |
                          +-------------------+
                          | 不需要规划/规划完成
                          v
                    +------------------+
                    | Tool Dispatch    |
                    | {bash, read,     |
                    |  write, edit,    |
                    |  load_skill,     |
                    |  todo}           |
                    +------------------+
```

**架构说明**：
1. 系统初始化时创建 `TodoManager` 实例，管理任务计划状态
2. LLM 接收用户任务后，判断是否需要多步骤规划
3. 如需要规划，调用 `todo` 工具创建任务列表
4. `TodoManager` 验证并存储计划，重置提醒计数器
5. 每轮未使用 `todo` 时，提醒计数器递增
6. 达到阈值（3 轮）时，系统插入 reminder 消息提醒更新计划
7. 模型基于计划逐步执行任务，更新任务状态

---

## 与 s03 的对比

### 变更总览

| 组件 | s03 | s04 | 变化说明 |
|------|-----|-----|----------|
| **导入模块** | 标准库 + `re` | + `time` | 新增 time 模块（代码中导入但未使用） |
| **数据结构** | `SkillLoader` 类 | + `PlanItem`, `PlanningState` | 新增任务项和计划状态数据类 |
| **任务管理** | 无 | `TodoManager` 类 | 新增任务管理器，维护计划状态 |
| **工具集** | 5 个工具 | 6 个工具 | 新增 `todo` 工具 |
| **execute_tool_calls** | 返回 `list[dict]` | 返回 `tuple[list[dict], str\|None]` | 新增 reminder 返回值 |
| **run_one_turn** | 简单追加 tool_result | 处理 reminder 系统消息 | 支持插入提醒消息 |
| **SYSTEM 提示词** | 工具使用指导 | + 4 条任务规划原则 | 新增 todo 使用指导 |

### 新增组件架构

```
    PlanItem 数据类
    ├── id: str           # 任务唯一标识
    ├── content: str      # 任务内容描述
    ├── status: str       # "pending" | "in_progress" | "completed"
    └── active_form: str  # 进行时描述（可选）

    PlanningState 数据类
    ├── items: list[PlanItem]          # 任务项列表
    └── rounds_since_update: int       # 未更新计划的轮数

    TodoManager 类
    ├── state: PlanningState           # 计划状态
    ├── update(items)                  # 创建/更新计划
    ├── note_round_without_update()    # 记录未更新轮数
    ├── reminder()                     # 检查是否需要提醒
    └── render()                       # 渲染计划显示

    全局实例
    └── TODO = TodoManager()           # 单例任务管理器
```

---

## 按执行顺序详解

### 第 1 阶段：任务数据结构定义

#### PlanItem 数据类

**机制概述**：
`PlanItem` 是任务计划的基本单位，表示多步骤任务中的单个步骤。每个任务项包含唯一标识、内容描述、执行状态和可选的进行时描述。

```python
@dataclass
class PlanItem: 
    id: str                     # 标记任务 id，便于辨识
    content: str                # 这一步要做什么
    status: str = "pending"     # "pending" | "in_progress" | "completed"
    active_form: str = ""       # 当它正在进行中时，可以用更自然的进行时描述
```

**字段说明**：
- `id`：字符串类型的唯一标识，用于在工具调用中引用特定任务项
- `content`：任务步骤的具体内容描述，如"创建项目目录"
- `status`：任务状态，三态枚举：
  - `"pending"`：尚未开始
  - `"in_progress"`：正在执行
  - `"completed"`：已完成
- `active_form`：可选字段，提供进行时态的自然语言描述，如"正在创建目录"

**状态流转**：
```
pending ──────> in_progress ──────> completed
   ^                                    |
   └────────────────────────────────────┘
              (重置/返工)
```

**设计思想**：
- **显式状态管理**：通过 status 字段明确追踪每个步骤的执行进度
- **标识符分离**：id 与 content 分离，便于工具调用和状态更新
- **人性化描述**：active_form 提供更自然的进度展示，增强用户体验
- **默认值设计**：status 默认为"pending"，active_form 默认为空，简化创建

---

#### PlanningState 数据类

**机制概述**：
`PlanningState` 是任务计划的容器，存储所有任务项列表和提醒计数器。它是 `TodoManager` 的内部状态，不直接暴露给外部。

```python
@dataclass
class PlanningState:
    items: list[PlanItem] = field(default_factory=list)
    rounds_since_update: int = 0  # 连续多少轮过去了，模型还没有更新这份计划
```

**字段说明**：
- `items`：PlanItem 列表，按执行顺序存储所有任务步骤
- `rounds_since_update`：自上次更新计划以来经过的对话轮数，用于提醒机制

**设计思想**：
- **状态封装**：将计划相关的所有状态集中管理
- **提醒计数**：通过 rounds_since_update 实现定期提醒，防止计划过时
- **默认工厂**：使用 `field(default_factory=list)` 避免可变默认参数的陷阱

---

### 第 3 阶段：TodoManager 类详解

#### 类结构与初始化

**机制概述**：
`TodoManager` 是任务管理系统的核心类，负责维护计划状态、验证更新、追踪轮数和生成提醒。它采用单例模式，全局只有一个实例。

```python
class TodoManager:
    def __init__(self):
        self.state = PlanningState()
```

**全局实例**：
```python
TODO = TodoManager()  # 全局单例
```

**设计思想**：
- **单例模式**：确保整个会话中只有一个计划状态，避免状态不一致
- **状态隔离**：每个运行的脚本有独立的 TODO 实例，多用户场景互不干扰

---

#### update() 方法

**机制概述**：
`update()` 是 `todo` 工具的处理函数，接收模型发送的任务列表，验证后更新计划状态。验证包括：数量限制、字段完整性、状态合法性、单一 in_progress 约束。

```python
def update(self, items: list) -> str:
    if len(items) > 20:
        return f"Error: Too many plan items ({len(items)}). Maximum allowed is 20. Please reduce the number of steps."
    
    normalized = []
    in_progress_count = 0
    for index, raw_item in enumerate(items):
        id = str(raw_item.get("id", "")).strip()
        content = str(raw_item.get("content", "")).strip()
        status = str(raw_item.get("status", "pending")).lower()
        active_form = str(raw_item.get("activeForm", "")).strip()
        
        if not id:
            return f"Error: Item {id} missing 'id' field."
        if not content:
            return f"Error: Item {index} missing 'content' field."
        if status not in {"pending", "in_progress", "completed"}:
            return f"Error: Item {index} has invalid status '{status}'. status should be in pending, in_progress, completed"
        
        if status == "in_progress":
            in_progress_count += 1
        
        normalized.append(PlanItem(
            id=id,
            content=content,
            status=status,
            active_form=active_form,
        ))
    
    if in_progress_count > 1:
        return "Error: Only one plan item can be in_progress at a time."
    
    self.state.items = normalized
    self.state.rounds_since_update = 0
    return self.render()
```

**验证逻辑**：
1. **数量限制**：最多 20 个任务项，防止计划过于复杂
2. **字段验证**：检查 `id` 和 `content` 字段存在且非空
3. **状态验证**：status 必须是三个合法值之一
4. **单一 in_progress**：同一时间最多一个任务项处于进行中

**返回值**：
- 成功：返回渲染后的计划文本
- 失败：返回错误信息字符串

**设计思想**：
- **防御性编程**：在接收外部输入时进行严格验证
- **错误友好**：返回明确的错误信息，指导模型修正
- **状态重置**：成功更新后重置提醒计数器
- **camelCase 兼容**：接受 `activeForm`（JSON 风格）而非 `active_form`

---

#### note_round_without_update() 方法

**机制概述**：
每轮对话中，如果模型未调用 `todo` 工具，则调用此方法递增提醒计数器。用于追踪计划的新鲜度。

```python
def note_round_without_update(self) -> None:
    self.state.rounds_since_update += 1
```

**设计思想**：
- **隐式追踪**：无需模型显式报告进度，系统自动追踪
- **简单计数**：使用整数计数器，避免复杂的时间计算

---

#### reminder() 方法

**机制概述**：
检查是否需要提醒模型更新计划。当计划存在且超过设定轮数未更新时，返回提醒消息；否则返回 None。

```python
PLAN_REMINDER_INTERVAL = 3  # 全局常量

def reminder(self) -> str | None:
    if not self.state.items:
        return None
    if self.state.rounds_since_update < PLAN_REMINDER_INTERVAL:
        return None
    return "<reminder>Refresh your current plan before continuing.</reminder>"
```

**触发条件**：
1. 计划列表非空（已有任务规划）
2. 连续未更新轮数 >= 3（PLAN_REMINDER_INTERVAL）

**返回值**：
- 需要提醒：返回 XML 格式的提醒消息
- 无需提醒：返回 None

**设计思想**：
- **定期同步**：防止模型长时间不更新计划，导致计划与实际进度脱节
- **温和提醒**：使用 XML 标签标识，便于系统识别和处理
- **阈值可调**：通过全局常量控制提醒频率

---

#### render() 方法

**机制概述**：
将当前计划渲染为人类可读的文本格式，用于返回给模型和展示给用户。使用符号标记不同状态的任务项，并显示完成进度。

```python
def render(self) -> str:
    if not self.state.items:
        return "No session plan yet."
    
    lines = []
    for item in self.state.items:
        marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]",}[item.status]
        line = f"{marker} {item.content}"
        if item.status == "in_progress" and item.active_form:
            line += f" ({item.active_form})"
        lines.append(line)
    
    completed = sum(1 for item in self.state.items if item.status == "completed")
    lines.append(f"\n({completed}/{len(self.state.items)} completed)")
    return "\n".join(lines)
```

**输出示例**：
```
[ ] 创建项目目录
[>] 编写主程序代码 (正在实现核心功能)
[ ] 编写测试用例
[x] 安装依赖包

(1/4 completed)
```

**符号说明**：
- `[ ]`：pending，尚未开始
- `[>]`：in_progress，正在进行
- `[x]`：completed，已完成

**设计思想**：
- **视觉区分**：使用不同符号直观展示任务状态
- **进度汇总**：底部显示完成进度，提供整体概览
- **可选详情**：active_form 仅在 in_progress 状态时显示，避免冗余

---

### 第 4 阶段：新增工具 - todo

#### 工具功能说明

**机制概述**：
`todo` 工具允许模型创建或重写当前会话的任务计划。它接收一个任务项列表，每个任务项包含 id、content、status 和可选的 activeForm。工具调用 `TodoManager.update()` 进行验证和存储。

**使用场景**：
1. 接收复杂多步骤任务时，先规划再执行
2. 任务执行过程中，根据实际情况调整计划
3. 收到系统提醒时，刷新计划状态

**工具处理函数**：
```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_REGISTRY.load_full_text(kw["name"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),  # 新增
}
```

---

#### JSON Schema 定义

**机制概述**：
`todo` 工具的参数定义使用 JSON Schema 格式，描述模型调用工具时应提供的参数结构。

```python
{"type": "function", "function": {
    "name": "todo",
    "description": "Create or Rewrite the current session plan for multi-step work.",
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "content": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        "activeForm": {
                            "type": "string",
                            "description": "Optional present-continuous label.",
                        },
                    },
                    "required": ["id", "content", "status"]
                }
            }
        },
        "required": ["items"]
    }
}}
```

**参数说明**：
- `items`（必需）：任务项数组
  - `id`（必需）：任务唯一标识符
  - `content`（必需）：任务内容描述
  - `status`（必需）：任务状态，枚举值
  - `activeForm`（可选）：进行时描述

**设计思想**：
- **明确约束**：使用 `enum` 限制 status 的合法值
- **必需字段**：只要求 id、content、status，降低使用门槛
- **描述清晰**：工具描述说明使用场景（multi-step work）

---

### 第 5 阶段：execute_tool_calls 优化

#### used_todo 标记

**机制概述**：
`execute_tool_calls` 函数新增 `used_todo` 标记，追踪本轮对话中模型是否调用了 `todo` 工具。该标记决定是重置提醒计数器还是递增计数器。

```python
def execute_tool_calls(response_content) -> tuple[list[dict], str | None]:
    used_todo = False
    results = []
    
    for tool_call in response_content.tool_calls:
        f_name = tool_call.function.name
        # ... 执行工具调用 ...
        
        if f_name == "todo":
            used_todo = True
    
    if used_todo:
        reminder = None
    else:
        TODO.note_round_without_update()
        reminder = TODO.reminder()
    
    return results, reminder
```

**设计思想**：
- **显式追踪**：通过布尔标记记录 todo 使用情况
- **自动更新**：调用 `todo` 时，`update()` 方法已重置计数器，无需额外操作
- **隐式递增**：未调用 todo 时，自动递增计数器并检查提醒

---

#### reminder 返回机制

**机制概述**：
`execute_tool_calls` 函数的返回值从 `list[dict]` 改为 `tuple[list[dict], str|None]`，新增第二个返回值用于传递提醒消息。

**s03 返回值**：
```python
def execute_tool_calls(response_content) -> list[dict]:
    # ...
    return results
```

**s04 返回值**：
```python
def execute_tool_calls(response_content) -> tuple[list[dict], str | None]:
    # ...
    return results, reminder
```

**设计思想**：
- **最小侵入**：通过返回值传递提醒，避免修改全局状态
- **类型安全**：使用 `str | None` 明确表示可能有或无提醒

---

### 第 6 阶段：run_one_turn 变化

#### reminder 消息处理

**机制概述**：
`run_one_turn` 函数接收 `execute_tool_calls` 返回的 reminder，如果存在则作为系统消息插入到消息历史中。

```python
def run_one_turn(state: LoopState) -> bool:
    # ... 调用 LLM ...
    
    if response_messages.tool_calls:
        results, reminder = execute_tool_calls(response_messages)  # 接收 reminder
        
        if not results:
            state.transition_reason = None
            return False
        
        if reminder:
            state.messages.append({
                "role": "system",
                "content": reminder,
            })
        
        for tool_result in results:
            state.messages.append(tool_result)
        
        state.turn_count += 1
        state.transition_reason = "tool_result"
        return True
    # ...
```

**系统消息插入**：
```python
state.messages.append({
    "role": "system",
    "content": "<reminder>Refresh your current plan before continuing.</reminder>",
})
```

**设计思想**：
- **系统级提醒**：使用 system role，强调提醒的重要性
- **非阻塞**：提醒消息插入后继续处理 tool_result，不影响正常流程
- **XML 格式**：使用 XML 标签包裹，便于模型识别和解析

---

### 第 7 阶段：SYSTEM 提示词变化

#### s03 vs s04 对比

**s03 SYSTEM 提示词**：
```python
SYSTEM = f"""You are a coding agent at {WORKDIR}.
1. Use the tool to finish tasks. Act first, then report clearly.
2. Use load_skill when a task needs specialized instructions before you act.
Skills available:
{SKILL_REGISTRY.describe_available()}"""
```

**s04 SYSTEM 提示词**：
```python
SYSTEM = f"""You are a coding agent at {WORKDIR}.
1.Use the todo tool to plan complex and multi-step tasks. Mark in_progress before starting, completed when done. Keep exactly one step in_progress when a task has multiple steps.
2.Use tools to solve tasks. Act, after executing the command, tell me that it has been completed.
3.Refresh the plan as work advances. Prefer tools over prose.
4.Use load_skill when a task needs specialized instructions before you act. Skills available: {SKILL_REGISTRY.describe_available()}"""
```

#### 4 条指导原则说明

**原则 1：任务规划**
```
Use the todo tool to plan complex and multi-step tasks. 
Mark in_progress before starting, completed when done. 
Keep exactly one step in_progress when a task has multiple steps.
```
- 明确使用场景：complex and multi-step tasks
- 状态标记要求：开始前标记 in_progress，完成后标记 completed
- 单一焦点约束：保持 exactly one step in_progress

**原则 2：工具优先**
```
Use tools to solve tasks. Act, after executing the command, tell me that it has been completed.
```
- 行动优先：先执行再报告
- 明确反馈：执行完成后告知用户

**原则 3：计划更新**
```
Refresh the plan as work advances. Prefer tools over prose.
```
- 动态更新：随着工作推进刷新计划
- 工具优先：使用工具而非纯文本描述

**原则 4：技能加载**（继承自 s03）
```
Use load_skill when a task needs specialized instructions before you act.
```
- 按需加载：需要领域知识时先加载技能

**设计思想**：
- **递进指导**：从规划到执行到更新，覆盖完整工作流
- **明确约束**：给出具体可执行的指导，而非抽象建议
- **继承扩展**：保留 s03 的技能加载指导，新增任务规划指导

---

## 完整框架流程图

```
┌─────────────┐
│    User     │  输入："帮我创建一个实时显示当前时间的网页，放在 time_page 目录中"
└──────┬──────┘
       │
       ▼
┌─────────────┐
│     LLM     │  分析任务复杂度
│  (接收任务) │  → 判断为多步骤任务
└──────┬──────┘
       │
       │ 需要规划
       ▼
┌─────────────┐
│  todo 工具  │  调用：todo(items=[
│  (创建计划) │    {"id":"1","content":"创建目录","status":"pending"},
│             │    {"id":"2","content":"编写 HTML","status":"pending"},
│             │    {"id":"3","content":"编写 JS","status":"pending"},
│             │    {"id":"4","content":"测试","status":"pending"}
│             │  ])
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ TodoManager │  验证并存储计划
│  .update()  │  → 返回渲染后的计划
└──────┬──────┘
       │
       ▼
┌─────────────┐
│     LLM     │  接收计划，开始执行
│  (执行阶段) │  → 更新 task 1 为 in_progress
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  bash 工具  │  执行：mkdir -p time_page
└──────┬──────┘
       │
       ▼
┌─────────────┐
│     LLM     │  更新 task 1 为 completed
│  (更新状态) │  更新 task 2 为 in_progress
└──────┬──────┘
       │
       │ ... 重复执行 ...
       │
       ▼
┌─────────────┐
│  Reminder   │  3 轮未更新计划时触发
│  (定期提醒) │  → "<reminder>Refresh your plan...</reminder>"
└──────┬──────┘
       │
       ▼
┌─────────────┐
│     LLM     │  收到提醒，刷新计划状态
│  (响应提醒) │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  所有任务   │  输出最终结果
│   完成      │
└─────────────┘
```

---

## 设计点总结

### 任务拆解原则

**核心思想**：将复杂任务分解为可独立执行的小步骤。

**拆解标准**：
- **原子性**：每个步骤应足够小，可单次工具调用完成
- **顺序性**：步骤之间有明确的先后依赖关系
- **可验证**：每个步骤完成后有明确的验证标准
- **数量控制**：不超过 20 个步骤，避免过度复杂

**示例**：
```
❌ 过度粗糙：
  1. 创建网页

✅ 合理拆解：
  1. 创建项目目录
  2. 创建 HTML 文件
  3. 创建 CSS 文件
  4. 创建 JavaScript 文件
  5. 测试网页功能
```

---

### 状态追踪机制

**核心思想**：通过显式状态标记追踪任务进度。

**状态定义**：
```
pending     → 尚未开始，等待执行
in_progress → 正在执行，当前焦点
completed   → 已完成，可验证
```

**状态流转规则**：
1. 新创建的任务默认为 pending
2. 开始执行前，必须将任务标记为 in_progress
3. 执行完成后，立即标记为 completed
4. 同一时间最多一个任务为 in_progress

**设计优势**：
- **进度可见**：用户和模型都能清晰了解当前进度
- **焦点管理**：单一 in_progress 约束避免多任务并行导致的混乱
- **错误恢复**：失败的任务可以重新标记为 pending 或 in_progress

---

### 定期提醒设计

**核心思想**：防止计划与实际进度脱节，强制定期同步。

**触发条件**：
```python
PLAN_REMINDER_INTERVAL = 3  # 3 轮未更新则提醒

if rounds_since_update >= 3 and items 非空:
    触发提醒
```

**提醒内容**：
```xml
<reminder>Refresh your current plan before continuing.</reminder>
```

**设计优势**：
- **防止遗忘**：避免模型忘记更新计划，导致计划过时
- **节奏控制**：强制模型定期回顾整体进度
- **温和干预**：使用提醒而非强制，保留模型灵活性

**潜在问题**：
- 固定阈值可能不适合所有场景
- 简单计数未考虑任务复杂度
- 可能打断模型的执行流

---

### 单一 in_progress 约束

**核心思想**：同一时间最多一个任务项处于进行中。

**验证逻辑**：
```python
in_progress_count = 0
for item in items:
    if item.status == "in_progress":
        in_progress_count += 1

if in_progress_count > 1:
    return "Error: Only one plan item can be in_progress at a time."
```

**设计理由**：
1. **焦点集中**：避免模型同时处理多个任务，降低出错概率
2. **顺序执行**：确保任务按依赖顺序执行
3. **简化追踪**：明确当前应该执行的任务，减少歧义
4. **进度清晰**：用户能清楚知道当前正在做什么

**例外情况**：
- 当前设计不支持并行任务
- 如需并行，应设计子任务系统

---

## 整体设计思想总结

### 1. 任务显式化（Explicit Task Management）

将隐式的执行计划显式化为数据结构：
- 任务项列表明确存储每个步骤
- 状态字段追踪执行进度
- 模型和用户都能看到完整计划

**优势**：可审计、可追踪、可调整

---

### 2. 状态驱动执行（State-Driven Execution）

通过状态变化驱动任务推进：
```
pending → in_progress → completed
```

**优势**：
- 明确的进度指标
- 便于错误恢复
- 支持断点续做

---

### 3. 约束引导行为（Constraint-Guided Behavior）

通过系统约束引导模型正确行为：
- 单一 in_progress 约束 → 强制顺序执行
- 提醒机制 → 强制定期同步
- 数量限制 → 防止过度复杂

**优势**：减少模型的自由度过高导致的错误

---

### 4. 反馈闭环（Feedback Loop）

建立完整的反馈循环：
```
规划 → 执行 → 更新 → 提醒 → 重新规划
```

**优势**：
- 及时发现计划与实际的偏差
- 支持动态调整
- 保持计划的时效性

---

### 5. 最小侵入设计（Minimal Intrusion）

在 s03 基础上最小化修改：
- 新增独立模块（TodoManager）
- 扩展现有函数（execute_tool_calls 返回值）
- 保留原有工具和工作流

**优势**：
- 降低理解成本
- 便于回退和调试
- 支持渐进式改进

---

### 6. 人机协作优化（Human-AI Collaboration）

设计考虑人类用户的可读性：
- render() 输出人类可读的计划
- 进度汇总（1/4 completed）
- 清晰的错误提示

**优势**：用户能理解并信任 AI 的执行过程

---

## 实践指南

### 测试示例（多步骤任务）

**测试命令**：
```bash
python v1_task_manager/chapter_04/s04_todo_write.py
```

**测试输入**：
```
帮我创建一个实时显示当前时间的网页，放在当前目录下的 time_page 目录中
```

**预期模型行为**：
1. 调用 `todo` 工具创建计划：
```json
{
  "items": [
    {"id": "1", "content": "创建 time_page 目录", "status": "pending"},
    {"id": "2", "content": "创建 index.html 文件", "status": "pending"},
    {"id": "3", "content": "添加 JavaScript 时间显示功能", "status": "pending"},
    {"id": "4", "content": "测试网页功能", "status": "pending"}
  ]
}
```

2. 接收计划后，逐步执行：
   - 更新任务 1 为 in_progress → bash: `mkdir -p time_page` → 更新为 completed
   - 更新任务 2 为 in_progress → write_file: `time_page/index.html` → 更新为 completed
   - ...

---

### todo 工具使用示例

**创建初始计划**：
```json
{
  "items": [
    {
      "id": "step_1",
      "content": "分析项目结构",
      "status": "in_progress",
      "activeForm": "正在分析项目结构"
    },
    {
      "id": "step_2",
      "content": "编写代码",
      "status": "pending"
    },
    {
      "id": "step_3",
      "content": "运行测试",
      "status": "pending"
    }
  ]
}
```


## 总结

### 核心设计思想

s04 引入了 **Todo 任务管理系统**，通过以下设计原则实现多步骤任务的规划和管理：

1. **任务显式化（Explicit Task Management）**
   将隐式的执行计划显式化为数据结构，通过 PlanItem 列表存储每个步骤，状态字段追踪执行进度。

2. **状态驱动执行（State-Driven Execution）**
   通过 `pending → in_progress → completed` 的状态流转驱动任务推进，提供明确的进度指标。

3. **约束引导行为（Constraint-Guided Behavior）**
   单一 in_progress 约束强制顺序执行，定期提醒机制强制定期同步，防止计划过时。

4. **最小侵入设计（Minimal Intrusion）**
   在 s03 基础上最小化修改，新增独立模块 TodoManager，保留原有工具和工作流。

### 与 s03 的关系

| 特性 | s03 | s04 |
|------|-----|-----|
| **知识管理** | Skill 系统（按需加载领域知识） | 继承 s03 |
| **任务管理** | 无 | Todo 系统（规划多步骤任务） |
| **工具数量** | 5 个 | 6 个（+todo） |
| **SYSTEM 提示词** | 技能列表 | 技能列表 + 任务规划指导 |

s04 在 s03 的动态知识扩展基础上，进一步解决了**复杂任务的执行管理**问题，形成完整的知识 + 任务双轮驱动架构。

---

*文档版本：v1.0*
*基于代码：v1_task_manager/chapter_04/s04_todo_write.py*
