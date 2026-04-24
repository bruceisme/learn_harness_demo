# v1_task_manager Core Framework Changes Analysis

**Document Version**: v2 
**Generated Time**: 2026-04-22 
**Project Path**: `learn_harness_demo/`

---

## Table of Contents

- [Chapter 1: Basic Agent Loop](#chapter-1-basic-agent-loop)
- [Chapter 2: Tool System Extension](#chapter-2-tool-system-extension)
- [Chapter 3: Skill System Introduction](#chapter-3-skill-system-introduction)
- [Chapter 4: Task Management System](#chapter-4-task-management-system)
- [Chapter 5: Sub-agent System](#chapter-5-sub-agent-system)
- [Chapter 6: Context Management](#chapter-6-context-management)
- [Chapter 7: Permission System](#chapter-7-permission-system)
- [Chapter 8: Hook System](#chapter-8-hook-system)
- [Chapter 9: Memory System](#chapter-9-memory-system)
- [Chapter 10: Build System](#chapter-10-build-system)
- [Chapter 11: Resume System](#chapter-11-resume-system)
- [Chapter 12: Task System Enhancement](#chapter-12-task-system-enhancement)
- [Chapter 13: v2 Background Tasks](#chapter-13-v2-background-tasks)
- [Chapter 14: Cron Scheduler](#chapter-14-cron-scheduler)
- [Chapter 18_2: Worktree Isolation](#chapter-18_2-worktree-isolation)
- [Chapter 19_2: MCP Plugin](#chapter-19_2-mcp-plugin)

---

## Chapter 1: Basic Agent Loop

**File Path**: `code/v1_task_manager/chapter_01/s01_agent_loop.py` 
**Full Analysis**: [../zh/chapter_01/s01_agent_loop_文档.md](../zh/chapter_01/s01_agent_loop_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `LoopState` | dataclass | Stores conversation history and round count, manages messages list and turn_count |
| `TOOLS` | list | Tool definition list, only includes bash tool in OpenAI function calling format definition |
| `run_one_turn()` | function | Single LLM call + tool execute, returns whether to continue loop |
| `agent_loop()` | function | Main loop entry, continues execution until model no longer calls tool |
| `execute_tool_calls()` | function | Parses LLM return tool_calls and executes corresponding tool |
| `run_bash()` | function | Bash tool implementation, executes shell command and returns output |

### Function Change Details

1. **Basic Agent Loop Structure**
 - Adopts `while run_one_turn(state): pass` concise loop pattern
 - LoopState manages messages list and turn_count counter
 - Each loop: LLM call → Parse tool_calls → Execute tool → Inject result → Next round

2. **Single Tool Support**
 - Only implements bash tool, used for executing shell commands
 - Tool definition adopts OpenAI function calling format
 - Parameters including `command` (required) string

3. **Simple Security Filter**
 - Dangerous command check: `rm -rf /`, `sudo`, `shutdown`, `reboot` etc.
 - Timeout protection: 120 seconds execution timeout limitation
 - Returns error information to model rather than directly throwing exception

4. **Interactive Entry**
 - `if __name__ == "__main__"` provides REPL-style interaction
 - Supports q/exit to exit and empty input to exit
 - Supports multi-round conversation, continues running until user exits or model completes

5. **Model Connection Configuration**
 - Uses OpenAI compatible API interface
 - Supports thinking model (enable_thinking=True)
 - Automatically gets available model list

```python
@dataclass
class LoopState:
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None

def run_one_turn(state: LoopState) -> bool:
    response = client.chat.completions.create(            
        model=MODEL, tools=TOOLS, messages=state.messages,
        max_tokens=8000, temperature=1,
        extra_body={"top_k": 20, "chat_template_kwargs": {"enable_thinking": True}}
    )
    response_messages = response.choices[0].message
    state.messages.append(response_messages)
    
    if response_messages.tool_calls:
        results = execute_tool_calls(response_messages)
        for tool_result in results:
            state.messages.append(tool_result)
        state.turn_count += 1
        return True
    return False
```

### Data Structure Example

```python
# LoopState instance
LoopState(
    messages=[
        {"role": "user", "content": "List files in current directory"},
        {"role": "assistant", "content": None, "tool_calls": [...]},
        {"role": "tool", "content": "file1.txt\nfile2.py", "tool_call_id": "..."}
    ],
    turn_count=2,
    transition_reason=None
)

# TOOLS definition
TOOLS = [{
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a bash command and return the output",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to execute"}
            },
            "required": ["command"]
        }
    }
}]
```

### Comparison with Previous Chapter

This chapter is the initial version, no comparison chapter.

### Architecture Diagram

```
┌──────────┐      ┌───────┐      ┌─────────┐
│   User   │ ───> │  LLM  │ ───> │  Tool   │
│  prompt  │      │       │      │ execute │
└──────────┘      └───┬───┘      └────┬────┘
                      ↑               │
                      │   tool_result │
                      └───────────────┘
                    (loop continues)
```

### Execution Process

```
1. User input → Add to messages
2. Call LLM → Get response (may contain tool_calls)
3. If tool_calls exist:
   a. Parse each tool_call
   b. Execute corresponding tool function
   c. Collect tool output
   d. Add tool_result to messages
4. Repeat steps 2-3 until LLM no longer calls tools
5. Return final response to user
```

### Chapter Summary

Chapter 1 establishes the most basic agent loop framework, including single bash tool support and simple security filter. Loop structure adopts the classic "LLM decision → Tool execution → Result feedback" mode, laying the foundation for subsequent chapter extensions. Core design remains concise for easy understanding and future extension.

---

## Chapter 2: Tool System Extension

**File Path**: `code/v1_task_manager/chapter_02/s02_tool_use.py` 
**Full Analysis**: [../zh/chapter_02/s02_tool_use_文档.md](../zh/chapter_02/s02_tool_use_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `TOOL_HANDLERS` | dict | Tool name to process function mapping, supports dynamic extension |
| `safe_path()` | function | Path security check, prevents directory traversal attack |
| `run_read()` | function | read_file tool implementation, reads file content |
| `run_write()` | function | write_file tool implementation, writes file content |
| `run_edit()` | function | edit_file tool implementation, replaces text in file |
| `execute_tool_calls()` | function | Tool call dispatch and execution, supports error handling |

### Function Change Details

1. **Tool Quantity Extension**
 - Added `read_file`: reads file content, supports limit parameter for line limitation
 - Added `write_file`: writes file content, overwrites existing content
 - Added `edit_file`: edits file, replaces specified old_text with new_text
 - Tool count extended from 1 to 4

2. **Tool Dispatch Mechanism**
 - Introduces `TOOL_HANDLERS` dictionary for tool routing
 - Supports dynamically extending new tools without modifying main loop
 - Unknown tools return error information to model

3. **Path Security Protection**
 - `safe_path()` uses `is_relative_to()` to check if path is within working directory
 - Prevents directory traversal attacks (such as `../../etc/passwd`)
 - All file operation tools must pass this check

4. **JSON Parse Error Handling**
 - Returns error information to model when tool parameter parse fails
 - Uses `continue` to skip failed tool call
 - Model can correct parameters and call again based on error information

5. **Output Length Limitation**
 - Tool output uniformly limited to 50000 characters
 - Prevents overly long output from occupying context
 - Excess part is truncated with hint to model

```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}

def safe_path(p: str) -> Path:
    """Ensure path is within workspace. Prevent directory traversal."""
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_read(path: str, limit: int = None) -> str:
    safe_p = safe_path(path)
    content = safe_p.read_text()
    if limit:
        lines = content.splitlines()[:limit]
        content = "\n".join(lines)
    return content
```

### Tool Parameter Definition

```python
# read_file tool definition
{
    "name": "read_file",
    "parameters": {
        "properties": {
            "path": {"description": "Path to file", "type": "string"},
            "limit": {"description": "Max lines to read", "type": "integer"}
        },
        "required": ["path"],
        "type": "object"
    }
}

# edit_file tool definition
{
    "name": "edit_file",
    "parameters": {
        "properties": {
            "path": {"description": "Path to file", "type": "string"},
            "old_text": {"description": "Text to replace", "type": "string"},
            "new_text": {"description": "Replacement text", "type": "string"}
        },
        "required": ["path", "old_text", "new_text"],
        "type": "object"
    }
}
```

### Comparison with Previous Chapter

| Feature | Chapter 1 | Chapter 2 |
|------|-----------|-----------|
| Tool Quantity | 1 (bash) | 4 (bash + file operations) |
| Tool Routing | if-else hard-coded | TOOL_HANDLERS dictionary |
| Path Security | None | safe_path() check |
| Error Handling | Simple | JSON parse error capture |
| Output Limitation | None | 50000 character limitation |

### Architecture Diagram

```
┌──────────┐      ┌───────┐      ┌──────────────────┐
│   User   │ ───> │  LLM  │ ───> │ Tool Dispatch    │
│  prompt  │      │       │      │ {                │
└──────────┘      └───┬───┘      │   bash: run_bash │
                      ↑          │   read: run_read │
                      │          │   write: run_wri │
                      │ tool_result                  │
                      │          │   edit: run_edit │
                      └──────────│ }                │
                                 └──────────────────┘
                                        │
                                        ▼
                                 ┌──────────────┐
                                 │ safe_path()  │
                                 │ (validate)   │
                                 └──────────────┘
```

### Error Handling Example

```python
# Parameter parse error
try:
    tool_input = json.loads(tool_call.function.arguments)
except json.JSONDecodeError as e:
    results.append({
        "role": "tool",
        "content": f"Failed to parse arguments: {e}",
        "tool_call_id": tool_call.id
    })
    continue

# Path security check error
try:
    safe_p = safe_path(tool_input["path"])
except ValueError as e:
    results.append({
        "role": "tool",
        "content": f"Security error: {e}",
        "tool_call_id": tool_call.id
    })
    continue
```

### Chapter Summary

Chapter 2 extends the tool system through tool dispatch dictionary while keeping the agent loop unchanged. File operation tool introduction enables the agent to directly read and write workspace files, path security check prevents directory traversal risks. Tool dispatch mechanism design facilitates adding new tools in the future.

---

## Chapter 3: Skill System Introduction

**File Path**: `code/v1_task_manager/chapter_03/s03_skill_loading.py` 
**Full Analysis**: [../zh/chapter_03/s03_skill_loading_文档.md](../zh/chapter_03/s03_skill_loading_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `SkillManifest` | dataclass | Skill metadata (name, description, path) |
| `SkillDocument` | dataclass | Skill complete document (manifest + body) |
| `SkillRegistry` | class | Skill loading and management, automatically scans skills directory |
| `load_skill` | tool | Dynamically loads skill content to context |
| `_parse_frontmatter()` | method | Parses Markdown frontmatter metadata |

### Function Change Details

1. **Skill Data Structure**
 - `SkillManifest` stores skill metadata: name, description, path
 - `SkillDocument` combines manifest and complete content body
 - Supports indexing and retrieval by name

2. **Skill Registry**
 - `SkillRegistry` automatically scans `skills/` directory for `SKILL.md` files
 - Uses frontmatter to parse skill metadata (YAML format)
 - Establishes index by skill name, supports fast lookup

3. **Skill Loading Tool**
 - Added `load_skill` tool for model to load skills on demand
 - Returns formatted `<skill name="...">...</skill>` tag
 - Unknown skills return error information and available skill list

4. **System Prompt Inject**
 - Lists all available skills in system prompt at startup
 - Model can choose to load related skills based on task requirements
 - Avoids injecting all skills at once to occupy context

5. **File Operation Classification**
 - `CONCURRENCY_SAFE = {"read_file"}` marks safe and concurrent tools
 - `CONCURRENCY_UNSAFE = {"write_file", "edit_file"}` marks unsafe tools
 - Provides basis for future concurrency control

```python
@dataclass
class SkillManifest:
    name: str
    description: str
    path: Path

@dataclass
class SkillDocument:
    manifest: SkillManifest
    body: str

class SkillRegistry:
    def _load_all(self) -> None:
        if not self.skills_dir.exists():
            return
        for path in sorted(self.skills_dir.rglob("SKILL.md")):
            meta, body = self._parse_frontmatter(path.read_text())
            name = meta.get("name", path.parent.name)
            description = meta.get("description", "No description")
            manifest = SkillManifest(name=name, description=description, path=path)
            self.documents[name] = SkillDocument(manifest=manifest, body=body.strip())
    
    def _parse_frontmatter(self, text: str) -> tuple[dict, str]:
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        meta = {}
        for line in match.group(1).strip().splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
        return meta, match.group(2)
    
    def load_full_text(self, name: str) -> str:
        document = self.documents.get(name)
        if not document:
            known = ", ".join(sorted(self.documents)) or "(none)"
            return f"Error: Unknown skill '{name}'. Available skills: {known}"
        return f'<skill name="{document.manifest.name}">\n{document.body}\n</skill>'
```

### Frontmatter Format Example

```yaml
---
name: jsonl_handler
description: Best practices for processing JSONL files in Python
---

# JSONL Handler Skill

## Overview
This skill provides patterns for reading and writing JSONL (JSON Lines) files.

## Reading JSONL
```python
with open("data.jsonl") as f:
 for line in f:
 record = json.loads(line)
 process(record)
```

## Writing JSONL
```python
with open("output.jsonl", "w") as f:
 for record in records:
 f.write(json.dumps(record) + "\n")
```
```

### Comparison with Previous Chapter

| Feature | Chapter 2 | Chapter 3 |
|------|-----------|-----------|
| Knowledge Management | None | SkillRegistry |
| Context Inject | Static | Dynamic load_skill |
| Tool Concurrency Mark | None | CONCURRENCY_SAFE/UNSAFE |
| Skill Discovery | None | Auto-scan SKILL.md |

### Architecture Diagram

```
┌───────────────┐     ┌─────────────┐     ┌──────────┐
│ skills/ dir   │ ──> │ SkillReg    │ <── │ load_skill│
│  └─ SKILL.md  │     │ (registry)  │     │  (tool)  │
│  └─ SKILL.md  │     └──────┬──────┘     └──────────┘
└───────────────┘            │
                             │ describe_available()
                             ▼
                    ┌────────────────┐
                    │ System Prompt  │
                    │ + available    │
                    │   skills list  │
                    └────────────────┘
```

### Skill Loading Process

```
1. Model calls load_skill(name="jsonl_handler")
2. SkillRegistry looks up corresponding skill
3. If found:
   - Returns <skill name="jsonl_handler">...</skill>
4. If not found:
   - Returns error message and available skill list
5. Result injected into conversation context
6. Model executes task based on skill content
```

### Chapter Summary

Chapter 3 introduces the skill system, allowing specific field knowledge and best practices to be encapsulated as loadable SKILL.md files. Model can dynamically load related skills based on task requirements, avoiding injecting too much content at once to occupy context. Frontmatter format supports structured metadata for skill classification and retrieval.

---

## Chapter 4: Task Management System

**File Path**: `code/v1_task_manager/chapter_04/s04_todo_write.py` 
**Full Analysis**: [../zh/chapter_04/s04_todo_write_文档.md](../zh/chapter_04/s04_todo_write_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `PlanItem` | dataclass | Single plan item (id, content, status, active_form) |
| `PlanningState` | dataclass | Plan state (items list + rounds_since_update) |
| `TodoManager` | class | Todo task management, supports update and render |
| `task_update` | tool | Update task plan |
| `render()` | method | Formatted output task list |

### Function Change Details

1. **Task Data Structure**
 - `PlanItem` includes id, content, status, active_form fields
 - status limited to `pending`, `in_progress`, `completed`
 - active_form used for in-progress description (such as "reading file")

2. **Single Task In-Progress Constraint**
 - At most one task in `in_progress` state at the same time
 - Prevents concurrent tasks leading to context confusion
 - Ensures task execution order

3. **Plan Update Validation**
 - Limits to maximum 20 plan items
 - Validates required fields (id, content) and valid state values
 - Returns detailed error information for model correction

4. **Round Tracking**
 - `rounds_since_update` records rounds since plan was last updated
 - Can be used to trigger plan review reminder
 - Helps model maintain plan timeliness

5. **Task Display Formatting**
 - `render()` method generates task list with state icons
 - Distinguishes completed (✅), in-progress (🔄), pending (⏳) tasks
 - In-progress tasks show active_form description

```python
@dataclass
class PlanItem: 
    id: str                     # Task ID for identification
    content: str                # What to do in this step
    status: str = "pending"     # pending | in_progress | completed
    active_form: str = ""       # In-progress description

@dataclass
class PlanningState:
    items: list[PlanItem] = field(default_factory=list)
    rounds_since_update: int = 0

class TodoManager:
    def update(self, items: list) -> str:
        if len(items) > 20:
            return f"Error: Too many plan items ({len(items)}). Maximum allowed is 20."
        
        normalized = []
        in_progress_count = 0
        for index, raw_item in enumerate(items):
            id = str(raw_item.get("id", "")).strip()
            content = str(raw_item.get("content", "")).strip()
            status = str(raw_item.get("status", "pending")).lower()
            active_form = str(raw_item.get("activeForm", "")).strip()
            
            if not id:
                return f"Error: Item {index} missing 'id' field."
            if not content:
                return f"Error: Item {index} missing 'content' field."
            if status not in {"pending", "in_progress", "completed"}:
                return f"Error: Invalid status '{status}'."
            if status == "in_progress":
                in_progress_count += 1
            
            normalized.append(PlanItem(id=id, content=content, status=status, active_form=active_form))
        
        if in_progress_count > 1:
            return "Error: Only one plan item can be in_progress at a time."
        
        self.state.items = normalized
        self.state.rounds_since_update = 0
        return self.render()
    
    def render(self) -> str:
        if not self.state.items:
            return "(no plan items)"
        lines = ["## Plan"]
        for item in self.state.items:
            icon = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}[item.status]
            status_text = item.active_form if item.status == "in_progress" else item.content
            lines.append(f"- [{item.id}] {icon} {status_text}")
        return "\n".join(lines)
```

### Task State Transition

```
pending ──────────────> in_progress ──────────────> completed
   │                         │                          │
   │                         │                          │
   └─────────────────────────┴──────────────────────────┘
                    (can revert to any state)
```

### Comparison with Previous Chapter

| Feature | Chapter 3 | Chapter 4 |
|------|-----------|-----------|
| Task Planning | None | TodoManager |
| State Tracking | None | PlanItem.status |
| Progress Reminder | None | rounds_since_update |
| Visualization | None | State icon rendering |

### Architecture Diagram

```
┌──────────┐     ┌──────────────┐     ┌─────────────┐
│   LLM    │ ──> │ task_update  │ ──> │ TodoManager │
│  prompt  │     │   (tool)     │     │             │
└──────────┘     └──────────────┘     └──────┬──────┘
                                             │
                              ┌──────────────┼──────────────┐
                              ▼              ▼              ▼
                        ┌──────────┐  ┌──────────┐  ┌──────────┐
                        │ pending  │  │in_progress│  │completed │
                        │   ⏳     │  │    🔄     │  │    ✅     │
                        └──────────┘  └──────────┘  └──────────┘
```

### Task List Example

```markdown
## Plan
- [1] ⏳ Read project structure
- [2] ⏳ Analyze core modules
- [3] 🔄 Writing test cases
- [4] ✅ Complete documentation update
```

### Chapter Summary

Chapter 4 introduces the task management system, enabling the agent to break down complex requirements into executable plan items. Single task in-progress constraint ensures task execution order, round tracking can be used to trigger plan review. State icons provide intuitive progress visualization.

---

## Chapter 5: Sub-agent System

**File Path**: `code/v1_task_manager/chapter_05/s05_subagent.py` 
**Full Analysis**: [../zh/chapter_05/s05_subagent_文档.md](../zh/chapter_05/s05_subagent_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `run_subagent()` | function | Start sub-agent to execute sub-task |
| `PARENT_TOOLS` | dict | Parent agent available tool set (task management class) |
| `CHILD_TOOLS` | dict | Child agent available tool set (execution class) |
| `task` | tool | Parent agent delegates task to sub-agent |
| `CHILD_SYSTEM` | str | Sub-agent system prompt |

### Function Change Details

1. **Parent-Child Agent Tool Separation**
 - Parent agent: `read_file`, `load_skill`, `task_*` series tools
 - Child agent: `bash`, `write_file`, `edit_file` execution tools
 - Tool separation ensures parent agent maintains concise context

2. **Sub-agent Function**
 - `run_subagent()` creates independent conversation context to execute sub-task
 - Sub-agent returns abstract to parent agent after completion
 - Supports nested calls (but requires attention to context limitation)

3. **Task Delegation Tool**
 - Added `task(prompt)` tool for parent agent to delegate tasks
 - Parent agent maintains concise context, only sees commands and results
 - Execution details do not pollute parent agent context

4. **Independent Context Management**
 - Sub-agent has independent messages history
 - Execution details do not pollute parent agent context
 - Sub-agent can have independent system prompt

5. **Tool Set Configuration**
 - `PARENT_TOOLS` and `CHILD_TOOLS` dictionary definition tool permissions
 - Facilitates adjusting parent-child agent ability boundaries
 - Supports different scenario tool set configuration

```python
# Parent agent tool set (task management class)
PARENT_TOOLS = {
    "read_file": {"type": "function", "function": {...}},
    "load_skill": {"type": "function", "function": {...}},
    "task_create": {"type": "function", "function": {...}},
    "task_update": {"type": "function", "function": {...}},
    "task_execute_ready": {"type": "function", "function": {...}}
}

# Child agent tool set (execution class)
CHILD_TOOLS = {
    "bash": {"type": "function", "function": {...}},
    "write_file": {"type": "function", "function": {...}},
    "edit_file": {"type": "function", "function": {...}}
}

def run_subagent(prompt: str) -> str:
    # Create sub-agent independent conversation
    child_history = [
        {"role": "system", "content": CHILD_SYSTEM},
        {"role": "user", "content": prompt}
    ]
    
    # Execute sub-agent loop
    child_state = LoopState(messages=child_history)
    while run_one_turn(child_state, tools=CHILD_TOOLS):
        pass
    
    # Extract summary and return to parent agent
    return extract_summary(child_state.messages)
```

### Parent-Child Agent Responsibility Division

| Responsibility | Parent Agent | Child Agent |
|------|--------|--------|
| Task Planning | ✅ | ❌ |
| Progress Tracking | ✅ | ❌ |
| File Reading | ✅ | ❌ |
| Skill Loading | ✅ | ❌ |
| Shell Execution | ❌ | ✅ |
| File Writing | ❌ | ✅ |
| File Editing | ❌ | ✅ |

### Comparison with Previous Chapter

| Feature | Chapter 4 | Chapter 5 |
|------|-----------|-----------|
| Execution Model | Single Agent | Parent + Child Agent |
| Tool Set | Unified | Parent-Child Separated |
| Context | Shared | Independent Sub-Context |
| Task Delegation | None | task Tool |

### Architecture Diagram

```
┌───────────────┐
│  Main Agent   │
│  (planning)   │
│ ┌───────────┐ │
│ │ read_file │ │
│ │load_skill │ │
│ │ task_*    │ │
│ └───────────┘ │
└───────┬───────┘
        │ task(prompt)
        ▼
┌───────────────┐
│ Sub Agent     │
│ (execution)   │
│ ┌───────────┐ │
│ │  bash     │ │
│ │  write    │ │
│ │  edit     │ │
│ └───────────┘ │
└───────┬───────┘
        │ result summary
        ▼
┌───────────────┐
│  Main Agent   │
│  (continue)   │
└───────────────┘
```

### Sub-agent Execution Process

```
1. Parent agent calls task(prompt="execute specific task")
2. Create sub-agent independent context:
   - system prompt: CHILD_SYSTEM
   - user prompt: passed prompt
3. Execute sub-agent loop:
   - use CHILD_TOOLS
   - continue until sub-agent completes
4. Extract execution summary
5. Return summary to parent agent
6. Parent agent continues planning
```

### Chapter Summary

Chapter 5 introduces the sub-agent system, separating task planning and execution. Parent agent is responsible for task breakdown and progress tracking, child agent is responsible for specific execution. Tool set separation ensures parent agent maintains concise context, focusing only on high-level decisions. This design decreases parent context pollution and improves long-session manageability.

---

## Chapter 6: Context Management

**File Path**: `code/v1_task_manager/chapter_06/s06_context.py` 
**Full Analysis**: [../zh/chapter_06/s06_context_文档.md](../zh/chapter_06/s06_context_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `CONTEXT_LIMIT` | const | Context length limit (characters) |
| `PERSIST_THRESHOLD` | const | Output persistence threshold |
| `TOOL_RESULTS_DIR` | Path | Tool result store directory |
| `compact()` | function | Context compression (LLM summary) |
| `estimate_tokens()` | function | Estimate token quantity |

### Function Change Details

1. **Context Budget Management**
 - `CONTEXT_LIMIT = 50000` characters as compact trigger point
 - Automatically triggers summary compression when exceeding limit
 - Prevents exceeding model context window

2. **Large Output Persistence**
 - When tool output exceeds `PERSIST_THRESHOLD = 30000` characters, write to file
 - Only keep preview and file path reference in context
 - Decrease context occupation while preserving complete output

3. **Tool Result Directory**
 - `TOOL_RESULTS_DIR = .task_outputs/tool-results/`
 - Each tool output saved as independent file
 - File naming includes timestamp and tool information

4. **LLM Summary Compression**
 - `auto_compact()` calls LLM to generate conversation summary
 - Replaces original history with summary to continue conversation
 - Preserves key decisions and state information

5. **Recent Result Retention**
 - `KEEP_RECENT_TOOL_RESULTS = 3` retains most recent N complete results
 - Earlier results are compressed or persisted
 - Balances context completeness and length

```python
CONTEXT_LIMIT = 50000
PERSIST_THRESHOLD = 30000
KEEP_RECENT_TOOL_RESULTS = 3

def estimate_tokens(messages: list) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(json.dumps(messages, default=str)) // 4

def auto_compact(messages: list) -> list:
    """Compress conversation history into a short continuation summary."""
    conversation_text = json.dumps(messages, default=str)[:80000]
    prompt = (
        "Summarize this conversation for continuity. Include:\n"
        "1) Task overview and success criteria\n"
        "2) Current state: completed work, files touched\n"
        "3) Key decisions and failed approaches\n"
        "4) Remaining next steps\n"
        "Be concise but preserve critical details.\n\n"
        + conversation_text
    )
    try:
        response = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": prompt}])
        summary = response.choices[0].message.content.strip()
    except Exception as e:
        summary = f"(compact failed: {e})"
    
    continuation = (
        "This session continues from a previous conversation that was compacted. "
        f"Summary of prior context:\n\n{summary}\n\n"
        "Continue from where we left off without re-asking the user."
    )
    return [{"role": "user", "content": continuation}]
```

### Persisted Output Format

```python
def persist_tool_output(tool_name: str, output: str) -> str:
    """Save large output to file and return reference."""
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{tool_name}_{timestamp}.txt"
    filepath = TOOL_RESULTS_DIR / filename
    filepath.write_text(output)
    
    relative_path = filepath.relative_to(WORKDIR)
    preview = output[:PREVIEW_CHARS] + "..." if len(output) > PREVIEW_CHARS else output
    
    return f"(Output persisted to {relative_path})\n\nPreview:\n{preview}"
```

### Comparison with Previous Chapter

| Feature | Chapter 5 | Chapter 6 |
|------|-----------|-----------|
| Context Limitation | No processing | Auto compact |
| Large Output Processing | Direct inject | Persist to file |
| History Management | Accumulative | Compress + retain recent |
| Token Estimation | None | estimate_tokens() |

### Architecture Diagram

```
┌─────────────┐
│ LLM output  │
│  >30k chars │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌──────────────────┐
│  Persist to │ ──> │ .task_outputs/   │
│   file      │     │ tool-results/    │
└─────────────┘     └──────────────────┘
       │
       ▼
┌─────────────┐
│ Inject ref  │
│ + preview   │
│ into ctx    │
└─────────────┘

When context > 50000 chars:
┌─────────────┐
│  Context    │
│  > LIMIT    │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│ auto_compact│ ──> │    LLM      │
│             │     │  summarize  │
└──────┬──────┘     └─────────────┘
       │
       ▼
┌─────────────┐
│  Replace    │
│  history    │
│  with       │
│  summary    │
└─────────────┘
```

### Context Management Strategy

```
1. Check output size after each tool execution
2. If output > PERSIST_THRESHOLD:
   - Save to file
   - Return reference + preview
3. Estimate context size after each conversation round
4. If context > CONTEXT_LIMIT:
   - Call auto_compact()
   - Replace history with summary
5. Retain most recent KEEP_RECENT_TOOL_RESULTS complete results
```

### Chapter Summary

Chapter 6 implements context management mechanism, controlling context length through output persistence and LLM summary compression. Large outputs are automatically saved to disk, conversation history can be compressed into summary, ensuring long sessions do not exceed model limitations. Token estimation provides approximate context usage situation.

---

## Chapter 7: Permission System

**File Path**: `code/v1_task_manager/chapter_07/s07_permission_system.py` 
**Full Analysis**: [../zh/chapter_07/s07_permission_文档.md](../zh/chapter_07/s07_permission_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `BashSecurityValidator` | class | Bash command security validator |
| `PermissionManager` | class | Permission decision manager |
| `MODES` | tuple | Permission modes (default/plan/auto) |
| `DEFAULT_RULES` | list | Default permission rules list |
| `is_workspace_trusted()` | function | Workspace trust check |

### Function Change Details

1. **Bash Security Validation**
 - `BashSecurityValidator` detects dangerous command patterns
 - Validation rules: `sudo`, `rm -rf`, `$()`, `IFS=` etc.
 - Severe patterns (sudo, rm_rf) directly rejected

2. **Permission Decision Pipeline**
 - Four stages: deny_rules → mode_check → allow_rules → ask_user
 - First matching rule determines behavior (allow/deny/ask)
 - Pipeline design facilitates extending new rules

3. **Three Permission Modes**
 - `default`: Non-read-only tools require user confirmation
 - `plan`: More strict format confirmation strategy
 - `auto`: Only high-risk operations require confirmation

4. **Rule Matching System**
 - Rule format: `{tool, path/content, behavior}`
 - Supports wildcard `*` matching
 - Rules checked in order, first match takes effect

5. **Consecutive Denial Tracking**
 - `consecutive_denials` counter prevents infinite asking
 - Automatically stops after reaching `max_consecutive_denials`
 - Avoids model falling into asking loop

```python
class BashSecurityValidator:
    VALIDATORS = [
        ("sudo", r"\bsudo\b"),
        ("rm_rf", r"\brm\s+(-[a-zA-Z]*)?r"),
        ("cmd_substitution", r"\$\("),
        ("ifs_injection", r"\bIFS\s*="),
    ]
    
    def validate(self, command: str) -> list:
        failures = []
        for name, pattern in self.VALIDATORS:
            if re.search(pattern, command):
                failures.append((name, pattern))
        return failures
    
    def is_safe(self, command: str) -> bool:
        return len(self.validate(command)) == 0

class PermissionManager:
    def __init__(self, mode: str = "default", rules: list = None):
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode}")
        self.mode = mode
        self.rules = rules or list(DEFAULT_RULES)
        self.consecutive_denials = 0
        self.max_consecutive_denials = 3
    
    def check(self, tool_name: str, tool_input: dict) -> dict:
        # Step 0: Bash security validation
        if tool_name == "bash":
            command = tool_input.get("command", "")
            failures = bash_validator.validate(command)
            if failures:
                severe = {"sudo", "rm_rf"}
                if any(f[0] in severe for f in failures):
                    return {"behavior": "deny", "reason": bash_validator.describe_failures(command)}
        
        # Step 1-3: Rule-based permission check
        for rule in self.rules:
            if self._matches_rule(rule, tool_name, tool_input):
                return {"behavior": rule["behavior"], "reason": f"Matched rule: {rule}"}
        
        # Default behavior based on mode
        if tool_name in READ_ONLY_TOOLS:
            return {"behavior": "allow", "reason": "Read-only tool"}
        return {"behavior": "ask", "reason": f"{tool_name} requires confirmation"}
```

### Permission Rules Example

```python
DEFAULT_RULES = [
    # Always deny dangerous commands
    {"tool": "bash", "content": "rm -rf /", "behavior": "deny"},
    {"tool": "bash", "content": "sudo *", "behavior": "deny"},
    # Allow reading any file
    {"tool": "read_file", "path": "*", "behavior": "allow"},
    # Allow writing to specific directory
    {"tool": "write_file", "path": "logs/*", "behavior": "allow"},
]
```

### Comparison with Previous Chapter

| Feature | Chapter 6 | Chapter 7 |
|------|-----------|-----------|
| Security Control | Simple blacklist | Multi-level permission pipeline |
| User Interaction | None | ask mode inquiry |
| Rule System | None | Configurable rules list |
| Mode Support | None | default/plan/auto |

### Architecture Diagram

```
┌─────────────┐
│ Tool Call   │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│ BashSecurityValidator│
│ (check dangerous)   │
└──────┬──────────────┘
       │ safe
       ▼
┌─────────────────────┐
│  PermissionManager  │
│  1. deny rules      │
│  2. mode check      │
│  3. allow rules     │
│  4. ask user        │
└──────┬──────────────┘
       │
   ┌───┴───┐
   ▼       ▼
 allow   deny/ask
```

### Permission Decision Process

```
1. Tool call occurs
2. BashSecurityValidator checks dangerous commands
   - If severe violation: directly deny
3. PermissionManager checks rules:
   a. deny_rules: match then deny
   b. mode_check: decide based on mode
   c. allow_rules: match then allow
   d. Default: ask user
4. Return decision to caller
```

### Chapter Summary

Chapter 7 establishes a complete permission system, including bash command security validation and multi-level permission decision pipeline. Three modes adapt to different scenarios, rule system supports flexible configuration, consecutive denial tracking prevents infinite asking. Permission system deeply integrates with tool calls, ensuring operation security.

---

## Chapter 8: Hook System

**File Path**: `code/v1_task_manager/chapter_08/s08_hook_system.py` 
**Full Analysis**: [../zh/chapter_08/s08_hook_doc.md](../zh/chapter_08/s08_hook_doc.md)