# s06: Context Compact - Code Documentation

---

## Overview

### Core Improvements

**From Infinite Context to Three-Layer Compression Mechanism**

s06 introduces a **context compression system** built on s05, solving the problem of context overflow caused by long conversations. Through a three-layer compression mechanism (Micro-Compact, Auto-Compact, Manual-Compact) and large output persistence, the framework can handle long-duration conversations.

### Design Philosophy

> **"Graded Compression + Persistent Storage"**

The core design philosophy of s06: adopt compression strategies of different granularities based on content type and context size, while writing large outputs to disk to avoid context expansion.

**Three-Layer Compression Mechanism**:
- **Micro-Compact**: Compress old tool results, keeping only the most recent few items in full detail
- **Auto-Compact**: When context exceeds limit, call the model to summarize the entire conversation history
- **Manual-Compact**: Model proactively calls the `compact` tool to trigger compression

**Persistence Strategy**:
- **Large Output Persistence**: Tool outputs exceeding the threshold are written to `.task_outputs/tool-results/` directory
- **Conversation Record Saving**: Complete conversations are saved as JSONL files before compression

### Code File Path

```
v1_task_manager/chapter_06/s06_context.py
```

### Core Architecture Diagram (Comparison with s05)

**s05 Architecture (No Compression Mechanism)**:
```
    +----------+      +-----------+      +------------------+
    |   User   | ---> |  LLM      | ---> | Tools            |
    |  prompt  |      |           |      | {task, todo,     |
    +----------|      |           |      |  read_file,      |
                                         |  compact?}       |
                                         +------------------+
        ^                                        |
        |                                        |
        +----------------------------------------+
                  Context grows continuously, no compression
```

**s06 Architecture (Three-Layer Compression + Persistence)**:
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
                              |          | Output Size Check|
                              |          +--------+--------+
                              |                   |
                      +-------+--------+  +-------+--------+
                      | ≤ PERSIST_     |  | > PERSIST_     |
                      |   THRESHOLD    |  |   THRESHOLD    |
                      +-------+--------+  +-------+--------+
                              |                   |
                              |                   v
                              |          +--------+--------+
                              |          | Write to Disk   |
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
            | After each tool|                  | When context   |
            | call, compress |                  | exceeds limit, |
            | old tool results|                 | summarize history|
            +-------+--------+                  +--------+-------+
                    |                                    |
                    +------------------+-----------------+
                                       |
                              +--------v--------+
                              | Compact Context |
                              | Continue Dialog |
                              +-----------------+
```

**Architecture Explanation**:
1. Execute Micro-Compact after each tool call to compress old tool results
2. Check context size before each conversation turn, trigger Auto-Compact if exceeded
3. Model can proactively call `compact` tool to trigger Manual-Compact
4. Large outputs (>30000 characters) are written to disk, returning preview + path

---

## Directory Structure Dependencies

The code in this chapter will create or use the following directories and files:

| Directory/File | Purpose | Creation Method |
|----------------|---------|-----------------|
| `.transcripts/` | Save conversation records (JSONL format) | Automatically created during auto-compaction |
| `.task_outputs/tool-results/` | Persist large output files | Automatically created when tool output exceeds threshold |
| `.claude/.claude_trusted` | Workspace trust marker file | Manually created by user |

**Conversation Record File Format** (`.transcripts/transcript_{timestamp}.jsonl`):
- One JSON object per line
- Contains fields like role, content, etc.
- Used to trace back conversation history after compression

**Large Output Persistence** (`.task_outputs/tool-results/{tool_call_id}.txt`):
- Triggered when tool output exceeds 30000 characters
- Saves complete output to file
- Returns preview (first 2000 characters) + file path to model

---

## Comparison with s05

### Change Overview

| Component | s05 | s06 | Change Description |
|-----------|-----|-----|-------------------|
| **New Config Parameters** | None | `CONTEXT_LIMIT`, `PERSIST_THRESHOLD`, `PREVIEW_CHARS`, `KEEP_RECENT_TOOL_RESULTS` | Compression and persistence threshold configuration |
| **New Directory Config** | None | `TRANSCRIPT_DIR`, `TOOL_RESULTS_DIR` | Conversation record and tool result storage paths |
| **New Data Class** | None | `CompactState` | Track compression state (has_compacted, last_summary, recent_files) |
| **New Functions** | None | `estimate_context_size`, `persist_large_output`, `micro_compact`, `compact_history`, `summarize_history`, `write_transcript`, `collect_tool_result_blocks`, `track_recent_file` | Core functions for compression and persistence |
| **New Tool** | None | `compact` | Model can manually trigger compression |
| **agent_loop Changes** | Direct dialog execution | Execute Micro-Compact first, then check Auto-Compact | Three-layer compression trigger mechanism |
| **execute_tool_calls Changes** | Return results only | Additionally return `manual_compact`, `compact_focus` | Support manual compression markers |

### New Component Architecture

```
s06 New Components:

