# s08: Hook System - Code Documentation

## Overview

s08 builds upon the s07 permission system by introducing an **extensible Hook plugin system**. The core improvement is the shift from hardcoded permission checks to an event-driven interceptor pipeline architecture.

### Core Improvements

1. **HookManager Class** - Unified management of hook loading and execution
2. **HOOK_EVENTS Tuple** - Defines supported event types (PreToolUse, PostToolUse, SessionStart)
3. **Dual-Layer Interception Pipeline** - Ring 0 (built-in security/permissions) + Ring 1 (external custom hooks)
4. **.hooks.json Configuration** - Externally defined hook scripts
5. **Matcher Mechanism** - Hooks trigger only for specific tools
6. **Environment Variable Injection** - HOOK_EVENT, HOOK_TOOL_NAME, HOOK_TOOL_INPUT, HOOK_TOOL_OUTPUT
7. **Three-Layer Return Value Handling** - updatedInput, additionalContext, permissionDecision
8. **/allow Command** - User actively grants directory permissions

### Design Philosophy

```
┌─────────────────────────────────────────────────────────────────┐
│                      Tool Call Triggered                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Ring 0: Built-in Security & Permission Hook (PermissionManager)  │
│  - BashSecurityValidator regex matching                          │
│  - deny_rules check                                              │
│  - mode judgment                                                 │
│  - allow_rules check                                             │
│  - ask_user user interaction                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │  blocked?         │
                    └─────────┬─────────┘
                       No     │     Yes
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Ring 1: External Custom Hook (_run_external_hooks)               │
│  - matcher tool matching                                         │
│  - Environment variable injection                                │
│  - subprocess script execution                                   │
│  - Return value parsing (updatedInput, additionalContext,         │
│    permissionDecision)                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Tool Execution                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PostToolUse Hook (Ring 1 only)                                  │
│  - Tool output monitoring                                        │
│  - Message injection append                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Return Result                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Comparison with s07

### Change Overview

| Component | s07 | s08 |
|------|-----|-----|
| Permission Management | PermissionManager independent call | Integrated into HookManager Ring 0 |
| Extension Mechanism | None | .hooks.json + HookManager |
| Event Types | None | PreToolUse, PostToolUse, SessionStart |
| External Scripts | None | subprocess executes custom commands |
| Environment Variable Injection | None | HOOK_EVENT, HOOK_TOOL_NAME, HOOK_TOOL_INPUT, HOOK_TOOL_OUTPUT |
| Return Value Handling | behavior (allow/deny/ask) | blocked, messages, updated_input, permission_override |
| Command Line | /mode, /rules | /mode, /rules, /allow |

### New Component Architecture

```
s08_hook_system.py
├── HOOK_EVENTS                      # Event type definitions
├── HookManager
│   ├── __init__()                   # Load .hooks.json configuration
│   ├── run_pre_tool_use()           # Ring 0 + Ring 1 unified pipeline
│   ├── run_post_tool_use()          # PostToolUse interception
│   ├── _run_external_hooks()        # External script execution
│   └── _check_workspace_trust()     # Workspace trust check
├── PermissionManager                # Built-in Ring 0 (maintains s07 logic)
├── BashSecurityValidator            # Bash security validator (maintains s07 logic)
└── Command Line Processing
    ├── /mode                        # Switch mode (inherited from s07)
    ├── /rules                       # View rules (inherited from s07)
    └── /allow                       # Actively authorize directory (new)
```

---

## s08 New Content Details (by Code Execution Order)

### Phase 1: Hook Configuration and Event Definitions (New)

#### HOOK_EVENTS Tuple

```python
HOOK_EVENTS = ("PreToolUse", "PostToolUse", "SessionStart")
HOOK_TIMEOUT = 30  # seconds
```

**Mechanism Overview**: Defines the hook event types supported by the system. PreToolUse triggers before tool execution for permission review and input modification; PostToolUse triggers after tool execution for output monitoring and context injection; SessionStart triggers at session start (not implemented in current version).

#### .hooks.json Configuration File Format

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "bash",
        "command": "./hooks/pre_bash.sh"
      },
      {
        "matcher": "*",
        "command": "./hooks/global_pre.sh"
      }
    ],
    "PostToolUse": [
      {
        "matcher": "write_file",
        "command": "./hooks/log_writes.sh"
      }
    ]
  }
}
```

