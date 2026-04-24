# s05: Subagent (子代理) - 代码文档

---

## 概述

### 核心改进

**从单一代理到主子代理协作架构**

s05 在 s04 的基础上引入了 **子代理（Subagent）系统**，实现了任务的上下文隔离和委托执行。主代理负责任务规划和分解，子代理负责具体任务的执行，执行细节仅保存在子代理的上下文中，主代理上下文保持整洁。

### 设计思想

> **"Context Isolation + Task Delegation（上下文隔离 + 任务委托）"**

s05 的核心设计思想：通过创建独立的子代理上下文执行具体任务，主代理只看到任务委托指令和子代理返回的总结，避免执行细节污染主上下文。

**核心机制**：
- **上下文隔离**：子代理拥有独立的消息历史，与主代理上下文分离
- **工具分割**：主代理和子代理使用不同的工具集，职责分离
- **任务委托**：主代理通过 `task` 工具创建子代理执行子任务
- **交接报告**：子代理完成任务后返回结构化总结

### 代码文件路径

```
v1_task_manager/chapter_05/s05_subagent.py
```

### 核心架构图（对比 s04）

**s04 架构（单一代理）**：
```
    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tools            |
    |  prompt  |      |       |      | {bash, read,     |
    +----------+      +---+---+      |  write, edit,    |
                          ^          |  load_skill,     |
                          |          |  todo}           |
                          |          +------------------+
                          +-----------------+
                               tool_result
```

**s05 架构（主子代理协作）**：
```
    +----------+      +-----------+      +------------------+
    |   User   | ---> |  Main     | ---> | Parent Tools     |
    |  prompt  |      |  Agent    |      | {read_file,      |
    +----------+      +-----+-----+      |  task, todo}     |
                              ^          +--------+---------+
                              |                   |
                              |                   | task 工具
                              |                   v
                              |          +-----------+
                              |          | Subagent  |
                              |          | (新上下文) |
                              |          +-----+-----+
                              |                |
                              |                | Child Tools
                              |                | {bash, read,
                              |                |  write, edit,
                              |                |  load_skill}
                              |                v
                              |          +-----------+
                              |          | 执行结果  |
                              |          | (总结返回) |
                              |          +-----+-----+
                              |                |
                              +----------------+
                                   返回总结
```

**架构说明**：
1. 主代理接收用户任务，判断是否需要委托子代理执行
2. 主代理调用 `task` 工具，传入子任务描述
3. `run_subagent()` 函数创建独立的子代理上下文
4. 子代理使用 `CHILD_TOOLS` 执行具体任务
5. 子代理完成任务后返回总结
6. 主代理接收总结，更新 todo 状态

---

## 与 s04 的对比

### 变更总览

| 组件 | s04 | s05 | 变化说明 |
|------|-----|-----|----------|
| **导入模块** | 标准库 | + `dataclasses` 增强 | 无显著变化 |
| **工具集** | 单一 TOOLS | `PARENT_TOOLS` + `CHILD_TOOLS` | 工具分割，主代理和子代理使用不同工具 |
| **SYSTEM 提示词** | 单一 SYSTEM | SYSTEM + SUBAGENT_SYSTEM | 双提示词，区分主代理和子代理角色 |
| **新增函数** | 无 | `run_subagent()`, `print_agent_thought()` | 子代理执行和格式化输出 |
| **task 工具** | 无 | 有 | 主代理通过 task 工具创建子代理 |
| **execute_tool_calls** | 处理 6 个工具 | 处理 7 个工具（+task） | 新增 task 工具处理逻辑 |
| **上下文管理** | 单一上下文 | 主上下文 + 子代理独立上下文 | 上下文隔离 |

### 新增组件架构

```
run_subagent() 函数
├── 创建独立消息历史
├── 子代理执行循环（最多 30 步）
└── 返回总结内容

工具分割
├── PARENT_TOOLS            # 主代理工具集
│   ├── read_file
│   ├── task
│   └── todo
└── CHILD_TOOLS             # 子代理工具集
    ├── bash
    ├── read_file
    ├── write_file
    ├── edit_file
    └── load_skill

双 SYSTEM 提示词
├── SYSTEM                  # 主代理提示词
│   ├── task 工具使用指导
│   ├── todo 工具使用指导
│   └── 验证子代理工作要求
└── SUBAGENT_SYSTEM         # 子代理提示词
    ├── 任务完成要求
    ├── 工具使用说明
    ├── load_skill 使用指导
    └── 交接报告要求
```