Data Classes:
└── CompactState
    ├── has_compacted: bool          # Whether compression has been executed
    ├── last_summary: str            # Last summary content
    └── recent_files: list[str]      # Recently accessed file paths

Configuration Parameters:
├── CONTEXT_LIMIT = 50000            # Context size limit (characters)
├── PERSIST_THRESHOLD = 30000        # Persistence threshold (characters)
├── PREVIEW_CHARS = 2000             # Preview character count
├── KEEP_RECENT_TOOL_RESULTS = 3     # Number of recent tool results to keep
├── TRANSCRIPT_DIR                   # Conversation record directory
└── TOOL_RESULTS_DIR                 # Tool result storage directory

Core Functions:
├── estimate_context_size(messages)  # Estimate context size
├── persist_large_output(tool_use_id, output)  # Large output persistence
├── collect_tool_result_blocks(messages)       # Collect tool result indices
├── micro_compact(messages)          # Micro compression
├── compact_history(messages, state, focus)    # History compression
├── summarize_history(messages)      # Call model to summarize
└── write_transcript(messages)       # Save conversation record

Tools:
└── compact (JSON Schema)
    └── focus (optional): str        # Key points to preserve during compression
```

---

## Detailed Explanation by Execution Order

### Phase 1: New Configuration Parameters

#### Mechanism Overview

s06 defines configuration parameters related to compression and persistence at the beginning of the file. These parameters control the trigger conditions and behavior of the three-layer compression mechanism.

```python
# --- Configuration Parameters ---
CONTEXT_LIMIT = 50000
PERSIST_THRESHOLD = 30000
PREVIEW_CHARS = 2000
PLAN_REMINDER_INTERVAL = 3
KEEP_RECENT_TOOL_RESULTS = 3

# --- Directory Configuration ---
WORKDIR = Path.cwd()
SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"
```

**Parameter Design Philosophy**:
- `CONTEXT_LIMIT` (50000): Upper limit for context size, triggers Auto-Compact when exceeded
- `PERSIST_THRESHOLD` (30000): Tool output persistence threshold, writes to disk when exceeded
- `PREVIEW_CHARS` (2000): Number of preview characters returned during persistence
- `KEEP_RECENT_TOOL_RESULTS` (3): Number of recent tool results kept by Micro-Compact
- `TRANSCRIPT_DIR`: Directory for saving complete conversation records before compression (`.transcripts/`)
- `TOOL_RESULTS_DIR`: Storage directory for large tool outputs (`.task_outputs/tool-results/`)

---

### Phase 2: CompactState Data Class

#### Mechanism Overview

`CompactState` is used to track compression state, maintaining context information across multiple compressions. Unlike `LoopState` which tracks conversation history, `CompactState` focuses on compression-related metadata.

```python
@dataclass
class CompactState:
    has_compacted: bool = False
    last_summary: str = ""
    recent_files: list[str] = field(default_factory=list)
