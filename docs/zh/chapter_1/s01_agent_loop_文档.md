# s01: The Agent Loop (Agent 循环) - 代码文档 v2

---

## 概述

### 核心概念

**一个工具 + 一个循环 = 一个 Agent**

这是构建 AI Agent 的最基础范式。本节通过一个最简实现展示了 Agent 的核心工作机制：

- **工具 (Tool)**：Agent 与真实世界交互的能力接口（本节使用 `bash` 工具）
- **循环 (Loop)**：持续接收模型输出、判断是否需要工具调用、执行并反馈结果的迭代过程

### Harness 层定位

这个 Agent Loop 属于 **Harness 层**——它是模型与真实世界的第一道连接。在生产环境中，会在此基础上叠加策略控制、钩子函数和生命周期管理等更复杂的机制。

### 代码文件路径

```
v1_task_manager/chapter_1/agent_loop.py
```

### 核心架构图

```
    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> |  Tool   |
    |  prompt  |      |       |      | execute |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                          (loop continues)
```

**循环说明**：
1. User 输入 prompt 发送给 LLM
2. LLM 判断是否需要调用工具，输出 tool_call
3. Agent Loop 解析 tool_call，执行对应工具
4. 将工具执行结果 (tool_result) 反馈给 LLM
5. 循环继续，直到 LLM 不再请求工具调用

---

## 执行流程预览图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        代码执行顺序概览                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  第 1 阶段：模块导入与基础配置（Python 解释器启动时立即执行）              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  import 语句                                                     │   │
│  │       ↓                                                          │   │
│  │  OpenAI 客户端配置 (api_key, base_url, client)                   │   │
│  │       ↓                                                          │   │
│  │  MODEL = client.models.list().data[0].id  (动态获取模型)         │   │
│  │       ↓                                                          │   │
│  │  SYSTEM 提示词定义                                                │   │
│  │       ↓                                                          │   │
│  │  TOOLS 工具定义 (JSON Schema)                                    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                            ↓                                            │
│  第 2 阶段：数据结构定义（类定义，暂不执行）                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  @dataclass                                                      │   │
│  │  class LoopState:                                                │   │
│  │      messages: list                                              │   │
│  │      turn_count: int = 1                                         │   │
│  │      transition_reason: str | None = None                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                            ↓                                            │
│  第 3 阶段：工具执行层（函数定义，暂不执行）                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  def run_bash(command: str) -> str                               │   │
│  │      ├── 危险命令过滤                                            │   │
│  │      ├── subprocess.run() 执行                                   │   │
│  │      └── 输出截断 (50000 字符) + 超时控制 (120s)                  │   │
│  │                                                                   │   │
│  │  def extract_text(content) -> str                                │   │
│  │      └── 兼容 str 和 list 两种格式的内容提取                       │   │
│  │                                                                   │   │
│  │  def execute_tool_calls(response_content) -> list[dict]          │   │
│  │      ├── 遍历 tool_calls                                         │   │
│  │      ├── 解析参数 (json.loads)                                   │   │
│  │      ├── 调用 run_bash()                                         │   │
│  │      └── 构建 tool 结果消息                                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                            ↓                                            │
│  第 4 阶段：核心循环逻辑（函数定义，暂不执行）                            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  def run_one_turn(state: LoopState) -> bool                      │   │
│  │      ├── client.chat.completions.create() 调用 LLM               │   │
│  │      ├── 追加 assistant 消息到历史                                │   │
│  │      ├── 判断是否有 tool_calls                                   │   │
│  │      │   ├── 有：execute_tool_calls() → 追加结果 → return True   │   │
│  │      │   └── 无：return False                                    │   │
│  │      └── 更新 turn_count 和 transition_reason                    │   │
│  │                                                                   │   │
│  │  def agent_loop(state: LoopState) -> None                        │   │
│  │      └── while run_one_turn(state): pass  (核心循环)             │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                            ↓                                            │
│  第 5 阶段：程序入口与交互（用户运行脚本时执行）                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  if __name__ == "__main__":                                      │   │
│  │      ├── history = [system message]                              │   │
│  │      ├── while True:  (交互循环)                                 │   │
│  │      │   ├── input() 获取用户查询                                 │   │
│  │      │   ├── history.append(user message)                        │   │
│  │      │   ├── state = LoopState(messages=history)                 │   │
│  │      │   ├── agent_loop(state)  (启动 Agent 循环)                 │   │
│  │      │   └── print(extract_text(history[-1]["content"]))         │   │
│  │      └── 支持多轮对话 (history 持续累积)                          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**调用关系图**：