---

## 按执行顺序详解

### 第 1 阶段：新增导入与工具函数

#### print_agent_thought() 函数

**机制概述**：
`print_agent_thought()` 是一个辅助函数，用于格式化打印代理的思考过程和输出内容。它使用彩色边框和标题标识不同代理的输出，增强终端输出的可读性。

```python
def print_agent_thought(agent_name: str, message, color_code: str):
    """提取并格式化打印 Agent 的思考过程和输出内容"""
    content = message.content
    if content:
        print(f"{color_code}╭─── [{agent_name} 思考/输出] ──────────────────────────\033[0m")
        print(f"{content.strip()}")
        print(f"{color_code}╰─────────────────────────────────────────────────────\033[0m")
```

**参数说明**：
- `agent_name`：代理名称，如 "Main Agent (第 1 轮)" 或 "Sub Agent (步骤 1)"
- `message`：LLM 返回的消息对象，包含 `content` 属性
- `color_code`：ANSI 颜色代码，用于区分不同代理

**颜色使用**：
- 主代理：`\033[34m`（蓝色）
- 子代理：`\033[36m`（青色）
- 子代理生成提示：`\033[35m`（紫色）
- 工具输出：`\033[33m`（黄色）
- 最终回复：`\033[32m`（绿色）

**设计思想**：
- **可视化区分**：通过颜色和边框区分不同代理和组件的输出
- **调试友好**：便于追踪代理执行流程和思考过程
- **非侵入式**：仅用于终端输出，不影响核心逻辑

---

### 第 2 阶段：工具分割设计

#### 工具分割机制概述

s05 将工具集分割为两个独立的部分：`CHILD_TOOLS`（子代理工具集）和 `PARENT_TOOLS`（主代理工具集）。这种分割基于职责分离原则，主代理负责任务规划和协调，子代理负责具体执行。

**设计思想**：
- **职责分离**：主代理关注任务分解和状态管理，子代理关注具体执行
- **上下文保护**：子代理无法访问 `todo` 工具，避免污染主代理的计划状态
- **能力最小化**：每个代理只拥有完成其职责所需的工具，降低误操作风险

---

#### CHILD_TOOLS（子代理工具集）

**机制概述**：
`CHILD_TOOLS` 是子代理可使用的工具列表，包含执行具体任务所需的底层操作工具。子代理通过这些工具直接操作文件系统和执行命令。

```python
CHILD_TOOLS = [
    {"type": "function", "function": {"name": "bash", ...}},
    {"type": "function", "function": {"name": "read_file", ...}},
    {"type": "function", "function": {"name": "write_file", ...}},
    {"type": "function", "function": {"name": "edit_file", ...}},
    {"type": "function", "function": {"name": "load_skill", ...}},
]
```

**工具列表**：
| 工具 | 功能 | 说明 |
|------|------|------|
| `bash` | 执行 shell 命令 | 运行系统命令、编译代码、运行测试等 |
| `read_file` | 读取文件 | 查看文件内容，支持 limit 参数限制行数 |
| `write_file` | 写入文件 | 创建或覆盖文件内容 |
| `edit_file` | 编辑文件 | 替换文件中的特定文本 |
| `load_skill` | 加载技能 | 加载领域知识文档到上下文 |

**设计思想**：
- **执行导向**：所有工具都是实际操作工具，无管理性工具
- **完整能力**：子代理拥有完整的文件操作和命令执行能力
- **技能支持**：支持 `load_skill`，子代理可按需加载领域知识

---

#### PARENT_TOOLS（主代理工具集）

**机制概述**：
`PARENT_TOOLS` 是主代理可使用的工具列表，包含任务管理（`todo`）、任务委托（`task`）和文件读取（`read_file`）工具。主代理不直接执行具体操作，而是通过委托和规划完成任务。

```python
PARENT_TOOLS = [
    {"type": "function", "function": {"name": "read_file", ...}},
    {"type": "function", "function": {"name": "task", ...}},
    {"type": "function", "function": {"name": "todo", ...}},
]
```

**工具列表**：
| 工具 | 功能 | 说明 |
|------|------|------|
| `read_file` | 读取文件 | 查看文件内容，了解项目结构 |
| `task` | 创建子代理 | 委托子任务给子代理执行 |
| `todo` | 管理计划 | 创建和更新多步骤任务计划 |

