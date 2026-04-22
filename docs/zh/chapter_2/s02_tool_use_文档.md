# s02: Tool Use (工具使用) - 代码文档 v2

---

## 概述

### 核心改进

**从单工具到多工具 dispatch 架构**

s02 在 s01 的基础上进行了扩展：将单一的 `bash` 工具扩展为 **4 个工具**（bash、read_file、write_file、edit_file），并引入了 **工具分发机制**（dispatch map）来路由不同的工具调用。

### 设计思想

> **"The loop didn't change at all. I just added tools."**

s02 的设计思想：**Agent 循环本身不需要修改**，只需扩展工具数组和添加工具分发映射即可完成多工具支持。

这也是整个项目以及 harness 工程的设计思想：核心 agents 循环本身不需要修改，不断拓展工具和功能即可。

### 代码文件路径

```
v1_task_manager/chapter_2/s02_tool_use.py
```

### 核心架构图

```
    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch    |
    |  prompt  |      |       |      | {                |
    +----------+      +---+---+      |   bash: run_bash |
                          ^          |   read: run_read |
                          |          |   write: run_wr  |
                          +----------+   edit: run_edit |
                          tool_result| }                |
                                     +------------------+
                                     (loop continues)
```

**架构说明**：
1. User 输入 prompt 发送给 LLM
2. LLM 根据可用工具列表选择调用哪个工具
3. Tool Dispatch 根据工具名称路由到对应的处理函数
4. 工具执行结果返回给 LLM
5. 循环继续，直到 LLM 不再请求工具调用

---

## 与 s01 的对比

### 变更总览

| 组件 | s01 | s02 | 变化说明 |
|------|-----|-----|----------|
| **Tools** | 1 个 (bash) | 4 个 (bash, read_file, write_file, edit_file) | 新增 3 个文件操作工具 |
| **Dispatch** | 硬编码 if | TOOL_HANDLERS 字典 | 从条件判断改为字典查找 |
| **路径安全** | 无 | safe_path() 沙箱 | 新增路径验证机制 |
| **Agent loop** | 不变 | 不变 | 核心循环逻辑一致 |
| **导入模块** | 标准库 | + pathlib.Path | 新增路径处理模块 |
| **SYSTEM 提示词** | "Use bash" | "Use the tool" | 通用化工具描述 |

### 架构对比

**s01 架构（单工具硬编码）**：
```
    +-------+      +------------------+
    |  LLM  | ---> | if name=="bash": |
    +-------+      |   run_bash()     |
                   +------------------+
```

**s02 架构（多工具分发）**：
```
    +-------+      +------------------+
    |  LLM  | ---> | TOOL_HANDLERS    |
    +-------+      |   [name](**args) |
                   +------------------+
```

**设计优势**：
- 可扩展性：添加新工具只需在 TOOL_HANDLERS 中添加一项
- 可维护性：消除冗长的 if/elif 链
- 类型安全：通过 JSON Schema 约束参数

---

## 按执行顺序详解

### 第 1 阶段：新增导入模块

#### pathlib.Path 的引入

**机制概述**：
s02 新增导入 `pathlib.Path` 模块，用于替代传统的 `os.path` 进行路径处理。`pathlib` 是 Python 3.4+ 的面向对象路径处理模块，提供更直观的路径操作 API。

```python
from pathlib import Path
WORKDIR = Path.cwd()
```

**设计思想**：
- `WORKDIR` 作为路径沙箱的基准目录，所有文件操作都被限制在此目录下
- 使用 `Path.cwd()` 获取当前工作目录的 Path 对象
- Path 对象支持 `/` 运算符进行路径拼接，如 `WORKDIR / "subdir" / "file.txt"`

**与 os.path 的对比**：
- pathlib 采用面向对象风格：`path.resolve()` vs `os.path.resolve(path)`
- 路径拼接更直观：`path / "subdir"` vs `os.path.join(path, "subdir")`
- 内置安全检查方法：`is_relative_to()` 可直接用于路径沙箱验证

---

### 第 2 阶段：路径安全沙箱

#### safe_path() 函数详解