**Mechanism Overview**: Configuration file defines the list of hook scripts corresponding to each event. Each hook contains a matcher (tool matcher) and command (execution command). matcher as "*" means matching all tools.

#### HookManager Initialization

```python
class HookManager:
    def __init__(self, perms_manager, config_path: Path = None, sdk_mode: bool = True):
        self.perms = perms_manager  # Inject permission manager
        self.hooks = {"PreToolUse": [], "PostToolUse": [], "SessionStart": []}
        self._sdk_mode = sdk_mode
        config_path = config_path or (WORKDIR / ".hooks.json")
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
                for event in HOOK_EVENTS:
                    self.hooks[event] = config.get("hooks", {}).get(event, [])
                print(f"[Hooks loaded from {config_path}]")
            except Exception as e:
                print(f"[Hook config error: {e}]")
```

**Mechanism Overview**: During initialization, inject the PermissionManager instance and load hook configuration from `.hooks.json` into the memory dictionary. sdk_mode controls whether to skip workspace trust checks.

## Directory Structure Dependencies

| File/Directory | Purpose | Creation Method |
|-----------|------|----------|
| `.hooks.json` | Hook configuration file | User manually creates |
| `.claude/.claude_trusted` | Workspace trust marker | User manually creates |

**.hooks.json Configuration File Format**:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "command": "echo 'Tool called'"
      }
    ],
    "PostToolUse": [],
    "SessionStart": []
  }
}
```

**Field Descriptions**:
- `matcher`: Tool name matching, `"*"` means global, or specify tool name like `"bash"`
- `command`: Shell command or script path to execute

**Trust Marker File** (`.claude/.claude_trusted`):
- Empty file is sufficient
- External hook execution is skipped in untrusted workspaces

---

### Phase 2: Dual-Layer Hook Architecture (New)

#### Ring 0: Built-in Security and Permissions (Inherited from s07, Integrated into Pipeline)

```python
def run_pre_tool_use(self, context: dict) -> dict:
    result = {"blocked": False, "block_reason": "", "messages": []}
    tool_name = context.get("tool_name", "")
    tool_input = context.get("tool_input", {})

    # --- [Stage 1: Built-in Security & Permission Hook (Ring 0)] ---
    decision = self.perms.check(tool_name, tool_input)
    
    if decision["behavior"] == "deny":
        return {"blocked": True, "block_reason": f"Permission denied: {decision['reason']}", "messages": []}
        
    elif decision["behavior"] == "ask":
        if not self.perms.ask_user(tool_name, tool_input):
            return {"blocked": True, "block_reason": f"User denied execution for {tool_name}", "messages": []}
```

**Mechanism Overview**: Calls PermissionManager.check() to execute built-in permission checks. Logic is identical to s07, see s07 documentation for details. The difference in s08 is that it serves as the first stage of the pipeline, and when blocked, it returns directly without executing Ring 1.

**Ring 0 Execution Order** (inherited from s07):
1. BashSecurityValidator regex matching (dangerous command detection)
2. deny_rules check
3. mode judgment (plan/auto/ask)
4. allow_rules check
5. ask_user user interaction (if needed)

#### Ring 1: External Custom Hook (New)

```python
# --- [Stage 2: External Custom Hook (Ring 1)] ---
ext_result = self._run_external_hooks("PreToolUse", context)
if ext_result["blocked"]:
    return ext_result
else:
    result["messages"].extend(ext_result["messages"])
    if "updated_input" in ext_result:
        context["tool_input"] = ext_result["updated_input"]
    return result
