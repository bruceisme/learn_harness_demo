# s06: Context Compact (上下文压缩) - 代码文档

---

## 概述

### 核心改进

**从无限上下文到三层压缩机制**

s06 在 s05 的基础上引入了 **上下文压缩系统**，解决了长对话导致上下文超限的问题。通过三层压缩机制（Micro-Compact、Auto-Compact、Manual-Compact）和大输出持久化，框架能够处理长时间对话。

### 设计思想

> **"分级压缩 + 持久化存储"**

s06 的核心设计思想：根据内容类型和上下文大小，采用不同粒度的压缩策略，同时将大输出写入磁盘避免上下文膨胀。

**三层压缩机制**：
- **Micro-Compact（微型压缩）**：压缩旧的工具结果，仅保留最近的几条完整内容
- **Auto-Compact（自动压缩）**：当上下文超限时，调用模型总结整个对话历史
- **Manual-Compact（手动压缩）**：模型主动调用 `compact` 工具触发压缩

**持久化策略**：
- **大输出持久化**：超过阈值的工具输出写入 `.task_outputs/tool-results/` 目录
- **对话记录保存**：压缩前将完整对话保存为 JSONL 文件

### 代码文件路径

```
v1_task_manager/chapter_6/s06_context.py
```

### 核心架构图（对比 s05）

**s05 架构（无压缩机制）**：
```
    +----------+      +-----------+      +------------------+
    |   User   | ---> |  LLM      | ---> | Tools            |
    |  prompt  |      |           |      | {task, todo,     |
    +----------+      +-----------+      |  read_file,      |
                                         |  compact?}       |
                                         +------------------+
        ↑                                        |
        |                                        |
        +----------------------------------------+
                  上下文持续增长，无压缩
```

**s06 架构（三层压缩 + 持久化）**：
```
    +----------+      +-----------+      +------------------+
    |   User   | ---> |  LLM      | ---> | Tools            |
    |  prompt  |      |           |      | {task, todo,     |
    +----------+      +-----+-----+      |  compact, ...}   |
                              |          +--------+---------+
                              |                   |
                              |                   | tool output
                              |                   v
                              |          +--------+--------+
                              |          | 输出大小判断    |
                              |          +--------+--------+
                              |                   |
                      +-------+--------+  +-------+--------+
                      | ≤ PERSIST_     |  | > PERSIST_     |
                      |   THRESHOLD    |  |   THRESHOLD    |
                      +-------+--------+  +-------+--------+
                              |                   |
                              |                   v
                              |          +--------+--------+
                              |          | 写入磁盘        |
                              |          | .task_outputs/  |
                              |          | tool-results/   |
                              |          +--------+--------+
                              |                   |
                              +-------------------+
                                      |
                    +-----------------+------------------+
                    |                                    |
            +-------v--------+                  +--------v-------+
            | Micro-Compact  |                  | Auto-Compact   |
            | 每次工具调用后 |                  | 上下文超限时   |
            | 压缩旧工具结果 |                  | 总结历史对话   |
            +-------+--------+                  +--------+-------+
                    |                                    |
                    +------------------+-----------------+
                                       |
                              +--------v--------+
                              | 紧凑的上下文    |
                              | 继续对话        |
                              +-----------------+
```

**架构说明**：
1. 每次工具调用后执行 Micro-Compact，压缩旧的工具结果
2. 每次对话轮次前检查上下文大小，超限则触发 Auto-Compact
3. 模型可主动调用 `compact` 工具触发 Manual-Compact
4. 大输出（>30000 字符）写入磁盘，返回预览 + 路径

---

## 目录结构依赖

本章节代码会创建或使用以下目录和文件：

| 目录/文件 | 用途 | 创建方式 |
|-----------|------|----------|
| `.transcripts/` | 保存对话记录（JSONL 格式） | auto-compaction 时自动创建 |
| `.task_outputs/tool-results/` | 持久化大输出文件 | 工具输出超过阈值时自动创建 |
| `.claude/.claude_trusted` | 工作区信任标记文件 | 用户手动创建 |