**机制概述**：
`safe_path()` 函数为所有文件操作提供路径安全验证。它接收一个相对路径字符串，返回经过验证的绝对 Path 对象。如果检测到路径逃逸尝试（如使用 `../` 访问工作目录外的文件），则抛出 `ValueError` 异常。

```python
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path
```

**路径沙箱设计思想**：
路径沙箱是 Agent 安全的重要防线。即使模型被恶意提示词攻击，也无法读取项目外部的敏感文件。沙箱通过三层防御实现：

1. **强制拼接工作目录**：`(WORKDIR / p)` 确保所有路径都基于工作目录
2. **解析符号链接和相对路径**：`.resolve()` 解析所有 `..` 和符号链接，得到真实绝对路径
3. **验证路径范围**：`is_relative_to(WORKDIR)` 检查解析后的路径是否仍在工作目录内部

**为什么需要限制工作区**：
- 防止目录穿越攻击（使用 `../` 访问上级目录）
- 防止符号链接逃逸（攻击者创建指向外部文件的符号链接）
- 防止绝对路径绕过（直接传入 `/etc/passwd` 等系统路径）
- 保护敏感文件（系统配置文件、密钥、凭证等）

**路径攻击场景示例**：
```
攻击场景 1：目录穿越
  输入：p = "../../etc/passwd"
  WORKDIR = "/home/user/AGENT_demo"
  
  (WORKDIR / p).resolve() 
  = "/home/user/AGENT_demo/../../etc/passwd".resolve()
  = "/home/user/etc/passwd"
  
  is_relative_to(WORKDIR) → False  ❌ 被拦截

攻击场景 2：符号链接逃逸
  攻击者创建符号链接：ln -s /etc/passwd ./link
  
  输入：p = "link"
  .resolve() 会跟随符号链接得到 "/etc/passwd"
  
  is_relative_to(WORKDIR) → False  ❌ 被拦截
```

---

### 第 3 阶段：新增工具实现

#### run_read() 函数

**机制概述**：
`run_read()` 用于读取文件内容，支持可选的 `limit` 参数限制读取行数。函数首先通过 `safe_path()` 验证路径安全性，然后读取文件并按行分割。如果指定了 `limit` 且文件行数超过限制，则截断内容并添加剩余行数提示。最终输出限制在 50000 字符以内，防止消耗过多 token。

```python
def run_read(path: str, limit: int = None) -> str:
    try:
        text = safe_path(path).read_text() 
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"
```

**机制**：
- `limit` 参数允许模型只读取大文件的前 N 行，适合探索性阅读
- 截断提示 `"... (X more lines)"` 告知模型文件还有更多内容
- 50000 字符上限防止单个工具调用消耗过多上下文
- 异常捕获确保文件读取失败时返回错误信息而非崩溃

---

#### run_write() 函数

**机制概述**：
`run_write()` 用于创建或覆盖文件。函数接收目标路径和完整内容，首先验证路径安全性，然后自动创建所有不存在的父目录，最后写入内容。这种设计避免了因目录不存在而导致的写入失败。

```python
def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path) 
        fp.parent.mkdir(parents=True, exist_ok=True) 
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"
```

**机制**：
- `fp.parent.mkdir(parents=True, exist_ok=True)` 递归创建所有不存在的父目录
- `parents=True` 允许创建多级目录（如 `deep/nested/dir/`）
- `exist_ok=True` 确保目录已存在时不报错
- `write_text()` 会覆盖已存在的文件，这是预期行为

---

#### run_edit() 函数

**机制概述**：
`run_edit()` 用于精确替换文件中的文本。函数读取文件内容，检查原文本是否存在，如果存在则执行替换（仅替换第一次出现），然后写回文件。这种设计比使用 bash 的 sed 命令更安全可控。

```python
def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"
```

**文本替换逻辑**：
- `content.replace(old_text, new_text, 1)` 的第三个参数 `1` 表示只替换第一次出现
- 只替换一次的设计原因：
  - 更安全：避免意外修改多处相同内容
  - 更精确：模型可以多次调用 edit 修改多处
  - 可预测：行为确定，不会产生意外副作用
- 如果原文本不存在，返回错误信息而非静默失败

---

### 第 4 阶段：工具分发机制