```

**Mechanism Overview**: Ring 1 executes after Ring 0 passes, supporting external script interception. Can modify tool input, append messages, or block execution.

---

### Phase 3: External Hook Execution Mechanism (New)

#### _run_external_hooks() Method

```python
def _run_external_hooks(self, event: str, context: dict) -> dict:
    result = {"blocked": False, "block_reason": "", "messages": []}
    if not self._check_workspace_trust():
        return result
        
    hooks = self.hooks.get(event, [])
    for hook_def in hooks:
        # matcher matching logic
        matcher = hook_def.get("matcher")
        if matcher and context:
            tool_name = context.get("tool_name", "")
            if matcher != "*" and matcher != tool_name:
                continue
        
        command = hook_def.get("command", "")
        if not command: 
            continue
        
        # Environment variable injection
        env = dict(os.environ)
        if context:
            env["HOOK_EVENT"] = event
            env["HOOK_TOOL_NAME"] = context.get("tool_name", "")
            env["HOOK_TOOL_INPUT"] = json.dumps(context.get("tool_input", {}), ensure_ascii=False)[:10000]
            if "tool_output" in context:
                env["HOOK_TOOL_OUTPUT"] = str(context["tool_output"])[:10000]
        
        try:
            r = subprocess.run(command, shell=True, cwd=WORKDIR, env=env, 
                              capture_output=True, text=True, timeout=HOOK_TIMEOUT)
            # Return value parsing...
```

**Mechanism Overview**: Iterates through the hook list corresponding to the event, executing matcher matching for each hook. After matching passes, inject environment variables and execute subprocess. Parses output based on return code: 0 means success and parse JSON, 1 means block, 2 means inject message.

#### matcher Matching Mechanism

```python
matcher = hook_def.get("matcher")
if matcher and context:
    tool_name = context.get("tool_name", "")
    if matcher != "*" and matcher != tool_name:
        continue
```

**Mechanism Overview**: matcher is used to restrict hooks to only take effect for specific tools. "*" means global matching, specific tool names (like "bash") mean execution only when the tool name matches.

#### Environment Variable Injection

| Variable Name | Meaning | Example |
|--------|------|------|
| HOOK_EVENT | Event type | PreToolUse |
| HOOK_TOOL_NAME | Tool name | bash |
| HOOK_TOOL_INPUT | Tool input JSON | {"command": "ls -la"} |
| HOOK_TOOL_OUTPUT | Tool output | Only available for PostToolUse |

**Mechanism Overview**: Environment variables enable external scripts to access tool call context information. Input and output are limited to 10000 characters to avoid overly large environment variables.

#### Return Value Parsing

```python
if r.returncode == 0:
    try:
        hook_output = json.loads(r.stdout)
        if "updatedInput" in hook_output and context:
            result["updated_input"] = hook_output["updatedInput"]
        if "additionalContext" in hook_output:
            result["messages"].append(hook_output["additionalContext"])
        if "permissionDecision" in hook_output:
            result["permission_override"] = hook_output["permissionDecision"]
    except: pass
elif r.returncode == 1:
    return {"blocked": True, "block_reason": r.stderr.strip() or "Blocked by external hook", "messages": []}
elif r.returncode == 2:
    msg = r.stderr.strip()
    if msg:
        result["messages"].append(msg)
```

**Mechanism Overview**: External scripts return JSON-formatted control instructions via standard output:
- `updatedInput`: Modify tool input parameters
- `additionalContext`: Context information appended to message list
- `permissionDecision`: Override permission decision

Return code 1 signals blocking via standard error, or return code 2 injects messages.

---

### Phase 4: run_pre_tool_use Unified Pipeline (New)

```python
def run_pre_tool_use(self, context: dict) -> dict:
    result = {"blocked": False, "block_reason": "", "messages": []}
    
    # --- [Stage 1: Built-in Security & Permission Hook (Ring 0)] ---
    decision = self.perms.check(tool_name, tool_input)
    if decision["behavior"] == "deny":
        return {"blocked": True, "block_reason": f"Permission denied: {decision['reason']}", "messages": []}
    elif decision["behavior"] == "ask":
        if not self.perms.ask_user(tool_name, tool_input):
            return {"blocked": True, "block_reason": f"User denied execution for {tool_name}", "messages": []}

    # --- [Stage 2: External Custom Hook (Ring 1)] ---
    ext_result = self._run_external_hooks("PreToolUse", context)
    if ext_result["blocked"]:
        return ext_result
    else:
        result["messages"].extend(ext_result["messages"])
        if "updated_input" in ext_result:
            context["tool_input"] = ext_result["updated_input"]
        return result
