# s04: Todo Write (Task Management) - Code Documentation

---

## Overview

### Core Improvements

**From Single-Step Execution to Multi-Step Task Planning**

s04 introduces a **Todo Task Management System** built on top of s03, enabling the model to plan and manage complex multi-step tasks. This addresses the limitation that single tool calls cannot complete complex requirements.

### Design Philosophy

> **"Plan complex tasks, track progress, and maintain state across turns."**

The core design philosophy of s04: **Task Decomposition + State Tracking**. Implemented through the following mechanisms:

- **Task Decomposition**: The model uses the `todo` tool to decompose complex requirements into an ordered list of steps
- **State Tracking**: Each task item has a clear state (pending/in_progress/completed)
- **Regular Reminders**: The system periodically reminds the model to update the plan, maintaining plan timeliness
- **Single in_progress Constraint**: At most one task item can be in progress at a time, ensuring focused attention

### Code File Path

```
v1_task_manager/chapter_4/s04_todo_write.py
```

### Core Architecture Diagram (Comparison with s03)

**s03 Architecture (Single-Step Execution)**:
```
    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch    |
    |  prompt  |      |       |      | {bash, read,     |
    +----------|      +---+---+      |  write, edit,    |
                          ^          |  load_skill}     |
                          |          +------------------+
                          +-----------------+
                               tool_result
```

**s04 Architecture (Task Planning + Execution)**:
```
    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Check if planning|
    |  prompt  |      |       |      | is needed        |
    +----------+      +---+---+      +--------+---------+
                          ^                   |
                          |                   | Planning needed
                          |            +------v------+
                    +-----+-----+      |   todo      |
                    |  Reminder | <----|   Tool      |
                    |  (Periodic)|     +------+------+
                    +-----+-----+             |
                          |                   | Create/Update plan
                          |            +------v------+
                          |            | TodoManager |
                          |            |  state.items|
                          |            +------+------+
                          |                   |
                          +-------------------+
                          | No planning needed/Planning complete
                          v
                    +------------------+
                    | Tool Dispatch    |
                    | {bash, read,     |
                    |  write, edit,    |
                    |  load_skill,     |
                    |  todo}           |
                    +------------------+
```

**Architecture Description**:
1. System creates a `TodoManager` instance at initialization to manage task plan state
2. LLM receives user task and determines if multi-step planning is needed
3. If planning is needed, call the `todo` tool to create a task list
4. `TodoManager` validates and stores the plan, resets the reminder counter
5. Each turn without using `todo`, the reminder counter increments
6. When threshold (3 turns) is reached, system inserts a reminder message to prompt plan update
7. Model executes tasks step by step based on the plan, updating task states

---

## Comparison with s03

### Change Overview

| Component | s03 | s04 | Change Description |
|------|-----|-----|----------|
| **Import Modules** | Standard library + `re` | + `time` | Added time module (imported but unused in code) |
| **Data Structures** | `SkillLoader` class | + `PlanItem`, `PlanningState` | Added task item and plan state dataclasses |
| **Task Management** | None | `TodoManager` class | Added task manager to maintain plan state |
| **Tool Set** | 5 tools | 6 tools | Added `todo` tool |
| **execute_tool_calls** | Returns `list[dict]` | Returns `tuple[list[dict], str\|None]` | Added reminder return value |
| **run_one_turn** | Simple tool_result append | Handles reminder system messages | Supports inserting reminder messages |
| **SYSTEM Prompt** | Tool usage guidance | + 4 task planning principles | Added todo usage guidance |

### New Component Architecture

```
    PlanItem Dataclass
    ├── id: str           # Unique task identifier
    ├── content: str      # Task content description
    ├── status: str       # "pending" | "in_progress" | "completed"
    └── active_form: str  # Progressive tense description (optional)

    PlanningState Dataclass
    ├── items: list[PlanItem]          # List of task items
    └── rounds_since_update: int       # Number of turns without plan update

    TodoManager Class
    ├── state: PlanningState           # Plan state
    ├── update(items)                  # Create/update plan
    ├── note_round_without_update()    # Record turns without update
    ├── reminder()                     # Check if reminder is needed
    └── render()                       # Render plan for display

    Global Instance
    └── TODO = TodoManager()           # Singleton task manager
```