```

**Field Description**:
- `has_compacted`: Marks whether compression has been executed, used to determine if current context is in a compressed state
- `last_summary`: Saves the summary content generated by the last compression, can be referenced in subsequent compressions
- `recent_files`: Records the most recently accessed 5 file paths, model can reopen these files after compression

**Design Philosophy**: Why Track Compression State

Compression loses some historical information. The role of `CompactState` is:
1. **State Marker**: `has_compacted` lets the system know the current context is compressed
2. **Information Retention**: `last_summary` saves the compressed summary, avoiding complete loss of history
3. **File Tracking**: `recent_files` records recently operated files, allowing model to quickly recover context after compression

---

### Phase 3: Micro-Compact Mechanism

#### Mechanism Overview

Micro-Compact is the finest-grained compression mechanism, executed after each tool call. It compresses old tool results, keeping only the most recent `KEEP_RECENT_TOOL_RESULTS` (3 items) in full detail, replacing the rest with brief placeholders.

**Execution Flow**:
```
Tool Call Complete → collect_tool_result_blocks() → micro_compact() → Update Message List
```

#### collect_tool_result_blocks() Function

```python
def collect_tool_result_blocks(messages: list) -> list[int]:
    tool_message_indices = []
    for index, message in enumerate(messages):
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        if role == "tool":
            tool_message_indices.append(index)
    return tool_message_indices
```

**Function**: Iterate through message list, collect indices of all messages with `role="tool"`, return index list for use by `micro_compact()`.

#### micro_compact() Function

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

**Compression Logic**:
1. Collect indices of all tool results
2. If tool result count ≤ 3, return directly (no compression needed)
3. Iterate through all tool results except the most recent 3
4. If content length > 120 characters, replace with placeholder text
5. Handle both dict and object message formats, compatible with different SDK versions

**KEEP_RECENT_TOOL_RESULTS Retention Strategy**:
- Keep the most recent 3 tool results in full detail
- When exceeding 3 items, old results are compressed to: `"[Earlier tool result compacted. Re-run the tool if you need full detail.]"`
- If model needs full detail of old results, it can re-execute the corresponding tool

---

### Phase 4: Large Output Persistence

#### Mechanism Overview

When tool output exceeds `PERSIST_THRESHOLD` (30000 characters), `persist_large_output()` writes the output to a disk file to avoid large outputs occupying context space. The return format is preview + file path.

#### persist_large_output() Function

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

**Threshold Judgment Logic**:
1. Check if output length ≤ 30000 characters
2. If not exceeded threshold, return original output directly
3. If exceeded threshold, execute persistence flow

**Persistence Flow**:
1. Create directory `.task_outputs/tool-results/` (if not exists)
2. Save complete output with filename `tool_use_id.txt`
3. Extract first 2000 characters as preview
4. Calculate relative path (relative to working directory)
5. Return structured format: `<persisted-output>...<persisted-output>`

**Return Format Example**:
```
<persisted-output>
Full output saved to: .task_outputs/tool-results/call_abc123.txt
Preview:
[First 2000 characters of output content...]
</persisted-output>
```

**Note**: s06 code defines the `persist_large_output()` function, but it is not integrated into the actual tool call chain. This function exists as a preparatory feature in s06 stage and is implemented in s10.

---

### Phase 5: Auto-Compact Mechanism

#### Mechanism Overview

Auto-Compact is automatically triggered when context size exceeds `CONTEXT_LIMIT` (50000 characters). It calls the model to summarize the entire conversation history, generating a compact summary to replace the original messages.

**Execution Flow**:
```
Check Context Size → estimate_context_size() → Exceeded? → compact_history()
                                              ↓
                                    write_transcript() Save Record
                                              ↓
                                    summarize_history() Call Model to Summarize
                                              ↓
                                    Generate New Compact Message List