```

**Mechanism Overview**: Unified pipeline executes Ring 0 and Ring 1 in sequence. When Ring 0 blocks, it returns directly without executing Ring 1. Ring 1's updated_input is updated into context for subsequent tool execution.

**Unified Return Value Format**:
```python
{
    "blocked": bool,           # Whether blocked
    "block_reason": str,       # Block reason
    "messages": list,          # Injected message list
    "updated_input": dict,     # Modified tool input (optional)
    "permission_override": str # Overridden permission decision (optional)
}
```

---

### Phase 5: run_post_tool_use Interception (New)

```python
def run_post_tool_use(self, context: dict) -> dict:
    return self._run_external_hooks("PostToolUse", context)
```

**Mechanism Overview**: PostToolUse only executes Ring 1 external hooks, used for monitoring and context injection after tool execution. Does not include Ring 0 permission checks because the tool has already completed execution.

---

### Phase 6: execute_tool_calls Changes (Modified)

```python
def execute_tool_calls(response_message) -> tuple[list[dict], str | None, bool, str | None]:
    for tool_call in response_message.tool_calls:
        f_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        args['tool_call_id'] = tool_call.id
        
        if f_name in TOOL_HANDLERS:
            ctx = {"tool_name": tool_call.function.name, "tool_input": args}
            
            # 1. Unified interception pipeline: permission check + external Pre-Hook
            pre_result = hooks.run_pre_tool_use(ctx)
            
            # If blocked by any mechanism
            if pre_result.get("blocked"):
                reason = pre_result.get("block_reason", "Blocked by pipeline/hook")
                output = f"Tool blocked by PreToolUse hook: {reason}"
                results.append({"role": "tool", "tool_call_id": tool_call.id, "name": f_name, "content": output})
                continue
            else:
                for msg in pre_result.get("messages", []):
                    results.append({"role": "tool", "tool_call_id": tool_call.id, "name": f_name, "content": f"[Hook message]: {msg}"})
            
            args = ctx.get("tool_input", args)

            # 2. Execute the tool itself
            handler = TOOL_HANDLERS.get(f_name)
            output = handler(**args) if handler else f"Unknown: {f_name}"
            
            # 3. Unified interception pipeline: external Post-Hook
            post_ctx = {"tool_name": f_name, "tool_input": args, "tool_output": output}
            post_result = hooks.run_post_tool_use(post_ctx)
            for msg in post_result.get("messages", []):
                results.append({"role": "tool", "tool_call_id": tool_call.id, "name": f_name, "content": f"[PostHook message]: {msg}"})
```

**Mechanism Overview**: Tool call execution flow:
1. Build context containing tool_name and tool_input
2. Call run_pre_tool_use() to execute Ring 0 + Ring 1
3. When blocked, return error message and skip tool execution
4. Execute tool handler
5. Call run_post_tool_use() to execute PostToolUse Hook
6. Append injected messages to result list

---

### Phase 7: /allow Command (New)

```python
if query.startswith("/allow"):
    parts = query.split(maxsplit=1)
    if len(parts) == 2:
        target_dir = parts[1].strip()
        if not target_dir.endswith("*"):
            target_dir = target_dir.rstrip("/\\") + "/*"
        
        perms.rules.append({
            "tool": "*",
            "path": target_dir,
            "behavior": "allow"
        })
        perms.consecutive_denials = 0
        print(f"\033[32m[Granted] Actively authorized framework to operate directory: {target_dir}\033[0m")
    else:
        print("Usage: /allow <path/to/folder>")