```
__main__
    │
    ├── 初始化 history = [SYSTEM]
    │
    └── while True (用户交互循环)
            │
            ├── input() 获取用户查询
            │
            ├── history.append({"role": "user", ...})
            │
            ├── state = LoopState(messages=history)
            │
            └── agent_loop(state)
                    │
                    └── while run_one_turn(state):
                            │
                            ├── client.chat.completions.create()
                            │       │
                            │       ├── model=MODEL
                            │       ├── tools=TOOLS
                            │       ├── messages=state.messages
                            │       └── extra_body.enable_thinking=True
                            │
                            ├── state.messages.append(assistant)
                            │
                            ├── if response_messages.tool_calls:
                            │       │
                            │       └── execute_tool_calls(response_messages)
                            │               │
                            │               ├── json.loads(arguments)
                            │               │
                            │               └── run_bash(command)
                            │                       │
                            │                       ├── dangerous 命令过滤
                            │                       ├── subprocess.run()
                            │                       ├── timeout=120
                            │                       └── out[:50000]
                            │
                            └── state.messages.append(tool_result)
```

---

## 第 1 阶段：模块导入与基础配置

> **阶段说明**：此阶段在 Python 脚本启动时立即执行，负责导入必要的模块、配置 API 客户端、定义系统提示词和工具规范。这些配置是整个 Agent 运行的基础环境。

### 1.1 导入模块

```python
import os, json
import subprocess
from dataclasses import dataclass
import time
from openai import OpenAI
```

**模块用途概述**：

| 模块 | 用途 |
|------|------|
| `os` | 获取当前工作目录，用于设置 subprocess 的工作目录 |
| `json` | 解析 tool_call 中的函数参数字符串为 Python 字典 |
| `subprocess` | 执行 bash 命令的核心模块 |
| `dataclasses.dataclass` | 装饰器，用于快速定义 `LoopState` 数据类 |
| `openai.OpenAI` | OpenAI Python SDK 的客户端类，用于调用兼容 OpenAI 接口的模型 API |

---

### 1.2 API 客户端配置

```python
import os
# 从环境变量获取 API 配置（推荐方式）
openai_api_key = os.getenv("OPENAI_API_KEY", "EMPTY")
openai_api_base = os.getenv("OPENAI_API_BASE", "http://your-server-ip:port/v1")
client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)

try:
    MODEL = client.models.list().data[0].id
    print(f"✅ 连通成功，模型：{MODEL}")
except Exception as e:
    print(f"❌ 获取模型失败：{e}")
    quit()
```

> **重要说明**：本教学文档及后续所有示例均采用 **OpenAI 兼容 API 接口格式** 构建 demo。这种格式已被广泛支持，包括 Qwen、Llama 等多种开源模型都提供 OpenAI 兼容接口，便于学习和迁移。

**环境变量配置方式（推荐）**：

使用环境变量管理敏感配置是最佳实践，可以避免将 API Key 等敏感信息硬编码在代码中。

**设置方法**：
```bash
# 临时设置（当前终端会话有效）
export OPENAI_API_KEY="your-api-key-here"
export OPENAI_API_BASE="http://your-server-ip:8000/v1"

# 永久设置（添加到 ~/.bashrc 或 ~/.zshrc）
echo 'export OPENAI_API_KEY="your-api-key-here"' >> ~/.bashrc
echo 'export OPENAI_API_BASE="http://your-server-ip:8000/v1"' >> ~/.bashrc
source ~/.bashrc
```

**优先级说明**：
- 如果设置了环境变量，使用环境变量中的值
- 如果未设置环境变量，使用默认值（`"EMPTY"` 和 `"http://your-server-ip:port/v1"`）

**配置说明**：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `api_key` | `"EMPTY"` 或环境变量 | 本地部署的模型通常不需要认证，可通过 `OPENAI_API_KEY` 环境变量设置 |
| `base_url` | `"http://your-server-ip:port/v1"` 或环境变量 | 本地模型服务器的 API 地址，可通过 `OPENAI_API_BASE` 环境变量设置 |
| `MODEL` | 动态获取 | 通过 `client.models.list()` 获取服务器上可用的第一个模型 ID |

