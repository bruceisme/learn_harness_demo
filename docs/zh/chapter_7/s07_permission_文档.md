# s07: Permission System (权限系统) - 代码文档

## 概述

s07 在 s06 的基础上引入了权限管理系统，使 Agent 在执行工具调用前必须经过安全检查。

**核心改进**：
- 从无权限检查到四层权限流水线
- 分层验证 + 用户最终控制的设计思想
- 三种运行模式支持不同自动化程度

**设计思想**：
- 危险命令预先拦截（BashSecurityValidator）
- 规则驱动的权限决策（DEFAULT_RULES）
- 用户保留最终决定权（ask_user）

## 与 s06 的对比

### 变更总览

| 组件 | s06 | s07 |
|------|-----|-----|
| 权限检查 | 无 | 四层流水线 |
| Bash 命令验证 | 简单字符串匹配 | BashSecurityValidator 类 |
| 运行模式 | 无 | default/plan/auto |
| 用户交互 | 无 | y/n/always 审批 |
| 命令行支持 | 无 | /mode, /rules |

### 新增组件架构

```
┌─────────────────────────────────────────────────────────┐
│                    Tool Call                            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│           BashSecurityValidator                         │
│   验证 sudo, rm_rf, cmd_substitution 等危险模式         │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              PermissionManager.check()                  │
│  ┌─────────────────────────────────────────────────┐   │
│  │ Step 0: Bash 安全验证 (严重模式直接 deny)        │   │
│  │ Step 1: Deny 规则匹配 (先匹配先胜利)             │   │
│  │ Step 2: Mode 检查 (plan 模式禁止写入)           │   │
│  │ Step 3: Allow 规则匹配                          │   │
│  │ Step 4: Ask User (默认行为)                     │   │
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
│   根据 behavior 分支处理                                │
└─────────────────────────────────────────────────────────┘
```

## 按执行顺序详解

### 第 1 阶段：BashSecurityValidator 类

**机制概述**：
`BashSecurityValidator` 类负责在执行 bash 命令前进行危险模式检测。它使用正则表达式匹配五种预定义的危险模式，对于严重威胁（`sudo`、`rm_rf`）直接拒绝，其他模式升级为询问用户。

```python
class BashSecurityValidator:
    VALIDATORS = [
        ("sudo", r"\bsudo\b"),                 # 权限提升
        ("rm_rf", r"\brm\s+(-[a-zA-Z]*)?r"),  # 递归删除
        ("cmd_substitution", r"\$\("),          # 命令替换
        ("ifs_injection", r"\bIFS\s*="),        # IFS 变量注入
    ]
    
    def validate(self, command: str) -> list:
        """检查命令是否触发任何验证器，返回失败列表"""
        failures = []
        for name, pattern in self.VALIDATORS:
            if re.search(pattern, command):
                failures.append((name, pattern))
        return failures
    
    def is_safe(self, command: str) -> bool:
        """便捷方法：无验证器触发则返回 True"""
        return len(self.validate(command)) == 0
    
    def describe_failures(self, command: str) -> str:
        """生成人类可读的验证失败描述"""
        failures = self.validate(command)
        if not failures:
            return "No issues detected"
        parts = [f"{name} (pattern: {pattern})" for name, pattern in failures]
        return "Security flags: " + ", ".join(parts)
```

**VALIDATORS 列表说明**：

| 验证器名称 | 正则模式 | 检测目标 |
|-----------|----------|----------|
| sudo | `\bsudo\b` | 权限提升命令 |
| rm_rf | `\brm\s+(-[a-zA-Z]*)?r` | 递归删除操作 |
| cmd_substitution | `\$\(` | 命令替换语法 |
| ifs_injection | `\bIFS\s*=` | 环境变量注入 |

### 第 2 阶段：工作区信任机制

**机制概述**：
`is_workspace_trusted()` 函数通过检查工作区是否存在特定的标记文件来判断该工作区是否被用户显式信任。这是一个简化的信任机制，为后续扩展更复杂的信任流程提供基础。

```python
def is_workspace_trusted(workspace: Path = None) -> bool:
    ws = workspace or WORKDIR
    trust_marker = ws / ".claude" / ".claude_trusted"
    return trust_marker.exists()
```