#### TOOL_HANDLERS 分发字典

**机制概述**：
`TOOL_HANDLERS` 是 s02 的核心设计，它是一个字典，将工具名称映射到对应的处理函数。通过字典查找替代硬编码的 if/elif 链，实现可扩展的工具架构。添加新工具只需在字典中添加一项，无需修改执行逻辑。

```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}
```

**设计思想：可扩展的工具架构**：
- 每个工具映射到一个 lambda 函数，lambda 负责从关键字参数中提取正确的参数
- 使用 lambda 包装的原因：工具函数的参数名与 LLM 传递的参数名可能不匹配，需要显式映射
- 统一调用接口：所有工具都通过 `TOOL_HANDLERS[name](**args)` 调用
- 可选参数支持：使用 `kw.get("limit")` 处理可选参数

**调用示例**：
```python
# 模型输出 tool_call:
# {"name": "read_file", "arguments": {"path": "test.py", "limit": 50}}

# 执行逻辑:
f_name = "read_file"
args = {"path": "test.py", "limit": 50}
output = TOOL_HANDLERS[f_name](**args)
# 等价于: output = run_read(path="test.py", limit=50)
```

---

### 第 5 阶段：execute_tool_calls 优化

#### 字典查找替代 if/elif

**机制概述**：
s02 重构了 `execute_tool_calls()` 函数，使用 `TOOL_HANDLERS` 字典查找替代 s01 中硬编码的 if/elif 链。这种设计使代码更简洁，添加新工具时无需修改执行函数。

**s01 实现（硬编码）**：
```python
def execute_tool_calls(response_content) -> list[dict]:
    results = []
    for tool_call in response_content.tool_calls:
        if tool_call.function.name == "bash":  # 硬编码
            args = json.loads(tool_call.function.arguments)
            command = args.get("command")
            output = run_bash(command)
            results.append({...})
    return results
```

**s02 实现（字典分发）**：
```python
def execute_tool_calls(response_content) -> list[dict]:
    results = []
    for tool_call in response_content.tool_calls:
        f_name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as e:
            # 错误处理...
            continue
        
        if f_name in TOOL_HANDLERS:
            output = TOOL_HANDLERS[f_name](**args)  # 字典查找
        else:
            output = f"Error: Tool {f_name} not found."
        
        results.append({...})
    return results
```

**设计优势**：
- 代码行数固定，不随工具数量增加而增长
- 添加新工具只需在 `TOOL_HANDLERS` 中增加一项
- 统一处理工具不存在的情况
- 统一错误处理逻辑

---

#### JSON 解析错误处理

**机制概述**：
`execute_tool_calls()` 新增了 JSON 解析错误处理。如果模型生成的工具参数不是有效的 JSON 格式，函数会捕获异常，返回错误信息给模型，并继续处理其他工具调用。这种设计形成反馈闭环，让模型有机会修正错误。

```python
try:
    args = json.loads(tool_call.function.arguments)
except json.JSONDecodeError as e:
    print(f"\033[31m[JSON Parse Error in {f_name}]\033[0m")
    output = f"Error: Failed to parse tool arguments. Invalid JSON format. {e}"
    results.append({"role": "tool", "tool_call_id": tool_call.id, "name": f_name, "content": output})
    continue
```

**错误处理流程**：
1. 尝试解析模型输出的 JSON 参数
2. 如果解析失败，捕获 `JSONDecodeError`
3. 打印红色错误日志（便于调试）
4. 构建错误消息返回给模型
5. 跳过本次工具执行，继续处理其他 tool_call

**为什么需要错误处理**：
- 模型可能输出格式错误的参数
- 特殊字符转义问题可能导致 JSON 解析失败
- 错误返回给模型可以形成反馈闭环，提高成功率

---

### 第 6 阶段：SYSTEM 提示词变化

**机制概述**：
SYSTEM 提示词从 s01 的 "Use bash" 改为 s02 的 "Use the tool"，反映多工具架构的变化。提示词通用化，避免列举所有工具名称，工具的具体能力由 TOOLS 列表的 JSON Schema 传达给模型。

**s01**：
```python
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to inspect and change the workspace. Act first, then report clearly."
```