**设计思想**：
- **管理导向**：工具聚焦于任务管理和协调，而非具体执行
- **信息获取**：保留 `read_file` 供主代理了解项目状态
- **委托能力**：`task` 工具是主代理委托任务的核心机制
- **计划控制**：`todo` 工具由主代理独占，确保计划的一致性

---

#### 工具对比

| 工具 | PARENT_TOOLS | CHILD_TOOLS | 说明 |
|------|--------------|-------------|------|
| `bash` | ❌ | ✅ | 仅子代理可执行 shell 命令 |
| `read_file` | ✅ | ✅ | 主代理和子代理都可读取文件 |
| `write_file` | ❌ | ✅ | 仅子代理可写入文件 |
| `edit_file` | ❌ | ✅ | 仅子代理可编辑文件 |
| `load_skill` | ❌ | ✅ | 仅子代理可加载技能 |
| `task` | ✅ | ❌ | 仅主代理可创建子代理 |
| `todo` | ✅ | ❌ | 仅主代理可管理任务计划 |

**注释掉的 bash 工具**：
`PARENT_TOOLS` 中原本有 `bash` 工具的定义，但被注释掉了：
```python
# {"type": "function","function": {"name": "bash", ... }},
```
这表明设计意图是完全剥夺主代理的直接执行能力，强制其通过子代理执行。

---

### 第 3 阶段：run_subagent() 函数详解

#### 机制概述

`run_subagent()` 函数是子代理系统的核心，负责创建独立上下文、执行子代理循环、返回任务总结。该函数被 `task` 工具的处理函数调用，当主代理需要委托任务时触发。

**核心流程**：
1. 打印子代理生成提示
2. 创建独立的子代理消息历史（包含 SUBAGENT_SYSTEM 提示词和用户任务）
3. 进入执行循环（最多 30 步）
4. 调用 LLM 获取响应
5. 执行工具调用（如果有）
6. 重复直到无工具调用或达到步数限制
7. 返回子代理的最终总结

```python
def run_subagent(prompt: str) -> str:
    print(f"\033[35m> Spawning Subagent : {prompt[:80]}...\033[0m")
    
    sub_messages = [{"role": "system", "content": SUBAGENT_SYSTEM},
                    {"role": "user", "content": prompt}] 
    sub_state = LoopState(messages=sub_messages)
    
    for step in range(30):  # safety limit
        response = client.chat.completions.create(            
            model=MODEL, 
            tools=CHILD_TOOLS, 
            messages=sub_state.messages,        
            max_tokens=8000,
            temperature=1,
            extra_body={
                "top_k": 20,
                "chat_template_kwargs": {"enable_thinking": True},
            }
        )
        response_message = response.choices[0].message
        sub_state.messages.append(response_message)
        print_agent_thought(f"Sub Agent (步骤 {step+1})", response_message, "\033[36m")

        if response_message.tool_calls:
            results, _ = execute_tool_calls(response_message)
            for tool_result in results:
                sub_state.messages.append(tool_result)
            sub_state.turn_count += 1
            sub_state.transition_reason = "tool_result"
        else:
            break
        
    if response_message.tool_calls:
        return f"[Subagent Warning: Task terminated after 30 steps. Last action was {response_message.tool_calls[0].function.name}]"
        
    return response_message.content or "Task finished (no summary provided)"
```

**参数说明**：
- `prompt`：子任务的具体描述，由主代理通过 `task` 工具传入

**返回值**：
- 成功完成：返回子代理的最终回复内容（总结）
- 步数超限：返回警告信息，说明最后执行的动作

---

#### 独立上下文创建

**机制概述**：
子代理的上下文完全独立于主代理，通过创建新的 `LoopState` 实例实现。子代理的消息历史只包含 `SUBAGENT_SYSTEM` 提示词和当前任务描述，不包含主代理的任何对话历史。

```python
sub_messages = [
    {"role": "system", "content": SUBAGENT_SYSTEM},
    {"role": "user", "content": prompt}
] 
sub_state = LoopState(messages=sub_messages)
```

**设计思想**：
- **上下文隔离**：子代理不知道主代理的对话历史，避免上下文污染
- **简洁性**：子代理只关注当前任务，减少无关信息干扰
- **可追踪性**：每个子代理的任务和输出独立记录

---

#### 子代理执行循环

**机制概述**：
子代理执行循环与主代理的执行逻辑类似，但使用 `CHILD_TOOLS` 和固定的 30 步限制。每轮循环调用 LLM 获取响应，执行工具调用，直到无工具调用或达到步数限制。

