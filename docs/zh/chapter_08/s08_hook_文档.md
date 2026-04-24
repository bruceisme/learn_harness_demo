# s08: Hook System (钩子系统) - 代码文档

## 概述

s08 在 s07 权限系统的基础上引入了**可扩展的 Hook 插件系统**。核心改进是从硬编码的权限检查转向事件驱动的拦截器管线架构。

### 核心改进

1. **HookManager 类** - 统一管理钩子的加载和执行
2. **HOOK_EVENTS 元组** - 定义支持的事件类型（PreToolUse, PostToolUse, SessionStart）
3. **双层拦截管线** - Ring 0（内置安全/权限）+ Ring 1（外部自定义 Hook）
4. **.hooks.json 配置** - 外部定义钩子脚本
5. **matcher 匹配机制** - Hook 只针对特定工具触发
6. **环境变量注入** - HOOK_EVENT, HOOK_TOOL_NAME, HOOK_TOOL_INPUT, HOOK_TOOL_OUTPUT
7. **三层返回值处理** - updatedInput, additionalContext, permissionDecision
8. **/allow 命令** - 用户主动授予目录权限

### 设计思想

```
┌─────────────────────────────────────────────────────────────────┐
│                      Tool Call 触发                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Ring 0: 内置安全与权限 Hook (PermissionManager)                  │
│  - BashSecurityValidator 正则匹配                                │
│  - deny_rules 检查                                               │
│  - mode 模式判断                                                 │
│  - allow_rules 检查                                              │
│  - ask_user 用户交互                                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │  blocked?         │
                    └─────────┬─────────┘
                       否     │     是
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Ring 1: 外部自定义 Hook (_run_external_hooks)                    │
│  - matcher 工具匹配                                              │
│  - 环境变量注入                                                  │
│  - subprocess 执行脚本                                           │
│  - 返回值解析 (updatedInput, additionalContext, permissionDecision)│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      工具执行                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PostToolUse Hook (仅 Ring 1)                                    │
│  - 工具输出监控                                                  │
│  - 注入消息追加                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      返回结果                                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 与 s07 的对比

### 变更总览

| 组件 | s07 | s08 |
|------|-----|-----|
| 权限管理 | PermissionManager 独立调用 | 集成到 HookManager Ring 0 |
| 扩展机制 | 无 | .hooks.json + HookManager |
| 事件类型 | 无 | PreToolUse, PostToolUse, SessionStart |
| 外部脚本 | 无 | subprocess 执行自定义命令 |
| 环境变量注入 | 无 | HOOK_EVENT, HOOK_TOOL_NAME, HOOK_TOOL_INPUT, HOOK_TOOL_OUTPUT |
| 返回值处理 | behavior (allow/deny/ask) | blocked, messages, updated_input, permission_override |
| 命令行 | /mode, /rules | /mode, /rules, /allow |

### 新增组件架构

```
s08_hook_system.py
├── HOOK_EVENTS                      # 事件类型定义
├── HookManager
│   ├── __init__()                   # 加载 .hooks.json 配置
│   ├── run_pre_tool_use()           # Ring 0 + Ring 1 统一管线
│   ├── run_post_tool_use()          # PostToolUse 拦截
│   ├── _run_external_hooks()        # 外部脚本执行
│   └── _check_workspace_trust()     # 工作区信任检查
├── PermissionManager                # 内置 Ring 0 (保持 s07 逻辑)
├── BashSecurityValidator            # Bash 安全验证器 (保持 s07 逻辑)
└── 命令行处理
    ├── /mode                        # 切换模式 (继承 s07)
    ├── /rules                       # 查看规则 (继承 s07)
    └── /allow                       # 主动授权目录 (新增)
```

---

## s08 新增内容详解（按代码执行顺序）

### 第 1 阶段：Hook 配置与事件定义（新增）

#### HOOK_EVENTS 元组

```python
HOOK_EVENTS = ("PreToolUse", "PostToolUse", "SessionStart")
HOOK_TIMEOUT = 30  # seconds
```

**机制概述**：定义系统支持的钩子事件类型。PreToolUse 在工具执行前触发，用于权限审查和输入修改；PostToolUse 在工具执行后触发，用于输出监控和上下文注入；SessionStart 在会话开始时触发（当前版本未实现）。

#### .hooks.json 配置文件格式

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

**机制概述**：配置文件定义每个事件对应的钩子脚本列表。每个钩子包含 matcher（工具匹配器）和 command（执行命令）。matcher 为 "*" 表示匹配所有工具。

#### HookManager 初始化

```python
class HookManager:
    def __init__(self, perms_manager, config_path: Path = None, sdk_mode: bool = True):
        self.perms = perms_manager  # 注入权限管理器
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