---

## Detailed Explanation by Execution Order

### Phase 1: Task Data Structure Definition

#### PlanItem Dataclass

**Mechanism Overview**:
`PlanItem` is the basic unit of a task plan, representing a single step in a multi-step task. Each task item contains a unique identifier, content description, execution status, and an optional progressive tense description.

```python
@dataclass
class PlanItem: 
    id: str                     # Task id marker for identification
    content: str                # What this step should do
    status: str = "pending"     # "pending" | "in_progress" | "completed"
    active_form: str = ""       # More natural progressive description when in progress
```

**Field Description**:
- `id`: String-type unique identifier, used to reference specific task items in tool calls
- `content`: Specific content description of the task step, e.g., "Create project directory"
- `status`: Task state, three-state enumeration:
  - `"pending"`: Not yet started
  - `"in_progress"`: Currently executing
  - `"completed"`: Completed
- `active_form`: Optional field, provides natural language description in progressive tense, e.g., "Creating directory"

**State Transition**:
```
pending ──────> in_progress ──────> completed
   ^                                    |
   └────────────────────────────────────┘
              (Reset/Rework)
```

**Design Philosophy**:
- **Explicit State Management**: Explicitly track execution progress of each step through status field
- **Identifier Separation**: id separated from content, facilitating tool calls and state updates
- **Human-Friendly Description**: active_form provides more natural progress display, enhancing user experience
- **Default Value Design**: status defaults to "pending", active_form defaults to empty, simplifying creation

---

#### PlanningState Dataclass

**Mechanism Overview**:
`PlanningState` is the container for task plans, storing all task item lists and reminder counters. It is the internal state of `TodoManager`, not directly exposed externally.

```python
@dataclass
class PlanningState:
    items: list[PlanItem] = field(default_factory=list)
    rounds_since_update: int = 0  # How many consecutive turns have passed without model updating the plan
```

**Field Description**:
- `items`: List of PlanItem, stores all task steps in execution order
- `rounds_since_update`: Number of dialogue turns since last plan update, used for reminder mechanism

**Design Philosophy**:
- **State Encapsulation**: Centralize management of all plan-related state
- **Reminder Counting**: Implement periodic reminders through rounds_since_update to prevent plan obsolescence
- **Default Factory**: Use `field(default_factory=list)` to avoid pitfalls of mutable default arguments

---

### Phase 3: TodoManager Class Details

#### Class Structure and Initialization

**Mechanism Overview**:
`TodoManager` is the core class of the task management system, responsible for maintaining plan state, validating updates, tracking turns, and generating reminders. It uses the singleton pattern, with only one instance globally.

```python
class TodoManager:
    def __init__(self):
        self.state = PlanningState()
```

**Global Instance**:
```python
TODO = TodoManager()  # Global singleton
```

**Design Philosophy**:
- **Singleton Pattern**: Ensure only one plan state exists throughout the session, avoiding state inconsistency
- **State Isolation**: Each running script has an independent TODO instance, no interference in multi-user scenarios

---

#### update() Method

**Mechanism Overview**:
`update()` is the handler function for the `todo` tool, receiving the task list sent by the model, validating it, and updating the plan state. Validation includes: quantity limits, field completeness, state legality, and single in_progress constraint.