```

#### estimate_context_size() Function

```python
def estimate_context_size(messages: list) -> int:
    return len(str(messages))
```

**Function**: Convert message list to string, return character count as estimated context size. This is a simplified estimation method; actual token count may differ.

#### write_transcript() Function

```python
def write_transcript(messages: list) -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with path.open("w") as handle:
        for message in messages:
            handle.write(json.dumps(message, default=str) + "\n")
    return path
```

**Function**: Save complete conversation record to JSONL file before compression.

**Save Format**:
- Directory: `.transcripts/`
- Filename: `transcript_{timestamp}.jsonl`
- Format: One JSON object per line (JSONL format)
- Purpose: After compression, if complete history needs to be recovered, it can be read from file

#### summarize_history() Function

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

**Function**: Call model to summarize conversation history.

**Prompt Design**:
- Requirements to preserve: current goal, important findings and decisions, files read/modified, remaining work, user constraints and preferences
- Output limit: `max_tokens=2000`,要求 concise and concrete
- Input limit: Truncate first 80000 characters (to prevent summary request itself from being too large)

#### compact_history() Function

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

**Compression Flow**:
1. Save complete conversation to `.transcripts/` directory
2. Call `summarize_history()` to generate summary
3. If `focus` parameter exists, append to summary (prompt key points to preserve for next compression)
4. If recent file list exists, append to summary
5. Update `CompactState`: `has_compacted=True`, `last_summary=summary`
6. Keep system message (if exists)
7. Create new user message containing summary content
8. Return compact message list (only system + 1 summary message)

**Effect After Compression**:
- Original: N messages (possibly dozens)
- After compression: 1-2 messages (system + summary)

---

### Phase 6: Manual-Compact Mechanism

#### Mechanism Overview

Manual-Compact allows the model to proactively call the `compact` tool to trigger compression. Unlike Auto-Compact, Manual-Compact is autonomously decided by the model based on conversation conditions.

#### compact Tool JSON Schema

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

**Parameter Description**:
- `focus` (optional): String, model autonomously specifies content key points to specially preserve during compression
- Example: `{"focus": "The current debugging session for file X"}`

#### execute_tool_calls Changes

```python
def execute_tool_calls(response_content) -> tuple[list[dict], str | None, bool, str | None]:
    used_todo = False
    manual_compact = False
    compact_focus = None
    results = []
    for tool_call in response_content.tool_calls:
        f_name = tool_call.function.name
        # ... Execute tool ...
        if f_name in TOOL_HANDLERS:
            output = TOOL_HANDLERS[f_name](**args)
            # Additional step for compression
            if f_name == "compact":
                manual_compact = True
                compact_focus = args.get("focus")
        # ... Return results ...
    return results, reminder, manual_compact, compact_focus
```

**Change Description**:
- Return value extended from `(results, reminder)` to `(results, reminder, manual_compact, compact_focus)`
- When `compact` tool call is detected, set `manual_compact=True`
- Extract `focus` parameter to pass to `compact_history()`

#### compact_focus Parameter

`compact_focus` allows the model to specify key points to preserve when calling the `compact` tool:

```python
if manual_compact:
    print("[manual compact]")
    state.messages = compact_history(state.messages, compact_state, focus=compact_focus)
```

In `compact_history()`, `focus` is appended to the summary:
```python
if focus:
    summary += f"\n\nFocus to preserve next: {focus}"
```

---

### Phase 7: agent_loop Changes

#### Mechanism Overview

`agent_loop()` is the core loop function of the main agent. s06 adds three-layer compression trigger logic on the basis of s05.

#### Trigger Timing for Three-Layer Compression

```python
def agent_loop(state: LoopState, compact_state: CompactState) -> None:
    while True:
        # 1. Execute Micro-Compact
        state.messages = micro_compact(state.messages)

        # 2. Check if global compression is triggered (Auto-Compact)
        if estimate_context_size(state.messages) > CONTEXT_LIMIT:
            print("[auto compact]")
            state.messages = compact_history(state.messages, compact_state)
        
        # 3. Run one turn of conversation
        has_next_step = run_one_turn(state, compact_state)
        
        # If model doesn't call tools (task ends or needs user input), exit automatic loop
        if not has_next_step:
            break
