# s01: The Agent Loop - Code Documentation v2

---

## Overview

### Core Concepts

**One Tool + One Loop = One Agent**

This is the most fundamental paradigm for building AI Agents. This section demonstrates the core working mechanism of an Agent through a minimal implementation:

- **Tool**: The capability interface for Agent to interact with the real world (uses `bash` tool in this section)
- **Loop**: An iterative process that continuously receives model output, determines whether tool invocation is needed, executes and feeds back results

### Harness Layer Positioning

This Agent Loop belongs to the **Harness Layer**—it is the first connection between the model and the real world. In production environments, more complex mechanisms such as policy control, hook functions, and lifecycle management will be built on top of this foundation.

### Code File Path

```
v1_task_manager/chapter_01/s01_agent_loop.py
```

### Core Architecture Diagram

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

**Loop Explanation**:
1. User input prompt is sent to LLM
2. LLM determines whether to call a tool and outputs tool_call
3. Agent Loop parses tool_call and executes the corresponding tool
4. Tool execution result (tool_result) is fed back to LLM
5. Loop continues until LLM no longer requests tool calls

---

## Execution Flow Preview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Code Execution Order Overview                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Phase 1: Module Import and Basic Configuration (executed immediately   │
│           when Python interpreter starts)                               │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  import statements                                              │   │
│  │       ↓                                                          │   │
│  │  OpenAI client configuration (api_key, base_url, client)        │   │
│  │       ↓                                                          │   │
│  │  MODEL = client.models.list().data[0].id (dynamically get model)│   │
│  │       ↓                                                          │   │
│  │  SYSTEM prompt definition                                        │   │
│  │       ↓                                                          │   │
│  │  TOOLS tool definition (JSON Schema)                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                            ↓                                            │
│  Phase 2: Data Structure Definition (class definition, not executed    │
│           yet)                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  @dataclass                                                      │   │
│  │  class LoopState:                                                │   │
│  │      messages: list                                              │   │
│  │      turn_count: int = 1                                         │   │
│  │      transition_reason: str | None = None                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                            ↓                                            │
│  Phase 3: Tool Execution Layer (function definition, not executed yet) │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  def run_bash(command: str) -> str                              │   │
│  │      ├── Dangerous command filtering                            │   │
│  │      ├── subprocess.run() execution                             │   │
│  │      └── Output truncation (50000 chars) + timeout (120s)       │   │
│  │                                                                   │   │
│  │  def extract_text(content) -> str                               │   │
│  │      └── Compatible content extraction for str and list formats │   │
│  │                                                                   │   │
│  │  def execute_tool_calls(response_content) -> list[dict]         │   │
│  │      ├── Iterate through tool_calls                             │   │
│  │      ├── Parse arguments (json.loads)                           │   │
│  │      ├── Call run_bash()                                        │   │
│  │      └── Build tool result messages                             │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                            ↓                                            │
│  Phase 4: Core Loop Logic (function definition, not executed yet)      │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  def run_one_turn(state: LoopState) -> bool                     │   │
│  │      ├── client.chat.completions.create() calls LLM             │   │
│  │      ├── Append assistant message to history                    │   │
│  │      ├── Check if there are tool_calls                          │   │
│  │      │   ├── Yes: execute_tool_calls() → append results → True  │   │
│  │      │   └── No: return False                                   │   │
│  │      └── Update turn_count and transition_reason                │   │
│  │                                                                   │   │
│  │  def agent_loop(state: LoopState) -> None                       │   │
│  │      └── while run_one_turn(state): pass (core loop)            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                            ↓                                            │
│  Phase 5: Program Entry and Interaction (executed when user runs       │
│           script)                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  if __name__ == "__main__":                                     │   │
│  │      ├── history = [system message]                             │   │
│  │      ├── while True: (interaction loop)                         │   │
│  │      │   ├── input() gets user query                            │   │
│  │      │   ├── history.append(user message)                       │   │
│  │      │   ├── state = LoopState(messages=history)                │   │
│  │      │   ├── agent_loop(state) (start Agent loop)               │   │
│  │      │   └── print(extract_text(history[-1]["content"]))        │   │
│  │      └── Supports multi-turn dialogue (history accumulates)     │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Call Relationship Diagram**:

```
__main__
    │
    ├── Initialize history = [SYSTEM]
    │
    └── while True (user interaction loop)
            │
            ├── input() gets user query
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
                            │                       ├── dangerous command filtering
                            │                       ├── subprocess.run()
                            │                       ├── timeout=120
                            │                       └── out[:50000]
                            │
                            └── state.messages.append(tool_result)
```