```python
def update(self, items: list) -> str:
    if len(items) > 20:
        return f"Error: Too many plan items ({len(items)}). Maximum allowed is 20. Please reduce the number of steps."
    
    normalized = []
    in_progress_count = 0
    for index, raw_item in enumerate(items):
        id = str(raw_item.get("id", "")).strip()
        content = str(raw_item.get("content", "")).strip()
        status = str(raw_item.get("status", "pending")).lower()
        active_form = str(raw_item.get("activeForm", "")).strip()
        
        if not id:
            return f"Error: Item {id} missing 'id' field."
        if not content:
            return f"Error: Item {index} missing 'content' field."
        if status not in {"pending", "in_progress", "completed"}:
            return f"Error: Item {index} has invalid status '{status}'. status should be in pending, in_progress, completed"
        
        if status == "in_progress":
            in_progress_count += 1
        
        normalized.append(PlanItem(
            id=id,
            content=content,
            status=status,
            active_form=active_form,
        ))
    
    if in_progress_count > 1:
        return "Error: Only one plan item can be in_progress at a time."
    
    self.state.items = normalized
    self.state.rounds_since_update = 0
    return self.render()
```

**Validation Logic**:
1. **Quantity Limit**: Maximum 20 task items to prevent overly complex plans
2. **Field Validation**: Check that `id` and `content` fields exist and are non-empty
3. **State Validation**: status must be one of three valid values
4. **Single in_progress**: At most one task item can be in progress at a time

**Return Value**:
- Success: Returns rendered plan text
- Failure: Returns error message string

**Design Philosophy**:
- **Defensive Programming**: Strictly validate when receiving external input
- **Error-Friendly**: Return clear error messages to guide model correction
- **State Reset**: Reset reminder counter after successful update
- **camelCase Compatibility**: Accept `activeForm` (JSON style) instead of `active_form`

---

#### note_round_without_update() Method

**Mechanism Overview**:
In each dialogue turn, if the model does not call the `todo` tool, this method is called to increment the reminder counter. Used to track plan freshness.

```python
def note_round_without_update(self) -> None:
    self.state.rounds_since_update += 1
```

**Design Philosophy**:
- **Implicit Tracking**: System automatically tracks without requiring model to explicitly report progress
- **Simple Counting**: Use integer counter, avoiding complex time calculations

---

#### reminder() Method

**Mechanism Overview**:
Check if the model needs to be reminded to update the plan. When a plan exists and has not been updated for a set number of turns, return a reminder message; otherwise return None.

```python
PLAN_REMINDER_INTERVAL = 3  # Global constant

def reminder(self) -> str | None:
    if not self.state.items:
        return None
    if self.state.rounds_since_update < PLAN_REMINDER_INTERVAL:
        return None
    return "<reminder>Refresh your current plan before continuing.</reminder>"
```

**Trigger Conditions**:
1. Plan list is non-empty (task planning already exists)
2. Consecutive turns without update >= 3 (PLAN_REMINDER_INTERVAL)

**Return Value**:
- Reminder needed: Returns XML-formatted reminder message
- No reminder needed: Returns None

**Design Philosophy**:
- **Periodic Synchronization**: Prevent model from not updating plan for a long time, causing plan to diverge from actual progress
- **Gentle Reminder**: Use XML tags for easy system identification and processing
- **Adjustable Threshold**: Control reminder frequency through global constant

---

#### render() Method

**Mechanism Overview**:
Render the current plan into human-readable text format, used for returning to the model and displaying to users. Use symbols to mark task items in different states and show completion progress.

```python
def render(self) -> str:
    if not self.state.items:
        return "No session plan yet."
    
    lines = []
    for item in self.state.items:
        marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]",}[item.status]
        line = f"{marker} {item.content}"
        if item.status == "in_progress" and item.active_form:
            line += f" ({item.active_form})"
        lines.append(line)
    
    completed = sum(1 for item in self.state.items if item.status == "completed")
    lines.append(f"\n({completed}/{len(self.state.items)} completed)")
    return "\n".join(lines)
```

**Output Example**:
```
[ ] Create project directory
[>] Write main program code (Implementing core functionality)
[ ] Write test cases
[x] Install dependencies

(1/4 completed)
```

**Symbol Description**:
- `[ ]`: pending, not yet started
- `[>]`: in_progress, currently in progress
- `[x]`: completed, completed