**机制概述**：初始化时注入 PermissionManager 实例，从 `.hooks.json` 加载钩子配置到内存字典。sdk_mode 控制是否跳过工作区信任检查。

## 目录结构依赖

| 文件/目录 | 用途 | 创建方式 |
|-----------|------|----------|
| `.hooks.json` | Hook 配置文件 | 用户手动创建 |
| `.claude/.claude_trusted` | 工作区信任标记 | 用户手动创建 |

**.hooks.json 配置文件格式**：
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

**字段说明**：
- `matcher`: 工具名匹配，`"*"` 表示全局，或指定工具名如 `"bash"`
- `command`: 要执行的 shell 命令或脚本路径

**信任标记文件**（`.claude/.claude_trusted`）：
- 空文件即可
- 非信任工作区会跳过外部 Hook 执行

---

### 第 2 阶段：双层 Hook 架构（新增）

#### Ring 0：内置安全与权限（继承 s07，集成到管线）

```python
def run_pre_tool_use(self, context: dict) -> dict:
    result = {"blocked": False, "block_reason": "", "messages": []}
    tool_name = context.get("tool_name", "")
    tool_input = context.get("tool_input", {})

    # --- [阶段 1: 内置安全与权限 Hook (Ring 0)] ---
    decision = self.perms.check(tool_name, tool_input)
    
    if decision["behavior"] == "deny":
        return {"blocked": True, "block_reason": f"Permission denied: {decision['reason']}", "messages": []}
        
    elif decision["behavior"] == "ask":
        if not self.perms.ask_user(tool_name, tool_input):
            return {"blocked": True, "block_reason": f"User denied execution for {tool_name}", "messages": []}
```

**机制概述**：调用 PermissionManager.check() 执行内置权限检查。逻辑与 s07 完全相同，详见 s07 文档。区别在于 s08 将其作为管线的第一阶段，阻断时直接返回，不再执行 Ring 1。

**Ring 0 执行顺序**（继承 s07）：
1. BashSecurityValidator 正则匹配（危险命令检测）
2. deny_rules 检查
3. mode 模式判断（plan/auto/ask）
4. allow_rules 检查
5. ask_user 用户交互（如需要）

#### Ring 1：外部自定义 Hook（新增）

```python
# --- [阶段 2: 外部自定义 Hook (Ring 1)] ---
ext_result = self._run_external_hooks("PreToolUse", context)
if ext_result["blocked"]:
    return ext_result
else:
    result["messages"].extend(ext_result["messages"])
    if "updated_input" in ext_result:
        context["tool_input"] = ext_result["updated_input"]
    return result
```

**机制概述**：Ring 1 在 Ring 0 通过后执行，支持外部脚本拦截。可修改工具输入、追加消息、或阻断执行。

---

### 第 3 阶段：外部 Hook 执行机制（新增）

#### _run_external_hooks() 方法

```python
def _run_external_hooks(self, event: str, context: dict) -> dict:
    result = {"blocked": False, "block_reason": "", "messages": []}
    if not self._check_workspace_trust():
        return result
        
    hooks = self.hooks.get(event, [])
    for hook_def in hooks:
        # matcher 匹配逻辑
        matcher = hook_def.get("matcher")
        if matcher and context:
            tool_name = context.get("tool_name", "")
            if matcher != "*" and matcher != tool_name:
                continue
        
        command = hook_def.get("command", "")
        if not command: 
            continue
        
        # 环境变量注入
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
            # 返回值解析...
```

**机制概述**：遍历事件对应的钩子列表，对每个钩子执行 matcher 匹配。匹配通过后，注入环境变量并执行 subprocess。根据返回码解析输出：0 表示成功并解析 JSON，1 表示阻断，2 表示注入消息。

#### matcher 匹配机制

```python
matcher = hook_def.get("matcher")
if matcher and context:
    tool_name = context.get("tool_name", "")
    if matcher != "*" and matcher != tool_name:
        continue
```

**机制概述**：matcher 用于限制钩子只对特定工具生效。"*" 表示全局匹配，具体工具名（如 "bash"）表示仅当工具名称匹配时执行。

#### 环境变量注入

