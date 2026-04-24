# s02: Tool Use - Code Documentation v2

---

## Overview

### Core Improvements

**From single-tool to multi-tool dispatch architecture**

s02 extends s01: expands from a single `bash` tool to **4 tools** (bash, read_file, write_file, edit_file), and introduces a **tool dispatch mechanism** (dispatch map) to route different tool calls.

### Design Philosophy

> **"The loop didn't change at all. I just added tools."**

s02's design philosophy: **The Agent loop itself doesn't need modification**; simply extend the tools array and add a tool dispatch mapping to achieve multi-tool support.

This is also the design philosophy of the entire project and the harness engineering: the core agents loop itself doesn't need modification; just keep expanding tools and functionality.

### Code File Path

```
v1_task_manager/chapter_02/s02_tool_use.py
```

### Core Architecture Diagram

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

**Architecture Explanation**:
1. User inputs prompt and sends to LLM
2. LLM selects which tool to call based on the available tools list
3. Tool Dispatch routes to the corresponding handler function based on tool name
4. Tool execution results return to LLM
5. Loop continues until LLM no longer requests tool calls

---

## Comparison with s01

### Change Overview

| Component | s01 | s02 | Change Description |
|------|-----|-----|----------|
| **Tools** | 1 (bash) | 4 (bash, read_file, write_file, edit_file) | Added 3 file operation tools |
| **Dispatch** | Hardcoded if | TOOL_HANDLERS dictionary | Changed from conditional to dictionary lookup |
| **Path Safety** | None | safe_path() sandbox | Added path validation mechanism |
| **Agent loop** | Unchanged | Unchanged | Core loop logic consistent |
| **Import modules** | Standard library | + pathlib.Path | Added path handling module |
| **SYSTEM prompt** | "Use bash" | "Use the tool" | Generalized tool description |

### Architecture Comparison

**s01 Architecture (single-tool hardcoded)**:
```
    +-------+      +------------------+
    |  LLM  | ---> | if name=="bash": |
    +-------+      |   run_bash()     |
                   +------------------+
```

**s02 Architecture (multi-tool dispatch)**:
```
    +-------+      +------------------+
    |  LLM  | ---> | TOOL_HANDLERS    |
    +-------+      |   [name](**args) |
                   +------------------+
```

**Design Advantages**:
- Extensibility: Adding a new tool only requires adding one entry in TOOL_HANDLERS
- Maintainability: Eliminates lengthy if/elif chains
- Type safety: Parameters constrained by JSON Schema

---

## Detailed Explanation by Execution Order

### Phase 1: New Import Module

#### Introduction of pathlib.Path

**Mechanism Overview**:
s02 adds import of `pathlib.Path` module to replace traditional `os.path` for path handling. `pathlib` is Python 3.4+'s object-oriented path handling module, providing a more intuitive path operation API.

```python
from pathlib import Path
WORKDIR = Path.cwd()
```

**Design Philosophy**:
- `WORKDIR` serves as the base directory for the path sandbox; all file operations are restricted to this directory
- Uses `Path.cwd()` to get the Path object of the current working directory
- Path objects support the `/` operator for path concatenation, e.g., `WORKDIR / "subdir" / "file.txt"`

**Comparison with os.path**:
- pathlib uses object-oriented style: `path.resolve()` vs `os.path.resolve(path)`
- More intuitive path concatenation: `path / "subdir"` vs `os.path.join(path, "subdir")`
- Built-in safety check methods: `is_relative_to()` can be directly used for path sandbox validation

---

### Phase 2: Path Safety Sandbox

#### safe_path() Function Details

**Mechanism Overview**:
The `safe_path()` function provides path safety validation for all file operations. It receives a relative path string and returns a validated absolute Path object. If path escape attempts are detected (such as using `../` to access files outside the working directory), it raises a `ValueError` exception.

```python
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path
```