**设计要点**：
- 使用 `try-except` 进行连接性检查，启动时验证 API 可用性
- 动态获取模型 ID 而非硬编码，提高配置灵活性

---

### 1.3 SYSTEM 提示词定义

```python
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to inspect and change the workspace. Act first, then report clearly."
```

**提示词设计**：
- 定义模型角色为 coding agent
- 告知模型当前工作目录，使其了解操作上下文
- 明确授权模型使用 bash 工具
- 指导模型行为模式：先执行操作，再清晰汇报

这是一个简洁的 system prompt，专注于工具使用授权和行为指导，避免过度约束模型。

---

### 1.4 TOOLS 工具定义

```python
TOOLS = [{
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a shell command.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute."
                }
            },
            "required": ["command"],
        }
    }
}]
```

**JSON Schema 结构说明**：

`TOOLS` 是一个列表，每个元素定义一个工具。本例中只定义了 `bash` 工具：

- **name**: 工具标识符，模型输出 tool_call 时使用的函数名
- **description**: 功能描述，帮助模型判断何时应该调用此工具
- **parameters**: 参数规范，使用 JSON Schema 格式定义参数类型和必填项
- **required**: 必填参数列表，确保模型不会遗漏关键参数

这种格式是 OpenAI Function Calling 的标准格式，被广泛支持。

---

## 第 2 阶段：数据结构定义

> **阶段说明**：此阶段定义 `LoopState` 数据类，用于封装 Agent 循环的状态。使用 `@dataclass` 装饰器可以自动生成 `__init__` 等方法，简化代码。

### 2.1 LoopState 数据类

```python
@dataclass
class LoopState:
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None
```

**字段说明**：

| 字段 | 类型 | 默认值 | 作用 |
|------|------|--------|------|
| `messages` | `list` | 无 | 存储完整的对话历史，包括 system、user、assistant、tool 所有角色的消息 |
| `turn_count` | `int` | `1` | 记录当前循环轮次，用于调试和状态追踪 |
| `transition_reason` | `str \| None` | `None` | 记录状态转换的原因（如 `"tool_result"`），用于理解循环决策逻辑 |

**设计优势**：
- 使用 `@dataclass` 简化数据类定义
- 将循环状态封装为单一对象，便于传递和管理
- `transition_reason` 提供可解释性，方便调试循环行为

**使用示例**：
```python
state.transition_reason = "tool_result"  # 因为工具结果继续循环
state.transition_reason = None           # 正常结束
```

---

## 第 3 阶段：工具执行层

> **阶段说明**：此阶段定义三个工具执行相关的函数。这些函数在第 4 阶段的核心循环中被调用。

### 3.1 run_bash() 函数详解

```python
def run_bash(command: str) -> str:
    # 不可执行操作，当 agent 试图执行列表中命令时打断，
    # 注意：此为基础演示，实际生产环境需要更完善的安全防护机制
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"] 
    if any(d in command for d in dangerous):
        return f"Error: Dangerous command blocked {command}"
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120) 
        out = (r.stdout + r.stderr).strip() 
        return out[:50000] if out else f"Command {command} executed successfully (no output)." 
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
```

**机制概述**：
该函数执行 shell 命令，包含三层处理：(1) 危险命令过滤，检查 5 种危险模式（`rm -rf /`、`sudo`、`shutdown`、`reboot`、`> /dev/`）并拦截；(2) subprocess 执行，设置工作目录、捕获输出、120 秒超时；(3) 输出处理，合并 stdout/stderr，限制 50000 字符，防止上下文爆炸。

> ⚠️ **安全提示**：此处的危险命令过滤仅为基础演示，简单的子字符串匹配容易被绕过。在实际生产环境中，必须对 Agent 的操作进行更严格的安全防护（如沙箱隔离、权限控制、命令白名单等）。

> ⚠️ **重要设计原则**：每次执行工具后都必须返回执行的动作和结果给模型。如果工具执行后没有返回任何信息，模型无法感知操作已完成，可能会陷入无限循环重复调用同一工具。

---

### 3.2 extract_text() 函数详解

```python
def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    elif not isinstance(content, list):
        return ""
    texts = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    return "\n".join(texts).strip()
```

**机制概述**：
该函数从响应内容中提取文本，支持两种格式：(1) 字符串格式直接返回；(2) 内容块列表格式则遍历每个块提取 `text` 属性，用换行符连接。设计目的是兼容不同模型的响应格式，安全处理未知类型避免异常。