**s02**：
```python
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use the tool to finish tasks. Act first, then report clearly."
```

**变化说明**：
- `Use bash` → `Use the tool`：从单一工具到通用工具
- 工具的具体能力由 TOOLS 列表定义传达给模型
- SYSTEM 提示词只需给出总体指导，保持简洁

---

## 完整框架流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           s02 完整执行流程                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐                                                               │
│  │   User   │                                                               │
│  └────┬─────┘                                                               │
│       │ "编辑 test.py 中的 hello 函数"                                       │
│       ▼                                                                      │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  history = [SYSTEM, user_message]                                      │ │
│  │  state = LoopState(messages=history)                                   │ │
│  │  agent_loop(state)                                                     │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│       │                                                                      │
│       ▼                                                                      │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  while run_one_turn(state):  ←─────────────────────────────────┐       │ │
│  │       │                                                         │       │ │
│  │       ▼                                                         │       │ │
│  │  ┌──────────────────────────────────────────────────────────┐   │       │ │
│  │  │  client.chat.completions.create()                        │   │       │ │
│  │  │    model=MODEL                                           │   │       │ │
│  │  │    tools=TOOLS  [bash, read_file, write_file, edit_file] │   │       │ │
│  │  │    messages=state.messages                               │   │       │ │
│  │  └────────────────────┬─────────────────────────────────────┘   │       │ │
│  │                       │                                          │       │ │
│  │                       ▼                                          │       │ │
│  │  ┌──────────────────────────────────────────────────────────┐   │       │ │
│  │  │  response_messages.tool_calls ?                          │   │       │ │
│  │  │                                                           │   │       │ │
│  │  │    ┌───────────┐         ┌───────────┐                   │   │       │ │
│  │  │    │    Yes    │         │    No     │                   │   │       │ │
│  │  │    └─────┬─────┘         └─────┬─────┘                   │   │       │ │
│  │  │          │                     │                         │   │       │ │
│  │  │          ▼                     ▼                         │   │       │ │
│  │  │  ┌─────────────────┐   ┌─────────────────┐               │   │       │ │
│  │  │  │ execute_tool_   │   │ return False    │               │   │       │ │
│  │  │  │ calls()         │   │ (结束循环)       │               │   │       │ │
│  │  │  └────────┬────────┘   └─────────────────┘               │   │       │ │
│  │  │           │                                              │   │       │ │
│  │  │           ▼                                              │   │       │ │
│  │  │  ┌─────────────────────────────────────────────────────┐ │   │       │ │
│  │  │  │  for tool_call in tool_calls:                       │ │   │       │ │
│  │  │  │       │                                             │ │   │       │ │
│  │  │  │       ▼                                             │ │   │       │ │
│  │  │  │  ┌────────────────────────────────────────────────┐ │ │   │       │ │
│  │  │  │  │  f_name = tool_call.function.name              │ │ │   │       │ │
│  │  │  │  │  args = json.loads(arguments)                  │ │ │   │       │ │
│  │  │  │  │  output = TOOL_HANDLERS[f_name](**args)        │ │ │   │       │ │
│  │  │  │  │                                                 │ │ │   │       │ │
│  │  │  │  │  TOOL_HANDLERS 分发:                            │ │ │   │       │ │
│  │  │  │  │  ┌─────────────────────────────────────────┐   │ │ │   │       │ │
│  │  │  │  │  │ "bash"       → run_bash(command)        │   │ │ │   │       │ │
│  │  │  │  │  │ "read_file"  → run_read(path, limit)    │   │ │ │   │       │ │
│  │  │  │  │  │ "write_file" → run_write(path, content) │   │ │ │   │       │ │
│  │  │  │  │  │ "edit_file"  → run_edit(path, old, new) │   │ │ │   │       │ │
│  │  │  │  │  └─────────────────────────────────────────┘   │ │ │   │       │ │
│  │  │  │  └────────────────────────────────────────────────┘ │ │   │       │ │
│  │  │  │           │                                         │ │   │       │ │
│  │  │  │           ▼                                         │ │   │       │ │
│  │  │  │  ┌────────────────────────────────────────────────┐ │ │   │       │ │
│  │  │  │  │  safe_path() 路径验证                          │ │ │   │       │ │
│  │  │  │  │  (仅文件操作工具)                               │ │ │   │       │ │
│  │  │  │  └────────────────────────────────────────────────┘ │ │   │       │ │
│  │  │  │           │                                         │ │   │       │ │
│  │  │  │           ▼                                         │ │   │       │ │
│  │  │  │  ┌────────────────────────────────────────────────┐ │ │   │       │ │
│  │  │  │  │  执行具体工具函数                               │ │ │   │       │ │
│  │  │  │  │  - run_bash: subprocess.run()                  │ │ │   │       │ │
│  │  │  │  │  - run_read: path.read_text()                  │ │ │   │       │ │
│  │  │  │  │  - run_write: path.write_text()                │ │ │   │       │ │
│  │  │  │  │  - run_edit: content.replace()                 │ │ │   │       │ │
│  │  │  │  └────────────────────────────────────────────────┘ │ │   │       │ │
│  │  │  │           │                                         │ │   │       │ │
│  │  │  │           ▼                                         │ │   │       │ │
│  │  │  │  ┌────────────────────────────────────────────────┐ │ │   │       │ │
│  │  │  │  │  results.append(tool_result)                   │ │ │   │       │ │
│  │  │  │  └────────────────────────────────────────────────┘ │ │   │       │ │
│  │  │  └─────────────────────────────────────────────────────┘ │   │       │ │
│  │  │           │                                              │   │       │ │
│  │  │           ▼                                              │   │       │ │
│  │  │  ┌──────────────────────────────────────────────────┐   │   │       │ │
│  │  │  │  state.messages.append(tool_result)              │   │   │       │ │
│  │  │  │  state.turn_count += 1                           │   │   │       │ │
│  │  │  │  return True  (继续循环)                          │   │   │       │ │
│  │  │  └──────────────────────────────────────────────────┘   │   │       │ │
│  │  │                                                         │   │       │ │
│  │  └─────────────────────────────────────────────────────────┘   │       │ │
│  │       │                                                        │       │ │
│  └───────┴────────────────────────────────────────────────────────┘       │ │
│                                                                           │ │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  循环结束，返回最终响应                                                 │ │
│  │  final_text = extract_text(history[-1]["content"])                    │ │
│  │  print(final_text)                                                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 设计点总结