**对话记录文件格式**（`.transcripts/transcript_{timestamp}.jsonl`）：
- 每行一个 JSON 对象
- 包含 role, content 等字段
- 用于压缩后追溯历史对话

**大输出持久化**（`.task_outputs/tool-results/{tool_call_id}.txt`）：
- 当工具输出超过 30000 字符时触发
- 保存完整输出到文件
- 返回预览（前 2000 字符）+ 文件路径给模型

---

## 与 s05 的对比

### 变更总览

| 组件 | s05 | s06 | 变化说明 |
|------|-----|-----|----------|
| **新增配置参数** | 无 | `CONTEXT_LIMIT`, `PERSIST_THRESHOLD`, `PREVIEW_CHARS`, `KEEP_RECENT_TOOL_RESULTS` | 压缩和持久化阈值配置 |
| **新增目录配置** | 无 | `TRANSCRIPT_DIR`, `TOOL_RESULTS_DIR` | 对话记录和工具结果存储路径 |
| **新增数据类** | 无 | `CompactState` | 追踪压缩状态（has_compacted, last_summary, recent_files） |
| **新增函数** | 无 | `estimate_context_size`, `persist_large_output`, `micro_compact`, `compact_history`, `summarize_history`, `write_transcript`, `collect_tool_result_blocks`, `track_recent_file` | 压缩和持久化核心函数 |
| **新增工具** | 无 | `compact` | 模型可手动触发压缩 |
| **agent_loop 变化** | 直接执行对话 | 先执行 Micro-Compact，再检查 Auto-Compact | 三层压缩触发机制 |
| **execute_tool_calls 变化** | 仅返回结果 | 额外返回 `manual_compact`, `compact_focus` | 支持手动压缩标记 |

### 新增组件架构

```
s06 新增组件：

数据类：
└── CompactState
    ├── has_compacted: bool          # 是否已压缩
    ├── last_summary: str            # 最后一次总结内容
    └── recent_files: list[str]      # 最近访问的文件路径

配置参数：
├── CONTEXT_LIMIT = 50000            # 上下文大小限制（字符）
├── PERSIST_THRESHOLD = 30000        # 持久化阈值（字符）
├── PREVIEW_CHARS = 2000             # 预览字符数
├── KEEP_RECENT_TOOL_RESULTS = 3     # 保留最近的工具结果数量
├── TRANSCRIPT_DIR                   # 对话记录目录
└── TOOL_RESULTS_DIR                 # 工具结果存储目录

核心函数：
├── estimate_context_size(messages)  # 估算上下文大小
├── persist_large_output(tool_use_id, output)  # 大输出持久化
├── collect_tool_result_blocks(messages)       # 收集工具结果索引
├── micro_compact(messages)          # 微型压缩
├── compact_history(messages, state, focus)    # 历史压缩
├── summarize_history(messages)      # 调用模型总结
└── write_transcript(messages)       # 保存对话记录

工具：
└── compact (JSON Schema)
    └── focus (optional): str        # 压缩时需要保留的重点
```

---

## 按执行顺序详解

### 第 1 阶段：新增配置参数

#### 机制概述

s06 在文件开头定义了压缩和持久化相关的配置参数，这些参数控制三层压缩机制的触发条件和行为。

```python
# --- 配置参数 ---
CONTEXT_LIMIT = 50000
PERSIST_THRESHOLD = 30000
PREVIEW_CHARS = 2000
PLAN_REMINDER_INTERVAL = 3
KEEP_RECENT_TOOL_RESULTS = 3

# --- 目录配置 ---
WORKDIR = Path.cwd()
SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"
```

**参数设计思想**：
- `CONTEXT_LIMIT`（50000）：上下文大小上限，超过此值触发 Auto-Compact
- `PERSIST_THRESHOLD`（30000）：工具输出持久化阈值，超过此值写入磁盘
- `PREVIEW_CHARS`（2000）：持久化时返回的预览字符数
- `KEEP_RECENT_TOOL_RESULTS`（3）：Micro-Compact 保留的最近工具结果数量
- `TRANSCRIPT_DIR`：压缩前保存的完整对话记录目录（`.transcripts/`）
- `TOOL_RESULTS_DIR`：大工具输出存储目录（`.task_outputs/tool-results/`）