---

## Phase 1: Module Import and Basic Configuration

> **Phase Description**: This phase executes immediately when the Python script starts, responsible for importing necessary modules, configuring API clients, defining system prompts and tool specifications. These configurations form the basic environment for the entire Agent operation.

### 1.1 Import Modules

```python
import os, json
import subprocess
from dataclasses import dataclass
import time
from openai import OpenAI
```

**Module Usage Overview**:

| Module | Usage |
|--------|-------|
| `os` | Get current working directory, used to set subprocess working directory |
| `json` | Parse function argument strings in tool_call to Python dictionaries |
| `subprocess` | Core module for executing bash commands |
| `dataclasses.dataclass` | Decorator for quickly defining `LoopState` data class |
| `openai.OpenAI` | OpenAI Python SDK client class, used to call model APIs compatible with OpenAI interface |

---

### 1.2 API Client Configuration

```python
import os
# Get API configuration from environment variables (recommended approach)
openai_api_key = os.getenv("OPENAI_API_KEY", "EMPTY")
openai_api_base = os.getenv("OPENAI_API_BASE", "http://your-server-ip:port/v1")
client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)

try:
    MODEL = client.models.list().data[0].id
    print(f"✅ Connection successful, model: {MODEL}")
except Exception as e:
    print(f"❌ Failed to get model: {e}")
    quit()
```

> **Important Note**: This teaching document and all subsequent examples use the **OpenAI-compatible API interface format** to build the demo. This format is widely supported, including Qwen, Llama and various other open-source models that provide OpenAI-compatible interfaces, making it easy to learn and migrate.

**Environment Variable Configuration (Recommended)**:

Using environment variables to manage sensitive configurations is a best practice that avoids hardcoding sensitive information like API Keys in the code.

**Setup Method**:
```bash
# Temporary setup (valid for current terminal session)
export OPENAI_API_KEY="your-api-key-here"
export OPENAI_API_BASE="http://your-server-ip:8000/v1"

# Permanent setup (add to ~/.bashrc or ~/.zshrc)
echo 'export OPENAI_API_KEY="your-api-key-here"' >> ~/.bashrc
echo 'export OPENAI_API_BASE="http://your-server-ip:8000/v1"' >> ~/.bashrc
source ~/.bashrc
```

**Priority Explanation**:
- If environment variables are set, use the values from environment variables
- If environment variables are not set, use default values (`"EMPTY"` and `"http://your-server-ip:port/v1"`)

**Configuration Explanation**:

| Configuration | Value | Description |
|---------------|-------|-------------|
| `api_key` | `"EMPTY"` or environment variable | Locally deployed models usually don't require authentication, can be set via `OPENAI_API_KEY` environment variable |
| `base_url` | `"http://your-server-ip:port/v1"` or environment variable | Local model server API address, can be set via `OPENAI_API_BASE` environment variable |
| `MODEL` | Dynamically obtained | Get the first available model ID on the server via `client.models.list()` |

**Design Points**:
- Use `try-except` for connectivity check, verify API availability at startup
- Dynamically obtain model ID instead of hardcoding, improving configuration flexibility

---

### 1.3 SYSTEM Prompt Definition

```python
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to inspect and change the workspace. Act first, then report clearly."
```

**Prompt Design**:
- Defines the model role as a coding agent
- Informs the model of the current working directory so it understands the operation context
- Explicitly authorizes the model to use the bash tool
- Guides model behavior pattern: act first, then report clearly

This is a concise system prompt focused on tool usage authorization and behavior guidance, avoiding over-constraining the model.

---

### 1.4 TOOLS Tool Definition

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

**JSON Schema Structure Explanation**:

`TOOLS` is a list where each element defines a tool. This example only defines the `bash` tool:

- **name**: Tool identifier, the function name used when model outputs tool_call
- **description**: Function description, helps the model determine when to call this tool
- **parameters**: Parameter specification, uses JSON Schema format to define parameter types and required fields
- **required**: Required parameter list, ensures the model doesn't miss key parameters

This format is the OpenAI Function Calling standard format, widely supported.

---

## Phase 2: Data Structure Definition

> **Phase Description**: This phase defines the `LoopState` data class, used to encapsulate the Agent loop state. Using the `@dataclass` decorator automatically generates methods like `__init__`, simplifying the code.

