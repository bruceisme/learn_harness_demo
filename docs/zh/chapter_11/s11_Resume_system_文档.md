# s11: Resume System (错误恢复机制增强)

## 概述

s11 在 s10 结构化系统提示词的基础上进行了**错误恢复机制增强**。核心改进是从无错误处理的单次调用升级为三层错误恢复策略，使 Agent 能够在遇到 max_tokens 限制、上下文过长、API 错误等场景时自动恢复并继续执行。

### 核心改进

1. **三层错误恢复策略** - 核心改动，针对 max_tokens、prompt_too_long、API 错误三类场景
2. **错误检测机制** - 通过 `finish_reason` 判断 LLM 响应状态
3. **LoopState 状态扩展** - 新增 `max_output_recovery_count` 字段追踪恢复次数
4. **用户交互界面改进** - ANSI 转义码包裹、Todo 状态显示、会话重置命令
5. **s10 功能完整保留** - SystemPromptBuilder、MemoryManager、HookManager 等核心组件无变化

### 代码文件路径

- **源代码**：v1_task_manager/chapter_11/s11_Resume_system.py
- **参考文档**：v1_task_manager/chapter_10/s10_build_system_文档.md
- **参考代码**：v1_task_manager/chapter_10/s10_build_system.py
- **记忆目录**：`.memory/`（工作区根目录下的隐藏目录）
- **技能目录**：`skills/`（工作区根目录下）
- **钩子配置**：`.hooks.json`（工作区根目录下的钩子拦截管线配置文件）
- **Claude 信任标记**：`.claude/.claude_trusted`（工作区根目录下的隐藏目录，用于标识受信任的工作区）

---

## 与 s10 的对比

### 变更总览

| 组件 | s10 | s11 |
|------|-----|-----|
| 错误恢复机制 | 无 | 三层错误恢复策略 |
| LLM 调用方式 | 直接调用 | `run_one_turn()` 包装 + 错误处理 |
| finish_reason 检查 | 无 | 检查 `finish_reason == "length"` |
| max_tokens 恢复 | 无 | 注入 `CONTINUATION_MESSAGE`，重试最多 3 次 |
| prompt_too_long 处理 | 无 | 触发 `auto_compact()` 压缩后重试 |
| API 错误退避 | 无 | 指数退避 + 随机抖动，最多 3 次重试 |
| LoopState 字段 | messages, turn_count, transition_reason | 新增 max_output_recovery_count |
| 用户输入提示符 | 简单 input | ANSI 转义码包裹 + Todo 状态显示 |
| 会话重置命令 | 无 | 新增会话重置命令 |
| run_subagent 错误处理 | 无 | try-except 包裹 API 调用 |
| SystemPromptBuilder | 6 层结构化构建 | 完整保留（无变化） |
| MemoryManager | 完整实现 | 完整保留（无变化） |
| HookManager | 完整实现 | 完整保留（无变化） |
| PermissionManager | 交互式 mode 选择 | 完整保留（无变化） |

---

## s11 新增内容详解（按代码执行顺序）

### 第 1 阶段：错误恢复配置常量

```python
MAX_RECOVERY_ATTEMPTS = 3
BACKOFF_BASE_DELAY = 1.0  # seconds
BACKOFF_MAX_DELAY = 30.0  # seconds
CONTINUATION_MESSAGE = (
    "Output limit hit. Continue directly from where you stopped -- "
    "no recap, no repetition. Pick up mid-sentence if needed."
)
```

| 常量 | 值 | 用途 |
|------|-----|------|
| MAX_RECOVERY_ATTEMPTS | 3 | 所有恢复策略的最大重试次数 |
| BACKOFF_BASE_DELAY | 1.0 | 指数退避的基础延迟（秒） |
| BACKOFF_MAX_DELAY | 30.0 | 退避延迟上限（秒） |
| CONTINUATION_MESSAGE | 字符串 | max_tokens 恢复时注入的提示消息 |

