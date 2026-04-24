# s07: Permission System - Code Documentation

## Overview

s07 introduces a permission management system based on s06, requiring agents to pass security checks before executing tool calls.

**Core Improvements**:
- From no permission checks to four-layer permission pipeline
- Layered validation + user final control design philosophy
- Three operation modes supporting different automation levels

**Design Philosophy**:
- Pre-intercept dangerous commands (BashSecurityValidator)
- Rule-driven permission decisions (DEFAULT_RULES)
- User retains final decision authority (ask_user)

## Comparison with s06

### Change Overview

| Component | s06 | s07 |
|------|-----|-----|
| Permission Checks | None | Four-layer pipeline |
| Bash Command Validation | Simple string matching | BashSecurityValidator class |
| Operation Modes | None | default/plan/auto |
| User Interaction | None | y/n/always approval |
| Command Line Support | None | /mode, /rules |

### New Component Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Tool Call                            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│           BashSecurityValidator                         │
│   Validate sudo, rm_rf, cmd_substitution dangerous patterns │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              PermissionManager.check()                  │
│  ┌─────────────────────────────────────────────────┐   │
│  │ Step 0: Bash security validation (severe modes  │   │
│  │           directly deny)                         │   │
│  │ Step 1: Deny rule matching (first match wins)   │   │
│  │ Step 2: Mode check (plan mode blocks writes)    │   │
│  │ Step 3: Allow rule matching                     │   │
│  │ Step 4: Ask User (default behavior)             │   │
│  └─────────────────────────────────────────────────┘   │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
     deny          ask         allow
        │            │            │
        │            ▼            │
        │     ask_user()          │
        │    (y/n/always)         │
        │            │            │
        ▼            ▼            ▼
┌─────────────────────────────────────────────────────────┐
│              execute_tool_calls                         │
│   Handle based on behavior branch                       │
└─────────────────────────────────────────────────────────┘
```

## Detailed Explanation by Execution Order

### Phase 1: BashSecurityValidator Class

**Mechanism Overview**:
`BashSecurityValidator` class is responsible for dangerous pattern detection before executing bash commands. It uses regular expressions to match five predefined dangerous patterns, directly rejecting severe threats (`sudo`, `rm_rf`), and upgrading other patterns to ask user.

```python
class BashSecurityValidator:
    VALIDATORS = [
        ("sudo", r"\bsudo\b"),                 # Privilege escalation
        ("rm_rf", r"\brm\s+(-[a-zA-Z]*)?r"),  # Recursive deletion
        ("cmd_substitution", r"\$\("),          # Command substitution
        ("ifs_injection", r"\bIFS\s*="),        # IFS variable injection
    ]
    
    def validate(self, command: str) -> list:
        """Check if command triggers any validator, return failure list"""
        failures = []
        for name, pattern in self.VALIDATORS:
            if re.search(pattern, command):
                failures.append((name, pattern))
        return failures
    
    def is_safe(self, command: str) -> bool:
        """Convenience method: return True if no validators triggered"""
        return len(self.validate(command)) == 0
    
    def describe_failures(self, command: str) -> str:
        """Generate human-readable validation failure description"""
        failures = self.validate(command)
        if not failures:
            return "No issues detected"
        parts = [f"{name} (pattern: {pattern})" for name, pattern in failures]
        return "Security flags: " + ", ".join(parts)