```

**Trigger Order**:
1. **Micro-Compact**: Executed at the beginning of each loop, compresses old tool results
2. **Auto-Compact**: Check context size, trigger if exceeded
3. **Dialog Execution**: Call `run_one_turn()` to execute one turn of conversation
4. **Manual-Compact**: Inside `run_one_turn()`, if model calls `compact` tool, trigger compression

#### History Update After Compression

```python
def run_one_turn(state: LoopState, compact_state: CompactState) -> bool:
    # ... Call model ...
    if response_message.tool_calls:
        results, reminder, manual_compact, compact_focus = execute_tool_calls(response_message)
        for tool_result in results:
            state.messages.append(tool_result)
        
        if manual_compact:
            print("[manual compact]")
            state.messages = compact_history(state.messages, compact_state, focus=compact_focus)
        # ...
```

**Update Logic**:
- Micro-Compact and Auto-Compact directly update `state.messages` in `agent_loop()`
- Manual-Compact updates `state.messages` in `run_one_turn()` after tool calls complete
- After compression, old history messages are replaced with summary messages, `state.messages` length significantly decreases

---

## Complete Framework Flowchart

```
+----------+
|   User   |
|  prompt  |
+-----+----+
      |
      v
+-----+------------+
| agent_loop Entry |
+-----+------------+
      |
      v
+-----+------------+
| 1. Micro-Compact |  Compress old tool results
| micro_compact()  |  Keep most recent 3
+-----+------------+
      |
      v
+-----+------------+
| 2. Check Context |  estimate_context_size()
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
| - Save transcript|        +-------+--------+
| - Call model to  |        | Model Response |
|   summarize      |        +-------+--------+
| - Update message |                |
|   list           |                |
+-----+------------+                |
      |                             |
      +-----------------------------+
                                    |
                                    v
                          +---------+----------+
                          | Has tool_calls?    |
                          +---------+----------+
                                    |
                    +---------------+---------------+
                    |                               |
                   Yes                               No
                    |                               |
                    v                               v
          +---------+----------+           +-------+--------+
          | execute_tool_calls |           | Task Ends     |
          +---------+----------+           | Exit Loop     |
                    |                      +----------------+
                    |
          +---------+----------+
          | Manual-Compact?    |
          +---------+----------+
                    |
        +-----------+-----------+
        |                       |
       Yes                      No
        |                       |
        v                       v