---

### 3.3 execute_tool_calls() 函数详解

```python
def execute_tool_calls(response_content) -> list[dict]:
    results = []
    for tool_call in response_content.tool_calls:
        if tool_call.function.name == "bash":
            args = json.loads(tool_call.function.arguments)
            command = args.get("command")

            print(f"\033[33m$ {command}\033[0m")
            output = run_bash(command) 
            print(output[:200])

            results.append({
                "role": "tool", 
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": output
            })
    return results
```

**机制概述**：
该函数解析并执行模型的工具调用请求。流程：(1) 遍历 tool_calls 列表；(2) 判断工具类型只处理 bash；(3) 使用 json.loads 解析参数字符串；(4) 调用 run_bash 执行命令；(5) 构建符合 API 格式的 tool 结果消息（包含 role、tool_call_id、name、content）。返回结果用于追加到消息历史反馈给模型。

**返回结果格式**：
```python
{
    "role": "tool",              # 固定为 "tool"
    "tool_call_id": "...",       # 对应 tool_call 的 ID，用于关联请求和响应
    "name": "bash",              # 工具名称
    "content": "命令执行输出"     # 工具执行结果
}
```

---

## 第 4 阶段：核心循环逻辑

> **阶段说明**：此阶段定义 Agent 的核心循环逻辑。`run_one_turn()` 执行单次对话回合，`agent_loop()` 持续调用 `run_one_turn()` 直到模型不再请求工具。

### 4.1 run_one_turn() 函数详解

```python
def run_one_turn(state: LoopState) -> bool:
    response = client.chat.completions.create(            
            model=MODEL, 
            tools=TOOLS, 
            messages=state.messages,        
            max_tokens=8000,
            temperature=1,
            extra_body={
                "top_k": 20,
                "chat_template_kwargs": {"enable_thinking": True},
            }
        )

    response_messages = response.choices[0].message
    state.messages.append({"role": "assistant", "content": response_messages.content})

    if response_messages.tool_calls:
        results = execute_tool_calls(response_messages)
        if not results:
            state.transition_reason = None
            return False
        for tool_result in results:
            state.messages.append(tool_result)
        state.turn_count += 1
        state.transition_reason = "tool_result"
        return True
    else:
        state.transition_reason = None
        return False
```

**单次对话回合的完整流程**：

```
┌─────────────────────────────────────────────────────────┐
│                    run_one_turn()                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  1. 调用 LLM API                                        │
│     └── client.chat.completions.create()                │
│                                                         │
│  2. 提取响应消息                                        │
│     └── response.choices[0].message                     │
│                                                         │
│  3. 追加 assistant 消息到历史                            │
│     └── state.messages.append({"role": "assistant", ...})│
│                                                         │
│  4. 判断是否有 tool_calls                               │
│     │                                                   │
│     ├── 有 tool_calls ──> 执行工具 ──> 追加结果 ──> True│
│     │                │                                   │
│     │                └── 更新 turn_count                │
│     │                └── 设置 transition_reason         │
│     │                                                   │
│     └── 无 tool_calls ────────────────────────────> False│
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**机制概述**：
该函数执行单次对话回合的完整流程：(1) 调用 LLM API 发送请求，传入对话历史、工具定义和生成参数；(2) 提取响应消息并追加 assistant 消息到历史；(3) 判断是否有 tool_calls——有则执行工具并将结果加入消息历史，更新状态返回 True 继续循环；无则返回 False 结束循环。返回值 True 表示需要继续循环，False 表示循环结束。

**参数配置说明**：

| 参数 | 值 | 说明 |
|------|-----|------|
| `model` | `MODEL` | 模型 ID（动态获取） |
| `tools` | `TOOLS` | 可用工具列表 |
| `messages` | `state.messages` | 完整对话历史 |
| `max_tokens` | `8000` | 最大生成长度 |
| `temperature` | `1` | 采样温度（1 表示标准随机性） |
| `extra_body.top_k` | `20` | 采样时从 top 20 个 token 中选择 |
| `extra_body.chat_template_kwargs.enable_thinking` | `True` | Qwen3.5 思考模式开关 |

**返回值含义**：
- `True`：有工具调用，需要继续循环
- `False`：无工具调用，循环结束

---

### 4.2 agent_loop() 函数详解

```python
def agent_loop(state: LoopState) -> None:
    while run_one_turn(state):
        pass