### 循环不变原则

**核心设计哲学**：
```
s01: Agent Loop + 1 tool (bash)
s02: Agent Loop + 4 tools (bash, read, write, edit)
     ↓
     循环代码相同！
```

**实现方式**：
- TOOLS 列表扩展：添加新工具的 JSON Schema
- TOOL_HANDLERS 字典：添加新工具的处理函数
- execute_tool_calls()：使用字典查找，无需修改

### 路径沙箱机制

**防御层次**：
```
用户输入路径
    │
    ▼
(WORKDIR / p)     ← 第 1 层：强制拼接工作目录
    │
    ▼
.resolve()        ← 第 2 层：解析符号链接和 ..
    │
    ▼
is_relative_to()  ← 第 3 层：验证是否在工作目录内
    │
    ▼
通过 → 返回 Path
失败 → 抛出 ValueError
```

### 工具分发字典

**数据结构**：
```python
TOOL_HANDLERS = {
    "tool_name": lambda **kw: handler_function(kw["param1"], kw.get("param2")),
    ...
}
```

**调用模式**：
```python
output = TOOL_HANDLERS[f_name](**args)
```

**优势**：
- O(1) 查找复杂度
- 代码简洁，易于维护
- 天然支持工具不存在的情况检查


## 实践指南

### 运行方法

```bash
# 1. 确保模型服务已启动 (http://your-server-ip:port/v1)

# 2. 运行脚本
cd v1_task_manager/chapter_2/
python3 s02_tool_use.py
```

**预期启动输出**：
```
✅ 连通成功，模型：qwen3.5-xxx
s01 >>
```

### 测试示例

#### 读取文件

```
s01 >> 读取 s02_tool_use.py 的前 30 行
```