---

### 第 2 阶段：CompactState 数据类

#### 机制概述

`CompactState` 用于追踪压缩状态，在多次压缩之间保持上下文信息。与 `LoopState` 追踪对话历史不同，`CompactState` 专注于压缩相关的元数据。

```python
@dataclass
class CompactState:
    has_compacted: bool = False
    last_summary: str = ""
    recent_files: list[str] = field(default_factory=list)
```

**字段说明**：
- `has_compacted`：标记是否已执行过压缩，用于判断当前上下文是否为压缩后的状态
- `last_summary`：保存最后一次压缩生成的总结内容，可在后续压缩中参考
- `recent_files`：记录最近访问的 5 个文件路径，压缩后提示模型可重新打开这些文件

**设计思想**：为什么需要追踪压缩状态

压缩会丢失部分历史信息，`CompactState` 的作用是：
1. **状态标记**：`has_compacted` 让系统知道当前上下文是经过压缩的
2. **信息保留**：`last_summary` 保存压缩后的总结，避免完全丢失历史
3. **文件追踪**：`recent_files` 记录最近操作的文件，压缩后模型可快速恢复上下文

---

### 第 3 阶段：Micro-Compact 机制

#### 机制概述

Micro-Compact 是粒度最细的压缩机制，在每次工具调用后执行。它压缩旧的工具结果，仅保留最近的 `KEEP_RECENT_TOOL_RESULTS`（3 条）完整内容，其余替换为简短占位符。

**执行流程**：
```
工具调用完成 → collect_tool_result_blocks() → micro_compact() → 更新消息列表
```

#### collect_tool_result_blocks() 函数

```python
def collect_tool_result_blocks(messages: list) -> list[int]:
    tool_message_indices = []
    for index, message in enumerate(messages):
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        if role == "tool":
            tool_message_indices.append(index)
    return tool_message_indices
```

**功能**：遍历消息列表，收集所有 `role="tool"` 的消息索引，返回索引列表供 `micro_compact()` 使用。

#### micro_compact() 函数

```python
def micro_compact(messages: list) -> list:
    tool_indices = collect_tool_result_blocks(messages)
    if len(tool_indices) <= KEEP_RECENT_TOOL_RESULTS:
        return messages
    for index in tool_indices[:-KEEP_RECENT_TOOL_RESULTS]:
        message = messages[index]
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
        
        if isinstance(content, str) and len(content) > 120:
            compact_text = "[Earlier tool result compacted. Re-run the tool if you need full detail.]"
            if isinstance(message, dict):
                message["content"] = compact_text
            else:
                try:
                    message.content = compact_text
                except AttributeError:
                    messages[index] = message.model_dump(exclude_none=True) if hasattr(message, "model_dump") else message.dict(exclude_none=True)
                    messages[index]["content"] = compact_text
    return messages
```

**压缩逻辑**：
1. 收集所有工具结果的索引
2. 如果工具结果数量 ≤ 3，直接返回（无需压缩）
3. 遍历除了最近 3 条之外的所有工具结果
4. 如果内容长度 > 120 字符，替换为占位符文本
5. 处理 dict 和对象两种消息格式，兼容不同 SDK 版本

**KEEP_RECENT_TOOL_RESULTS 保留策略**：
- 保留最近的 3 条工具结果完整内容
- 超过 3 条时，旧的结果被压缩为：`"[Earlier tool result compacted. Re-run the tool if you need full detail.]"`
- 模型如需旧结果的完整内容，可重新执行对应工具

---

### 第 4 阶段：大输出持久化

#### 机制概述
当工具输出超过 `PERSIST_THRESHOLD`（30000 字符）时，`persist_large_output()` 将输出写入磁盘文件，避免大输出占用上下文空间。返回格式为预览 + 文件路径。