```

**机制概述**：
这是整个 Agent 的核心循环，逻辑极其简洁：当 `run_one_turn(state)` 返回 True 时持续执行，每次执行都会调用 LLM、检查 tool_call、执行工具并将结果加入消息历史；当返回 False 时表示 LLM 不再请求工具调用，循环结束。设计哲学是极简主义，将复杂性封装在 `run_one_turn` 中，依赖 `LoopState` 在迭代间传递状态。

**主循环控制**：

```
while run_one_turn(state) 返回 True:
    - 持续执行 run_one_turn
    - 每次执行都会：
      1. 调用 LLM
      2. 检查是否有 tool_call
      3. 如果有，执行工具并将结果加入消息历史
      4. 返回 True 继续循环

当 run_one_turn 返回 False:
    - 表示 LLM 不再请求工具调用
    - 循环结束
```

**设计哲学**：
- 极简主义：核心循环只有 3 行代码
- 将复杂性封装在 `run_one_turn` 中
- 依赖 `LoopState` 在迭代间传递状态

---

## 第 5 阶段：程序入口与交互

> **阶段说明**：此阶段是 Python 脚本的入口点，负责启动交互式会话。它维护对话历史、获取用户输入、创建 LoopState 并启动 agent_loop。

### 5.1 __main__ 入口详解

```python
if __name__ == "__main__":
    history = [{"role": "system", "content": SYSTEM},]
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        state = LoopState(messages=history)
        agent_loop(state)
        final_text = extract_text(history[-1]["content"])
        if final_text:
            print(final_text)
        print()
```

**交互式循环流程**：

```
┌──────────────────────────────────────────────────────────────┐
│                       __main__ 入口                           │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. 初始化 history = [system message]                        │
│                                                              │
│  2. 进入主交互循环 while True:                               │
│     │                                                        │
│     ├── 获取用户输入 input()                                 │
│     │   └── 捕获 EOFError/KeyboardInterrupt → break          │
│     │                                                        │
│     ├── 检查退出命令 (q/exit/空) → break                     │
│     │                                                        │
│     ├── 添加用户消息到 history                               │
│     │                                                        │
│     ├── 创建 LoopState 并启动 agent_loop                     │
│     │   └── agent_loop 内部循环执行直到无 tool_call          │
│     │                                                        │
│     ├── 提取并打印最终响应                                   │
│     │   └── extract_text(history[-1]["content"])             │
│     │                                                        │
│     └── 循环继续（history 保持，支持多轮对话）                │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**机制概述**：
这是 Python 脚本的入口点，负责启动交互式会话。流程：(1) 初始化包含 system 消息的对话历史；(2) 进入主交互循环持续获取用户输入；(3) 支持 EOFError、KeyboardInterrupt 异常处理和退出命令（q、exit、空输入）；(4) 将用户输入追加到历史，创建 LoopState 并启动 agent_loop；(5) 提取最终文本响应并打印。history 在循环外维护，保留完整上下文支持多轮对话。

**特性说明**：
- 支持多轮对话：`history` 在循环外维护，保留完整上下文
- 友好的退出机制：支持 `q`、`exit`、空输入或 Ctrl+C
- 彩色提示符：`\033[36m` 显示青色提示符
- 自动提取最终文本响应并打印

---

### 5.2 完整执行流程追踪

**从脚本启动到完成一次用户查询的完整流程**：

