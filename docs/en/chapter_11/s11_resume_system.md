# s11: Resume System (Error Recovery Mechanism Enhancement)

## Overview

s11 builds upon s10's structured system prompts with **error recovery mechanism enhancements**. The core improvement upgrades from a single-call approach without error handling to a three-layer error recovery strategy, enabling the Agent to automatically recover and continue execution when encountering scenarios such as max_tokens limits, context too long, or API errors.

### Core Improvements

1. **Three-Layer Error Recovery Strategy** - Core change, targeting three scenarios: max_tokens, prompt_too_long, and API errors
2. **Error Detection Mechanism** - Uses `finish_reason` to determine LLM response status
3. **LoopState Extension** - New `max_output_recovery_count` field to track recovery attempts
4. **User Interface Improvements** - ANSI escape code wrapping, Todo status display, session reset command
5. **s10 Features Fully Retained** - SystemPromptBuilder, MemoryManager, HookManager, and other core components unchanged

### Code File Paths

- **Source Code**: v1_task_manager/chapter_11/s11_Resume_system.py
- **Reference Document**: v1_task_manager/chapter_10/s10_build_system_文档.md
- **Reference Code**: v1_task_manager/chapter_10/s10_build_system.py
- **Memory Directory**: `.memory/` (hidden directory at workspace root)
- **Skills Directory**: `skills/` (at workspace root)
- **Hook Configuration**: `.hooks.json` (hook interception pipeline configuration file at workspace root)
- **Claude Trust Marker**: `.claude/.claude_trusted` (hidden directory at workspace root, used to identify trusted workspaces)

---

## Comparison with s10

### Change Overview

| Component | s10 | s11 |
|------|-----|-----|
| Error Recovery Mechanism | None | Three-layer error recovery strategy |
| LLM Call Method | Direct call | `run_one_turn()` wrapper + error handling |
| finish_reason Check | None | Check `finish_reason == "length"` |
| max_tokens Recovery | None | Inject `CONTINUATION_MESSAGE`, retry up to 3 times |
| prompt_too_long Handling | None | Trigger `auto_compact()` to compress then retry |
| API Error Backoff | None | Exponential backoff + random jitter, up to 3 retries |
| LoopState Fields | messages, turn_count, transition_reason | Added max_output_recovery_count |
| User Input Prompt | Simple input | ANSI escape code wrapping + Todo status display |
| Session Reset Command | None | Added session reset command |
| run_subagent Error Handling | None | try-except wrapping API calls |
| SystemPromptBuilder | 6-layer structured build | Fully retained (unchanged) |
| MemoryManager | Full implementation | Fully retained (unchanged) |
| HookManager | Full implementation | Fully retained (unchanged) |
| PermissionManager | Interactive mode selection | Fully retained (unchanged) |

---

## s11 New Content Detailed Explanation (by Code Execution Order)

### Phase 1: Error Recovery Configuration Constants

```python
MAX_RECOVERY_ATTEMPTS = 3
BACKOFF_BASE_DELAY = 1.0  # seconds
BACKOFF_MAX_DELAY = 30.0  # seconds
CONTINUATION_MESSAGE = (
    "Output limit hit. Continue directly from where you stopped -- "
    "no recap, no repetition. Pick up mid-sentence if needed."
)
```

| Constant | Value | Purpose |
|------|-----|------|
| MAX_RECOVERY_ATTEMPTS | 3 | Maximum retry count for all recovery strategies |
| BACKOFF_BASE_DELAY | 1.0 | Base delay for exponential backoff (seconds) |
| BACKOFF_MAX_DELAY | 30.0 | Upper limit for backoff delay (seconds) |
| CONTINUATION_MESSAGE | String | Prompt message injected during max_tokens recovery |

### Backoff Delay Calculation

```python
def backoff_delay(attempt: int) -> float:
    delay = min(BACKOFF_BASE_DELAY * (2 ** attempt), BACKOFF_MAX_DELAY)
    jitter = random.uniform(0, 1)
    return delay + jitter
```

| attempt | Base Delay | Random Jitter | Total Delay Range |
|---------|----------|----------|------------|
| 0 | 1.0s | 0-1s | 1.0-2.0s |
| 1 | 2.0s | 0-1s | 2.0-3.0s |
| 2 | 4.0s | 0-1s | 4.0-5.0s |

---

### Phase 2: auto_compact() Function - Strategy 2 Core

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

**Processing Flow**:
1. Convert message history to JSON string (truncate to first 80000 characters)
2. Call LLM to generate summary (2000 tokens)
3. Return single user message (system prompt retained by caller)

---

### Phase 3: LoopState Extension

**s10**:
```python
@dataclass
class LoopState:
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None
```

**s11**:
```python
@dataclass
class LoopState:
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None
    max_output_recovery_count: int = 0  # New field
```