**Design Philosophy**:
- **Visual Distinction**: Use different symbols to intuitively display task status
- **Progress Summary**: Display completion progress at bottom, providing overall overview
- **Optional Details**: active_form only displays in in_progress state, avoiding redundancy

---

### Phase 4: New Tool - todo

#### Tool Function Description

**Mechanism Overview**:
The `todo` tool allows the model to create or rewrite the task plan for the current session. It receives a list of task items, each containing id, content, status, and optional activeForm. The tool calls `TodoManager.update()` for validation and storage.

**Usage Scenarios**:
1. When receiving complex multi-step tasks, plan first before execution
2. During task execution, adjust plan based on actual situation
3. When receiving system reminder, refresh plan status

**Tool Handler Function**:
```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_REGISTRY.load_full_text(kw["name"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),  # Added
}
```

---

#### JSON Schema Definition

**Mechanism Overview**:
The parameter definition for the `todo` tool uses JSON Schema format, describing the parameter structure the model should provide when calling the tool.

```python
{"type": "function", "function": {
    "name": "todo",
    "description": "Create or Rewrite the current session plan for multi-step work.",
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "content": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        "activeForm": {
                            "type": "string",
                            "description": "Optional present-continuous label.",
                        },
                    },
                    "required": ["id", "content", "status"]
                }
            }
        },
        "required": ["items"]
    }
}}
```

**Parameter Description**:
- `items` (required): Array of task items
  - `id` (required): Unique task identifier
  - `content` (required): Task content description
  - `status` (required): Task state, enum value
  - `activeForm` (optional): Progressive tense description

**Design Philosophy**:
- **Explicit Constraints**: Use `enum` to limit valid values for status
- **Required Fields**: Only require id, content, status, lowering usage threshold
- **Clear Description**: Tool description explains usage scenario (multi-step work)

---

### Phase 5: execute_tool_calls Optimization

#### used_todo Flag

**Mechanism Overview**:
The `execute_tool_calls` function adds a `used_todo` flag to track whether the model called the `todo` tool in the current dialogue turn. This flag determines whether to reset the reminder counter or increment it.

```python
def execute_tool_calls(response_content) -> tuple[list[dict], str | None]:
    used_todo = False
    results = []
    
    for tool_call in response_content.tool_calls:
        f_name = tool_call.function.name
        # ... Execute tool call ...
        
        if f_name == "todo":
            used_todo = True
    
    if used_todo:
        reminder = None
    else:
        TODO.note_round_without_update()
        reminder = TODO.reminder()
    
    return results, reminder
```

**Design Philosophy**:
- **Explicit Tracking**: Record todo usage through boolean flag
- **Automatic Update**: When `todo` is called, `update()` method has already reset the counter, no additional operation needed
- **Implicit Increment**: When todo is not called, automatically increment counter and check for reminder

---

#### reminder Return Mechanism

**Mechanism Overview**:
The return value of `execute_tool_calls` function changes from `list[dict]` to `tuple[list[dict], str|None]`, adding a second return value for passing reminder messages.

**s03 Return Value**:
```python
def execute_tool_calls(response_content) -> list[dict]:
    # ...
    return results
```

**s04 Return Value**:
```python
def execute_tool_calls(response_content) -> tuple[list[dict], str | None]:
    # ...
    return results, reminder
```

**Design Philosophy**:
- **Minimal Intrusion**: Pass reminder through return value, avoiding modification of global state
- **Type Safety**: Use `str | None` to explicitly indicate reminder may or may not exist

---

### Phase 6: run_one_turn Changes

#### reminder Message Handling

**Mechanism Overview**:
The `run_one_turn` function receives the reminder returned by `execute_tool_calls`, and if it exists, inserts it as a system message into the message history.