| 变量名 | 含义 | 示例 |
|--------|------|------|
| HOOK_EVENT | 事件类型 | PreToolUse |
| HOOK_TOOL_NAME | 工具名称 | bash |
| HOOK_TOOL_INPUT | 工具输入 JSON | {"command": "ls -la"} |
| HOOK_TOOL_OUTPUT | 工具输出 | 仅 PostToolUse 可用 |

**机制概述**：环境变量使外部脚本能访问工具调用的上下文信息。输入和输出限制为 10000 字符，避免环境变量过大。

#### 返回值解析

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

**机制概述**：外部脚本通过标准输出返回 JSON 格式的控制指令：
- `updatedInput`：修改工具输入参数
- `additionalContext`：追加到消息列表的上下文信息
- `permissionDecision`：覆盖权限决策

通过标准错误返回阻断信号（返回码 1）或注入消息（返回码 2）。

---

### 第 4 阶段：run_pre_tool_use 统一管线（新增）

```python
def run_pre_tool_use(self, context: dict) -> dict:
    result = {"blocked": False, "block_reason": "", "messages": []}
    
    # --- [阶段 1: 内置安全与权限 Hook (Ring 0)] ---
    decision = self.perms.check(tool_name, tool_input)
    if decision["behavior"] == "deny":
        return {"blocked": True, "block_reason": f"Permission denied: {decision['reason']}", "messages": []}
    elif decision["behavior"] == "ask":
        if not self.perms.ask_user(tool_name, tool_input):
            return {"blocked": True, "block_reason": f"User denied execution for {tool_name}", "messages": []}

    # --- [阶段 2: 外部自定义 Hook (Ring 1)] ---
    ext_result = self._run_external_hooks("PreToolUse", context)
    if ext_result["blocked"]:
        return ext_result
    else:
        result["messages"].extend(ext_result["messages"])
        if "updated_input" in ext_result:
            context["tool_input"] = ext_result["updated_input"]
        return result
```

**机制概述**：统一管线按顺序执行 Ring 0 和 Ring 1。Ring 0 阻断时直接返回，不执行 Ring 1。Ring 1 的 updated_input 会更新到 context 中供后续工具执行使用。

**返回值格式统一**：
```python
{
    "blocked": bool,           # 是否阻断
    "block_reason": str,       # 阻断原因
    "messages": list,          # 注入的消息列表
    "updated_input": dict,     # 修改后的工具输入 (可选)
    "permission_override": str # 覆盖的权限决策 (可选)
}
```

---

### 第 5 阶段：run_post_tool_use 拦截（新增）

```python
def run_post_tool_use(self, context: dict) -> dict:
    return self._run_external_hooks("PostToolUse", context)
```

**机制概述**：PostToolUse 仅执行 Ring 1 外部 Hook，用于工具执行后的监控和上下文注入。不包含 Ring 0 权限检查，因为工具已经完成执行。

---

### 第 6 阶段：execute_tool_calls 变化（改动）

```python
def execute_tool_calls(response_message) -> tuple[list[dict], str | None, bool, str | None]:
    for tool_call in response_message.tool_calls:
        f_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        args['tool_call_id'] = tool_call.id
        
        if f_name in TOOL_HANDLERS:
            ctx = {"tool_name": tool_call.function.name, "tool_input": args}
            
            # 1. 统一拦截管线：权限检查 + 外部 Pre-Hook
            pre_result = hooks.run_pre_tool_use(ctx)
            
            # 如果被任何机制阻断
            if pre_result.get("blocked"):
                reason = pre_result.get("block_reason", "Blocked by pipeline/hook")
                output = f"Tool blocked by PreToolUse hook: {reason}"
                results.append({"role": "tool", "tool_call_id": tool_call.id, "name": f_name, "content": output})
                continue
            else:
                for msg in pre_result.get("messages", []):
                    results.append({"role": "tool", "tool_call_id": tool_call.id, "name": f_name, "content": f"[Hook message]: {msg}"})
            
            args = ctx.get("tool_input", args)

            # 2. 执行工具本身
            handler = TOOL_HANDLERS.get(f_name)
            output = handler(**args) if handler else f"Unknown: {f_name}"
            
            # 3. 统一拦截管线：外部 Post-Hook
            post_ctx = {"tool_name": f_name, "tool_input": args, "tool_output": output}
            post_result = hooks.run_post_tool_use(post_ctx)
            for msg in post_result.get("messages", []):
                results.append({"role": "tool", "tool_call_id": tool_call.id, "name": f_name, "content": f"[PostHook message]: {msg}"})
```