---

### Phase 4: run_one_turn() Three-Layer Strategy

**Layer 1**: LLM Call Error Capture
- context_length_exceeded → Strategy 2: auto_compact() + continue
- Other errors → Strategy 3: backoff_delay() + sleep() + continue

**Layer 2**: finish_reason Check
- finish_reason == "length" → Strategy 1: Inject continuation + retry
- Others → Reset counter

**Layer 3**: Tool Execution
- tool_calls → execute_tool_calls() + return True
- No tool calls → return False

---

### Phase 5: Strategy 1 - max_tokens Recovery

**Trigger Condition**: `finish_reason == "length"`

**Recovery Flow**:
```python
if finish_reason == "length":
    state.max_output_recovery_count += 1
    if state.max_output_recovery_count <= MAX_RECOVERY_ATTEMPTS:
        state.messages.append({"role": "user", "content": CONTINUATION_MESSAGE})
        return True
    else:
        return False
```

**Injected Message**:
```
Output limit hit. Continue directly from where you stopped --
no recap, no repetition. Pick up mid-sentence if needed.
```

---

### Phase 6: Strategy 2 - prompt_too_long Compression

**Trigger Condition**: `"context_length_exceeded" in str(e).lower()`

**Recovery Flow**:
```python
compacted_msgs = auto_compact(state.messages)
sys_msg = state.messages[0]  # Retain system prompt
state.messages[:] = [sys_msg] + compacted_msgs
continue  # retry
```

---

### Phase 7: Strategy 3 - API Error Backoff

**Trigger Condition**: API exception and not context_length_exceeded

**Backoff Delay**:
| attempt | Delay Range |
|---------|----------|
| 0 | 1.0-2.0s |
| 1 | 2.0-3.0s |
| 2 | 4.0-5.0s |

---

### Phase 8: User Interface Improvements

**Enhanced Prompt**:

The original code contains ANSI escape codes for colored display and line control in the terminal. Since these escape codes display as garbled text in documents, the following uses an annotated clear version to explain their functionality:

```python
# Status tag: Yellow display for Todo status information
# \x01\033[33m\x02 = Start non-printing sequence + Yellow foreground color (33m) + End non-printing sequence
# \x01\033[0m\x02 = Start non-printing sequence + Reset color (0m) + End non-printing sequence
status_tag = f"[Todo {completed}/{len(todo_items)} | {active_name[:30]}...]"  # Yellow display

# Prompt: Clear line + Cyan display
# \x01\033[2K\r\x02 = Clear entire line (2K) + Carriage return (\r) + Non-printing wrapper
# \x01\033[36m\x02 = Cyan foreground color (36m)
# \x01\033[0m\x02 = Reset color (0m)
prompt_str = "s11 >> "  # Cyan display
```

**ANSI Escape Code Details**:

| Escape Sequence | Meaning | Effect |
|----------|------|------|
| `\x01\033[33m\x02` | Start non-printing + Yellow foreground | Text displays in yellow |
| `\x01\033[36m\x02` | Start non-printing + Cyan foreground | Text displays in cyan |
| `\x01\033[0m\x02` | Start non-printing + Reset color | Restore default color |
| `\x01\033[2K\r\x02` | Clear entire line + Carriage return | Clear current line content and return to line start |

**Technical Notes**:
- `\x01` and `\x02`: SOH (Start of Header) and STX (Start of Text) characters, used to wrap non-printing sequences to prevent readline library from incorrectly calculating cursor position
- `\033`: ESC character, start symbol for ANSI escape sequences
- `[33m`: Set foreground color to yellow
- `[36m`: Set foreground color to cyan
- `[0m`: Reset all attributes and colors
- `[2K`: Clear current entire line content
- `\r`: Carriage return, moves cursor to line start

---

### Phase 9: Session Reset Command

Function: Clear conversation history, Todo list, and compact status, while retaining the system prompt.

---

### Phase 10: Retained Features

| Component | Status |
|------|------|
| SystemPromptBuilder | Fully retained |
| MemoryManager | Fully retained |
| DreamConsolidator | Fully retained (pending activation) |
| HookManager | Fully retained |
| PermissionManager | Fully retained |

---

## Directory Structure Dependencies

| Directory/File | Purpose | Creation Method |
|-----------|------|----------|
| skills/ | Skill documents | Manually created |
| .memory/ | Persistent memory | Automatically created by MemoryManager |
| .memory/MEMORY.md | Memory index | Rebuilt by _rebuild_index() |
| .transcripts/ | Session transcripts | Created by write_transcript() |
| .task_outputs/tool-results/ | Large tool outputs | Created by persist_large_output() |
| .hooks.json | Hook configuration | Manually created |

---

## Complete Framework Flowchart