### 2.1 LoopState Data Class

```python
@dataclass
class LoopState:
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None
```

**Field Explanation**:

| Field | Type | Default Value | Function |
|-------|------|---------------|----------|
| `messages` | `list` | None | Stores complete dialogue history, including messages from all roles: system, user, assistant, tool |
| `turn_count` | `int` | `1` | Records current loop turn, used for debugging and state tracking |
| `transition_reason` | `str \| None` | `None` | Records the reason for state transition (e.g., `"tool_result"`), used to understand loop decision logic |

**Design Advantages**:
- Uses `@dataclass` to simplify data class definition
- Encapsulates loop state into a single object, easy to pass and manage
- `transition_reason` provides explainability, convenient for debugging loop behavior

**Usage Example**:
```python
state.transition_reason = "tool_result"  # Continue loop due to tool result
state.transition_reason = None           # Normal end
```

---

## Phase 3: Tool Execution Layer

> **Phase Description**: This phase defines three tool execution related functions. These functions are called in the core loop of Phase 4.

### 3.1 run_bash() Function Detailed Explanation

```python
def run_bash(command: str) -> str:
    # Non-executable operations, interrupt when agent attempts to execute commands in the list,
    # Note: This is a basic demonstration, actual production environment needs more comprehensive security protection mechanisms
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

**Mechanism Overview**:
This function executes shell commands with three layers of processing: (1) Dangerous command filtering, checks 5 dangerous patterns (`rm -rf /`, `sudo`, `shutdown`, `reboot`, `> /dev/`) and intercepts them; (2) subprocess execution, sets working directory, captures output, 120 second timeout; (3) Output processing, merges stdout/stderr, limits to 50000 characters to prevent context explosion.

> ⚠️ **Security Notice**: The dangerous command filtering here is only a basic demonstration; simple substring matching can be easily bypassed. In actual production environments, stricter security protection must be applied to Agent operations (such as sandbox isolation, permission control, command whitelists, etc.).

> ⚠️ **Important Design Principle**: After each tool execution, the executed action and result must be returned to the model. If no information is returned after tool execution, the model cannot perceive that the operation is complete and may fall into an infinite loop repeatedly calling the same tool.

---

### 3.2 extract_text() Function Detailed Explanation

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

**Mechanism Overview**:
This function extracts text from response content, supporting two formats: (1) String format returns directly; (2) Content block list format iterates through each block to extract `text` attribute, joins with newline characters. Designed to be compatible with different model response formats, safely handles unknown types to avoid exceptions.

---

### 3.3 execute_tool_calls() Function Detailed Explanation

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

**Mechanism Overview**:
This function parses and executes the model's tool call requests. Process: (1) Iterate through tool_calls list; (2) Determine tool type, only process bash; (3) Use json.loads to parse argument string; (4) Call run_bash to execute command; (5) Build tool result messages conforming to API format (including role, tool_call_id, name, content). Returns results to append to message history and feed back to the model.

**Return Result Format**:
```python
{
    "role": "tool",              # Fixed as "tool"
    "tool_call_id": "...",       # Corresponds to tool_call ID, used to associate request and response
    "name": "bash",              # Tool name
    "content": "command execution output"  # Tool execution result
}
```

---

## Phase 4: Core Loop Logic

> **Phase Description**: This phase defines the core loop logic of the Agent. `run_one_turn()` executes a single dialogue turn, `agent_loop()` continuously calls `run_one_turn()` until the model no longer requests tools.

### 4.1 run_one_turn() Function Detailed Explanation

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

**Complete Process of Single Dialogue Turn**:

```
┌─────────────────────────────────────────────────────────┐
│                    run_one_turn()                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  1. Call LLM API                                        │
│     └── client.chat.completions.create()                │
│                                                         │
│  2. Extract response message                            │
│     └── response.choices[0].message                     │
│                                                         │
│  3. Append assistant message to history                 │
│     └── state.messages.append({"role": "assistant", ...})│
│                                                         │
│  4. Check if there are tool_calls                       │
│     │                                                   │
│     ├── Has tool_calls ──> Execute tools ──> Append results ──> True│
│     │                │                                   │
│     │                └── Update turn_count              │
│     │                └── Set transition_reason          │
│     │                                                   │
│     └── No tool_calls ────────────────────────────> False│
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Mechanism Overview**:
This function executes the complete process of a single dialogue turn: (1) Call LLM API to send request, passing dialogue history, tool definitions and generation parameters; (2) Extract response message and append assistant message to history; (3) Check if there are tool_calls—if yes, execute tools and add results to message history, update state and return True to continue loop; if no, return False to end loop. Return value True means continue loop, False means end loop.