**循环逻辑**：
```python
for step in range(30):  # safety limit
    # 1. 调用 LLM
    response = client.chat.completions.create(...)
    
    # 2. 追加响应到历史
    sub_state.messages.append(response_message)
    
    # 3. 打印思考过程
    print_agent_thought(f"Sub Agent (步骤 {step+1})", response_message, "\033[36m")
    
    # 4. 执行工具调用
    if response_message.tool_calls:
        results, _ = execute_tool_calls(response_message)
        for tool_result in results:
            sub_state.messages.append(tool_result)
        sub_state.turn_count += 1
    else:
        break  # 无工具调用，结束循环
```

**步数限制**：
- 最大步数：30 步
- 超限处理：返回警告信息，说明任务被终止
- 正常退出：LLM 返回无工具调用的响应时退出

**设计思想**：
- **安全防护**：防止子代理陷入无限循环
- **透明调试**：打印每步思考过程，便于追踪执行流程
- **复用逻辑**：复用 `execute_tool_calls` 处理工具调用

---

#### 结果返回机制

**机制概述**：
子代理完成任务后，返回最终的总结内容给主代理。总结应包含任务完成情况、关键发现和验证结果。

**返回值处理**：
```python
if response_message.tool_calls:
    return f"[Subagent Warning: Task terminated after 30 steps. Last action was {response_message.tool_calls[0].function.name}]"
    
return response_message.content or "Task finished (no summary provided)"
```

**正常返回**：
- 子代理的最终回复内容（通常为任务总结）
- 如果无内容，返回默认提示 "Task finished (no summary provided)"

**异常返回**：
- 步数超限时返回警告信息
- 警告信息包含最后执行的动作名称

**设计思想**：
- **总结导向**：期望子代理返回简洁的总结，而非详细过程
- **异常处理**：明确标识异常情况，便于主代理判断
- **默认值**：提供默认返回值，避免空返回

---

### 第 4 阶段：新增 task 工具

#### 机制概述

`task` 工具是主代理委托子任务的核心机制。主代理通过调用 `task` 工具，传入任务描述，触发 `run_subagent()` 函数创建并执行子代理。子代理完成任务后返回总结，作为 `task` 工具的返回值给主代理。

**工具处理函数**：
```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_REGISTRY.load_full_text(kw["name"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),
    "task":       lambda **kw: run_subagent(kw["prompt"]),  # 新增
}
```

**调用流程**：
```
主代理调用 task 工具
       ↓
TOOL_HANDLERS["task"](**args)
       ↓
run_subagent(kw["prompt"])
       ↓
创建子代理上下文 → 执行循环 → 返回总结
       ↓
总结作为 tool_result 返回给主代理
```

---

#### JSON Schema 定义

**机制概述**：
`task` 工具的参数定义使用 JSON Schema 格式，描述主代理调用工具时应提供的参数结构。

```python
{"type": "function", "function": {
    "name": "task", 
    "description": "Spawn a subagent with fresh context to finish. It shares the filesystem but not conversation history.",
    "parameters": {
        "type": "object", 
        "properties": {
            "prompt": {"type": "string", "description": "The specific task instructions for the subagent."}, 
            "description": {"type": "string", "description": "Short description of the task"}
        }, 
        "required": ["prompt"]
    }
}}
```

**参数说明**：
- `prompt`（必需）：子任务的具体指令，子代理将基于此指令执行任务
- `description`（可选）：任务的简短描述，可能用于日志或显示

**设计思想**：
- **清晰描述**：工具描述明确说明子代理有独立上下文，共享文件系统但不共享对话历史
- **必需参数**：只要求 `prompt`，降低使用门槛
- **可选描述**：`description` 可选，提供额外元数据

---

### 第 5 阶段：双 SYSTEM 提示词

#### 机制概述

s05 引入了两个独立的 SYSTEM 提示词：`SYSTEM` 用于主代理，`SUBAGENT_SYSTEM` 用于子代理。两个提示词根据各自的角色和职责定制，指导代理正确使用工具和完成任务。

---

#### SYSTEM（主代理提示词）

**机制概述**：
主代理的 SYSTEM 提示词强调任务规划、子代理委托和工作验证。主代理不直接执行操作，而是通过 `todo` 和 `task` 工具管理和委托任务。

