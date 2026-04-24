# s05: Subagent - Code Documentation

---

## Overview

### Core Improvements

**From Single Agent to Main-Subagent Collaborative Architecture**

s05 introduces a **Subagent System** built on top of s04, achieving task context isolation and delegated execution. The main agent is responsible for task planning and decomposition, while subagents are responsible for executing specific tasks. Execution details are only preserved in the subagent's context, keeping the main agent's context clean.

### Design Philosophy

> **"Context Isolation + Task Delegation"**

The core design philosophy of s05: Execute specific tasks by creating independent subagent contexts. The main agent only sees task delegation instructions and summaries returned by subagents, avoiding execution detail pollution in the main context.

**Core Mechanisms**:
- **Context Isolation**: Subagents have independent message histories, separated from the main agent context
- **Tool Partitioning**: Main agent and subagents use different tool sets, separating responsibilities
- **Task Delegation**: Main agent creates subagents to execute subtasks through the `task` tool
- **Handover Report**: Subagents return structured summaries after completing tasks

### Code File Path

```
v1_task_manager/chapter_05/s05_subagent.py
```

### Core Architecture Diagram (Comparison with s04)

**s04 Architecture (Single Agent)**:
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

**s05 Architecture (Main-Subagent Collaboration)**:
```
    +----------+      +-----------+      +------------------+
    |   User   | ---> |  Main     | ---> | Parent Tools     |
    |  prompt  |      |  Agent    |      | {read_file,      |
    +----------+      +-----+-----+      |  task, todo}     |
                              ^          +--------+---------+
                              |                   |
                              |                   | task tool
                              |                   v
                              |          +-----------+
                              |          | Subagent  |
                              |          |(New Ctx)  |
                              |          +-----+-----+
                              |                |
                              |                | Child Tools
                              |                | {bash, read,
                              |                |  write, edit,
                              |                |  load_skill}
                              |                v
                              |          +-----------+
                              |          | Execution |
                              |          | (Summary) |
                              |          +-----+-----+
                              |                |
                              +----------------+
                                   Return summary
```

**Architecture Explanation**:
1. Main agent receives user task and determines if delegation to subagent is needed
2. Main agent calls `task` tool, passing subtask description
3. `run_subagent()` function creates independent subagent context
4. Subagent executes specific tasks using `CHILD_TOOLS`
5. Subagent returns summary after completing task
6. Main agent receives summary, updates todo status

---

## Comparison with s04

### Change Overview

| Component | s04 | s05 | Change Description |
|------|-----|-----|----------|
| **Import Modules** | Standard library | + `dataclasses` enhancement | No significant changes |
| **Tool Set** | Single TOOLS | `PARENT_TOOLS` + `CHILD_TOOLS` | Tool partitioning, main agent and subagent use different tools |
| **SYSTEM Prompt** | Single SYSTEM | SYSTEM + SUBAGENT_SYSTEM | Dual prompts, distinguishing main agent and subagent roles |
| **New Functions** | None | `run_subagent()`, `print_agent_thought()` | Subagent execution and formatted output |
| **task Tool** | None | Yes | Main agent creates subagents via task tool |
| **execute_tool_calls** | Handles 6 tools | Handles 7 tools (+task) | Added task tool handling logic |
| **Context Management** | Single context | Main context + independent subagent contexts | Context isolation |

### New Component Architecture

```
run_subagent() Function
├── Create independent message history
├── Subagent execution loop (max 30 steps)
└── Return summary content

Tool Partitioning
├── PARENT_TOOLS            # Main agent tool set
│   ├── read_file
│   ├── task
│   └── todo
└── CHILD_TOOLS             # Child agent tool set
    ├── bash
    ├── read_file
    ├── write_file
    ├── edit_file
    └── load_skill

Dual SYSTEM Prompts
├── SYSTEM                  # Main agent prompt
│   ├── task tool usage guidance
│   ├── todo tool usage guidance
│   └── Subagent work verification requirements
└── SUBAGENT_SYSTEM         # Subagent prompt
    ├── Task completion requirements
    ├── Tool usage instructions
    ├── load_skill usage guidance
    └── Handover report requirements
```