**Path Sandbox Design Philosophy**:
The path sandbox is an important defense line for Agent safety. Even if the model is attacked by malicious prompts, it cannot read sensitive files outside the project. The sandbox is implemented through three layers of defense:

1. **Forced work directory concatenation**: `(WORKDIR / p)` ensures all paths are based on the work directory
2. **Resolve symlinks and relative paths**: `.resolve()` resolves all `..` and symlinks to get the real absolute path
3. **Validate path scope**: `is_relative_to(WORKDIR)` checks if the resolved path is still within the work directory

**Why Restrict Workspace**:
- Prevent directory traversal attacks (using `../` to access parent directories)
- Prevent symlink escape (attackers create symlinks pointing to external files)
- Prevent absolute path bypass (directly passing system paths like `/etc/passwd`)
- Protect sensitive files (system config files, keys, credentials, etc.)

**Path Attack Scenario Examples**:
```
Attack Scenario 1: Directory Traversal
  Input: p = "../../etc/passwd"
  WORKDIR = "/home/user/AGENT_demo"
  
  (WORKDIR / p).resolve() 
  = "/home/user/AGENT_demo/../../etc/passwd".resolve()
  = "/home/user/etc/passwd"
  
  is_relative_to(WORKDIR) → False  ❌ Blocked

Attack Scenario 2: Symlink Escape
  Attacker creates symlink: ln -s /etc/passwd ./link
  
  Input: p = "link"
  .resolve() follows the symlink to get "/etc/passwd"
  
  is_relative_to(WORKDIR) → False  ❌ Blocked
```

---

### Phase 3: New Tool Implementation

#### run_read() Function

**Mechanism Overview**:
`run_read()` is used to read file content, supporting an optional `limit` parameter to restrict the number of lines read. The function first validates path safety through `safe_path()`, then reads the file and splits by lines. If `limit` is specified and file lines exceed the limit, content is truncated and a remaining lines hint is added. Final output is limited to 50000 characters to prevent consuming too many tokens.

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

**Mechanism**:
- The `limit` parameter allows the model to read only the first N lines of large files, suitable for exploratory reading
- Truncation hint `"... (X more lines)"` informs the model that the file has more content
- 50000 character limit prevents a single tool call from consuming too much context
- Exception capture ensures file read failures return error messages instead of crashing

---

#### run_write() Function

**Mechanism Overview**:
`run_write()` is used to create or overwrite files. The function receives the target path and complete content, first validates path safety, then automatically creates all non-existent parent directories, and finally writes the content. This design avoids write failures due to non-existent directories.

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

**Mechanism**:
- `fp.parent.mkdir(parents=True, exist_ok=True)` recursively creates all non-existent parent directories
- `parents=True` allows creating multi-level directories (such as `deep/nested/dir/`)
- `exist_ok=True` ensures no error when directory already exists
- `write_text()` overwrites existing files, which is the expected behavior

---

#### run_edit() Function

**Mechanism Overview**:
`run_edit()` is used to precisely replace text in files. The function reads file content, checks if the original text exists, and if it exists, performs the replacement (only replacing the first occurrence), then writes back to the file. This design is safer and more controllable than using bash's sed command.

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

**Text Replacement Logic**:
- The third parameter `1` in `content.replace(old_text, new_text, 1)` means only replace the first occurrence
- Design reasons for replacing only once:
  - Safer: Avoids accidentally modifying multiple identical contents
  - More precise: The model can call edit multiple times to modify multiple places
  - Predictable: Behavior is deterministic, won't produce unexpected side effects
- If the original text doesn't exist, returns an error message instead of failing silently

---

### Phase 4: Tool Dispatch Mechanism

#### TOOL_HANDLERS Dispatch Dictionary

**Mechanism Overview**:
`TOOL_HANDLERS` is the core design of s02; it's a dictionary that maps tool names to corresponding handler functions. Dictionary lookup replaces hardcoded if/elif chains, achieving an extensible tool architecture. Adding a new tool only requires adding an entry in the dictionary without modifying execution logic.

```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}
```