**信任标记文件**：
- 路径：`.claude/.claude_trusted`（相对于工作目录）
- 作用：显式标记受信任的工作区
- 当前版本：仅作为基础机制，未在主流程中强制使用

## 目录结构依赖

| 文件/目录 | 用途 | 创建方式 |
|-----------|------|----------|
| `.claude/.claude_trusted` | 工作区信任标记 | 用户手动创建 |

**信任标记文件**：
- 空文件即可
- 存在于工作区时表示信任该目录
- 影响 Hook 系统的外部 Hook 执行（非信任工作区跳过外部 Hook）

### 第 3 阶段：权限规则定义

**机制概述**：
`DEFAULT_RULES` 是一个权限规则列表，每条规则定义了对特定工具、路径或内容的允许/拒绝行为。规则按顺序检查，先匹配的规则生效（First Match Wins）。

```python
DEFAULT_RULES = [
    # 始终拒绝危险模式
    {"tool": "bash", "content": "rm -rf /", "behavior": "deny"},
    {"tool": "bash", "content": "sudo *", "behavior": "deny"},
    # 允许读取所有文件
    {"tool": "read_file", "path": "*", "behavior": "allow"},
]
```

**规则格式**：

```python
{
    "tool": "<tool_name 或 *>",      # 工具名称，* 表示匹配所有
    "path": "<glob 模式或 *>",        # 路径匹配（用于文件操作）
    "content": "<fnmatch 模式>",      # 内容匹配（用于 bash 命令）
    "behavior": "allow|deny|ask"      # 行为：允许/拒绝/询问
}
```

**规则匹配顺序**：
1. 规则列表按定义顺序遍历
2. 第一条匹配的规则决定行为
3. 未匹配任何规则时进入 ask 流程

### 第 4 阶段：PermissionManager 类

**机制概述**：
`PermissionManager` 是权限决策的核心组件，实现了四层权限流水线。它支持三种运行模式，管理规则列表，并追踪连续拒绝次数以防止 Agent 陷入重复请求的循环。

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

**三种运行模式**：

| 模式 | 行为 |
|------|------|
| default | 默认模式：遵循规则 + 未匹配时询问用户 |
| plan | 计划模式：禁止所有写入操作，仅允许读取 |
| auto | 自动模式：安全操作自动批准 |

**check() 方法的四层流水线**：

```python
def check(self, tool_name: str, tool_input: dict) -> dict:
    # Step 0: Bash 安全验证 (在 deny 规则之前)
    if tool_name == "bash":
        command = tool_input.get("command", "")
        failures = bash_validator.validate(command)
        if failures:
            severe = {"sudo", "rm_rf"}
            severe_hits = [f for f in failures if f[0] in severe]
            if severe_hits:
                return {"behavior": "deny", "reason": ...}
            return {"behavior": "ask", "reason": ...}
    
    # Step 1: Deny 规则 (始终优先检查)
    for rule in self.rules:
        if rule["behavior"] != "deny":
            continue
        if self._matches(rule, tool_name, tool_input):
            return {"behavior": "deny", "reason": ...}
    
    # Step 2: Mode 检查
    if self.mode == "plan":
        if tool_name in WRITE_TOOLS:
            return {"behavior": "deny", "reason": "Plan mode: write operations are blocked"}
        return {"behavior": "allow", "reason": "Plan mode: read-only allowed"}
    
    if self.mode == "auto":
        return {"behavior": "allow", "reason": "Auto mode: safe operation auto-approved"}
    
    # Step 3: Allow 规则
    for rule in self.rules:
        if rule["behavior"] != "allow":
            continue
        if self._matches(rule, tool_name, tool_input):
            self.consecutive_denials = 0
            return {"behavior": "allow", "reason": ...}
    
    # Step 4: Ask User (默认行为)
    return {"behavior": "ask", "reason": "No rule matched, asking user"}
```

**ask_user() 用户交互**：