---

## Detailed Explanation by Execution Order

### Phase 1: New Imports and Utility Functions

#### print_agent_thought() Function

**Mechanism Overview**:
`print_agent_thought()` is a helper function for formatting and printing agent thought processes and output content. It uses colored borders and titles to identify output from different agents, enhancing terminal output readability.

```python
def print_agent_thought(agent_name: str, message, color_code: str):
    """Extract and format print Agent's thought process and output content"""
    content = message.content
    if content:
        print(f"{color_code}╭─── [{agent_name} Thought/Output] ──────────────────────────\033[0m")
        print(f"{content.strip()}")
        print(f"{color_code}╰─────────────────────────────────────────────────────\033[0m")
```

**Parameter Descriptions**:
- `agent_name`: Agent name, e.g., "Main Agent (Turn 1)" or "Sub Agent (Step 1)"
- `message`: LLM response message object, containing `content` attribute
- `color_code`: ANSI color code for distinguishing different agents

**Color Usage**:
- Main agent: `\033[34m` (Blue)
- Subagent: `\033[36m` (Cyan)
- Subagent spawn prompt: `\033[35m` (Magenta)
- Tool output: `\033[33m` (Yellow)
- Final response: `\033[32m` (Green)

**Design Philosophy**:
- **Visual Distinction**: Differentiate output from different agents and components through colors and borders
- **Debug-Friendly**: Easy to trace agent execution flow and thought process
- **Non-Intrusive**: Only used for terminal output, not affecting core logic

---

### Phase 2: Tool Partitioning Design

#### Tool Partitioning Mechanism Overview

s05 splits the tool set into two independent parts: `CHILD_TOOLS` (subagent tool set) and `PARENT_TOOLS` (main agent tool set). This partitioning is based on the principle of separation of concerns - the main agent is responsible for task planning and coordination, while subagents are responsible for specific execution.

**Design Philosophy**:
- **Separation of Concerns**: Main agent focuses on task decomposition and state management, subagent focuses on specific execution
- **Context Protection**: Subagents cannot access `todo` tool, avoiding pollution of main agent's plan state
- **Capability Minimization**: Each agent only has tools needed to complete its responsibilities, reducing misoperation risk

---

#### CHILD_TOOLS (Subagent Tool Set)

**Mechanism Overview**:
`CHILD_TOOLS` is the list of tools available to subagents, containing low-level operation tools needed for executing specific tasks. Subagents use these tools to directly manipulate the file system and execute commands.

```python
CHILD_TOOLS = [
    {"type": "function", "function": {"name": "bash", ...}},
    {"type": "function", "function": {"name": "read_file", ...}},
    {"type": "function", "function": {"name": "write_file", ...}},
    {"type": "function", "function": {"name": "edit_file", ...}},
    {"type": "function", "function": {"name": "load_skill", ...}},
]
```

**Tool List**:
| Tool | Function | Description |
|------|------|------|
| `bash` | Execute shell commands | Run system commands, compile code, run tests, etc. |
| `read_file` | Read file | View file content, supports limit parameter for line count |
| `write_file` | Write file | Create or overwrite file content |
| `edit_file` | Edit file | Replace specific text in file |
| `load_skill` | Load skill | Load domain knowledge documents into context |

**Design Philosophy**:
- **Execution-Oriented**: All tools are actual operation tools, no management tools
- **Complete Capability**: Subagents have complete file operation and command execution capabilities
- **Skill Support**: Supports `load_skill`, subagents can load domain knowledge on demand

---

#### PARENT_TOOLS (Main Agent Tool Set)

**Mechanism Overview**:
`PARENT_TOOLS` is the list of tools available to the main agent, containing task management (`todo`), task delegation (`task`), and file reading (`read_file`) tools. The main agent does not directly execute specific operations but completes tasks through delegation and planning.

```python
PARENT_TOOLS = [
    {"type": "function", "function": {"name": "read_file", ...}},
    {"type": "function", "function": {"name": "task", ...}},
    {"type": "function", "function": {"name": "todo", ...}},
]
```