```
Session Start
    │
    ▼
agent_loop(state, compact_state)
│   - Update system prompt
│   - micro_compact()
│   - run_one_turn()
    │
    ▼
Layer 1: LLM Call (for attempt in range(4))
│   try: response = client.chat.completions.create()
│   except:
│       context_length_exceeded? -> Strategy 2 + continue
│       attempt < 3? -> Strategy 3 + continue
│       else -> return False
    │
    ▼
Layer 2: finish_reason Check
│   finish_reason == "length"?
│       -> max_output_recovery_count += 1
│       -> count <= 3? -> Strategy 1 + return True
│       -> else -> return False
    │
    ▼
Layer 3: Tool Execution
    tool_calls? -> execute_tool_calls() + return True
    else -> return False


Strategy 1: max_tokens Recovery
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
|   Yes       No                                              |
|    |         |                                              |
|    v         v                                              |
| Inject    return False                                      |
| CONTINUATION  (Stop)                                        |
| MESSAGE                                                     |
|    |                                                        |
|    v                                                        |
| return True (Retry)                                         |
+-------------------------------------------------------------+

Strategy 2: prompt_too_long Compression
+-------------------------------------------------------------+
| "context_length_exceeded" in error                          |
|         |                                                   |
|         v                                                   |
| auto_compact(state.messages)                                |
|         |                                                   |
|         v                                                   |
| Retain sys_msg + Replace history                            |
|         |                                                   |
|         v                                                   |
| continue (Retry)                                            |
+-------------------------------------------------------------+

Strategy 3: API Error Backoff
+-------------------------------------------------------------+
| API Exception (not context_length_exceeded)                 |
|         |                                                   |
|         v                                                   |
| attempt < 3?                                                |
|    +----+----+                                              |
|    |         |                                              |
|   Yes       No                                              |
|    |         |                                              |
|    v         v                                              |
| backoff_   return False                                     |
| delay()    (Stop)                                           |
| sleep()                                                     |
|    |                                                        |
|    v                                                        |
| continue (Retry)                                            |
+-------------------------------------------------------------+
```

---

## Design Points Summary

### Core Design Mechanism 1: Three-Layer Error Recovery

| Layer | Target Error | Recovery Method |
|------|----------|----------|
| Layer 1 | LLM call exception | try-except capture |
| Layer 2 | finish_reason="length" | Inject continuation |
| Layer 3 | Tool execution | execute_tool_calls() |

### Core Design Mechanism 2: Error Type Classification

| Error Type | Detection Method | Recovery Strategy |
|----------|----------|----------|
| max_tokens | finish_reason == "length" | Strategy 1 |
| prompt_too_long | "context_length_exceeded" | Strategy 2 |
| API Error | Other exceptions | Strategy 3 |

### Core Design Mechanism 3: Independent Counter

- attempt: LLM call retry count (all errors)
- max_output_recovery_count: max_tokens errors only

### Core Design Mechanism 4: System Prompt Retention

Retain state.messages[0] (system prompt) during compression.

### Core Design Mechanism 5: ANSI Escape Code Wrapping

Use `\\x01` (SOH) and `\\x02` (STX) characters to wrap ANSI escape codes, preventing readline library from incorrectly calculating cursor position.

---

## Overall Design Philosophy Summary

1. **Layered Error Handling**: Three-layer strategy targeting different error types.

2. **Error Type Driven**: Select recovery method based on error cause.

3. **Limited Retry Principle**: All strategies limited to 3 retries.

4. **State Tracking and Reset**: Independent counters, reset after success.

5. **Core Context Protection**: Retain system prompt during compression.

6. **Progressive Recovery**: Lightweight strategies prioritized.

---

## Practice Guide

### Running Method

```bash
cd v1_task_manager/chapter_11
python s11_Resume_system.py
```

### Test Examples

#### 1. View Error Recovery Logs

Observe during execution:
- `[Recovery] max_tokens hit (1/3). Injecting continuation...`
- `[Recovery] Prompt too long. Compacting... (attempt 1)`
- `[Recovery] API error: ... Retrying in 1.5s (attempt 1/3)`

#### 2. Verify Todo Status Display

```
[Todo 1/3 | 正在读取文件...] s11 >>
```

---

## Summary

### Core Design Philosophy

s11 enables the Agent to automatically recover from scenarios such as max_tokens, context too long, and API errors through a three-layer error recovery strategy. The design principles are **layered processing** and **limited retry**.

### Core Mechanisms

1. Three-layer error recovery
2. Error type classification
3. Independent counters
4. System prompt retention
5. ANSI wrapping

### Version Notes

- **File Path**: v1_task_manager/chapter_11/s11_Resume_system.py
- **Core Change**: Three-layer error recovery strategy
- **Inherited Content**: s10 core components fully retained

---
*Document Version: v1.0*
*Based on Code: v1_task_manager/chapter_11/s11_Resume_system.py*