```

**Mechanism Overview**: /allow command dynamically adds allow rules, authorizing permissions for all tools to operate on specified directories. Automatically completes wildcards to avoid double slash issues.

**Usage Examples**:
```
s01 >> /allow ./data
[Granted] Actively authorized framework to operate directory: ./data/*

s01 >> /allow src/config
[Granted] Actively authorized framework to operate directory: src/config/*
```

---

## Relationship with s07

### Simplified Comparison

| Feature | s07 | s08 |
|------|-----|-----|
| Permission Management | PermissionManager independent call | HookManager integrated call |
| Extension Capability | None | .hooks.json configures external scripts |
| Event System | None | HOOK_EVENTS tuple |
| Environment Variable Injection | None | 4 HOOK_* environment variables |
| Return Value Format | behavior (allow/deny/ask) | blocked/messages/updated_input |
| Command Line | /mode, /rules | /mode, /rules, /allow |

### Inherited Content (See s07 Documentation for Details)

The following content remains unchanged in s08. For detailed explanations, please refer to the s07 documentation:

- **PermissionManager Class**: Logic fully preserved, integrated into pipeline as Ring 0
- **BashSecurityValidator**: Dangerous command regex validation logic unchanged
- **MODES Three Runtime Modes**: plan/auto/ask mode judgment logic unchanged
- **DEFAULT_RULES Default Rules**: Built-in allow/deny rule list unchanged
- **User Interaction Approval Flow**: ask_user() method y/n/always interaction logic unchanged
- **/mode and /rules Commands**: Command line support fully inherited

---

## Practice Guide

### .hooks.json Configuration Examples

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "bash",
        "command": "./hooks/check_bash.sh"
      },
      {
        "matcher": "write_file",
        "command": "./hooks/audit_write.sh"
      },
      {
        "matcher": "*",
        "command": "./hooks/log_all.sh"
      }
    ],
    "PostToolUse": [
      {
        "matcher": "write_file",
        "command": "./hooks/track_changes.sh"
      }
    ]
  }
}
```

### External Script Examples

**PreToolUse Hook (bash)**:
```bash
#!/bin/bash
# hooks/check_bash.sh

# Check for dangerous commands
if echo "$HOOK_TOOL_INPUT" | grep -q "rm -rf"; then
    echo "Blocked: rm -rf detected" >&2
    exit 1
fi

# Return modified input
echo '{"updatedInput": {"command": "ls -la"}}'
exit 0
```

**PostToolUse Hook (Python)**:
```python
#!/usr/bin/env python3
# hooks/log_writes.py

import os
import json

tool_output = os.environ.get("HOOK_TOOL_OUTPUT", "")

# Log to file
with open(".hook_logs/write_operations.log", "a") as f:
    f.write(f"Output: {tool_output}\n")

# Inject context message
print(json.dumps({
    "additionalContext": f"File operation logged at {time.time()}"
}))
```

### /allow Command Usage

```
s01 >> /allow ./data
[Granted] Actively authorized framework to operate directory: ./data/*

s01 >> /allow src/config
[Granted] Actively authorized framework to operate directory: src/config/*
```

**Note**: Authorization appends to rules list, valid for current session.

### Testing Examples

1. Create test hook:
```bash
mkdir -p hooks
cat > hooks/test_hook.sh << 'EOF'
#!/bin/bash
echo '{"additionalContext": "Hook executed successfully"}'
EOF
chmod +x hooks/test_hook.sh
```

2. Create configuration file:
```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "*", "command": "./hooks/test_hook.sh"}
    ]
  }
}
```

3. Run framework and call any tool, observe `[Hook message]` in output.

---

## Summary

### Core Design Philosophy

s08 extends s07's hardcoded permission checks into an event-driven pluggable architecture by introducing the Hook system. The dual-layer interception pipeline (Ring 0 + Ring 1) provides extensibility while maintaining a security baseline.

### Version Information

- **File Path**: v1_task_manager/chapter_8/s08_hook_system.py
- **Configuration Path**: .hooks.json (workspace root directory)