**Tool List**:
| Tool | Function | Description |
|------|------|------|
| `read_file` | Read file | View file content, understand project structure |
| `task` | Create subagent | Delegate subtasks to subagent for execution |
| `todo` | Manage plan | Create and update multi-step task plans |

**Design Philosophy**:
- **Management-Oriented**: Tools focus on task management and coordination, not specific execution
- **Information Access**: Retain `read_file` for main agent to understand project status
- **Delegation Capability**: `task` tool is the core mechanism for main agent to delegate tasks
- **Plan Control**: `todo` tool is exclusively held by main agent, ensuring plan consistency

---

#### Tool Comparison

| Tool | PARENT_TOOLS | CHILD_TOOLS | Description |
|------|--------------|-------------|------|
| `bash` | ❌ | ✅ | Only subagents can execute shell commands |
| `read_file` | ✅ | ✅ | Both main agent and subagents can read files |
| `write_file` | ❌ | ✅ | Only subagents can write files |
| `edit_file` | ❌ | ✅ | Only subagents can edit files |
| `load_skill` | ❌ | ✅ | Only subagents can load skills |
| `task` | ✅ | ❌ | Only main agent can create subagents |
| `todo` | ✅ | ❌ | Only main agent can manage task plans |

**Commented-out bash Tool**:
The `PARENT_TOOLS` originally had a `bash` tool definition, but it was commented out:
```python
# {"type": "function","function": {"name": "bash", ... }},
```
This indicates the design intent is to completely deprive the main agent of direct execution capability, forcing it to execute through subagents.

---

### Phase 3: run_subagent() Function Details

#### Mechanism Overview

The `run_subagent()` function is the core of the subagent system, responsible for creating independent contexts, executing the subagent loop, and returning task summaries. This function is called by the `task` tool's handler function, triggered when the main agent needs to delegate tasks.

**Core Flow**:
1. Print subagent spawn prompt
2. Create independent subagent message history (containing SUBAGENT_SYSTEM prompt and user task)
3. Enter execution loop (max 30 steps)
4. Call LLM to get response
5. Execute tool calls (if any)
6. Repeat until no tool calls or step limit reached
7. Return subagent's final summary

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
        print_agent_thought(f"Sub Agent (Step {step+1})", response_message, "\033[36m")

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

**Parameter Descriptions**:
- `prompt`: Specific description of the subtask, passed by main agent through `task` tool

**Return Values**:
- Successful completion: Returns subagent's final response content (summary)
- Step limit exceeded: Returns warning message indicating the last action executed

---

#### Independent Context Creation

**Mechanism Overview**:
The subagent's context is completely independent from the main agent, achieved by creating a new `LoopState` instance. The subagent's message history only contains the `SUBAGENT_SYSTEM` prompt and current task description, without any of the main agent's conversation history.

```python
sub_messages = [
    {"role": "system", "content": SUBAGENT_SYSTEM},
    {"role": "user", "content": prompt}
] 
sub_state = LoopState(messages=sub_messages)
```

**Design Philosophy**:
- **Context Isolation**: Subagent doesn't know main agent's conversation history, avoiding context pollution
- **Simplicity**: Subagent only focuses on current task, reducing interference from irrelevant information
- **Traceability**: Each subagent's task and output are independently recorded

---

#### Subagent Execution Loop

**Mechanism Overview**:
The subagent execution loop is similar to the main agent's execution logic, but uses `CHILD_TOOLS` and a fixed 30-step limit. Each loop iteration calls the LLM for a response, executes tool calls, until no tool calls or step limit is reached.

**Loop Logic**:
```python
for step in range(30):  # safety limit
    # 1. Call LLM
    response = client.chat.completions.create(...)
    
    # 2. Append response to history
    sub_state.messages.append(response_message)
    
    # 3. Print thought process
    print_agent_thought(f"Sub Agent (Step {step+1})", response_message, "\033[36m")
    
    # 4. Execute tool calls
    if response_message.tool_calls:
        results, _ = execute_tool_calls(response_message)
        for tool_result in results:
            sub_state.messages.append(tool_result)
        sub_state.turn_count += 1
    else:
        break  # No tool calls, end loop
```