### 退避延迟计算

```python
def backoff_delay(attempt: int) -> float:
    delay = min(BACKOFF_BASE_DELAY * (2 ** attempt), BACKOFF_MAX_DELAY)
    jitter = random.uniform(0, 1)
    return delay + jitter
```

| attempt | 基础延迟 | 随机抖动 | 总延迟范围 |
|---------|----------|----------|------------|
| 0 | 1.0s | 0-1s | 1.0-2.0s |
| 1 | 2.0s | 0-1s | 2.0-3.0s |
| 2 | 4.0s | 0-1s | 4.0-5.0s |

---

### 第 2 阶段：auto_compact() 函数 - Strategy 2 核心

```python
def auto_compact(messages: list) -> list:
    conversation_text = json.dumps(messages, default=str)[:80000]
    prompt = (
        "Summarize this conversation so work can continue.\n"
        "Preserve: current goal, findings, files, remaining work, preferences.\n"
        + conversation_text
    )
    try:
        response = client.chat.completions.create(
            model=MODEL, 
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )
        summary = response.choices[0].message.content.strip()
    except Exception as e:
        summary = f"(compact failed: {e})"
    return [{"role": "user", "content": f"Session continued from compacted context:\n{summary}"}]
```

**处理流程**：
1. 将消息历史转为 JSON 字符串（截取前 80000 字符）
2. 调用 LLM 生成摘要（2000 tokens）
3. 返回单条 user 消息（系统提示在调用方保留）

---

### 第 3 阶段：LoopState 扩展

**s10**：
```python
@dataclass
class LoopState:
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None
```

**s11**：
```python
@dataclass
class LoopState:
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None
    max_output_recovery_count: int = 0  # 新增字段
```

---

### 第 4 阶段：run_one_turn() 三层策略

**Layer 1**: LLM 调用错误捕获
- context_length_exceeded → Strategy 2: auto_compact() + continue
- 其他错误 → Strategy 3: backoff_delay() + sleep() + continue

**Layer 2**: finish_reason 检查
- finish_reason == "length" → Strategy 1: 注入 continuation + retry
- 其他 → 重置计数器

**Layer 3**: 工具执行
- tool_calls → execute_tool_calls() + return True
- 无工具调用 → return False

---

### 第 5 阶段：Strategy 1 - max_tokens 恢复

**触发条件**：`finish_reason == "length"`

**恢复流程**：
```python
if finish_reason == "length":
    state.max_output_recovery_count += 1
    if state.max_output_recovery_count <= MAX_RECOVERY_ATTEMPTS:
        state.messages.append({"role": "user", "content": CONTINUATION_MESSAGE})
        return True
    else:
        return False
```

**注入消息**：
```
Output limit hit. Continue directly from where you stopped --
no recap, no repetition. Pick up mid-sentence if needed.
```

---

### 第 6 阶段：Strategy 2 - prompt_too_long 压缩

**触发条件**：`"context_length_exceeded" in str(e).lower()`

**恢复流程**：
```python
compacted_msgs = auto_compact(state.messages)
sys_msg = state.messages[0]  # 保留系统提示
state.messages[:] = [sys_msg] + compacted_msgs
continue  # retry
```

---

### 第 7 阶段：Strategy 3 - API 错误退避

**触发条件**：API 异常且非 context_length_exceeded

**退避延迟**：
| attempt | 延迟范围 |
|---------|----------|
| 0 | 1.0-2.0s |
| 1 | 2.0-3.0s |
| 2 | 4.0-5.0s |

---

### 第 8 阶段：用户交互界面改进

**提示符增强**：

原始代码包含 ANSI 转义码，用于在终端中实现彩色显示和行控制。由于这些转义码在文档中显示为乱码，以下使用带注释的清晰版本说明其功能：