**Design Philosophy: Extensible Tool Architecture**:
- Each tool maps to a lambda function; the lambda is responsible for extracting correct parameters from keyword arguments
- Reason for using lambda wrappers: Tool function parameter names may not match parameter names passed by LLM, requiring explicit mapping
- Unified call interface: All tools are called via `TOOL_HANDLERS[name](**args)`
- Optional parameter support: Uses `kw.get("limit")` to handle optional parameters

**Call Example**:
```python
# Model outputs tool_call:
# {"name": "read_file", "arguments": {"path": "test.py", "limit": 50}}

# Execution logic:
f_name = "read_file"
args = {"path": "test.py", "limit": 50}
output = TOOL_HANDLERS[f_name](**args)
# Equivalent to: output = run_read(path="test.py", limit=50)
```

---

### Phase 5: execute_tool_calls Optimization

#### Dictionary Lookup Replaces if/elif

**Mechanism Overview**:
s02 refactors the `execute_tool_calls()` function, using `TOOL_HANDLERS` dictionary lookup to replace the hardcoded if/elif chain in s01. This design makes code more concise; adding new tools doesn't require modifying the execution function.

**s01 Implementation (hardcoded)**:
```python
def execute_tool_calls(response_content) -> list[dict]:
    results = []
    for tool_call in response_content.tool_calls:
        if tool_call.function.name == "bash":  # hardcoded
            args = json.loads(tool_call.function.arguments)
            command = args.get("command")
            output = run_bash(command)
            results.append({...})
    return results
```

**s02 Implementation (dictionary dispatch)**:
```python
def execute_tool_calls(response_content) -> list[dict]:
    results = []
    for tool_call in response_content.tool_calls:
        f_name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as e:
            # Error handling...
            continue
        
        if f_name in TOOL_HANDLERS:
            output = TOOL_HANDLERS[f_name](**args)  # dictionary lookup
        else:
            output = f"Error: Tool {f_name} not found."
        
        results.append({...})
    return results
```

**Design Advantages**:
- Fixed number of code lines, doesn't grow with tool count
- Adding a new tool only requires adding an entry in `TOOL_HANDLERS`
- Unified handling of tool-not-found cases
- Unified error handling logic

---

#### JSON Parse Error Handling

**Mechanism Overview**:
`execute_tool_calls()` adds JSON parse error handling. If the tool parameters generated by the model are not in valid JSON format, the function catches the exception, returns an error message to the model, and continues processing other tool calls. This design forms a feedback loop, giving the model a chance to correct errors.

```python
try:
    args = json.loads(tool_call.function.arguments)
except json.JSONDecodeError as e:
    print(f"\033[31m[JSON Parse Error in {f_name}]\033[0m")
    output = f"Error: Failed to parse tool arguments. Invalid JSON format. {e}"
    results.append({"role": "tool", "tool_call_id": tool_call.id, "name": f_name, "content": output})
    continue
```

**Error Handling Flow**:
1. Attempt to parse JSON parameters output by the model
2. If parsing fails, catch `JSONDecodeError`
3. Print red error log (for debugging)
4. Build error message and return to model
5. Skip this tool execution, continue processing other tool_calls

**Why Error Handling is Needed**:
- Model may output malformed parameters
- Special character escaping issues may cause JSON parse failures
- Returning errors to the model forms a feedback loop, improving success rate

---

### Phase 6: SYSTEM Prompt Changes

**Mechanism Overview**:
The SYSTEM prompt changes from s01's "Use bash" to s02's "Use the tool", reflecting the multi-tool architecture change. The prompt is generalized, avoiding listing all tool names; specific tool capabilities are conveyed to the model by the TOOLS list's JSON Schema.

**s01**:
```python
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to inspect and change the workspace. Act first, then report clearly."
```

**s02**:
```python
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use the tool to finish tasks. Act first, then report clearly."
```