```

**VALIDATORS List Description**:

| Validator Name | Regex Pattern | Detection Target |
|-----------|----------|----------|
| sudo | `\bsudo\b` | Privilege escalation commands |
| rm_rf | `\brm\s+(-[a-zA-Z]*)?r` | Recursive deletion operations |
| cmd_substitution | `\$\(` | Command substitution syntax |
| ifs_injection | `\bIFS\s*=` | Environment variable injection |

### Phase 2: Workspace Trust Mechanism

**Mechanism Overview**:
`is_workspace_trusted()` function determines if a workspace is explicitly trusted by the user by checking for the existence of a specific marker file. This is a simplified trust mechanism, providing a foundation for subsequent expansion of more complex trust flows.

```python
def is_workspace_trusted(workspace: Path = None) -> bool:
    ws = workspace or WORKDIR
    trust_marker = ws / ".claude" / ".claude_trusted"
    return trust_marker.exists()
```

**Trust Marker File**:
- Path: `.claude/.claude_trusted` (relative to working directory)
- Purpose: Explicitly mark trusted workspaces
- Current version: Only serves as basic mechanism, not强制 used in main flow

## Directory Structure Dependencies

| File/Directory | Purpose | Creation Method |
|-----------|------|----------|
| `.claude/.claude_trusted` | Workspace trust marker | Manually created by user |

**Trust Marker File**:
- Empty file is sufficient
- Existence in workspace indicates trust in that directory
- Affects external Hook execution in Hook system (non-trusted workspaces skip external Hooks)

### Phase 3: Permission Rule Definition

**Mechanism Overview**:
`DEFAULT_RULES` is a permission rule list, each rule defines allow/deny behavior for specific tools, paths, or content. Rules checked in order, first matching rule takes effect (First Match Wins).

```python
DEFAULT_RULES = [
    # Always deny dangerous patterns
    {"tool": "bash", "content": "rm -rf /", "behavior": "deny"},
    {"tool": "bash", "content": "sudo *", "behavior": "deny"},
    # Allow reading all files
    {"tool": "read_file", "path": "*", "behavior": "allow"},
]
```

**Rule Format**:

```python
{
    "tool": "<tool_name or *>",      # Tool name, * matches all
    "path": "<glob pattern or *>",   # Path matching (for file operations)
    "content": "<fnmatch pattern>",  # Content matching (for bash commands)
    "behavior": "allow|deny|ask"     # Behavior: allow/deny/ask
}
```

**Rule Matching Order**:
1. Rule list traversed in definition order
2. First matching rule determines behavior
3. Enter ask flow when no rules matched

### Phase 4: PermissionManager Class

**Mechanism Overview**:
`PermissionManager` is the core component for permission decisions, implementing a four-layer permission pipeline. It supports three operation modes, manages rule lists, and tracks consecutive denial counts to prevent agents from entering loops of repeated requests.

```python
class PermissionManager:
    def __init__(self, mode: str = "default", rules: list = None):
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode}. Choose from {MODES}")
        self.mode = mode
        self.rules = rules or list(DEFAULT_RULES)
        self.consecutive_denials = 0
        self.max_consecutive_denials = 3
```

**Three Operation Modes**:

| Mode | Behavior |
|------|------|
| default | Default mode: follow rules + ask user when unmatched |
| plan | Plan mode: block all write operations, read-only allowed |
| auto | Auto mode: safe operations auto-approved |

**check() Method Four-Layer Pipeline**:

```python
def check(self, tool_name: str, tool_input: dict) -> dict:
    # Step 0: Bash security validation (before deny rules)
    if tool_name == "bash":
        command = tool_input.get("command", "")
        failures = bash_validator.validate(command)
        if failures:
            severe = {"sudo", "rm_rf"}
            severe_hits = [f for f in failures if f[0] in severe]
            if severe_hits:
                return {"behavior": "deny", "reason": ...}
            return {"behavior": "ask", "reason": ...}
    
    # Step 1: Deny rules (always checked first)
    for rule in self.rules:
        if rule["behavior"] != "deny":
            continue
        if self._matches(rule, tool_name, tool_input):
            return {"behavior": "deny", "reason": ...}
    
    # Step 2: Mode check
    if self.mode == "plan":
        if tool_name in WRITE_TOOLS:
            return {"behavior": "deny", "reason": "Plan mode: write operations are blocked"}
        return {"behavior": "allow", "reason": "Plan mode: read-only allowed"}
    
    if self.mode == "auto":
        return {"behavior": "allow", "reason": "Auto mode: safe operation auto-approved"}
    
    # Step 3: Allow rules
    for rule in self.rules:
        if rule["behavior"] != "allow":
            continue
        if self._matches(rule, tool_name, tool_input):
            self.consecutive_denials = 0
            return {"behavior": "allow", "reason": ...}
    
    # Step 4: Ask User (default behavior)
    return {"behavior": "ask", "reason": "No rule matched, asking user"}