+-------+--------+      +-------+--------+
| compact_history|      | Append tool_result|
| Pass focus param|     | Continue next round|
+----------------+      +----------------+
```

---

## Design Point Summary

### Three-Layer Compression Mechanism

| Compression Type | Trigger Condition | Compression Object | Compression Granularity |
|------------------|-------------------|--------------------|------------------------|
| **Micro-Compact** | After each tool call | Tool result messages | Compress old results beyond 3 items |
| **Auto-Compact** | Context > 50000 characters | Entire conversation history | Call model to summarize |
| **Manual-Compact** | Model calls compact tool | Entire conversation history | Call model to summarize (can specify focus) |

### Large Output Persistence

- **Trigger Condition**: Tool output > 30000 characters
- **Storage Location**: `.task_outputs/tool-results/{tool_use_id}.txt`
- **Return Format**: Preview (2000 characters) + file path
- **Purpose**: Avoid large outputs occupying context space

### Conversation Record Saving

- **Trigger Timing**: Before each Auto-Compact or Manual-Compact
- **Storage Location**: `.transcripts/transcript_{timestamp}.jsonl`
- **Format**: JSONL (one JSON object per line)
- **Purpose**: Preserve complete history before compression for traceability

### Compression State Tracking

- **CompactState Fields**:
  - `has_compacted`: Whether compression has been executed
  - `last_summary`: Last summary content
  - `recent_files`: 5 most recently accessed file paths
- **Purpose**: Retain core metadata after compression, helping model recover context

---

## Overall Design Philosophy Summary

1. **Graded Compression Strategy**: Adopt compression mechanisms of different granularities based on content type and context size. Micro-Compact handles tool results, Auto/Manual-Compact handle overall history.

2. **Persistence Replaces Context Storage**: Large outputs and complete conversation history are written to disk, context only retains necessary information, breaking through model context length limits.

3. **Save Complete Records Before Compression**: Before each compression, save complete conversation in JSONL format, ensuring information is traceable and avoiding permanent information loss due to compression.

4. **Model Autonomous Compression Authority**: Through the `compact` tool, grant the model the power to proactively compress; the model can autonomously decide compression timing based on conversation conditions.

5. **Compression State Tracking**: `CompactState` records compression history and recent files; after compression, the model can still obtain important context information.

---

## Relationship with s05

### Comparison Table

| Feature | s05 | s06 |
|---------|-----|-----|
| **Context Management** | Infinite growth | Three-layer compression mechanism |
| **Tool Output Processing** | Direct return | Large output persistence (preparatory) |
| **Conversation Records** | None | JSONL file saving |
| **Compression Trigger** | None | Automatic + Manual |
| **State Tracking** | LoopState | LoopState + CompactState |
| **Configuration Parameters** | Basic configuration | + Compression/persistence thresholds |
| **Tool Set** | 6+1 tools | 6+2 tools (+compact) |

### Inheritance Relationship

s06 completely retains all functionality of s05:
- Main-sub agent collaboration architecture
- `task` tool delegates subtasks
- `todo` task management
- `load_skill` skill loading
- Tool splitting (PARENT_TOOLS / CHILD_TOOLS)

On this basis, adds:
- Three-layer compression mechanism
- Large output persistence
- Conversation record saving
- Compression state tracking

---

## Practice Guide

### Test Example (Long Conversation Compression)

```bash
cd v1_task_manager/chapter_6
python s06_context.py
```

**Test Scenario**:
1. Start agent, execute multiple tool calls that produce large outputs (e.g., `bash` executing commands with long output)
2. Observe Micro-Compact: old tool results are compressed
3. Continue conversation until context exceeds 50000 characters
4. Observe Auto-Compact: triggers model summary, message list shortens

### compact Tool Usage Example

**Model Call Example**:
```json
{
  "name": "compact",
  "arguments": {
    "focus": "The current debugging session for main.py, including the syntax error on line 42"
  }
}
```

**Effect**:
- Compress conversation history
- Summary preserves specified key points: `"Focus to preserve next: The current debugging session for main.py..."`
- Append list of recently accessed files

### View Compression Records

**Conversation Records**:
```bash
ls -la .transcripts/
cat .transcripts/transcript_*.jsonl
```

**Tool Results**:
```bash
ls -la .task_outputs/tool-results/
cat .task_outputs/tool-results/call_*.txt
```

---

## Summary

### Core Design Philosophy

s06 solves the long conversation context overflow problem through **three-layer compression mechanism + persistent storage**:
- **Micro-Compact**: Compress old tool results, keep most recent 3
- **Auto-Compact**: Automatically summarize when context exceeds limit
- **Manual-Compact**: Model proactively triggers compression
- **Persistence**: Large outputs and complete conversations written to disk

### Version Information

- **Code Path**: `v1_task_manager/chapter_06/s06_context.py`
- **Inherited Version**: s05 (Subagent System)
- **Core Additions**: `CompactState`, three-layer compression, persistence
- **Configuration File**: No independent configuration file, parameters hardcoded at beginning of file