#### persist_large_output() 函数

```python
def persist_large_output(tool_use_id: str, output: str) -> str:
    if len(output) <= PERSIST_THRESHOLD:
        return output
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    if not stored_path.exists():
        stored_path.write_text(output)
    preview = output[:PREVIEW_CHARS]
    rel_path = stored_path.relative_to(WORKDIR)
    return (
        "<persisted-output>\n"
        f"Full output saved to: {rel_path}\n"
        "Preview:\n"
        f"{preview}\n"
        "</persisted-output>"
    )
```

**阈值判断逻辑**：
1. 检查输出长度是否 ≤ 30000 字符
2. 如果未超过阈值，直接返回原始输出
3. 如果超过阈值，执行持久化流程

**持久化流程**：
1. 创建目录 `.task_outputs/tool-results/`（如果不存在）
2. 以 `tool_use_id.txt` 为文件名保存完整输出
3. 提取前 2000 字符作为预览
4. 计算相对路径（相对于工作目录）
5. 返回结构化格式：`<persisted-output>...<persisted-output>`

**返回格式示例**：
```
<persisted-output>
Full output saved to: .task_outputs/tool-results/call_abc123.txt
Preview:
[前 2000 字符的输出内容...]
</persisted-output>
```

**注意**：s06 代码中定义了 `persist_large_output()` 函数，但在实际工具调用链中未集成调用。该函数在 s06 阶段作为预备功能存在，在s10中实装。

---

### 第 5 阶段：Auto-Compact 机制

#### 机制概述

Auto-Compact 在上下文大小超过 `CONTEXT_LIMIT`（50000 字符）时自动触发。它调用模型总结整个对话历史，生成紧凑的总结替换原始消息。

**执行流程**：
```
检查上下文大小 → estimate_context_size() → 超限？ → compact_history()
                                              ↓
                                    write_transcript() 保存记录
                                              ↓
                                    summarize_history() 调用模型总结
                                              ↓
                                    生成新的紧凑消息列表
```

#### estimate_context_size() 函数

```python
def estimate_context_size(messages: list) -> int:
    return len(str(messages))
```

**功能**：将消息列表转换为字符串，返回字符数作为上下文大小的估算值。这是一个简化的估算方法，实际 token 数可能不同。

#### write_transcript() 函数

```python
def write_transcript(messages: list) -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with path.open("w") as handle:
        for message in messages:
            handle.write(json.dumps(message, default=str) + "\n")
    return path
```

**功能**：在压缩前保存完整对话记录到 JSONL 文件。

**保存格式**：
- 目录：`.transcripts/`
- 文件名：`transcript_{时间戳}.jsonl`
- 格式：每行一个 JSON 对象（JSONL 格式）
- 作用：压缩后如需恢复完整历史，可从文件读取

#### summarize_history() 函数

```python
def summarize_history(messages: list) -> str:
    conversation = json.dumps(messages, default=str)[:80000]
    prompt = (
        "Summarize this coding-agent conversation so work can continue.\n"
        "Preserve:\n"
        "1. The current goal\n"
        "2. Important findings and decisions\n"
        "3. Files read or changed\n"
        "4. Remaining work\n"
        "5. User constraints and preferences\n"
        "Be compact but concrete.\n\n"
        f"{conversation}"
    )
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    return response.choices[0].message.content.strip()
```

**功能**：调用模型总结对话历史。

**提示词设计**：
- 要求保留：当前目标、重要发现和决策、读/改的文件、剩余工作、用户约束和偏好
- 限制输出：`max_tokens=2000`，要求简洁具体
- 输入限制：截取前 80000 字符（防止总结请求本身过大）

#### compact_history() 函数