**Step Limit**:
- Maximum steps: 30
- Exceed handling: Return warning message indicating task termination
- Normal exit: Exit when LLM returns response without tool calls

**Design Philosophy**:
- **Safety Protection**: Prevent subagent from falling into infinite loops
- **Transparent Debugging**: Print each step's thought process for easy execution flow tracing
- **Logic Reuse**: Reuse `execute_tool_calls` to handle tool calls

---

#### Result Return Mechanism

**Mechanism Overview**:
After completing the task, the subagent returns the final summary content to the main agent. The summary should include task completion status, key findings, and verification results.

**Return Value Handling**:
```python
if response_message.tool_calls:
    return f"[Subagent Warning: Task terminated after 30 steps. Last action was {response_message.tool_calls[0].function.name}]"
    
return response_message.content or "Task finished (no summary provided)"
```

**Normal Return**:
- Subagent's final response content (usually task summary)
- If no content, return default prompt "Task finished (no summary provided)"

**Exception Return**:
- Return warning message when step limit is exceeded
- Warning message includes the name of the last action executed

**Design Philosophy**:
- **Summary-Oriented**: Expect subagent to return concise summary, not detailed process
- **Exception Handling**: Clearly identify exceptional situations for main agent judgment
- **Default Value**: Provide default return value to avoid empty returns

---

### Phase 4: New task Tool

#### Mechanism Overview

The `task` tool is the core mechanism for the main agent to delegate subtasks. The main agent calls the `task` tool, passing a task description, which triggers the `run_subagent()` function to create and execute a subagent. After the subagent completes the task, it returns a summary as the `task` tool's return value to the main agent.

**Tool Handler Function**:
```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_REGISTRY.load_full_text(kw["name"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),
    "task":       lambda **kw: run_subagent(kw["prompt"]),  # Added
}
```

**Call Flow**:
```
Main agent calls task tool
       ↓
TOOL_HANDLERS["task"](**args)
       ↓
run_subagent(kw["prompt"])
       ↓
Create subagent context → Execute loop → Return summary
       ↓
Summary returned to main agent as tool_result
```

---

#### JSON Schema Definition

**Mechanism Overview**:
The `task` tool parameter definition uses JSON Schema format, describing the parameter structure the main agent should provide when calling the tool.

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

**Parameter Descriptions**:
- `prompt` (Required): Specific instructions for the subtask, subagent will execute based on this instruction
- `description` (Optional): Short description of the task, possibly used for logging or display

**Design Philosophy**:
- **Clear Description**: Tool description explicitly states subagent has independent context, shares filesystem but not conversation history
- **Required Parameters**: Only require `prompt`, lowering usage barrier
- **Optional Description**: `description` is optional, providing additional metadata

---

### Phase 5: Dual SYSTEM Prompts

#### Mechanism Overview

s05 introduces two independent SYSTEM prompts: `SYSTEM` for the main agent and `SUBAGENT_SYSTEM` for subagents. Both prompts are customized according to their respective roles and responsibilities, guiding agents to correctly use tools and complete tasks.

---

#### SYSTEM (Main Agent Prompt)

**Mechanism Overview**:
The main agent's SYSTEM prompt emphasizes task planning, subagent delegation, and work verification. The main agent does not directly execute operations but manages and delegates tasks through `todo` and `task` tools.

```python
SYSTEM = f"""You are a coding agent at {WORKDIR}. 
1.Use the task tool to delegate exploration or subtasks.
2.Use the todo tool to plan complex and multi-step tasks. Mark in_progress before starting, completed when done. Keep exactly one step in_progress when a task has multiple steps.
3.Do NOT immediately mark a task as 'completed' just because the subagent claims it is done. You MUST verify the subagent's work before calling the todo tool to mark it completed. If the work is flawed, explain the issue and spawn a new task to fix it."""
```

**Three Guiding Principles**:

**Principle 1: Task Delegation**
```
Use the task tool to delegate exploration or subtasks.
```
- Explicitly use `task` tool to delegate subtasks
- Both exploratory and execution tasks should be delegated