**Change Description**:
- `Use bash` → `Use the tool`: From single tool to generic tool
- Specific tool capabilities are conveyed to the model by the TOOLS list definition
- SYSTEM prompt only needs to give overall guidance, keeping it concise

---

## Complete Framework Flowchart

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           s02 Complete Execution Flow                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐                                                               │
│  │   User   │                                                               │
│  └────┬─────┘                                                               │
│       │ "Edit the hello function in test.py"                                │
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
│  │  │  │ calls()         │   │ (end loop)      │               │   │       │ │
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
│  │  │  │  │  TOOL_HANDLERS dispatch:                        │ │ │   │       │ │
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
│  │  │  │  │  safe_path() path validation                   │ │ │   │       │ │
│  │  │  │  │  (file operation tools only)                    │ │ │   │       │ │
│  │  │  │  └────────────────────────────────────────────────┘ │ │   │       │ │
│  │  │  │           │                                         │ │   │       │ │
│  │  │  │           ▼                                         │ │   │       │ │
│  │  │  │  ┌────────────────────────────────────────────────┐ │ │   │       │ │
│  │  │  │  │  Execute specific tool functions                │ │ │   │       │ │
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
│  │  │  └─────────────────────────────────────────────────────┘   │       │ │
│  │  │           │                                              │   │       │ │
│  │  │           ▼                                              │   │       │ │
│  │  │  ┌──────────────────────────────────────────────────┐   │   │       │ │
│  │  │  │  state.messages.append(tool_result)              │   │   │       │ │
│  │  │  │  state.turn_count += 1                           │   │   │       │ │
│  │  │  │  return True  (continue loop)                     │   │   │       │ │
│  │  │  └──────────────────────────────────────────────────┘   │   │       │ │
│  │  │                                                         │   │       │ │
│  │  └─────────────────────────────────────────────────────────┘   │       │ │
│  │       │                                                        │       │ │
│  └───────┴────────────────────────────────────────────────────────┘       │ │
│                                                                           │ │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Loop ends, return final response                                      │ │
│  │  final_text = extract_text(history[-1]["content"])                    │ │
│  │  print(final_text)                                                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Design Point Summary

### Loop Invariance Principle

**Core Design Philosophy**:
```
s01: Agent Loop + 1 tool (bash)
s02: Agent Loop + 4 tools (bash, read, write, edit)
     ↓
     Same loop code!
```

**Implementation**:
- TOOLS list extension: Add JSON Schema for new tools
- TOOL_HANDLERS dictionary: Add handler functions for new tools
- execute_tool_calls(): Use dictionary lookup, no modification needed

### Path Sandbox Mechanism

**Defense Layers**:
```
User inputs path
    │
    ▼
(WORKDIR / p)     ← Layer 1: Forced work directory concatenation
    │
    ▼
.resolve()        ← Layer 2: Resolve symlinks and ..
    │
    ▼
is_relative_to()  ← Layer 3: Validate if within work directory
    │
    ▼
Pass → Return Path
Fail → Throw ValueError
```

### Tool Dispatch Dictionary

**Data Structure**:
```python
TOOL_HANDLERS = {
    "tool_name": lambda **kw: handler_function(kw["param1"], kw.get("param2")),
    ...
}
```

**Call Pattern**:
```python
output = TOOL_HANDLERS[f_name](**args)
```

**Advantages**:
- O(1) lookup complexity
- Concise code, easy to maintain
- Naturally supports tool-not-found checks


## Practice Guide

### Running Method

```bash
# 1. Ensure model service is running (http://your-server-ip:port/v1)

# 2. Run script
cd v1_task_manager/chapter_02/
python3 s02_tool_use.py
```

**Expected Startup Output**:
```
✅ Connection successful, model: qwen3.5-xxx
s01 >>
```

### Test Examples

#### Read File

```
s01 >> Read the first 30 lines of s02_tool_use.py
```

**Expected Behavior**:
1. LLM calls `read_file` tool with parameters `{"path": "s02_tool_use.py", "limit": 30}`
2. `run_read()` executes path validation, reads file, truncates content
3. Returns first 30 lines with remaining lines hint