**预期行为**：
1. LLM 调用 `read_file` 工具，参数 `{"path": "s02_tool_use.py", "limit": 30}`
2. `run_read()` 执行路径验证、读取文件、截断内容
3. 返回前 30 行内容和剩余行数提示

**预期输出**：
```
#!/usr/bin/env python3
"""
s02_tool_use.py - Tools
...
(共 30 行)
... (XXX more lines)
```

---

#### 创建文件

```
s01 >> 创建一个名为 hello.py 的文件，内容是打印 "Hello, Agent!"
```

**预期行为**：
1. LLM 调用 `write_file` 工具，参数 `{"path": "hello.py", "content": "print(\"Hello, Agent!\")"}`
2. `run_write()` 执行路径验证、创建父目录、写入内容
3. 返回确认信息

**预期输出**：
```
Wrote 28 bytes to hello.py
```

---

#### 编辑文件

```
s01 >> 把 hello.py 中的 "Hello, Agent!" 改成 "Hello, World!"
```

**预期行为**：
1. LLM 调用 `edit_file` 工具
2. `run_edit()` 执行路径验证、读取内容、检查原文本、替换、写回
3. 返回确认信息

**预期输出**：
```
Edited hello.py
```

---

#### 多工具组合任务

```
s01 >> 创建一个配置文件 config.json，然后读取它确认内容
```

**预期行为**：
1. 第一轮：LLM 调用 `write_file` 创建 config.json
2. 第二轮：LLM 调用 `read_file` 读取确认
3. 返回最终总结

**消息历史演变**：
```
[system] "You are a coding agent..."
[user] "创建一个配置文件 config.json，然后读取它确认内容"
[assistant] (tool_call: write_file)
[tool] "Wrote 50 bytes to config.json"
[assistant] (tool_call: read_file)
[tool] "{...config 内容...}"
[assistant] "配置文件已创建并确认..."
```

---

#### 路径逃逸测试（被拦截）

```
s01 >> 读取 ../../etc/passwd
```

**预期行为**：
1. LLM 调用 `read_file` 工具
2. `safe_path()` 验证路径失败
3. 抛出 `ValueError`
4. 异常被捕获，返回错误信息

**预期输出**：
```
Error: Path escapes workspace
```

路径沙箱成功拦截了目录穿越攻击。

---

### 退出方式

| 方式 | 操作 |
|------|------|
| 命令退出 | 输入 `q` 或 `exit` |
| 空输入退出 | 直接按回车（空字符串） |
| 强制退出 | `Ctrl + C` |

---

## 整体设计总结

### 1. 循环不变，工具可扩展

Agent 循环是稳定的核心逻辑，不应随工具数量变化而修改。通过 TOOLS 列表和 TOOL_HANDLERS 字典的配置化设计，添加新工具只需修改配置，无需改动核心循环。这体现了"对扩展开放，对修改封闭"的开闭原则。

### 2. 安全优先

路径沙箱是所有文件操作工具的默认防护机制。通过强制拼接工作目录、解析符号链接、验证路径范围三层防御，确保工具无法访问项目外部的敏感文件。安全设计应作为默认选项，而非可配置项。

### 3. 工具互补

4 个工具各有明确的职责边界：
- `bash`：执行系统命令，支持管道、重定向等 shell 特性
- `read_file`：安全读取文件，支持 limit 参数
- `write_file`：安全创建文件，自动创建父目录
- `edit_file`：精确文本替换，只修改指定内容

工具之间功能互补，避免重叠，每个工具专注于解决特定场景。

### 4. 反馈闭环

错误信息返回给模型，形成反馈闭环。JSON 解析错误、路径验证失败、文本未找到等情况都通过工具结果返回给模型，让模型有机会修正错误。这种设计提高了任务成功率。

### 5. 简洁优先

核心循环保持简洁，复杂逻辑封装在工具函数中。execute_tool_calls() 使用统一的字典查找模式，不随工具数量增长而变得复杂。简洁的代码更易维护和理解。

---

**基于代码**：`v1_task_manager/chapter_2/s02_tool_use.py`  
**学习目标**：理解多工具 dispatch 架构和路径安全沙箱设计  
**前置知识**：s01 Agent Loop 机制