**Parameter Configuration Explanation**:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `model` | `MODEL` | Model ID (dynamically obtained) |
| `tools` | `TOOLS` | Available tool list |
| `messages` | `state.messages` | Complete dialogue history |
| `max_tokens` | `8000` | Maximum generation length |
| `temperature` | `1` | Sampling temperature (1 means standard randomness) |
| `extra_body.top_k` | `20` | Select from top 20 tokens during sampling |
| `extra_body.chat_template_kwargs.enable_thinking` | `True` | Qwen3.5 thinking mode switch |

**Return Value Meaning**:
- `True`: Has tool calls, need to continue loop
- `False`: No tool calls, loop ends

---

### 4.2 agent_loop() Function Detailed Explanation

```python
def agent_loop(state: LoopState) -> None:
    while run_one_turn(state):
        pass
```

**Mechanism Overview**:
This is the core loop of the entire Agent, extremely concise logic: continues executing when `run_one_turn(state)` returns True; each execution calls LLM, checks tool_call, executes tools and adds results to message history; when it returns False, it means LLM no longer requests tool calls and the loop ends. Design philosophy is minimalism, encapsulating complexity in `run_one_turn`, relying on `LoopState` to pass state between iterations.

**Main Loop Control**:

```
while run_one_turn(state) returns True:
    - Continuously execute run_one_turn
    - Each execution will:
      1. Call LLM
      2. Check if there is tool_call
      3. If yes, execute tool and add result to message history
      4. Return True to continue loop

When run_one_turn returns False:
    - Indicates LLM no longer requests tool calls
    - Loop ends
```

**Design Philosophy**:
- Minimalism: Core loop is only 3 lines of code
- Encapsulate complexity in `run_one_turn`
- Rely on `LoopState` to pass state between iterations

---

## Phase 5: Program Entry and Interaction

> **Phase Description**: This phase is the Python script entry point, responsible for starting the interactive session. It maintains dialogue history, gets user input, creates LoopState and starts agent_loop.

### 5.1 __main__ Entry Detailed Explanation

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

**Interactive Loop Flow**:

```
┌──────────────────────────────────────────────────────────────┐
│                       __main__ Entry                          │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Initialize history = [system message]                    │
│                                                              │
│  2. Enter main interaction loop while True:                  │
│     │                                                        │
│     ├── Get user input input()                               │
│     │   └── Catch EOFError/KeyboardInterrupt → break         │
│     │                                                        │
│     ├── Check exit commands (q/exit/empty) → break           │
│     │                                                        │
│     ├── Append user message to history                       │
│     │                                                        │
│     ├── Create LoopState and start agent_loop                │
│     │   └── agent_loop internal loop executes until no tool_call │
│     │                                                        │
│     ├── Extract and print final response                     │
│     │   └── extract_text(history[-1]["content"])             │
│     │                                                        │
│     └── Continue loop (history preserved, supports multi-turn dialogue) │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**Mechanism Overview**:
This is the Python script entry point, responsible for starting the interactive session. Process: (1) Initialize dialogue history containing system message; (2) Enter main interaction loop to continuously get user input; (3) Support EOFError, KeyboardInterrupt exception handling and exit commands (q, exit, empty input); (4) Append user input to history, create LoopState and start agent_loop; (5) Extract final text response and print. history is maintained outside the loop, preserving complete context to support multi-turn dialogue.

**Feature Explanation**:
- Supports multi-turn dialogue: `history` is maintained outside the loop, preserving complete context
- Friendly exit mechanism: supports `q`, `exit`, empty input or Ctrl+C
- Colored prompt: `\033[36m` displays cyan prompt
- Automatically extracts and prints final text response

---

### 5.2 Complete Execution Flow Tracking

**Complete flow from script startup to completing one user query**:

```
1. Script startup (python3 s01_agent_loop.py)
   │
   ├─→ Execute Phase 1: Import modules, configure API, define SYSTEM and TOOLS
   │     └── Print "✅ Connection successful, model: qwen3.5-xxx"
   │
   ├─→ Execute Phase 2: Define LoopState class
   │
   ├─→ Execute Phase 3: Define tool execution functions
   │
   ├─→ Execute Phase 4: Define core loop functions
   │
   └─→ Execute Phase 5: Enter __main__

2. User inputs query ("View current directory")
   │
   ├─→ history.append({"role": "user", "content": "View current directory"})
   │
   ├─→ state = LoopState(messages=history)
   │
   └─→ agent_loop(state)

3. agent_loop internal loop
   │
   ├─→ 1st run_one_turn(state)
   │     │
   │     ├─→ Call LLM (messages: [system, user], tools: [bash])
   │     │
   │     ├─→ Model returns tool_call:
   │     │     [
   │     │       {
   │     │         "name": "bash",
   │     │         "arguments": {"command": "ls -la"}
   │     │       }
   │     │     ]
   │     │
   │     ├─→ Execute tool and get result
   │     │     └── run_bash("ls -la") → "dir1\ndir2\nfile.txt"
   │     │
   │     └─→ Return True (continue loop)
   │
   ├─→ 2nd run_one_turn(state)
   │     │
   │     ├─→ Call LLM (messages: [system, user, assistant, tool])
   │     │
   │     ├─→ Model returns final text response (no tool_call)
   │     │
   │     └─→ Return False (end loop)
   │
   └─→ agent_loop returns

4. Extract and print final response
   │
   └─→ Print model response

5. Wait for next user input...
```

---

## Key Design Points Summary

### 1. Message Accumulation Mechanism

```python
# In run_one_turn
state.messages.append({"role": "assistant", "content": response_messages.content})
# ...
for tool_result in results:
    state.messages.append(tool_result)
```

**Mechanism Explanation**:

Each LLM response and tool execution result is appended to the message history, maintaining complete dialogue context. This design:

- Supports multi-turn reasoning, model can continue decision-making based on previous tool results
- Implements context preservation, each turn has complete historical information
- Facilitates debugging and reviewing the entire interaction process

**Dialogue History Accumulation Example**:

```
Turn 1:
├── [system] "You are a coding agent..."
├── [user] "View current directory"
├── [assistant] None (contains tool_call)
└── [tool] "dir1\ndir2\nfile.txt"

Turn 2 (continues based on Turn 1 result):
├── [system] "You are a coding agent..."
├── [user] "View current directory"
├── [assistant] None (contains tool_call)
├── [tool] "dir1\ndir2\nfile.txt"
├── [assistant] "Current directory contains..." (final response)
└── [user] "Next question..." (new input)
```

---

### 2. tool_calls Judgment Logic

```python
if response_messages.tool_calls:
    # Has tool calls, execute and return True to continue loop
else:
    # No tool calls, return False to end loop
```

**Judgment Logic**:

| Condition | Meaning | Action |
|-----------|---------|--------|
| `response_messages.tool_calls` is true | LLM requests to call one or more tools | Execute tools, feed results back to LLM, continue loop |
| `response_messages.tool_calls` is false/empty | LLM considers no tools needed, task complete | End loop, return final response |

**Key Points**:
- Relies on LLM to autonomously judge when to stop
- No need to preset maximum loop count
- Potential infinite loop risk (production environment needs protection)

---

### 3. Dangerous Command Filtering Mechanism

```python
dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"] 
if any(d in command for d in dangerous):
    return f"Error: Dangerous command blocked {command}"
```

**Filtering Strategy**:

| Dangerous Pattern | Risk | Filtering Method |
|-------------------|------|------------------|
| `rm -rf /` | Delete all files in root directory | Substring matching |
| `sudo` | Privilege escalation | Substring matching |
| `shutdown` | Shutdown system | Substring matching |
| `reboot` | Reboot system | Substring matching |
| `> /dev/` | Redirect to device file | Substring matching |

> ⚠️ **Limitations**: Simple substring matching can be easily bypassed (such as concatenation, encoding, variable substitution, etc.). Production environment needs sandbox containers, permission isolation, command whitelists and other stricter measures.

---

### 4. Output Length Limitation

```python
return out[:50000] if out else f"Command {command} executed successfully (no output)."
```

**Design Considerations**:

| Factor | Description |
|--------|-------------|
| Context window limit | Prevent single tool output from consuming too many tokens |
| Response time control | Avoid delays caused by transferring large amounts of data |
| Information density | Most command outputs are far smaller than this limit |

**Truncation Strategy**: Keep first 50000 characters, no truncation notice; return success notice instead of empty string when output is empty.

---

### 5. Timeout Control

```python
subprocess.run(..., timeout=120)
...
except subprocess.TimeoutExpired:
    return "Error: Timeout (120s)"
```

**Timeout Setting**: 120 seconds, balances long-running tasks and responsiveness. Catches timeout exceptions and returns friendly error messages, allowing loop to continue without causing program crash.

---

### 6. LoopState State Tracking

```python
@dataclass
class LoopState:
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None
```

**State Tracking Dimensions**:

| Field | Tracking Content | Debugging Value |
|-------|------------------|-----------------|
| `messages` | Complete dialogue history | Review entire interaction process |
| `turn_count` | Loop turns | Identify abnormally long loops |
| `transition_reason` | State transition reason | Understand loop decision logic |

**Usage Example**:
```python
state.transition_reason = "tool_result"  # Continue loop due to tool result
state.transition_reason = None           # Normal end
```

---

## Qwen3.5 Feature Explanation

### enable_thinking Thinking Mode

```python
extra_body={
    "top_k": 20,
    "chat_template_kwargs": {"enable_thinking": True},
}
```

`chat_template_kwargs: {"enable_thinking": True}` is the **thinking mode switch specific to Qwen3.5 model**.

**Working Principle**:

| Mode | Behavior | Output Characteristics |
|------|----------|------------------------|
| `enable_thinking: True` | Enable thinking mode | Model generates a "thinking process" before giving final answer, showing reasoning chain |
| `enable_thinking: False` | Disable thinking mode | Model outputs final answer directly, without showing intermediate reasoning process |

**Impact on Model Output**:

1. **Output Structure Change**: Model generates thinking process within `thought>` tags, then outputs final answer

   **Thinking Mode Output Structure Example**:
   ```
   thought>
   Let me analyze this problem...
   First need to consider...
   Then should...
   Finally conclude...
   /thought>
   
   The final answer is...
   ```

2. **Tool Call Scenarios**:
   - Model analyzes whether to call tools during thinking process
   - Thinking content is not counted in tool_call judgment
   - Final tool_call still normally triggers tool execution

3. **Advantages**:
   - Improves explainability of complex tasks
   - Helps debug model decision process
   - May improve performance on complex reasoning tasks

> **Note**: This parameter is a Qwen3.5 specific extension, other models may not support it or may require different configuration methods.

---

## Practice Guide

### How to Run the Code

```bash
# 1. Ensure model service is running (http://your-server-ip:port/v1)

# 2. Run script
cd v1_task_manager/chapter_01/
python3 s01_agent_loop.py
```

**Expected Startup Output**:
```
✅ Connection successful, model: qwen3.5-xxx
s01 >>
```

### Test Example Prompts

#### Example 1: View Current Directory

```
s01 >> List files in current directory
```

**Expected Behavior**:
1. LLM calls `bash` tool to execute `ls -la`
2. Display command output
3. Return file list summary

#### Example 2: Create File

```
s01 >> Create a file named test.txt with content "Hello Agent"
```

**Expected Behavior**:
1. LLM calls `bash` to execute `echo "Hello Agent" > test.txt`
2. Verify file creation success
3. Return confirmation message

#### Example 3: Multi-step Task

```
s01 >> List all Python files, then count their total lines
```

**Expected Behavior**:
1. First round: Execute `find . -name "*.py"` to find Python files
2. Second round: Execute `wc -l` on each file to count lines
3. Summarize results and return

### Exit Methods

| Method | Operation |
|--------|-----------|
| Command exit | Input `q` or `exit` |
| Empty input exit | Press Enter directly (empty string) |
| Force exit | `Ctrl + C` |

---

## Summary

### Core Takeaways

1. **Essence of Agent**: One Tool + One Loop = One Agent
   - Tools provide capability boundaries
   - Loop implements autonomous decision-making

2. **Harness Layer Design**:
   - Minimalist core loop (3 lines of code)
   - State encapsulated in `LoopState` data class
   - Message history accumulation implements context preservation

3. **Tool Call Mechanism**:
   - JSON Schema defines tool interface
   - LLM autonomously decides when to call tools
   - Tool result feedback forms closed loop

4. **Security and Limitations**:
   - Dangerous command filtering (basic protection)
   - Output length limitation (50000 characters)
   - Timeout control (120 seconds)

---

**Based on code**: `s01_agent_loop.py` (v1_task_manager/chapter_01/s01_agent_loop.py)  
**Learning Objective**: Understand the core mechanism of Agent Loop