```python
# 状态标签：黄色显示 Todo 状态信息
# \x01\033[33m\x02 = 开始非打印序列 + 黄色前景色 (33m) + 结束非打印序列
# \x01\033[0m\x02 = 开始非打印序列 + 重置颜色 (0m) + 结束非打印序列
status_tag = f"[Todo {completed}/{len(todo_items)} | {active_name[:30]}...]"  # 黄色显示

# 提示符：清除行 + 青色显示
# \x01\033[2K\r\x02 = 清除整行 (2K) + 回车 (\r) + 非打印包裹
# \x01\033[36m\x02 = 青色前景色 (36m)
# \x01\033[0m\x02 = 重置颜色 (0m)
prompt_str = "s11 >> "  # 青色显示
```

**ANSI 转义码详解**：

| 转义序列 | 含义 | 效果 |
|----------|------|------|
| `\x01\033[33m\x02` | 开始非打印 + 黄色前景色 | 文字显示为黄色 |
| `\x01\033[36m\x02` | 开始非打印 + 青色前景色 | 文字显示为青色 |
| `\x01\033[0m\x02` | 开始非打印 + 重置颜色 | 恢复默认颜色 |
| `\x01\033[2K\r\x02` | 清除整行 + 回车 | 清除当前行内容并回到行首 |

**技术说明**：
- `\x01` 和 `\x02`：SOH (Start of Header) 和 STX (Start of Text) 字符，用于包裹非打印序列，防止 readline 库错误计算光标位置
- `\033`：ESC 字符，ANSI 转义序列的起始符
- `[33m`：设置前景色为黄色
- `[36m`：设置前景色为青色
- `[0m`：重置所有属性和颜色
- `[2K`：清除当前整行内容
- `\r`：回车符，将光标移至行首

---

### 第 9 阶段：会话重置命令

功能：清空对话历史、Todo 列表、压缩状态，保留系统提示。

---

### 第 10 阶段：保留功能

| 组件 | 状态 |
|------|------|
| SystemPromptBuilder | 完整保留 |
| MemoryManager | 完整保留 |
| DreamConsolidator | 完整保留（待激活） |
| HookManager | 完整保留 |
| PermissionManager | 完整保留 |

---

## 目录结构依赖

| 目录/文件 | 用途 | 创建方式 |
|-----------|------|----------|
| skills/ | 技能文档 | 手动创建 |
| .memory/ | 持久化记忆 | MemoryManager 自动创建 |
| .memory/MEMORY.md | 记忆索引 | _rebuild_index() 重建 |
| .transcripts/ | 会话转录 | write_transcript() 创建 |
| .task_outputs/tool-results/ | 大型工具输出 | persist_large_output() 创建 |
| .hooks.json | 钩子配置 | 手动创建 |

---

## 完整框架流程图

```
会话启动
    │
    ▼
agent_loop(state, compact_state)
│   - 更新系统提示
│   - micro_compact()
│   - run_one_turn()
    │
    ▼
Layer 1: LLM 调用 (for attempt in range(4))
│   try: response = client.chat.completions.create()
│   except:
│       context_length_exceeded? -> Strategy 2 + continue
│       attempt < 3? -> Strategy 3 + continue
│       else -> return False
    │
    ▼
Layer 2: finish_reason 检查
│   finish_reason == "length"?
│       -> max_output_recovery_count += 1
│       -> count <= 3? -> Strategy 1 + return True
│       -> else -> return False
    │
    ▼
Layer 3: 工具执行
    tool_calls? -> execute_tool_calls() + return True
    else -> return False


Strategy 1: max_tokens 恢复
+-------------------------------------------------------------+
| finish_reason == "length"                                   |
|         |                                                   |
|         v                                                   |
| max_output_recovery_count += 1                             |
|         |                                                   |
|         v                                                   |
| count <= 3?                                                 |
|    +----+----+                                              |
|    |         |                                              |
|   是        否                                              |
|    |         |                                              |
|    v         v                                              |
| 注入      return False                                      |
| CONTINUATION  (停止)                                        |
| MESSAGE                                                     |
|    |                                                        |
|    v                                                        |
| return True (重试)                                          |
+-------------------------------------------------------------+

Strategy 2: prompt_too_long 压缩
+-------------------------------------------------------------+
| "context_length_exceeded" in error                          |
|         |                                                   |
|         v                                                   |
| auto_compact(state.messages)                                |
|         |                                                   |
|         v                                                   |
| 保留 sys_msg + 替换历史                                      |
|         |                                                   |
|         v                                                   |
| continue (重试)                                             |
+-------------------------------------------------------------+

Strategy 3: API 错误退避
+-------------------------------------------------------------+
| API Exception (非 context_length_exceeded)                  |
|         |                                                   |
|         v                                                   |
| attempt < 3?                                                |
|    +----+----+                                              |
|    |         |                                              |
|   是        否                                              |
|    |         |                                              |
|    v         v                                              |
| backoff_   return False                                     |
| delay()    (停止)                                           |
| sleep()                                                     |
|    |                                                        |
|    v                                                        |
| continue (重试)                                             |
+-------------------------------------------------------------+
```