```python
def ask_user(self, tool_name: str, tool_input: dict) -> bool:
    preview = json.dumps(tool_input, ensure_ascii=False)[:200]
    print(f"\n  [Permission] {tool_name}: {preview}")
    try:
        answer = input("  Allow? (y/n/always): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    
    if answer == "always":
        # 添加永久允许规则
        self.rules.append({"tool": tool_name, "path": "*", "behavior": "allow"})
        self.consecutive_denials = 0
        return True
    
    if answer in ("y", "yes"):
        self.consecutive_denials = 0
        return True
    
    # 追踪连续拒绝次数
    self.consecutive_denials += 1
    if self.consecutive_denials >= self.max_consecutive_denials:
        print(f"  [{self.consecutive_denials} consecutive denials -- "
              "consider switching to plan mode]")
    return False
```

**_matches() 规则匹配**：

```python
def _matches(self, rule: dict, tool_name: str, tool_input: dict) -> bool:
    # 工具名称匹配
    if rule.get("tool") and rule["tool"] != "*":
        if rule["tool"] != tool_name:
            return False
    
    # 路径模式匹配 (使用 fnmatch)
    if "path" in rule and rule["path"] != "*":
        path = tool_input.get("path", "")
        if not fnmatch(path, rule["path"]):
            return False
    
    # 内容模式匹配 (用于 bash 命令)
    if "content" in rule:
        command = tool_input.get("command", "")
        if not fnmatch(command, rule["content"]):
            return False
    
    return True
```

### 第 5 阶段：execute_tool_calls 变化

**机制概述**：
s07 的 `execute_tool_calls` 函数在工具执行前集成了权限检查。根据 `check()` 返回的 `behavior`（deny/ask/allow）进行分支处理，并追踪连续拒绝次数。

```python
def execute_tool_calls(response_content, perms) -> tuple[list[dict], str | None, bool, str | None]:
    results = []
    for tool_call in response_content.tool_calls:
        f_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        
        if f_name in TOOL_HANDLERS:
            # 权限判断
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

**连续拒绝计数**：
- `consecutive_denials` 在每次用户拒绝后递增
- 用户批准时重置为 0
- 达到 `max_consecutive_denials`（默认 3）时提示用户切换到 plan 模式

### 第 6 阶段：命令行支持

**机制概述**：
主循环中添加了两个命令行指令，支持运行时切换模式和查看规则列表。这些指令在用户输入处理阶段被拦截，不传递给 Agent。

```python
if __name__ == "__main__":
    # 启动时选择模式
    mode_input = input("Mode (default): ").strip().lower() or "default"
    perms = PermissionManager(mode=mode_input)
    
    while True:
        query = input("s01 >> ")
        
        # /mode 命令切换模式
        if query.startswith("/mode"):
            parts = query.split()
            if len(parts) == 2 and parts[1] in MODES:
                perms.mode = parts[1]
                print(f"[Switched to {parts[1]} mode]")
            else:
                print(f"Usage: /mode <{'|'.join(MODES)}>")
            continue
        
        # /rules 命令查看规则
        if query.strip() == "/rules":
            for i, rule in enumerate(perms.rules):
                print(f"  {i}: {rule}")
            continue
        
        # 正常处理用户输入
        history.append({"role": "user", "content": query})
        ...