```python
def compact_history(messages: list, state: CompactState, focus: str | None = None) -> list:
    transcript_path = write_transcript(messages)
    print(f"[transcript saved: {transcript_path}]")
    summary = summarize_history(messages)
    if focus:
        summary += f"\n\nFocus to preserve next: {focus}"
    if state.recent_files:
        recent_lines = "\n".join(f"- {path}" for path in state.recent_files)
        summary += f"\n\nRecent files to reopen if needed:\n{recent_lines}"
    state.has_compacted = True
    state.last_summary = summary
    system_message = messages[0] if messages and messages[0].get("role") == "system" else None

    compacted_message = {
        "role": "user",
        "content": (
            "This conversation was compacted so the agent can continue working.\n\n"
            f"{summary}"
        ),
    }
    return [system_message, compacted_message] if system_message else [compacted_message]
```

**压缩流程**：
1. 保存完整对话到 `.transcripts/` 目录
2. 调用 `summarize_history()` 生成总结
3. 如果有 `focus` 参数，附加到总结中（提示下次压缩保留的重点）
4. 如果有最近访问的文件列表，附加到总结中
5. 更新 `CompactState`：`has_compacted=True`，`last_summary=summary`
6. 保留 system 消息（如果存在）
7. 创建新的用户消息，包含总结内容
8. 返回紧凑的消息列表（仅 system + 1 条总结消息）

**压缩后效果**：
- 原始：N 条消息（可能几十条）
- 压缩后：1-2 条消息（system + 总结）

---

### 第 6 阶段：Manual-Compact 机制

#### 机制概述

Manual-Compact 允许模型主动调用 `compact` 工具触发压缩。与 Auto-Compact 不同，Manual-Compact 由模型根据对话情况自主决定何时压缩。

#### compact 工具 JSON Schema

```python
{"type": "function", "function": {
    "name": "compact",
    "description": "Summarize earlier conversation so work can continue in a smaller context.",
    "parameters": {
        "type": "object",
        "properties": {
            "focus": {
                "type": "string"
            }
        }
    }
}}
```

**参数说明**：
- `focus`（可选）：字符串，模型自主指定压缩时需要特别保留的内容重点
- 示例：`{"focus": "The current debugging session for file X"}`

#### execute_tool_calls 变化

```python
def execute_tool_calls(response_content) -> tuple[list[dict], str | None, bool, str | None]:
    used_todo = False
    manual_compact = False
    compact_focus = None
    results = []
    for tool_call in response_content.tool_calls:
        f_name = tool_call.function.name
        # ... 执行工具 ...
        if f_name in TOOL_HANDLERS:
            output = TOOL_HANDLERS[f_name](**args)
            # 压缩的额外步骤
            if f_name == "compact":
                manual_compact = True
                compact_focus = args.get("focus")
        # ... 返回结果 ...
    return results, reminder, manual_compact, compact_focus
```

**变化说明**：
- 返回值从 `(results, reminder)` 扩展为 `(results, reminder, manual_compact, compact_focus)`
- 检测到 `compact` 工具调用时，设置 `manual_compact=True`
- 提取 `focus` 参数传递给 `compact_history()`

#### compact_focus 参数

`compact_focus` 允许模型在调用 `compact` 工具时指定重点保留的内容：

```python
if manual_compact:
    print("[manual compact]")
    state.messages = compact_history(state.messages, compact_state, focus=compact_focus)
```

在 `compact_history()` 中，`focus` 会被附加到总结中：
```python
if focus:
    summary += f"\n\nFocus to preserve next: {focus}"
```

---

### 第 7 阶段：agent_loop 变化

#### 机制概述

`agent_loop()` 是主代理的核心循环函数。s06 在 s05 的基础上增加了三层压缩的触发逻辑。

#### 三层压缩的触发时机

```python
def agent_loop(state: LoopState, compact_state: CompactState) -> None:
    while True:
        # 1. 执行微型压缩 (Micro-Compact)
        state.messages = micro_compact(state.messages)

        # 2. 检查是否触发全局压缩 (Auto-Compact)
        if estimate_context_size(state.messages) > CONTEXT_LIMIT:
            print("[auto compact]")
            state.messages = compact_history(state.messages, compact_state)
        
        # 3. 运行一轮对话
        has_next_step = run_one_turn(state, compact_state)
        
        # 如果模型没有调用工具（任务结束或需要用户输入），退出自动循环
        if not has_next_step:
            break
```