**机制概述**：工具调用执行流程：
1. 构建 context 包含 tool_name 和 tool_input
2. 调用 run_pre_tool_use() 执行 Ring 0 + Ring 1
3. blocked 时返回错误消息，跳过工具执行
4. 执行工具处理器
5. 调用 run_post_tool_use() 执行 PostToolUse Hook
6. 追加注入消息到结果列表

---

### 第 7 阶段：/allow 命令（新增）

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
        print(f"\033[32m[Granted] 已主动授权框架操作目录：{target_dir}\033[0m")
    else:
        print("Usage: /allow <path/to/folder>")
```

**机制概述**：/allow 命令动态添加 allow 规则，授权对所有工具操作指定目录的权限。自动补全通配符，避免双斜杠问题。

**使用示例**：
```
s01 >> /allow ./data
[Granted] 已主动授权框架操作目录：./data/*

s01 >> /allow src/config
[Granted] 已主动授权框架操作目录：src/config/*
```

---

## 与 s07 的关系

### 简化对比

| 特性 | s07 | s08 |
|------|-----|-----|
| 权限管理 | PermissionManager 独立调用 | HookManager 集成调用 |
| 扩展能力 | 无 | .hooks.json 配置外部脚本 |
| 事件系统 | 无 | HOOK_EVENTS 元组 |
| 环境变量注入 | 无 | 4 个 HOOK_* 环境变量 |
| 返回值格式 | behavior (allow/deny/ask) | blocked/messages/updated_input |
| 命令行 | /mode, /rules | /mode, /rules, /allow |

### 继承内容（详见 s07 文档）

以下内容在 s08 中保持不变，详细说明请参阅 s07 文档：

- **PermissionManager 类**：逻辑完全保留，作为 Ring 0 集成到管线
- **BashSecurityValidator**：危险命令正则验证逻辑不变
- **MODES 三种运行模式**：plan/auto/ask 模式判断逻辑不变
- **DEFAULT_RULES 默认规则**：内置允许/拒绝规则列表不变
- **用户交互审批流程**：ask_user() 方法的 y/n/always 交互逻辑不变
- **/mode 和 /rules 命令**：命令行支持完全继承

---

## 实践指南

### .hooks.json 配置示例

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

### 外部脚本示例

**PreToolUse Hook (bash)**：
```bash
#!/bin/bash
# hooks/check_bash.sh

# 检查是否有危险命令
if echo "$HOOK_TOOL_INPUT" | grep -q "rm -rf"; then
    echo "Blocked: rm -rf detected" >&2
    exit 1
fi

# 返回修改后的输入
echo '{"updatedInput": {"command": "ls -la"}}'
exit 0
```

**PostToolUse Hook (Python)**：
```python
#!/usr/bin/env python3
# hooks/log_writes.py

import os
import json

tool_output = os.environ.get("HOOK_TOOL_OUTPUT", "")

# 记录到日志文件
with open(".hook_logs/write_operations.log", "a") as f:
    f.write(f"Output: {tool_output}\n")

# 注入上下文消息
print(json.dumps({
    "additionalContext": f"File operation logged at {time.time()}"
}))
```

### /allow 命令使用

```
s01 >> /allow ./data
[Granted] 已主动授权框架操作目录：./data/*

s01 >> /allow src/config
[Granted] 已主动授权框架操作目录：src/config/*
```

**注意**：授权会追加到 rules 列表，当前会话有效。

### 测试示例

1. 创建测试 Hook：
```bash
mkdir -p hooks
cat > hooks/test_hook.sh << 'EOF'
#!/bin/bash
echo '{"additionalContext": "Hook executed successfully"}'
EOF
chmod +x hooks/test_hook.sh
```

2. 创建配置文件：
```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "*", "command": "./hooks/test_hook.sh"}
    ]
  }
}
```

3. 运行框架并调用任意工具，观察输出中的 `[Hook message]`。

---

## 总结

### 核心设计思想

s08 通过引入 Hook 系统，将 s07 的硬编码权限检查扩展为事件驱动的可插拔架构。双层拦截管线（Ring 0 + Ring 1）在保持安全基线的同时提供了可扩展能力。

### 版本说明

- **文件路径**：v1_task_manager/chapter_08/s08_hook_system.py
- **配置路径**：.hooks.json（工作区根目录）