```python
def run_one_turn(state: LoopState) -> bool:
    # ... Call LLM ...
    
    if response_messages.tool_calls:
        results, reminder = execute_tool_calls(response_messages)  # Receive reminder
        
        if not results:
            state.transition_reason = None
            return False
        
        if reminder:
            state.messages.append({
                "role": "system",
                "content": reminder,
            })
        
        for tool_result in results:
            state.messages.append(tool_result)
        
        state.turn_count += 1
        state.transition_reason = "tool_result"
        return True
    # ...
```

**System Message Insertion**:
```python
state.messages.append({
    "role": "system",
    "content": "<reminder>Refresh your current plan before continuing.</reminder>",
})
```

**Design Philosophy**:
- **System-Level Reminder**: Use system role to emphasize importance of reminder
- **Non-Blocking**: Continue processing tool_result after inserting reminder message, not affecting normal flow
- **XML Format**: Wrap with XML tags for easy model identification and parsing

---

### Phase 7: SYSTEM Prompt Changes

#### s03 vs s04 Comparison

**s03 SYSTEM Prompt**:
```python
SYSTEM = f"""You are a coding agent at {WORKDIR}.
1. Use the tool to finish tasks. Act first, then report clearly.
2. Use load_skill when a task needs specialized instructions before you act.
Skills available:
{SKILL_REGISTRY.describe_available()}"""
```

**s04 SYSTEM Prompt**:
```python
SYSTEM = f"""You are a coding agent at {WORKDIR}.
1.Use the todo tool to plan complex and multi-step tasks. Mark in_progress before starting, completed when done. Keep exactly one step in_progress when a task has multiple steps.
2.Use tools to solve tasks. Act, after executing the command, tell me that it has been completed.
3.Refresh the plan as work advances. Prefer tools over prose.
4.Use load_skill when a task needs specialized instructions before you act. Skills available: {SKILL_REGISTRY.describe_available()}"""
```

#### 4 Guiding Principles Description

**Principle 1: Task Planning**
```
Use the todo tool to plan complex and multi-step tasks. 
Mark in_progress before starting, completed when done. 
Keep exactly one step in_progress when a task has multiple steps.
```
- Clear usage scenario: complex and multi-step tasks
- State marking requirement: mark in_progress before starting, completed when done
- Single focus constraint: keep exactly one step in_progress

**Principle 2: Tool Priority**
```
Use tools to solve tasks. Act, after executing the command, tell me that it has been completed.
```
- Action first: execute first then report
- Clear feedback: inform user after execution completes

**Principle 3: Plan Update**
```
Refresh the plan as work advances. Prefer tools over prose.
```
- Dynamic update: refresh plan as work progresses
- Tool priority: use tools instead of pure text description

**Principle 4: Skill Loading** (Inherited from s03)
```
Use load_skill when a task needs specialized instructions before you act.
```
- Load on demand: load skills first when domain knowledge is needed

**Design Philosophy**:
- **Progressive Guidance**: From planning to execution to update, covering complete workflow
- **Explicit Constraints**: Provide specific executable guidance, not abstract suggestions
- **Inheritance and Extension**: Retain s03's skill loading guidance, add task planning guidance

---

## Complete Framework Flowchart

```
┌─────────────┐
│    User     │  Input: "Help me create a webpage that displays the current time in real-time, put it in time_page directory"
└──────┬──────┘
       │
       ▼
┌─────────────┐
│     LLM     │  Analyze task complexity
│  (Receive   │  → Determine as multi-step task
│   Task)     │
└──────┬──────┘
       │
       │ Planning needed
       ▼
┌─────────────┐
│  todo Tool  │  Call: todo(items=[
│  (Create    │    {"id":"1","content":"Create directory","status":"pending"},
│   Plan)     │    {"id":"2","content":"Write HTML","status":"pending"},
│             │    {"id":"3","content":"Write JS","status":"pending"},
│             │    {"id":"4","content":"Test","status":"pending"}
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
│     LLM     │  Receive plan, start execution
│  (Execution │  → Update task 1 to in_progress
│   Phase)    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  bash Tool  │  Execute: mkdir -p time_page
└──────┬──────┘
       │
       ▼
┌─────────────┐
│     LLM     │  Update task 1 to completed
│  (Update    │  Update task 2 to in_progress
│   State)    │
└──────┬──────┘
       │
       │ ... Repeat execution ...
       │
       ▼
┌─────────────┐
│  Reminder   │  Trigger when 3 turns without plan update
│  (Periodic  │  → "<reminder>Refresh your plan...</reminder>"
│   Reminder) │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│     LLM     │  Receive reminder, refresh plan status
│  (Respond   │
│  to Reminder)│
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   All       │  Output final result
│   Tasks     │
│  Completed  │
└─────────────┘
```