```python
SYSTEM = f"""You are a coding agent at {WORKDIR}. 
1.Use the task tool to delegate exploration or subtasks.
2.Use the todo tool to plan complex and multi-step tasks. Mark in_progress before starting, completed when done. Keep exactly one step in_progress when a task has multiple steps.
3.Do NOT immediately mark a task as 'completed' just because the subagent claims it is done. You MUST verify the subagent's work before calling the todo tool to mark it completed. If the work is flawed, explain the issue and spawn a new task to fix it."""
```

**三条指导原则**：

**原则 1：任务委托**
```
Use the task tool to delegate exploration or subtasks.
```
- 明确使用 `task` 工具委托子任务
- 探索性任务和执行性任务都应委托

**原则 2：任务规划**（继承自 s04）
```
Use the todo tool to plan complex and multi-step tasks. 
Mark in_progress before starting, completed when done. 
Keep exactly one step in_progress when a task has multiple steps.
```
- 复杂任务需要先规划
- 状态标记规范
- 单一 in_progress 约束

**原则 3：工作验证**
```
Do NOT immediately mark a task as 'completed' just because the subagent claims it is done. 
You MUST verify the subagent's work before calling the todo tool to mark it completed. 
If the work is flawed, explain the issue and spawn a new task to fix it.
```
- 禁止盲目信任子代理
- 必须验证子代理工作
- 发现问题时创建修复任务

**设计思想**：
- **委托优先**：鼓励使用子代理执行具体任务
- **验证责任**：主代理对子代理的工作质量负责
- **计划管理**：保持 s04 的任务规划机制

---

#### SUBAGENT_SYSTEM（子代理提示词）

**机制概述**：
子代理的 SYSTEM 提示词强调任务执行、工具使用和交接报告。子代理专注于完成具体任务，并在完成后提供详细的总结报告。

```python
SUBAGENT_SYSTEM = f"""You are a coding subagent at {WORKDIR}. 
1.Complete the given task, then summarize your findings or your work.
2.Use tools to solve tasks. Act, after executing the command, tell me that it has been completed.
3.Use load_skill when a task needs specialized instructions before you act. Skills available: {SKILL_REGISTRY.describe_available()}
4.When finishing a task, you MUST provide a detailed handover report including: 1. Files created/modified. 2. Key functions implemented. 3. Output of any verification commands (e.g., test results or syntax checks) you ran.
"""
```

**四条指导原则**：

**原则 1：任务完成与总结**
```
Complete the given task, then summarize your findings or your work.
```
- 完成任务是第一目标
- 完成后必须提供总结

**原则 2：工具执行**
```
Use tools to solve tasks. Act, after executing the command, tell me that it has been completed.
```
- 使用工具解决问题
- 执行后明确报告完成

**原则 3：技能加载**
```
Use load_skill when a task needs specialized instructions before you act. 
Skills available: {SKILL_REGISTRY.describe_available()}
```
- 需要领域知识时先加载技能
- 动态列出可用技能

**原则 4：交接报告**
```
When finishing a task, you MUST provide a detailed handover report including: 
1. Files created/modified. 
2. Key functions implemented. 
3. Output of any verification commands (e.g., test results or syntax checks) you ran.
```
- 必须提供详细的交接报告
- 报告包含三个必需部分

**设计思想**：
- **执行导向**：子代理的核心职责是完成任务
- **报告规范**：强制要求结构化总结，便于主代理验证
- **技能支持**：支持按需加载领域知识
- **行动优先**：鼓励先执行再报告

---

### 第 6 阶段：execute_tool_calls 变化

#### task 工具处理

**机制概述**：
`execute_tool_calls` 函数通过 `TOOL_HANDLERS` 字典处理所有工具调用，包括新增的 `task` 工具。`task` 工具的处理函数调用 `run_subagent()` 创建并执行子代理，返回子代理的总结作为工具结果。

**处理逻辑**：
```python
for tool_call in response_content.tool_calls:
    f_name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)
    
    if f_name in TOOL_HANDLERS:
        output = TOOL_HANDLERS[f_name](**args)  # task 工具调用 run_subagent()
        print(f"\033[33m[Tool: {f_name}]\033[0m:\t", output[:200])
    else:
        output = f"Error: Tool {f_name} not found."

    results.append({
        "role": "tool", 
        "tool_call_id": tool_call.id,
        "name": tool_call.function.name,
        "content": output
    })
```