---

## 设计点总结

### 核心设计机制 1：三层错误恢复

| 层级 | 目标错误 | 恢复方式 |
|------|----------|----------|
| Layer 1 | LLM 调用异常 | try-except 捕获 |
| Layer 2 | finish_reason="length" | 注入 continuation |
| Layer 3 | 工具执行 | execute_tool_calls() |

### 核心设计机制 2：错误类型分类

| 错误类型 | 判断方式 | 恢复策略 |
|----------|----------|----------|
| max_tokens | finish_reason == "length" | Strategy 1 |
| prompt_too_long | "context_length_exceeded" | Strategy 2 |
| API 错误 | 其他异常 | Strategy 3 |

### 核心设计机制 3：独立计数器

- attempt：LLM 调用重试次数（所有错误）
- max_output_recovery_count：仅 max_tokens 错误

### 核心设计机制 4：系统提示保留

压缩时保留 state.messages[0]（系统提示）。

### 核心设计机制 5：ANSI 转义码包裹

使用 `\\x01` (SOH) 和 `\\x02` (STX) 字符包裹 ANSI 转义码，防止 readline 库错误计算光标位置。

---

## 整体设计思想总结

1. **分层错误处理**：三层策略针对不同错误类型。

2. **错误类型驱动**：根据错误原因选择恢复方式。

3. **有限重试原则**：所有策略限制 3 次重试。

4. **状态追踪与重置**：独立计数器，成功后重置。

5. **核心上下文保护**：压缩时保留系统提示。

6. **渐进式恢复**：轻量策略优先。

---

## 实践指南

### 运行方法

```bash
cd v1_task_manager/chapter_11
python s11_Resume_system.py
```

### 测试示例

#### 1. 查看错误恢复日志

运行中观察：
- `[Recovery] max_tokens hit (1/3). Injecting continuation...`
- `[Recovery] Prompt too long. Compacting... (attempt 1)`
- `[Recovery] API error: ... Retrying in 1.5s (attempt 1/3)`

#### 2. 验证 Todo 状态显示

```
[Todo 1/3 | 正在读取文件...] s11 >>
```

---

## 总结

### 核心设计思想

s11 通过三层错误恢复策略，使 Agent 能够从 max_tokens、上下文过长、API 错误等场景中自动恢复。设计原则是**分层处理**和**有限重试**。

### 核心机制

1. 三层错误恢复
2. 错误类型分类
3. 独立计数器
4. 系统提示保留
5. ANSI 包裹

### 版本说明

- **文件路径**：v1_task_manager/chapter_11/s11_Resume_system.py
- **核心改动**：三层错误恢复策略
- **继承内容**：s10 核心组件完整保留

---
*文档版本：v1.0*
*基于代码：v1_task_manager/chapter_11/s11_Resume_system.py*