---

## Design Point Summary

### Task Decomposition Principles

**Core Idea**: Decompose complex tasks into small independently executable steps.

**Decomposition Criteria**:
- **Atomicity**: Each step should be small enough to complete with a single tool call
- **Sequentiality**: Clear dependency relationships between steps
- **Verifiability**: Clear verification criteria after each step completes
- **Quantity Control**: No more than 20 steps to avoid excessive complexity

**Example**:
```
❌ Overly coarse:
  1. Create webpage

✅ Reasonable decomposition:
  1. Create project directory
  2. Create HTML file
  3. Create CSS file
  4. Create JavaScript file
  5. Test webpage functionality
```

---

### State Tracking Mechanism

**Core Idea**: Track task progress through explicit state markers.

**State Definition**:
```
pending     → Not yet started, waiting for execution
in_progress → Currently executing, current focus
completed   → Completed, verifiable
```

**State Transition Rules**:
1. Newly created tasks default to pending
2. Before starting execution, must mark task as in_progress
3. After execution completes, immediately mark as completed
4. At most one task can be in_progress at a time

**Design Advantages**:
- **Visible Progress**: Both user and model can clearly understand current progress
- **Focus Management**: Single in_progress constraint avoids confusion from multi-task parallelism
- **Error Recovery**: Failed tasks can be re-marked as pending or in_progress

---

### Periodic Reminder Design

**Core Idea**: Prevent plan from diverging from actual progress, enforce periodic synchronization.

**Trigger Condition**:
```python
PLAN_REMINDER_INTERVAL = 3  # Remind after 3 turns without update

if rounds_since_update >= 3 and items non-empty:
    Trigger reminder
```

**Reminder Content**:
```xml
<reminder>Refresh your current plan before continuing.</reminder>
```

**Design Advantages**:
- **Prevent Forgetting**: Avoid model forgetting to update plan, causing plan obsolescence
- **Rhythm Control**: Force model to periodically review overall progress
- **Gentle Intervention**: Use reminder instead of enforcement, preserving model flexibility

**Potential Issues**:
- Fixed threshold may not suit all scenarios
- Simple counting does not consider task complexity
- May interrupt model's execution flow

---

### Single in_progress Constraint

**Core Idea**: At most one task item can be in progress at a time.

**Validation Logic**:
```python
in_progress_count = 0
for item in items:
    if item.status == "in_progress":
        in_progress_count += 1

if in_progress_count > 1:
    return "Error: Only one plan item can be in_progress at a time."
```

**Design Rationale**:
1. **Focused Attention**: Avoid model handling multiple tasks simultaneously, reducing error probability
2. **Sequential Execution**: Ensure tasks execute in dependency order
3. **Simplified Tracking**: Clearly identify which task should be executed currently, reducing ambiguity
4. **Clear Progress**: Users can clearly know what is currently being done

**Exception Cases**:
- Current design does not support parallel tasks
- If parallelism is needed, should design a subtask system

---

## Overall Design Philosophy Summary

### 1. Explicit Task Management

Make implicit execution plans explicit as data structures:
- Task item list explicitly stores each step
- Status fields track execution progress
- Both model and users can see the complete plan

**Advantages**: Auditable, traceable, adjustable

---

### 2. State-Driven Execution