**task 工具执行流程**：
```
1. 主代理调用 task 工具，传入 prompt
2. TOOL_HANDLERS["task"](**args) 被调用
3. run_subagent(kw["prompt"]) 执行
4. 子代理创建独立上下文
5. 子代理执行循环（最多 30 步）
6. 子代理返回总结
7. 总结作为 tool_result 返回给主代理
8. 主代理接收总结，继续执行
```

**设计思想**：
- **统一处理**：所有工具通过 `TOOL_HANDLERS` 字典统一分发
- **透明调用**：主代理不知道 `task` 工具内部创建子代理
- **结果封装**：子代理的总结作为普通工具结果返回

---

## 完整框架流程图

```
┌─────────────┐
│    User     │  输入："帮我创建一个完整的 Web 应用，包含前后端"
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Main Agent │  分析任务复杂度
│ (接收任务)  │  → 判断为复杂多步骤任务
└──────┬──────┘
       │
       │ 需要规划
       ▼
┌─────────────┐
│  todo 工具  │  调用：todo(items=[
│ (创建计划)  │    {"id":"1","content":"创建后端 API","status":"pending"},
│             │    {"id":"2","content":"创建前端页面","status":"pending"},
│             │    {"id":"3","content":"集成测试","status":"pending"}
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
│  Main Agent │  接收计划，开始执行
│ (执行阶段)  │  → 更新 task 1 为 in_progress
└──────┬──────┘
       │
       │ 需要委托执行
       ▼
┌─────────────┐
│  task 工具  │  调用：task(prompt="创建后端 API，使用 Flask 框架...")
│(创建子代理) │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ run_subagent│  创建独立上下文
│   ()        │  → SUBAGENT_SYSTEM + 任务 prompt
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Subagent   │  执行循环（最多 30 步）
│  (执行任务) │  → 使用 CHILD_TOOLS
│             │  → bash, write_file, read_file...
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Subagent   │  完成任务，返回总结：
│  (返回总结) │  "创建了 app.py，包含以下 API 端点...
│             │   运行测试，所有测试通过..."
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Main Agent │  接收总结
│ (接收结果)  │  → 验证子代理工作
│             │  → read_file 检查代码
│             │  → bash 运行测试
└──────┬──────┘
       │
       │ 验证通过
       ▼
┌─────────────┐
│  todo 工具  │  更新 task 1 为 completed
│ (更新状态)  │  更新 task 2 为 in_progress
└──────┬──────┘
       │
       │ ... 重复执行后续任务 ...
       │
       ▼
┌─────────────┐
│  所有任务   │  输出最终结果
│   完成      │
└─────────────┘
```

---

## 设计点总结

### 上下文隔离原则

**核心思想**：子代理拥有独立的消息历史，与主代理上下文完全分离。

**隔离机制**：
- 子代理的消息历史只包含 `SUBAGENT_SYSTEM` 和当前任务 prompt
- 子代理不知道主代理的对话历史
- 子代理的工具结果（总结）返回给主代理，但详细执行过程不返回

**设计优势**：
- **保持主上下文整洁**：主代理只看到任务委托和结果总结，避免执行细节污染
- **降低 token 消耗**：子代理的详细执行过程不计入主上下文
- **任务聚焦**：子代理专注于当前任务，不受主上下文干扰

**代价**：
- 子代理无法利用主上下文的背景信息
- 主代理需要通过其他方式（如文件读取）验证子代理工作

---

### 工具分割设计

**核心思想**：根据职责分离原则，主代理和子代理使用不同的工具集。

**分割逻辑**：
| 代理类型 | 职责 | 工具集 |
|----------|------|--------|
| 主代理 | 任务规划、协调、验证 | `read_file`, `task`, `todo` |
| 子代理 | 具体执行 | `bash`, `read_file`, `write_file`, `edit_file`, `load_skill` |

**设计优势**：
- **职责清晰**：每个代理只关注自己的职责范围
- **状态保护**：子代理无法修改主代理的任务计划
- **能力最小化**：降低误操作风险

---

### 任务委托机制

**核心思想**：主代理通过 `task` 工具将具体任务委托给子代理执行。

**委托流程**：
1. 主代理判断需要委托任务
2. 主代理调用 `task` 工具，传入任务描述
3. `run_subagent()` 创建子代理并执行
4. 子代理完成任务，返回总结
5. 主代理接收总结，继续执行

**设计优势**：
- **模块化执行**：复杂任务可分解为多个子任务并行或串行执行
- **关注点分离**：主代理关注整体规划，子代理关注具体执行
- **可追踪性**：每个子任务有明确的输入和输出