**Principle 2: Task Planning** (Inherited from s04)
```
Use the todo tool to plan complex and multi-step tasks. 
Mark in_progress before starting, completed when done. 
Keep exactly one step in_progress when a task has multiple steps.
```
- Complex tasks require planning first
- Status marking specifications
- Single in_progress constraint

**Principle 3: Work Verification**
```
Do NOT immediately mark a task as 'completed' just because the subagent claims it is done. 
You MUST verify the subagent's work before calling the todo tool to mark it completed. 
If the work is flawed, explain the issue and spawn a new task to fix it.
```
- Prohibit blind trust in subagents
- Must verify subagent work
- Create fix task when issues are found

**Design Philosophy**:
- **Delegation Priority**: Encourage using subagents for specific task execution
- **Verification Responsibility**: Main agent is responsible for subagent work quality
- **Plan Management**: Maintain s04's task planning mechanism

---

#### SUBAGENT_SYSTEM (Subagent Prompt)

**Mechanism Overview**:
The subagent's SYSTEM prompt emphasizes task execution, tool usage, and handover reporting. Subagents focus on completing specific tasks and providing detailed summary reports upon completion.

```python
SUBAGENT_SYSTEM = f"""You are a coding subagent at {WORKDIR}. 
1.Complete the given task, then summarize your findings or your work.
2.Use tools to solve tasks. Act, after executing the command, tell me that it has been completed.
3.Use load_skill when a task needs specialized instructions before you act. Skills available: {SKILL_REGISTRY.describe_available()}
4.When finishing a task, you MUST provide a detailed handover report including: 1. Files created/modified. 2. Key functions implemented. 3. Output of any verification commands (e.g., test results or syntax checks) you ran.
"""
```

**Four Guiding Principles**:

**Principle 1: Task Completion and Summary**
```
Complete the given task, then summarize your findings or your work.
```
- Completing the task is the primary goal
- Must provide summary after completion

**Principle 2: Tool Execution**
```
Use tools to solve tasks. Act, after executing the command, tell me that it has been completed.
```
- Use tools to solve problems
- Clearly report completion after execution

**Principle 3: Skill Loading**
```
Use load_skill when a task needs specialized instructions before you act. 
Skills available: {SKILL_REGISTRY.describe_available()}
```
- Load skills first when domain knowledge is needed
- Dynamically list available skills

**Principle 4: Handover Report**
```
When finishing a task, you MUST provide a detailed handover report including: 
1. Files created/modified. 
2. Key functions implemented. 
3. Output of any verification commands (e.g., test results or syntax checks) you ran.
```
- Must provide detailed handover report
- Report contains three required parts

**Design Philosophy**:
- **Execution-Oriented**: Subagent's core responsibility is task completion
- **Report Specification**: Enforce structured summary for easy main agent verification
- **Skill Support**: Support on-demand domain knowledge loading
- **Action First**: Encourage execution before reporting

---

### Phase 6: execute_tool_calls Changes

#### task Tool Handling

**Mechanism Overview**:
The `execute_tool_calls` function handles all tool calls through the `TOOL_HANDLERS` dictionary, including the new `task` tool. The `task` tool's handler function calls `run_subagent()` to create and execute a subagent, returning the subagent's summary as the tool result.

**Handling Logic**:
```python
for tool_call in response_content.tool_calls:
    f_name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)
    
    if f_name in TOOL_HANDLERS:
        output = TOOL_HANDLERS[f_name](**args)  # task tool calls run_subagent()
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

**task Tool Execution Flow**:
```
1. Main agent calls task tool, passing prompt
2. TOOL_HANDLERS["task"](**args) is called
3. run_subagent(kw["prompt"]) executes
4. Subagent creates independent context
5. Subagent executes loop (max 30 steps)
6. Subagent returns summary
7. Summary returned to main agent as tool_result
8. Main agent receives summary, continues execution
```

**Design Philosophy**:
- **Unified Handling**: All tools uniformly dispatched through `TOOL_HANDLERS` dictionary
- **Transparent Call**: Main agent doesn't know `task` tool internally creates subagent
- **Result Encapsulation**: Subagent's summary returned as normal tool result

---

## Complete Framework Flowchart

```
┌─────────────┐
│    User     │  Input: "Help me create a complete web application with frontend and backend"
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Main Agent │  Analyze task complexity
│ (Receive    │  → Determine as complex multi-step task
│  task)      │
└──────┬──────┘
       │
       │ Planning needed
       ▼