Drive task progression through state changes:
```
pending → in_progress → completed
```

**Advantages**:
- Clear progress metrics
- Easy error recovery
- Support for resumption from breakpoints

---

### 3. Constraint-Guided Behavior

Guide model behavior through system constraints:
- Single in_progress constraint → Enforce sequential execution
- Reminder mechanism → Enforce periodic synchronization
- Quantity limit → Prevent excessive complexity

**Advantages**: Reduce errors caused by excessive model freedom

---

### 4. Feedback Loop

Establish complete feedback cycle:
```
Plan → Execute → Update → Remind → Replan
```

**Advantages**:
- Timely detection of deviation between plan and reality
- Support for dynamic adjustment
- Maintain plan timeliness

---

### 5. Minimal Intrusion Design

Minimize changes on top of s03:
- Add independent module (TodoManager)
- Extend existing functions (execute_tool_calls return value)
- Retain original tools and workflow

**Advantages**:
- Lower understanding cost
- Easy rollback and debugging
- Support for incremental improvement

---

### 6. Human-AI Collaboration Optimization

Design considers human user readability:
- render() outputs human-readable plans
- Progress summary (1/4 completed)
- Clear error messages

**Advantages**: Users can understand and trust AI's execution process

---

## Practical Guide

### Test Example (Multi-Step Task)

**Test Command**:
```bash
python v1_task_manager/chapter_4/s04_todo_write.py
```

**Test Input**:
```
Help me create a webpage that displays the current time in real-time, put it in the time_page directory under the current directory
```

**Expected Model Behavior**:
1. Call `todo` tool to create plan:
```json
{
  "items": [
    {"id": "1", "content": "Create time_page directory", "status": "pending"},
    {"id": "2", "content": "Create index.html file", "status": "pending"},
    {"id": "3", "content": "Add JavaScript time display functionality", "status": "pending"},
    {"id": "4", "content": "Test webpage functionality", "status": "pending"}
  ]
}
```

2. After receiving plan, execute step by step:
   - Update task 1 to in_progress → bash: `mkdir -p time_page` → Update to completed
   - Update task 2 to in_progress → write_file: `time_page/index.html` → Update to completed
   - ...

---

### todo Tool Usage Example

**Create Initial Plan**:
```json
{
  "items": [
    {
      "id": "step_1",
      "content": "Analyze project structure",
      "status": "in_progress",
      "activeForm": "Analyzing project structure"
    },
    {
      "id": "step_2",
      "content": "Write code",
      "status": "pending"
    },
    {
      "id": "step_3",
      "content": "Run tests",
      "status": "pending"
    }
  ]
}
```

---

## Summary

### Core Design Philosophy

s04 introduces a **Todo Task Management System**, implementing planning and management of multi-step tasks through the following design principles:

1. **Explicit Task Management**
   Make implicit execution plans explicit as data structures, storing each step through PlanItem list, tracking execution progress with status fields.

2. **State-Driven Execution**
   Drive task progression through state transition `pending → in_progress → completed`, providing clear progress metrics.

3. **Constraint-Guided Behavior**
   Single in_progress constraint enforces sequential execution, periodic reminder mechanism enforces periodic synchronization to prevent plan obsolescence.

4. **Minimal Intrusion Design**
   Minimize changes on top of s03, add independent module TodoManager, retain original tools and workflow.

### Relationship with s03

| Feature | s03 | s04 |
|------|-----|-----|
| **Knowledge Management** | Skill system (load domain knowledge on demand) | Inherited from s03 |
| **Task Management** | None | Todo system (plan multi-step tasks) |
| **Tool Count** | 5 | 6 (+todo) |
| **SYSTEM Prompt** | Skill list | Skill list + task planning guidance |

s04 builds on s03's dynamic knowledge extension, further addressing the **complex task execution management** problem, forming a complete knowledge + task dual-drive architecture.

---

*Document Version: v1.0*
*Based on Code: v1_task_manager/chapter_4/s04_todo_write.py*