---

### 交接报告规范

**核心思想**：子代理完成任务后必须提供结构化的交接报告，便于主代理验证。

**报告要求**：
1. **Files created/modified**：列出创建或修改的文件
2. **Key functions implemented**：描述实现的关键功能
3. **Verification output**：提供验证命令的输出（如测试结果）

**示例报告**：
```
任务完成总结：

1. 创建/修改的文件：
   - app.py (新建)
   - requirements.txt (新建)
   - tests/test_app.py (新建)

2. 实现的关键功能：
   - GET /api/time - 返回当前时间
   - GET /api/status - 返回服务状态

3. 验证结果：
   $ python -m pytest tests/
   === 5 passed in 0.12s ===
```

**设计优势**：
- **标准化**：统一的报告格式便于主代理快速理解
- **可验证**：包含验证结果，主代理可确认工作质量
- **可追溯**：列出文件变更，便于后续审查

---

## 整体设计思想总结

### 1. 上下文隔离（Context Isolation）

通过创建独立的子代理上下文，将执行细节与主上下文分离：
- 子代理的消息历史独立于主代理
- 只有总结结果返回给主代理
- 主上下文保持简洁，只包含关键决策和状态

**优势**：降低 token 消耗、保持主上下文清晰、提高执行效率

---

### 2. 职责分离（Separation of Concerns）

主代理和子代理承担不同的职责：
- 主代理：任务规划、子任务委托、工作验证
- 子代理：具体任务执行、工具调用、结果总结

**优势**：清晰的职责边界、降低代理复杂度、提高可维护性

---

### 3. 工具最小化（Minimal Tool Access）

每个代理只拥有完成其职责所需的工具：
- 主代理无法直接执行操作，必须通过子代理
- 子代理无法修改任务计划，只能执行和报告

**优势**：降低误操作风险、保护关键状态、强化职责边界

---

### 4. 验证责任（Verification Responsibility）

主代理对子代理的工作质量负责：
- 禁止盲目信任子代理的总结
- 必须通过独立手段验证工作结果
- 发现问题时创建修复任务

**优势**：确保工作质量、建立信任机制、支持错误恢复

---

### 5. 标准化报告（Standardized Reporting）

子代理必须提供结构化的交接报告：
- 文件变更列表
- 关键功能描述
- 验证结果输出

**优势**：便于主代理理解、支持快速验证、提供可追溯记录

---

### 6. 安全限制（Safety Limits）

通过步数限制防止子代理陷入无限循环：
- 最大执行步数：30 步
- 超限时返回警告信息
- 主代理可根据警告决定后续操作

**优势**：防止资源耗尽、提供异常处理机制、保持系统稳定性

---

## 与 s04 的关系

### 对比表格

| 特性 | s04 | s05 |
|------|-----|-----|
| **架构** | 单一代理 | 主代理 + 子代理 |
| **上下文** | 单一上下文 | 主上下文 + 独立子上下文 |
| **工具集** | 统一 TOOLS | PARENT_TOOLS + CHILD_TOOLS |
| **SYSTEM 提示词** | 单一 SYSTEM | SYSTEM + SUBAGENT_SYSTEM |
| **任务执行** | 代理直接执行 | 委托子代理执行 |
| **todo 管理** | 代理直接更新 | 主代理更新，子代理无权访问 |
| **技能加载** | 代理直接加载 | 子代理按需加载 |
| **输出格式** | 直接输出 | 格式化打印（print_agent_thought） |

### 继承与扩展

**继承内容**：
- `TodoManager` 类及其完整功能
- `SkillRegistry` 类及其完整功能
- `LoopState` 数据类
- 基础工具函数（`run_bash`, `run_read`, `run_write`, `run_edit`）
- `execute_tool_calls` 核心逻辑
- `agent_loop` 和 `run_one_turn` 执行框架

**扩展内容**：
- `run_subagent()` 函数（新增）
- `print_agent_thought()` 函数（新增）
- 工具分割（`PARENT_TOOLS` / `CHILD_TOOLS`）
- `task` 工具（新增）
- `SUBAGENT_SYSTEM` 提示词（新增）

---

## 实践指南

### 测试示例（主代理划分任务 + 子代理执行）

**测试命令**：
```bash
python v1_task_manager/chapter_05/s05_subagent.py
```

**测试输入**：
```
帮我创建一个简单的 Python 项目，包含一个计算器和对应的测试文件
```