```
1. 脚本启动 (python3 agent_loop.py)
   │
   ├─→ 执行第 1 阶段：导入模块、配置 API、定义 SYSTEM 和 TOOLS
   │     └── 打印 "✅ 连通成功，模型：qwen3.5-xxx"
   │
   ├─→ 执行第 2 阶段：定义 LoopState 类
   │
   ├─→ 执行第 3 阶段：定义工具执行函数
   │
   ├─→ 执行第 4 阶段：定义核心循环函数
   │
   └─→ 执行第 5 阶段：进入 __main__

2. 用户输入查询 ("查看当前目录")
   │
   ├─→ history.append({"role": "user", "content": "查看当前目录"})
   │
   ├─→ state = LoopState(messages=history)
   │
   └─→ agent_loop(state)

3. agent_loop 内部循环
   │
   ├─→ 第 1 次 run_one_turn(state)
   │     │
   │     ├─→ 调用 LLM (messages: [system, user], tools: [bash])
   │     │
   │     ├─→ 模型返回 tool_call:
   │     │     [
   │     │       {
   │     │         "name": "bash",
   │     │         "arguments": {"command": "ls -la"}
   │     │       }
   │     │     ]
   │     │
   │     ├─→ 执行工具并获取结果
   │     │     └── run_bash("ls -la") → "dir1\ndir2\nfile.txt"
   │     │
   │     └─→ 返回 True (继续循环)
   │
   ├─→ 第 2 次 run_one_turn(state)
   │     │
   │     ├─→ 调用 LLM (messages: [system, user, assistant, tool])
   │     │
   │     ├─→ 模型返回最终文本响应 (无 tool_call)
   │     │
   │     └─→ 返回 False (结束循环)
   │
   └─→ agent_loop 返回

4. 提取并打印最终响应
   │
   └─→ 打印模型响应

5. 等待下一个用户输入...
```

---

## 关键设计点总结

### 1. 消息累积机制

```python
# 在 run_one_turn 中
state.messages.append({"role": "assistant", "content": response_messages.content})
# ...
for tool_result in results:
    state.messages.append(tool_result)
```

**机制说明**：

每次 LLM 响应和工具执行结果都追加到消息历史，保持完整的对话上下文。这种设计：

- 支持多轮推理，模型可以基于之前的工具结果继续决策
- 实现上下文保持，每轮对话都有完整的历史信息
- 便于调试和复盘整个交互过程

**对话历史累积示例**：

```
第 1 轮:
├── [system] "You are a coding agent..."
├── [user] "查看当前目录"
├── [assistant] None (包含 tool_call)
└── [tool] "dir1\ndir2\nfile.txt"

第 2 轮 (基于第 1 轮结果继续):
├── [system] "You are a coding agent..."
├── [user] "查看当前目录"
├── [assistant] None (包含 tool_call)
├── [tool] "dir1\ndir2\nfile.txt"
├── [assistant] "当前目录包含..." (最终响应)
└── [user] "下一个问题..." (新输入)
```

---

### 2. tool_calls 判断逻辑

```python
if response_messages.tool_calls:
    # 有工具调用，执行并返回 True 继续循环
else:
    # 无工具调用，返回 False 结束循环
```

**判断逻辑**：

| 条件 | 含义 | 动作 |
|------|------|------|
| `response_messages.tool_calls` 为真 | LLM 请求调用一个或多个工具 | 执行工具，将结果反馈给 LLM，继续循环 |
| `response_messages.tool_calls` 为假/空 | LLM 认为不需要工具，任务完成 | 结束循环，返回最终响应 |

**关键点**：
- 依赖 LLM 自主判断何时停止
- 不需要预设最大循环次数
- 可能存在无限循环风险（生产环境需添加保护）

---

### 3. 危险命令过滤机制

```python
dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"] 
if any(d in command for d in dangerous):
    return f"Error: Dangerous command blocked {command}"
```

**过滤策略**：

| 危险模式 | 风险 | 过滤方式 |
|----------|------|----------|
| `rm -rf /` | 删除根目录所有文件 | 子字符串匹配 |
| `sudo` | 提权执行 | 子字符串匹配 |
| `shutdown` | 关机 | 子字符串匹配 |
| `reboot` | 重启 | 子字符串匹配 |
| `> /dev/` | 重定向到设备文件 | 子字符串匹配 |

> ⚠️ **局限性**：简单的子字符串匹配容易被绕过（如拼接、编码、变量替换等）。生产环境需要沙箱容器、权限隔离、命令白名单等更严格措施。

---

### 4. 输出长度限制

```python
return out[:50000] if out else f"Command {command} executed successfully (no output)."
```

**设计考虑**：

| 因素 | 说明 |
|------|------|
| 上下文窗口限制 | 防止单次工具输出消耗过多 token |
| 响应时间控制 | 避免传输大量数据导致延迟 |
| 信息密度 | 大多数命令输出远小于此限制 |

**截断策略**：保留前 50000 字符，无截断提示；空输出时返回成功提示而非空字符串。

---

### 5. 超时控制

```python
subprocess.run(..., timeout=120)
...
except subprocess.TimeoutExpired:
    return "Error: Timeout (120s)"
```

**超时设置**：120 秒，平衡长时间任务和响应性。捕获超时异常并返回友好错误信息，允许循环继续而不导致程序崩溃。