**Expected Output**:
```
#!/usr/bin/env python3
"""
s02_tool_use.py - Tools
...
(total 30 lines)
... (XXX more lines)
```

---

#### Create File

```
s01 >> Create a file named hello.py with content printing "Hello, Agent!"
```

**Expected Behavior**:
1. LLM calls `write_file` tool with parameters `{"path": "hello.py", "content": "print(\"Hello, Agent!\")"}`
2. `run_write()` executes path validation, creates parent directory, writes content
3. Returns confirmation message

**Expected Output**:
```
Wrote 28 bytes to hello.py
```

---

#### Edit File

```
s01 >> Change "Hello, Agent!" in hello.py to "Hello, World!"
```

**Expected Behavior**:
1. LLM calls `edit_file` tool
2. `run_edit()` executes path validation, reads content, checks original text, replaces, writes back
3. Returns confirmation message

**Expected Output**:
```
Edited hello.py
```

---

#### Multi-Tool Combination Task

```
s01 >> Create a config file config.json, then read it to confirm content
```

**Expected Behavior**:
1. Round 1: LLM calls `write_file` to create config.json
2. Round 2: LLM calls `read_file` to read and confirm
3. Returns final summary

**Message History Evolution**:
```
[system] "You are a coding agent..."
[user] "Create a config file config.json, then read it to confirm content"
[assistant] (tool_call: write_file)
[tool] "Wrote 50 bytes to config.json"
[assistant] (tool_call: read_file)
[tool] "{...config content...}"
[assistant] "Config file created and confirmed..."
```

---

#### Path Escape Test (Blocked)

```
s01 >> Read ../../etc/passwd
```

**Expected Behavior**:
1. LLM calls `read_file` tool
2. `safe_path()` validation fails
3. Throws `ValueError`
4. Exception caught, returns error message

**Expected Output**:
```
Error: Path escapes workspace
```

The path sandbox successfully blocked the directory traversal attack.

---

### Exit Methods

| Method | Operation |
|------|------|
| Command exit | Input `q` or `exit` |
| Empty input exit | Press Enter directly (empty string) |
| Force exit | `Ctrl + C` |

---

## Overall Design Summary

### 1. Loop Invariant, Tools Extensible

The Agent loop is stable core logic and should not be modified as tool count changes. Through the configurable design of TOOLS list and TOOL_HANDLERS dictionary, adding new tools only requires modifying configuration, not the core loop. This embodies the Open/Closed Principle: "open for extension, closed for modification."

### 2. Safety First

The path sandbox is the default protection mechanism for all file operation tools. Through three layers of defense—forced work directory concatenation, symlink resolution, and path scope validation—it ensures tools cannot access sensitive files outside the project. Safety design should be a default option, not a configurable item.

### 3. Tool Complementarity

The 4 tools each have clear responsibility boundaries:
- `bash`: Execute system commands, supporting shell features like pipes, redirection
- `read_file`: Safely read files, supporting limit parameter
- `write_file`: Safely create files, automatically creating parent directories
- `edit_file`: Precise text replacement, only modifying specified content

Tools complement each other functionally, avoiding overlap, with each tool focusing on solving specific scenarios.

### 4. Feedback Loop

Error messages are returned to the model, forming a feedback loop. JSON parse errors, path validation failures, text-not-found cases are all returned to the model through tool results, giving the model a chance to correct errors. This design improves task success rate.

### 5. Simplicity First

The core loop remains concise; complex logic is encapsulated in tool functions. execute_tool_calls() uses a unified dictionary lookup pattern, not becoming complex as tool count grows. Simple code is easier to maintain and understand.

---

**Based on code**: `v1_task_manager/chapter_02/s02_tool_use.py`  
**Learning objective**: Understand multi-tool dispatch architecture and path safety sandbox design  
**Prerequisite knowledge**: s01 Agent Loop mechanism