┌─────────────┐
│  todo tool  │  Call: todo(items=[
│ (Create     │    {"id":"1","content":"Create backend API","status":"pending"},
│  plan)      │    {"id":"2","content":"Create frontend page","status":"pending"},
│             │    {"id":"3","content":"Integration testing","status":"pending"}
│             │  ])
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ TodoManager │  Validate and store plan
│  .update()  │  → Return rendered plan
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Main Agent │  Receive plan, start execution
│ (Execution  │  → Update task 1 to in_progress
│  phase)     │
└──────┬──────┘
       │
       │ Delegation needed
       ▼
┌─────────────┐
│  task tool  │  Call: task(prompt="Create backend API using Flask framework...")
│(Create      │
│ Subagent)   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ run_subagent│  Create independent context
│   ()        │  → SUBAGENT_SYSTEM + task prompt
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Subagent   │  Execute loop (max 30 steps)
│  (Execute   │  → Use CHILD_TOOLS
│   task)     │  → bash, write_file, read_file...
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Subagent   │  Complete task, return summary:
│  (Return    │  "Created app.py with following API endpoints...
│   Summary)  │   Ran tests, all tests passed..."
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Main Agent │  Receive summary
│ (Receive    │  → Verify subagent work
│  result)    │  → read_file to check code
│             │  → bash to run tests
└──────┬──────┘
       │
       │ Verification passed
       ▼
┌─────────────┐
│  todo tool  │  Update task 1 to completed
│ (Update     │  Update task 2 to in_progress
│  status)    │
└──────┬──────┘
       │
       │ ... Repeat execution for subsequent tasks ...
       │
       ▼
┌─────────────┐
│   All tasks │  Output final result
│  completed  │
└─────────────┘
```

---

## Design Point Summary

### Context Isolation Principle

**Core Idea**: Subagents have independent message histories, completely separated from the main agent context.

**Isolation Mechanism**:
- Subagent's message history only contains `SUBAGENT_SYSTEM` and current task prompt
- Subagent doesn't know main agent's conversation history
- Subagent's tool results (summary) are returned to main agent, but detailed execution process is not returned

**Design Advantages**:
- **Keep Main Context Clean**: Main agent only sees task delegation and result summaries, avoiding execution detail pollution
- **Reduce Token Consumption**: Subagent's detailed execution process is not counted in main context
- **Task Focus**: Subagent focuses on current task, not disturbed by main context

**Trade-offs**:
- Subagent cannot utilize background information from main context
- Main agent needs other means (e.g., file reading) to verify subagent work

---

### Tool Partitioning Design

**Core Idea**: Based on separation of concerns principle, main agent and subagents use different tool sets.

**Partitioning Logic**:
| Agent Type | Responsibilities | Tool Set |
|----------|------|--------|
| Main Agent | Task planning, coordination, verification | `read_file`, `task`, `todo` |
| Subagent | Specific execution | `bash`, `read_file`, `write_file`, `edit_file`, `load_skill` |

**Design Advantages**:
- **Clear Responsibilities**: Each agent only focuses on its responsibility scope
- **State Protection**: Subagents cannot modify main agent's task plan
- **Capability Minimization**: Reduce misoperation risk

---

### Task Delegation Mechanism

**Core Idea**: Main agent delegates specific tasks to subagents for execution through the `task` tool.

**Delegation Flow**:
1. Main agent determines task delegation is needed
2. Main agent calls `task` tool, passing task description
3. `run_subagent()` creates subagent and executes
4. Subagent completes task, returns summary
5. Main agent receives summary, continues execution

**Design Advantages**:
- **Modular Execution**: Complex tasks can be decomposed into multiple subtasks for parallel or serial execution
- **Separation of Concerns**: Main agent focuses on overall planning, subagent focuses on specific execution
- **Traceability**: Each subtask has clear input and output

---

### Handover Report Specification

**Core Idea**: Subagents must provide structured handover reports after completing tasks for easy main agent verification.

**Report Requirements**:
1. **Files created/modified**: List created or modified files
2. **Key functions implemented**: Describe implemented key functions
3. **Verification output**: Provide verification command output (e.g., test results)

**Example Report**:
```
Task Completion Summary:

1. Files created/modified:
   - app.py (new)
   - requirements.txt (new)
   - tests/test_app.py (new)

2. Key functions implemented:
   - GET /api/time - Returns current time
   - GET /api/status - Returns service status

3. Verification results:
   $ python -m pytest tests/
   === 5 passed in 0.12s ===
```

**Design Advantages**:
- **Standardization**: Unified report format for quick main agent understanding
- **Verifiability**: Includes verification results, main agent can confirm work quality
- **Traceability**: Lists file changes for subsequent review

---

## Overall Design Philosophy Summary

### 1. Context Isolation

Through creating independent subagent contexts, separate execution details from main context:
- Subagent's message history is independent from main agent
- Only summary results are returned to main agent
- Main context remains concise, containing only key decisions and states

**Advantages**: Reduce token consumption, keep main context clear, improve execution efficiency

---

### 2. Separation of Concerns

Main agent and subagents undertake different responsibilities:
- Main agent: Task planning, subtask delegation, work verification
- Subagent: Specific task execution, tool calls, result summary

**Advantages**: Clear responsibility boundaries, reduce agent complexity, improve maintainability

---

### 3. Minimal Tool Access

Each agent only has tools needed to complete its responsibilities:
- Main agent cannot directly execute operations, must go through subagent
- Subagent cannot modify task plan, can only execute and report

**Advantages**: Reduce misoperation risk, protect critical state, reinforce responsibility boundaries

---

### 4. Verification Responsibility

Main agent is responsible for subagent work quality:
- Prohibit blind trust in subagent summaries
- Must verify work results through independent means
- Create fix tasks when issues are found

**Advantages**: Ensure work quality, establish trust mechanism, support error recovery

---

### 5. Standardized Reporting

Subagents must provide structured handover reports:
- File change list
- Key function descriptions
- Verification result output

**Advantages**: Easy for main agent understanding, support quick verification, provide traceable records

---

### 6. Safety Limits

Prevent subagents from falling into infinite loops through step limits:
- Maximum execution steps: 30
- Return warning message when exceeded
- Main agent can decide subsequent operations based on warning

**Advantages**: Prevent resource exhaustion, provide exception handling mechanism, maintain system stability

---

## Relationship with s04

### Comparison Table

| Feature | s04 | s05 |
|------|-----|-----|
| **Architecture** | Single agent | Main agent + Subagent |
| **Context** | Single context | Main context + Independent sub-contexts |
| **Tool Set** | Unified TOOLS | PARENT_TOOLS + CHILD_TOOLS |
| **SYSTEM Prompt** | Single SYSTEM | SYSTEM + SUBAGENT_SYSTEM |
| **Task Execution** | Agent directly executes | Delegate to subagent for execution |
| **todo Management** | Agent directly updates | Main agent updates, subagent has no access |
| **Skill Loading** | Agent directly loads | Subagent loads on demand |
| **Output Format** | Direct output | Formatted printing (print_agent_thought) |

### Inheritance and Extension

**Inherited Content**:
- `TodoManager` class and its complete functionality
- `SkillRegistry` class and its complete functionality
- `LoopState` dataclass
- Basic tool functions (`run_bash`, `run_read`, `run_write`, `run_edit`)
- `execute_tool_calls` core logic
- `agent_loop` and `run_one_turn` execution framework

**Extended Content**:
- `run_subagent()` function (new)
- `print_agent_thought()` function (new)
- Tool partitioning (`PARENT_TOOLS` / `CHILD_TOOLS`)
- `task` tool (new)
- `SUBAGENT_SYSTEM` prompt (new)

---

## Practice Guide

### Test Example (Main Agent Task Division + Subagent Execution)

**Test Command**:
```bash
python v1_task_manager/chapter_05/s05_subagent.py
```

**Test Input**:
```
Help me create a simple Python project with a calculator and corresponding test files
```

**Expected Main Agent Behavior**:
1. Call `todo` tool to create plan:
```json
{
  "items": [
    {"id": "1", "content": "Create project structure", "status": "pending"},
    {"id": "2", "content": "Implement calculator functionality", "status": "pending"},
    {"id": "3", "content": "Write test cases", "status": "pending"},
    {"id": "4", "content": "Run tests for verification", "status": "pending"}
  ]
}
```

2. Call `task` tool to delegate first subtask:
```json
{
  "prompt": "Create project directory calculator_project with following structure:\n- calculator_project/__init__.py\n- calculator_project/calculator.py\n\nImplement a Calculator class in calculator.py with add, subtract, multiply, divide four methods."
}
```

3. Subagent executes and returns summary:
```
Task Completion Summary:

1. Files created/modified:
   - calculator_project/__init__.py (new)
   - calculator_project/calculator.py (new)

2. Key functions implemented:
   - Calculator class
   - add(a, b) - Addition
   - subtract(a, b) - Subtraction
   - multiply(a, b) - Multiplication
   - divide(a, b) - Division

3. Verification results:
   $ python -c "from calculator_project.calculator import Calculator; c = Calculator(); print(c.add(1, 2))"
   3
```

4. Main agent verifies subagent work:
```bash
read_file: calculator_project/calculator.py
bash: python -c "from calculator_project.calculator import Calculator; c = Calculator(); print(c.add(1, 2))"
```

5. Update todo after verification passes:
```json
{
  "items": [
    {"id": "1", "content": "Create project structure", "status": "completed"},
    {"id": "2", "content": "Implement calculator functionality", "status": "in_progress"},
    {"id": "3", "content": "Write test cases", "status": "pending"},
    {"id": "4", "content": "Run tests for verification", "status": "pending"}
  ]
}
```

6. Continue delegating subsequent subtasks until all tasks complete

---

### task Tool Usage Examples

**Delegate Exploratory Task**:
```json
{
  "prompt": "Analyze the project structure in the current directory, find all Python files, and report the main function of each file."
}
```

**Delegate Execution Task**:
```json
{
  "prompt": "Create a requirements.txt file in the project root directory containing following dependencies:\n- flask>=2.0.0\n- pytest>=7.0.0\n\nThen run pip install -r requirements.txt to install dependencies."
}
```

**Delegate Fix Task**:
```json
{
  "prompt": "Fix the divide method in calculator.py to raise ValueError exception when divisor is 0, instead of returning None. Run tests to verify after fix."
}
```

---

## Summary

### Core Design Philosophy

s05 introduces a **Subagent System** with the following design principles to achieve context isolation and task delegation:

1. **Context Isolation**
   Subagents have independent message histories, execution details don't pollute main context, only summary results are returned to main agent.

2. **Separation of Concerns**
   Main agent is responsible for task planning and coordination, subagent is responsible for specific execution, both communicate through `task` tool.

3. **Tool Partitioning**
   Main agent and subagents use different tool sets, main agent cannot directly execute operations, subagent cannot modify task plans.

4. **Verification Responsibility**
   Main agent must verify subagent work results, cannot blindly trust subagent summary reports.

5. **Standardized Reporting**
   Subagents must provide structured handover reports after completing tasks, including file changes, function descriptions, and verification results.

6. **Safety Limits**
   Subagent execution has a 30-step upper limit to prevent infinite loops, returns warning message when exceeded.

### Relationship with s04

| Feature | s04 | s05 |
|------|-----|-----|
| **Architecture** | Single agent executes all tasks | Main agent planning + Subagent execution |
| **Context Management** | Single context accumulates all history | Main context + Independent sub-contexts |
| **Tool Usage** | Unified tool set | Tool partitioning, responsibility separation |
| **Task Execution** | Agent directly calls tools | Delegate to subagent via task tool |

s05 builds upon s04's task planning foundation, further solving the **context bloat** and **execution detail pollution** problems. Through the subagent system, execution details are isolated in independent contexts, maintaining the cleanliness and efficiency of the main agent context.

---

*Document Version: v1.0*
*Based on Code: v1_task_manager/chapter_05/s05_subagent.py*