**预期主代理行为**：
1. 调用 `todo` 工具创建计划：
```json
{
  "items": [
    {"id": "1", "content": "创建项目结构", "status": "pending"},
    {"id": "2", "content": "实现计算器功能", "status": "pending"},
    {"id": "3", "content": "编写测试用例", "status": "pending"},
    {"id": "4", "content": "运行测试验证", "status": "pending"}
  ]
}
```

2. 调用 `task` 工具委托第一个子任务：
```json
{
  "prompt": "创建项目目录 calculator_project，包含以下结构：\n- calculator_project/__init__.py\n- calculator_project/calculator.py\n\n在 calculator.py 中实现一个 Calculator 类，包含 add, subtract, multiply, divide 四个方法。"
}
```

3. 子代理执行并返回总结：
```
任务完成总结：

1. 创建/修改的文件：
   - calculator_project/__init__.py (新建)
   - calculator_project/calculator.py (新建)

2. 实现的关键功能：
   - Calculator 类
   - add(a, b) - 加法
   - subtract(a, b) - 减法
   - multiply(a, b) - 乘法
   - divide(a, b) - 除法

3. 验证结果：
   $ python -c "from calculator_project.calculator import Calculator; c = Calculator(); print(c.add(1, 2))"
   3
```

4. 主代理验证子代理工作：
```bash
read_file: calculator_project/calculator.py
bash: python -c "from calculator_project.calculator import Calculator; c = Calculator(); print(c.add(1, 2))"
```

5. 验证通过后更新 todo：
```json
{
  "items": [
    {"id": "1", "content": "创建项目结构", "status": "completed"},
    {"id": "2", "content": "实现计算器功能", "status": "in_progress"},
    {"id": "3", "content": "编写测试用例", "status": "pending"},
    {"id": "4", "content": "运行测试验证", "status": "pending"}
  ]
}
```

6. 继续委托后续子任务，直到所有任务完成

---

### task 工具使用示例

**委托探索性任务**：
```json
{
  "prompt": "分析当前目录下的项目结构，找出所有的 Python 文件，并报告每个文件的主要功能。"
}
```

**委托执行性任务**：
```json
{
  "prompt": "在项目根目录创建一个 requirements.txt 文件，包含以下依赖：\n- flask>=2.0.0\n- pytest>=7.0.0\n\n然后运行 pip install -r requirements.txt 安装依赖。"
}
```

**委托修复性任务**：
```json
{
  "prompt": "修复 calculator.py 中的 divide 方法，当除数为 0 时抛出 ValueError 异常，而不是返回 None。修复后运行测试验证。"
}
```

---

## 总结

### 核心设计思想

s05 引入了 **子代理（Subagent）系统**，通过以下设计原则实现上下文隔离和任务委托：

1. **上下文隔离（Context Isolation）**
   子代理拥有独立的消息历史，执行细节不污染主上下文，只有总结结果返回给主代理。

2. **职责分离（Separation of Concerns）**
   主代理负责任务规划和协调，子代理负责具体执行，两者通过 `task` 工具通信。

3. **工具分割（Tool Partitioning）**
   主代理和子代理使用不同的工具集，主代理无法直接执行操作，子代理无法修改任务计划。

4. **验证责任（Verification Responsibility）**
   主代理必须验证子代理的工作结果，不能盲目信任子代理的总结报告。

5. **标准化报告（Standardized Reporting）**
   子代理完成任务后必须提供结构化的交接报告，包含文件变更、功能描述和验证结果。

6. **安全限制（Safety Limits）**
   子代理执行有 30 步的上限，防止无限循环，超限时返回警告信息。

### 与 s04 的关系

| 特性 | s04 | s05 |
|------|-----|-----|
| **架构** | 单一代理执行所有任务 | 主代理规划 + 子代理执行 |
| **上下文管理** | 单一上下文累积所有历史 | 主上下文 + 独立子上下文 |
| **工具使用** | 统一工具集 | 工具分割，职责分离 |
| **任务执行** | 代理直接调用工具 | 通过 task 工具委托子代理 |

s05 在 s04 的任务规划基础上，进一步解决了 **上下文膨胀** 和 **执行细节污染** 的问题，通过子代理系统将执行细节隔离在独立上下文中，保持主代理上下文的整洁和高效。

---

*文档版本：v1.0*
*基于代码：v1_task_manager/chapter_05/s05_subagent.py*