```

**支持命令**：

| 命令 | 功能 | 示例 |
|------|------|------|
| `/mode <mode>` | 切换运行模式 | `/mode plan` |
| `/rules` | 查看当前规则列表 | `/rules` |

## 完整框架流程图

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
                                 │ (非 bash 或无严重标记)
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│  Step 1: Deny Rules                                                │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ for rule in rules:                                           │ │
│  │   if rule.behavior == "deny" and _matches():                 │ │
│  │     return DENY                                              │ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────┬───────────────────────────────────┘
                                 │ (未匹配 deny 规则)
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
                                 │ (default 模式或未处理)
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
                                 │ (未匹配 allow 规则)
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│  Step 4: Ask User                                                  │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ return ASK (默认行为)                                        │ │
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

## 设计点总结

### 四层权限流水线

1. **Step 0 - Bash 安全验证**：在执行任何规则检查前，先对 bash 命令进行危险模式检测
2. **Step 1 - Deny 规则**：拒绝规则具有最高优先级，匹配即拒绝
3. **Step 2 - Mode 检查**：根据运行模式决定允许或拒绝（plan 模式禁止写入）
4. **Step 3 - Allow 规则**：允许规则匹配后直接通过
5. **Step 4 - Ask User**：未匹配任何规则时询问用户

### 危险命令验证

- 使用正则表达式匹配危险模式
- 严重威胁（sudo, rm_rf）直接拒绝
- 其他威胁升级为询问用户
- 可扩展的 VALIDATORS 列表设计

### 三种运行模式

- **default**：遵循规则，未匹配时询问
- **plan**：只读模式，禁止所有写入操作
- **auto**：自动模式，安全操作自动批准

### 用户最终控制

- 用户通过 `ask_user()` 保留最终决定权
- `always` 选项可添加永久允许规则
- 连续拒绝计数提示用户切换模式

## 整体设计思想总结

1. **分层防御**：Bash 验证 → 规则匹配 → 模式检查 → 用户确认，每层独立生效
2. **规则优先**：显式定义的规则优先于隐式行为，避免模糊决策
3. **用户主权**：所有未明确允许的操作默认询问用户，用户拥有最终决定权
4. **模式驱动**：通过运行模式快速切换安全级别，适应不同场景需求
5. **可追溯性**：每次拒绝都记录原因，连续拒绝触发提示
6. **渐进式信任**：用户可选择 `always` 建立永久信任规则

## 与 s06 的关系

### 对比表格

| 维度 | s06 | s07 |
|------|-----|-----|
| 核心功能 | 上下文压缩 | 权限管理 |
| Bash 处理 | `run_bash()` 简单黑名单 | `BashSecurityValidator` 正则验证 |
| 工具执行 | 直接执行 | 权限检查后执行 |
| 用户交互 | 无 | ask_user() 审批 |
| 配置方式 | 硬编码参数 | DEFAULT_RULES + 运行时命令 |
| 运行模式 | 无 | default/plan/auto |

### 继承关系

s07 的核心扩展：
- 新增 `BashSecurityValidator` 类
- 新增 `PermissionManager` 类
- 新增 `is_workspace_trusted()` 函数
- 修改 `execute_tool_calls()` 集成权限检查
- 修改主循环支持 `/mode` 和 `/rules` 命令

## 实践指南

### 测试示例

**危险命令拦截**：

```bash
# 启动 s07
python s07_permission_system.py

# 测试 sudo 命令（应被直接拒绝）
Agent: bash(command="sudo apt update")
# 输出: [DENIED] bash: Bash validator: sudo (pattern: \bsudo\b)

# 测试命令替换（应询问用户）
Agent: bash(command="echo $(whoami)")
# 输出: [Permission] bash: {"command": "echo $(whoami)"}
#       Allow? (y/n/always):
```

**模式切换**：

```bash
# 切换到 plan 模式（禁止写入）
s01 >> /mode plan
[Switched to plan mode]

# 尝试写入文件（应被拒绝）
Agent: write_file(path="test.txt", content="hello")
# 输出: [DENIED] write_file: Plan mode: write operations are blocked

# 读取文件（应被允许）
Agent: read_file(path="test.txt")
# 输出: [Tool: read_file]: <file content>
```

### 权限规则配置示例

**添加自定义规则**：

```python
# 在启动后通过 /rules 查看当前规则
s01 >> /rules
  0: {'tool': 'bash', 'content': 'rm -rf /', 'behavior': 'deny'}
  1: {'tool': 'bash', 'content': 'sudo *', 'behavior': 'deny'}
  2: {'tool': 'read_file', 'path': '*', 'behavior': 'allow'}

# 运行时添加规则（通过 ask_user 的 always 选项）
Agent: write_file(path="output.txt", content="data")
# 输出: [Permission] write_file: {"path": "output.txt", ...}
#       Allow? (y/n/always): always
# 规则列表自动添加: {'tool': 'write_file', 'path': '*', 'behavior': 'allow'}
```

## 总结

### 核心设计思想

s07 通过引入权限管理系统，实现了从"执行所有请求"到"验证后执行"的转变。四层流水线确保危险操作被拦截，同时保留用户对未明确规则的操作的最终决定权。三种运行模式适应不同安全需求的场景。

### 版本说明

- **基础版本**：当前实现是教学版本，规则系统和验证器保持简洁
- **扩展点**：VALIDATORS 列表、DEFAULT_RULES、运行模式均可扩展
- **信任机制**：`is_workspace_trusted()` 为基础实现，可扩展更复杂的信任流程