---

### 6. LoopState 状态追踪

```python
@dataclass
class LoopState:
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None
```

**状态追踪维度**：

| 字段 | 追踪内容 | 调试价值 |
|------|----------|----------|
| `messages` | 完整对话历史 | 复盘整个交互过程 |
| `turn_count` | 循环轮次 | 识别异常长的循环 |
| `transition_reason` | 状态转换原因 | 理解循环决策逻辑 |

**使用示例**：
```python
state.transition_reason = "tool_result"  # 因为工具结果继续循环
state.transition_reason = None           # 正常结束
```

---

## Qwen3.5 特性说明

### enable_thinking 思考模式

```python
extra_body={
    "top_k": 20,
    "chat_template_kwargs": {"enable_thinking": True},
}
```

`chat_template_kwargs: {"enable_thinking": True}` 是 **Qwen3.5 模型特有的思考模式开关**。

**工作原理**：

| 模式 | 行为 | 输出特点 |
|------|------|----------|
| `enable_thinking: True` | 启用思考模式 | 模型在给出最终答案前，会先生成一段"思考过程"，展示推理链条 |
| `enable_thinking: False` | 禁用思考模式 | 模型直接输出最终答案，不展示中间推理过程 |

**对模型输出的影响**：

1. **输出结构变化**：模型会在 `thought>` 标签内生成思考过程，然后输出最终答案

   **思考模式输出结构示例**：
   ```
   thought>
   让我分析一下这个问题...
   首先需要考虑...
   然后应该...
   最后得出结论...
   /thought>
   
   最终答案是...
   ```

2. **工具调用场景**：
   - 模型会在思考过程中分析是否需要调用工具
   - 思考内容不计入 tool_call 判断
   - 最终的 tool_call 仍然正常触发工具执行

3. **优势**：
   - 提高复杂任务的可解释性
   - 有助于调试模型决策过程
   - 可能提升复杂推理任务的表现

> **注意**：此参数是 Qwen3.5 的特定扩展，其他模型可能不支持或需要不同的配置方式。

---

## 实践指南

### 如何运行代码

```bash
# 1. 确保模型服务已启动 (http://your-server-ip:port/v1)

# 2. 运行脚本
cd v1_task_manager/chapter_1/
python3 agent_loop.py
```

**预期启动输出**：
```
✅ 连通成功，模型：qwen3.5-xxx
s01 >>
```

### 测试示例提示词

#### 示例 1：查看当前目录

```
s01 >> 查看当前目录下有哪些文件
```

**预期行为**：
1. LLM 调用 `bash` 工具执行 `ls -la`
2. 显示命令输出
3. 返回文件列表摘要

#### 示例 2：创建文件

```
s01 >> 创建一个名为 test.txt 的文件，内容为 "Hello Agent"
```

**预期行为**：
1. LLM 调用 `bash` 执行 `echo "Hello Agent" > test.txt`
2. 验证文件创建成功
3. 返回确认信息

#### 示例 3：多步骤任务

```
s01 >> 列出所有 Python 文件，然后统计它们的总行数
```

**预期行为**：
1. 第一轮：执行 `find . -name "*.py"` 查找 Python 文件
2. 第二轮：对每个文件执行 `wc -l` 统计行数
3. 汇总结果并返回

### 退出方式

| 方式 | 操作 |
|------|------|
| 命令退出 | 输入 `q` 或 `exit` |
| 空输入退出 | 直接按回车（空字符串） |
| 强制退出 | `Ctrl + C` |

---

## 总结

### 核心收获

1. **Agent 的本质**：一个工具 + 一个循环 = 一个 Agent
   - 工具提供能力边界
   - 循环实现自主决策

2. **Harness 层设计**：
   - 极简的核心循环（3 行代码）
   - 状态封装在 `LoopState` 数据类中
   - 消息历史累积实现上下文保持

3. **工具调用机制**：
   - JSON Schema 定义工具接口
   - LLM 自主决定何时调用工具
   - 工具结果反馈形成闭环

4. **安全与限制**：
   - 危险命令过滤（基础防护）
   - 输出长度限制（50000 字符）
   - 超时控制（120 秒）

---

**基于代码**：`agent_loop.py` (v1_task_manager/chapter_1/agent_loop.py)  
**学习目标**：理解 Agent Loop 的核心机制