```

**ask_user() User Interaction**:

```python
def ask_user(self, tool_name: str, tool_input: dict) -> bool:
    preview = json.dumps(tool_input, ensure_ascii=False)[:200]
    print(f"\n  [Permission] {tool_name}: {preview}")
    try:
        answer = input("  Allow? (y/n/always): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    
    if answer == "always":
        # Add permanent allow rule
        self.rules.append({"tool": tool_name, "path": "*", "behavior": "allow"})
        self.consecutive_denials = 0
        return True
    
    if answer in ("y", "yes"):
        self.consecutive_denials = 0
        return True
    
    # Track consecutive denial count
    self.consecutive_denials += 1
    if self.consecutive_denials >= self.max_consecutive_denials:
        print(f"  [{self.consecutive_denials} consecutive denials -- "
              "consider switching to plan mode]")
    return False
```

**_matches() Rule Matching**:

```python
def _matches(self, rule: dict, tool_name: str, tool_input: dict) -> bool:
    # Tool name matching
    if rule.get("tool") and rule["tool"] != "*":
        if rule["tool"] != tool_name:
            return False
    
    # Path pattern matching (using fnmatch)
    if "path" in rule and rule["path"] != "*":
        path = tool_input.get("path", "")
        if not fnmatch(path, rule["path"]):
            return False
    
    # Content pattern matching (for bash commands)
    if "content" in rule:
        command = tool_input.get("command", "")
        if not fnmatch(command, rule["content"]):
            return False
    
    return True
```

### Phase 5: execute_tool_calls Changes

**Mechanism Overview**:
s07's `execute_tool_calls` function integrates permission checks before tool execution. Branches based on `behavior` (deny/ask/allow) returned by `check()`, and tracks consecutive denial counts.

```python
def execute_tool_calls(response_content, perms) -> tuple[list[dict], str | None, bool, str | None]:
    results = []
    for tool_call in response_content.tool_calls:
        f_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        
        if f_name in TOOL_HANDLERS:
            # Permission judgment
            decision = perms.check(f_name, args)
            
            if decision["behavior"] == "deny":
                output = f"Permission denied: {decision['reason']}"
                print(f"  [DENIED] {f_name}: {decision['reason']}")
            
            elif decision["behavior"] == "ask":
                if perms.ask_user(f_name, args):
                    handler = TOOL_HANDLERS.get(f_name)
                    output = handler(**args) if handler else f"Unknown: {f_name}"
                else:
                    output = f"Permission denied by user for {f_name}"
                    print(f"  [USER DENIED] {f_name}")
            
            else:  # allow
                output = TOOL_HANDLERS[f_name](**args)
        
        results.append({
            "role": "tool", 
            "tool_call_id": tool_call.id,
            "name": tool_call.function.name,
            "content": output
        })
    
    return results, reminder, manual_compact, compact_focus
```

**Consecutive Denial Count**:
- `consecutive_denials` increments after each user denial
- Reset to 0 when user approves
- When reaching `max_consecutive_denials` (default 3), prompts user to switch to plan mode

### Phase 6: Command Line Support

**Mechanism Overview**:
Two command line instructions added in main loop, supporting runtime mode switching and viewing rule list. These instructions intercepted during user input handling, not passed to Agent.

```python
if __name__ == "__main__":
    # Select mode at startup
    mode_input = input("Mode (default): ").strip().lower() or "default"
    perms = PermissionManager(mode=mode_input)
    
    while True:
        query = input("s01 >> ")
        
        # /mode command switches mode
        if query.startswith("/mode"):
            parts = query.split()
            if len(parts) == 2 and parts[1] in MODES:
                perms.mode = parts[1]
                print(f"[Switched to {parts[1]} mode]")
            else:
                print(f"Usage: /mode <{'|'.join(MODES)}>")
            continue
        
        # /rules command views rules
        if query.strip() == "/rules":
            for i, rule in enumerate(perms.rules):
                print(f"  {i}: {rule}")
            continue
        
        # Normal user input handling
        history.append({"role": "user", "content": query})
        ...
```

**Supported Commands**:

| Command | Function | Example |
|------|------|------|
| `/mode <mode>` | Switch operation mode | `/mode plan` |
| `/rules` | View current rule list | `/rules` |

## Complete Framework Flowchart

```
┌────────────────────────────────────────────────────────────────────┐
│                        Tool Call                                   │
│                    (tool_name, tool_input)                         │
└────────────────────────────────┬───────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│  Step 0: BashSecurityValidator                                     │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ if tool_name == "bash":                                      │ │
│  │   failures = validator.validate(command)                     │ │
│  │   if severe (sudo, rm_rf): return DENY                       │ │
│  │   elif other flags: return ASK                               │ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────┬───────────────────────────────────┘
                                 │ (non-bash or no severe flags)
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│  Step 1: Deny Rules                                                │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ for rule in rules:                                           │ │
│  │   if rule.behavior == "deny" and _matches():                 │ │
│  │     return DENY                                              │ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────┬───────────────────────────────────┘
                                 │ (no deny rule matched)
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│  Step 2: Mode Check                                                │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ if mode == "plan":                                           │ │
│  │   if tool in WRITE_TOOLS: return DENY                        │ │
│  │   else: return ALLOW                                         │ │
│  │ if mode == "auto":                                           │ │
│  │   return ALLOW                                               │ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────┬───────────────────────────────────┘
                                 │ (default mode or unhandled)
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│  Step 3: Allow Rules                                               │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ for rule in rules:                                           │ │
│  │   if rule.behavior == "allow" and _matches():                │ │
│  │     consecutive_denials = 0                                  │ │
│  │     return ALLOW                                             │ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────┬───────────────────────────────────┘
                                 │ (no allow rule matched)
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│  Step 4: Ask User                                                  │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ return ASK (default behavior)                                │ │
│  │   ↓                                                          │ │
│  │ user input: y/n/always                                       │ │
│  │   - y: ALLOW, reset denials                                  │ │
│  │   - always: ALLOW + add rule, reset denials                  │ │
│  │   - n: DENY, increment consecutive_denials                   │ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────┬───────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│                    execute_tool_calls                              │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ switch (behavior):                                           │ │
│  │   case DENY:   return "Permission denied: <reason>"          │ │
│  │   case ASK:    if user approves: execute; else: deny         │ │
│  │   case ALLOW:  execute tool handler                          │ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
```

## Design Point Summary

### Four-Layer Permission Pipeline

1. **Step 0 - Bash Security Validation**: Before executing any rule checks, first perform dangerous pattern detection on bash commands
2. **Step 1 - Deny Rules**: Deny rules have highest priority, deny immediately upon match
3. **Step 2 - Mode Check**: Decide allow or deny based on operation mode (plan mode blocks writes)
4. **Step 3 - Allow Rules**: Pass directly upon allow rule match
5. **Step 4 - Ask User**: Ask user when no rules matched

### Dangerous Command Validation

- Use regular expressions to match dangerous patterns
- Severe threats (sudo, rm_rf) directly denied
- Other threats upgraded to ask user
- Extensible VALIDATORS list design

### Three Operation Modes

- **default**: Follow rules, ask when unmatched
- **plan**: Read-only mode, block all write operations
- **auto**: Auto mode, safe operations auto-approved

### User Final Control

- User retains final decision authority through `ask_user()`
- `always` option can add permanent allow rules
- Consecutive denial count prompts user to switch modes

## Overall Design Philosophy Summary

1. **Layered Defense**: Bash validation → Rule matching → Mode check → User confirmation, each layer independently effective
2. **Rule Priority**: Explicitly defined rules take priority over implicit behavior, avoiding ambiguous decisions
3. **User Sovereignty**: All operations not explicitly allowed default to asking user, user has final decision authority
4. **Mode-Driven**: Quickly switch security levels through operation modes, adapting to different scenario requirements
5. **Traceability**: Each denial records reason, consecutive denials trigger prompts
6. **Progressive Trust**: User can choose `always` to establish permanent trust rules

## Relationship with s06

### Comparison Table

| Dimension | s06 | s07 |
|------|-----|-----|
| Core Function | Context compression | Permission management |
| Bash Handling | `run_bash()` simple blacklist | `BashSecurityValidator` regex validation |
| Tool Execution | Direct execution | Execute after permission check |
| User Interaction | None | ask_user() approval |
| Configuration | Hardcoded parameters | DEFAULT_RULES + runtime commands |
| Operation Modes | None | default/plan/auto |

### Inheritance Relationship

s07 core extensions:
- Added `BashSecurityValidator` class
- Added `PermissionManager` class
- Added `is_workspace_trusted()` function
- Modified `execute_tool_calls()` to integrate permission checks
- Modified main loop to support `/mode` and `/rules` commands

## Practice Guide

### Test Example

**Dangerous Command Interception**:

```bash
# Start s07
python s07_permission_system.py

# Test sudo command (should be directly denied)
Agent: bash(command="sudo apt update")
# Output: [DENIED] bash: Bash validator: sudo (pattern: \bsudo\b)

# Test command substitution (should ask user)
Agent: bash(command="echo $(whoami)")
# Output: [Permission] bash: {"command": "echo $(whoami)"}
#       Allow? (y/n/always):
```

**Mode Switching**:

```bash
# Switch to plan mode (block writes)
s01 >> /mode plan
[Switched to plan mode]

# Try to write file (should be denied)
Agent: write_file(path="test.txt", content="hello")
# Output: [DENIED] write_file: Plan mode: write operations are blocked

# Read file (should be allowed)
Agent: read_file(path="test.txt")
# Output: [Tool: read_file]: <file content>
```

### Permission Rule Configuration Example

**Add Custom Rules**:

```python
# View current rules via /rules after startup
s01 >> /rules
  0: {'tool': 'bash', 'content': 'rm -rf /', 'behavior': 'deny'}
  1: {'tool': 'bash', 'content': 'sudo *', 'behavior': 'deny'}
  2: {'tool': 'read_file', 'path': '*', 'behavior': 'allow'}

# Add rules at runtime (via ask_user's always option)
Agent: write_file(path="output.txt", content="data")
# Output: [Permission] write_file: {"path": "output.txt", ...}
#       Allow? (y/n/always): always
# Rule list automatically adds: {'tool': 'write_file', 'path': '*', 'behavior': 'allow'}
```

## Summary

### Core Design Philosophy

s07 achieves transition from "execute all requests" to "execute after verification" through introducing permission management system. Four-layer pipeline ensures dangerous operations are intercepted, while retaining user's final decision authority for operations without explicit rules. Three operation modes adapt to scenarios with different security requirements.

### Version Description

- **Base Version**: Current implementation is teaching version, rule system and validators kept concise
- **Extension Points**: VALIDATORS list, DEFAULT_RULES, operation modes are all extensible
- **Trust Mechanism**: `is_workspace_trusted()` is basic implementation, can expand more complex trust flows