**触发顺序**：
1. **Micro-Compact**：每次循环开始执行，压缩旧的工具结果
2. **Auto-Compact**：检查上下文大小，超限则触发
3. **对话执行**：调用 `run_one_turn()` 执行一轮对话
4. **Manual-Compact**：在 `run_one_turn()` 内部，如果模型调用 `compact` 工具，触发压缩

#### 压缩后的历史更新

```python
def run_one_turn(state: LoopState, compact_state: CompactState) -> bool:
    # ... 调用模型 ...
    if response_message.tool_calls:
        results, reminder, manual_compact, compact_focus = execute_tool_calls(response_message)
        for tool_result in results:
            state.messages.append(tool_result)
        
        if manual_compact:
            print("[manual compact]")
            state.messages = compact_history(state.messages, compact_state, focus=compact_focus)
        # ...
```

**更新逻辑**：
- Micro-Compact 和 Auto-Compact 直接在 `agent_loop()` 中更新 `state.messages`
- Manual-Compact 在 `run_one_turn()` 中，工具调用完成后更新 `state.messages`
- 压缩后，旧的历史消息被替换为总结消息，`state.messages` 长度显著减少

---

## 完整框架流程图

```
+----------+
|   User   |
|  prompt  |
+-----+----+
      |
      v
+-----+------------+
| agent_loop 入口  |
+-----+------------+
      |
      v
+-----+------------+
| 1. Micro-Compact |  压缩旧工具结果
| micro_compact()  |  保留最近 3 条
+-----+------------+
      |
      v
+-----+------------+
| 2. 检查上下文大小 |  estimate_context_size()
+-----+------------+
      |
      +-----> [≤ CONTEXT_LIMIT] ----+
      |                             |
      v                             v
[> CONTEXT_LIMIT]           +-------+--------+
      |                     | 3. run_one_turn|
      v                     +-------+--------+
+-----+------------+                |
| Auto-Compact     |                |
| compact_history()|                v
| - 保存 transcript|        +-------+--------+
| - 调用模型总结   |        | 模型响应      |
| - 更新消息列表   |        +-------+--------+
+-----+------------+                |
      |                             |
      +-----------------------------+
                                    |
                                    v
                          +---------+----------+
                          | 有 tool_calls?     |
                          +---------+----------+
                                    |
                    +---------------+---------------+
                    |                               |
                   是                               否
                    |                               |
                    v                               v
          +---------+----------+           +-------+--------+
          | execute_tool_calls |           | 任务结束      |
          +---------+----------+           | 退出循环      |
                    |                      +----------------+
                    |
          +---------+----------+
          | Manual-Compact?    |
          +---------+----------+
                    |
        +-----------+-----------+
        |                       |
       是                      否
        |                       |
        v                       v
+-------+--------+      +-------+--------+
| compact_history|      | 追加 tool_result|
| focus 参数传递  |      | 继续下一轮     |
+----------------+      +----------------+
```

---

## 设计点总结

### 三层压缩机制

| 压缩类型 | 触发条件 | 压缩对象 | 压缩粒度 |
|----------|----------|----------|----------|
| **Micro-Compact** | 每次工具调用后 | 工具结果消息 | 压缩超过 3 条的旧结果 |
| **Auto-Compact** | 上下文 > 50000 字符 | 整个对话历史 | 调用模型总结 |
| **Manual-Compact** | 模型调用 compact 工具 | 整个对话历史 | 调用模型总结（可指定 focus） |

### 大输出持久化

- **触发条件**：工具输出 > 30000 字符
- **存储位置**：`.task_outputs/tool-results/{tool_use_id}.txt`
- **返回格式**：预览（2000 字符）+ 文件路径
- **目的**：避免大输出占用上下文空间

### 对话记录保存

- **触发时机**：每次 Auto-Compact 或 Manual-Compact 前
- **存储位置**：`.transcripts/transcript_{时间戳}.jsonl`
- **格式**：JSONL（每行一个 JSON 对象）
- **目的**：压缩前保留完整历史，便于追溯

### 压缩状态追踪

- **CompactState 字段**：
  - `has_compacted`：是否已压缩
  - `last_summary`：最后一次总结内容
  - `recent_files`：最近访问的 5 个文件路径
- **作用**：在压缩后保留核心元数据，帮助模型恢复上下文

---

## 整体设计思想总结

1. **分级压缩策略**：根据内容类型和上下文大小，采用不同粒度的压缩机制。Micro-Compact 处理工具结果，Auto/Manual-Compact 处理整体历史。

2. **持久化替代上下文存储**：大输出和完整对话历史写入磁盘，上下文仅保留必要信息，突破模型上下文长度限制。

3. **压缩前保存完整记录**：每次压缩前保存 JSONL 格式的完整对话，确保信息可追溯，避免压缩导致信息永久丢失。

4. **模型自主压缩权**：通过 `compact` 工具赋予模型主动压缩的权力，模型可根据对话情况自主决定压缩时机。

5. **压缩状态追踪**：`CompactState` 记录压缩历史和最近文件，压缩后模型仍可获取重要上下文信息。

---

## 与 s05 的关系

### 对比表格

| 特性 | s05 | s06 |
|------|-----|-----|
| **上下文管理** | 无限增长 | 三层压缩机制 |
| **工具输出处理** | 直接返回 | 大输出持久化（预备） |
| **对话记录** | 无 | JSONL 文件保存 |
| **压缩触发** | 无 | 自动 + 手动 |
| **状态追踪** | LoopState | LoopState + CompactState |
| **配置参数** | 基础配置 | + 压缩/持久化阈值 |
| **工具集** | 6+1 个工具 | 6+2 个工具（+compact） |

### 继承关系

s06 完整保留了 s05 的所有功能：
- 主子代理协作架构
- `task` 工具委托子任务
- `todo` 任务管理
- `load_skill` 技能加载
- 工具分割（PARENT_TOOLS / CHILD_TOOLS）

在此基础上增加：
- 三层压缩机制
- 大输出持久化
- 对话记录保存
- 压缩状态追踪

---

## 实践指南

### 测试示例（长对话压缩）

```bash
cd v1_task_manager/chapter_6
python s06_context.py
```

**测试场景**：
1. 启动 agent，执行多个产生大输出的工具调用（如 `bash` 执行长输出命令）
2. 观察 Micro-Compact：旧工具结果被压缩
3. 继续对话直到上下文超过 50000 字符
4. 观察 Auto-Compact：触发模型总结，消息列表缩短

### compact 工具使用示例

**模型调用示例**：
```json
{
  "name": "compact",
  "arguments": {
    "focus": "The current debugging session for main.py, including the syntax error on line 42"
  }
}
```

**效果**：
- 压缩历史对话
- 总结中保留指定重点：`"Focus to preserve next: The current debugging session for main.py..."`
- 附加最近访问的文件列表

### 查看压缩记录

**对话记录**：
```bash
ls -la .transcripts/
cat .transcripts/transcript_*.jsonl
```

**工具结果**：
```bash
ls -la .task_outputs/tool-results/
cat .task_outputs/tool-results/call_*.txt
```

---

## 总结

### 核心设计思想

s06 通过 **三层压缩机制 + 持久化存储** 解决了长对话上下文超限问题：
- **Micro-Compact**：压缩旧工具结果，保留最近 3 条
- **Auto-Compact**：上下文超限自动总结
- **Manual-Compact**：模型主动触发压缩
- **持久化**：大输出和完整对话写入磁盘

### 版本说明

- **代码路径**：`v1_task_manager/chapter_6/s06_context.py`
- **继承版本**：s05（Subagent 系统）
- **核心新增**：`CompactState`、三层压缩、持久化
- **配置文件**：无独立配置文件，参数硬编码在文件开头
