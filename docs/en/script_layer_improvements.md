# v1_task_manager Script Layer Improvements Analysis

本DocumentAnalysis `v1_task_manager` DirectoryEach Chapter Python Code `if __name__ == "__main__":` Script Layer Changes Below，TrackEvolution Process from Simple Interactive Loop to Event-driven Architecture。

---

## Directory Structure

Existing Chapters：
- `chapter_1` 至 `chapter_14`（Continuous）
- `chapter_18_2`（s18_v2_singleagent_worktree_task_isolation.py）
- `chapter_19_2`（s19_v2_mcp_plugin.py）

Note：`chapter_15` 至 `chapter_17` Does Not Exist in This Directory。

---

## Evolution Stage Overview

| Chapter | File Name | Main Script Layer Changes |
|------|--------|---------------|
| chapter_1 | agent_loop.py | Basic Interactive Loop |
| chapter_2 | s02_tool_use.py | Same as chapter_1 Basically Consistent |
| chapter_3 | s03_skill_loading.py | Same as chapter_1 Basically Consistent |
| chapter_4 | s04_todo_write.py | Same as chapter_1 Basically Consistent |
| chapter_5 | s05_subagent.py | Output Processing Enhancement，Color Printing |
| chapter_6 | s06_context.py | Context Compression State Retention |
| chapter_7 | s07_permission_system.py | Permission Mode Selection，Runtime Commands `/mode`、`/rules` |
| chapter_8 | s08_hook_system.py | Dynamic Authorization Command `/allow` |
| chapter_9 | s09_memory_system.py | Memory Loading，`/memories` Commands |
| chapter_10 | s10_build_system.py | System Prompt Builder `prompt_builder.main_build()` |
| chapter_11 | s11_Resume_system.py | Dynamic Prompt（Todo Progress），`/clear` Commands |
| chapter_12 | s12_task_system.py | Prompt LabelFrom "Todo" Change to "Tasks" |
| chapter_13 | s13_v2_backtask.py | Same as chapter_12 Basically Consistent |
| chapter_14 | s14_cron_scheduler.py | Event-driven Architecture，Multi-threaded Event Queue |
| chapter_18_2 | s18_v2_singleagent_worktree_task_isolation.py | Worktree Information Display |
| chapter_19_2 | s19_v2_mcp_plugin.py | MCP Plugin Initialization，`/tools`、`/mcp` Commands |

---

## Detailed Analysis

### Capiter 1-4：Basic Interactive Loop

**File**：
- `chapter_1/agent_loop.py`
- `chapter_2/s02_tool_use.py`
- `chapter_3/s03_skill_loading.py`
- `chapter_4/s04_todo_write.py`

**Script Layer Code Structure**：

```python
if __name__ == "__main__":
    history = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    while True:
        query = input("User: ")
        if query.lower() in ("q", "exit"):
            break
        
        history.append({"role": "user", "content": query})
        state = LoopState(messages=history)
        agent_loop(state)
        history = state.messages
        
        last_message = state.messages[-1]
        raw_content = (
            last_message.content
            if hasattr(last_message, "content")
            else last_message.get("content", "")
        )
        final_text = extract_text(raw_content)
        if final_text:
            print(f"[最终回复] {final_text}")
        print()
```

**Features**：
- Simple `while input()` Loop
- Basic History Management
- Unified Output Processing Logic（Compatible `ChatCompletionMessage` ObjectandDictionary）

**Evolution Description**：
- The Script Layer Logic of These Four Chapters is Basically Consistent
- Main Changes Occur at Core Logic Layer（Such as chapter_4 Introduction TodoManager），But Script Layer Entry Code Remains Unchanged

---

### Capiter 5：Output Processing Enhancement

**File**：`chapter_5/s05_subagent.py`

**New Content**：

```python
# 彩色打印最终回复
print(f"\033[32m[最终回复]\033[0m {final_text}")
```

**变化Description**：
- Use ANSI 转义序列 `\033[32m` 将finally回复Markfor绿色
- EnhanceOutput可读性，区分UserInputand agent 回复

---

### Capiter 6：Context Compression State Retention

**File**：`chapter_6/s06_context.py`

**New Content**：

```python
compact_state = CompactState()
# ... 循环中 ...
history = state.messages  # 使用 state.messages 而非直接赋值
```

**变化Description**：
- Introduction `CompactState()` ObjectUsed forTrackContext压缩State
- LoopEndafterUpdate `history = state.messages` 以Support压缩after 消息List保持
- forafter续Context压缩FunctionProvideState持久化Support

---

### Capiter 7：权限模Control

**File**：`chapter_7/s07_permission_system.py`

**New Content**：

```python
# 启动时选择权限模式
mode_input = input(f"Mode ({'/'.join(MODES)}): ").strip()
if mode_input in MODES:
    perms.mode = mode_input
    print(f"[Switched to {mode_input} mode]")

# 运行时命令
if query.startswith("/mode"):
    parts = query.split()
    if len(parts) == 2 and parts[1] in MODES:
        perms.mode = parts[1]
        print(f"[Switched to {parts[1]} mode]")
    else:
        print(f"Usage: /mode <{'|'.join(MODES)}>")
    continue

if query.strip() == "/rules":
    for i, rule in enumerate(perms.rules):
        print(f"  {i}: {rule}")
    continue
```

**变化Description**：
- 启动时允许User选择权限模（default/plan/auto）
- 新增 `/mode <mode>` Commands，SupportRun时切换权限模
- 新增 `/rules` Commands，查看当before权限RulesList

---

### Capiter 8：Dynamic Authorization Command

**File**：`chapter_8/s08_hook_system.py`

**New Content**：

```python
if query.startswith("/allow"):
    parts = query.split(maxsplit=1)
    if len(parts) == 2:
        target_dir = parts[1].strip()
        if not target_dir.endswith("*"):
            target_dir = target_dir.rstrip("/\\") + "/*"
        perms.rules.append({"tool": "*", "path": target_dir, "behavior": "allow"})
        perms.consecutive_denials = 0
        print(f"\033[32m[Granted] 已主动授权框架操作目录：{target_dir}\033[0m")
    else:
        print("Usage: /allow <path/to/folder>")
    continue
```

**变化Description**：
- 新增 `/allow <path>` Commands，Used for动态授予SpecificTable of Contents 写权限
- 自动Specification化路径（添加 `/*` after缀IndicateTable of Contents及其子Table of Contents）
- ResetContinuous拒绝Counter，避免触发自动ProtectionMechanism

---

### Capiter 9：Memory System初始化

**File**：`chapter_9/s09_memory_system.py`

**New Content**：

```python
# 启动时加载 Memory
compact_state = CompactState()
memory_mgr.load_all()
mem_count = len(memory_mgr.memories)
if mem_count:
    print(f"[{mem_count} memories loaded into context]")
else:
    print("[No existing memories. The agent can create them with save_memory.]")

# 执行 SessionStart Hook
start_result = hooks._run_external_hooks("SessionStart", {"trigger": True})
for msg in start_result.get("messages", []):
    print(f"\033[35m👋 [SessionStart Hook]: {msg}\033[0m")

# 新增 /memories 命令
if query.strip() == "/memories":
    if memory_mgr.memories:
        for name, mem in memory_mgr.memories.items():
            print(f"  [{mem['type']}] {name}: {mem['description']}")
    else:
        print("  (no memories)")
    continue
```

**变化Description**：
- 启动时Call `memory_mgr.load_all()` 加载持久化记忆
- 打印记忆加载计数，ProvideStateFeedback
- Execute `SessionStart` Hook，Support会话启动时 outside部回调
- 新增 `/memories` Commands，列出当before加载 记忆

---

### Capiter 10：System Prompt Builder

**File**：`chapter_10/s10_build_system.py`

**New Content**：

```python
main_system = prompt_builder.main_build()
history = [{"role": "system", "content": main_system}]
```

**变化Description**：
- Introduction `SystemPromptBuilder`（`prompt_builder`）
- Call `main_build()` 动态GenerateSystemHint词
- 替代硬编码 `SYSTEM_PROMPT` 常量，Support更灵活 Hint词组装

---

### Capiter 11：Dynamic Promptand会话清理

**File**：`chapter_11/s11_Resume_system.py`

**New Content**：

```python
# 动态提示符（显示 Todo 进度）
todo_count = len(TODO.items)
todo_done = sum(1 for t in TODO.items.values() if t.get("status") == "done")
active_task = next((t["title"] for t in TODO.items.values() if t.get("status") == "active"), "none")
prompt = f"\033[36m[Todo {todo_done}/{todo_count} | {active_task}]\033[0m\nUser: "
query = input(prompt)

# /clear 命令
if query.strip() == "/clear":
    main_system = prompt_builder.main_build()
    history = [{"role": "system", "content": main_system}]
    TODO.items = {}
    compact_state = CompactState()
    print("\033[32m[Session Cleared] 历史记录与任务状态已清空，准备开始新任务。\033[0m")
    continue
```

**变化Description**：
- **UI Upgrade**：Hint符动态Show Todo Progress `[Todo x/y | active_task...]`
- Use ANSI 转义序列 `\033[36m` 将Hint符Markfor青色
- 新增 `/clear` Commands，Reset会话State（历史记录、Todo List、压缩State）
- Solution退FormatShowQuestion（through ANSI 序列包装Hint符）

---

### Capiter 12：任务System适配

**File**：`chapter_12/s12_task_system.py`

**变化inside容**：

```python
# 提示符标签从 "Todo" 变为 "Tasks"
task_count = len(TASKS.items)
task_done = sum(1 for t in TASKS.items.values() if t.get("status") == "done")
active_task = next((t["title"] for t in TASKS.items.values() if t.get("status") == "active"), "none")
prompt = f"\033[36m[Tasks {task_done}/{task_count} | {active_task}]\033[0m\nUser: "

# /clear 命令适配新的 TASKS 对象
if query.strip() == "/clear":
    main_system = prompt_builder.main_build()
    history = [{"role": "system", "content": main_system}]
    TASKS.rounds_since_update = 0  # 改为重置 TASKS 而非 TODO
    compact_state = CompactState()
    continue
```

**变化Description**：
- Data源From `TODO` Object切换for `TASKS` Object
- Prompt LabelFrom "Todo" Change to "Tasks"
- `/clear` Commands改forReset `TASKS.rounds_since_update` Rather Than `TODO.items`

---

### Capiter 13：basic保持不变

**File**：`chapter_13/s13_v2_backtask.py`

**变化Description**：
- 脚本层逻辑Same as chapter_12 Basically Consistent
- Discover一行被Note释掉 `BG.drain_notifications()` Call（未实际生效）
- main变化at Core Logic Layer（BackgroundManager 修复），脚本层无明显改动

---

### Capiter 14：Event-driven Architecture

**File**：`chapter_14/s14_cron_scheduler.py`

**Architecture重大变化**：No LongerUseSimple `while input()` Loop，IntroductionMulti-threaded Event QueueMechanism。

**核心改动**：

```python
# ── 启动事件驱动线程 ──────────────────────────────────
_event_queue: Queue = Queue()
_stop_cron_watcher = threading.Event()
_input_ready = threading.Event()
_input_ready.set()   # 初始状态：允许立刻显示提示符

threading.Thread(
    target=input_reader, args=(_event_queue, _input_ready), daemon=True, name="input_reader"
).start()
threading.Thread(
    target=cron_watcher, args=(_event_queue, _stop_cron_watcher),
    daemon=True, name="cron_watcher"
).start()

# ── 主循环：阻塞在 event_queue 上，由任意事件唤醒 ───────────────
try:
    while True:
        event_type, content = _event_queue.get()  # 任意事件到来即唤醒

        # ── quit ────────────────────────────────────────────────────
        if event_type == "quit":
            _stop_cron_watcher.set()
            scheduler.stop()
            break

        # ── cron 触发：无需用户输入，直接注入历史并运行 agent_loop ──
        if event_type == "cron":
            print()
            history.append({
                "role": "user",
                "content": f"<cron-notification>\n{content}\n</cron-notification>",
            })
            state = LoopState(messages=history)
            agent_loop(state, compact_state)
            history = state.messages
            # ... 输出处理 ...
            _input_ready.set()   # 恢复提示符
            continue

        # ── user 输入 ────────────────────────────────────────────────
        query = content
        # ... 处理用户输入和命令 ...
```

**新增Commands**：
- `/cron`：查看定时任务List
- `/test`：触发Test事件，Verify cron NotifyMechanism

**Resource清理逻辑**：

```python
finally:
    _input_ready.set()       # 解除 input_reader 的 wait() 阻塞
    _stop_cron_watcher.set()
    scheduler.stop()
    # 还原 stdout/stderr
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    if _log_file is not None:
        try:
            _log_file.close()
        except Exception:
            pass
    # 还原终端状态
    if _saved_tty is not None:
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _saved_tty)
        except Exception:
            pass
    print("\n[Bye]")
```

**变化Description**：
- **Architecture变更**：From同步 `input()` LoopChange to异步事件驱动Model
- **多线程**：`input_reader` 线程Responsible读取UserInput，`cron_watcher` 线程Responsible定时任务触发
- **事件队列**：主Loop阻塞at `_event_queue.get()` on，Process三种事件Type：
 - `quit`：Exit会话
 - `cron`：定时任务触发（无需UserInput）
 - `user`：UserInput
- **会话日志**：Use `_Tee` Class将 stdout/stderr 重定towardto日志File
- **终端StateProtection**：保存and还原 termios 设置，防止 Ctrl+C Exitafter终端StateException

---

### Capiter 18_2：Worktree 任务Isolation

**File**：`chapter_18_2/s18_v2_singleagent_worktree_task_isolation.py`

**New Content**：

```python
# [s18_v2] 启动时显示 worktree 和 repo root 信息
print(f"[Repo root: {REPO_ROOT}]")
if not WORKTREES.git_available:
    print("[Note: Not in a git repo. worktree_* tools will return errors.]")
else:
    wt_list = WORKTREES.list_all()
    print(f"[Worktrees: {wt_list}]")
```

**变化Description**：
- 启动时DetectandShow git 仓库根Table of Contents
- Show当before worktree List
- if不at git 仓库in，Hint worktree RelatedTool将Return错误
- 脚本层主体逻辑Same as chapter_14 保持一致（Event-driven Architecture）

---

### Capiter 19_2：MCP PluginSystem

**File**：`chapter_19_2/s19_v2_mcp_plugin.py`

**New Content**：

```python
# [s19_v2] MCP Plugin 初始化：扫描插件 → 连接 MCP server → 注册工具
_mcp_plugin_names = plugin_loader.scan()
if _mcp_plugin_names:
    print(f"[MCP] Found {len(_mcp_plugin_names)} plugin(s): {', '.join(_mcp_plugin_names)}")
    for server_full_name, server_cfg in plugin_loader.get_mcp_servers().items():
        command = server_cfg.get("command", "")
        args = server_cfg.get("args", [])
        env = server_cfg.get("env", {})
        mcp_client = MCPClient(server_full_name, command, args, env)
        print(f"[MCP] Connecting to server '{server_full_name}': {command} {' '.join(args)}")
        if mcp_client.connect():
            tools_list = mcp_client.list_tools()
            mcp_router.register_client(mcp_client)
            print(f"[MCP] '{server_full_name}' connected: {len(tools_list)} tool(s)")
        else:
            print(f"[MCP] '{server_full_name}' connection failed, skipping.")
    total_mcp = len(mcp_router.get_all_tools())
    if total_mcp:
        print(f"[MCP] {total_mcp} MCP tool(s) available. Use /mcp to inspect.")
else:
    print("[MCP] No plugins found. To add an MCP server, create .claude-plugin/plugin.json.")

# 新增 /tools 命令
if query.strip() == "/tools":
    all_tools = build_mcp_tool_pool(PARENT_TOOLS)
    native_tools_disp = [t for t in all_tools if not t.get("function", {}).get("name", "").startswith("mcp__")]
    mcp_tools_disp    = [t for t in all_tools if     t.get("function", {}).get("name", "").startswith("mcp__")]
    print(f"  Native tools ({len(native_tools_disp)}):")
    for tool in native_tools_disp:
        func = tool.get("function", {})
        print(f"    {func.get('name','')}: {func.get('description','')[:60]}")
    if mcp_tools_disp:
        print(f"  MCP tools ({len(mcp_tools_disp)}):")
        for tool in mcp_tools_disp:
            func = tool.get("function", {})
            print(f"    {func.get('name','')}: {func.get('description','')[:60]}")
    continue

# 新增 /mcp 命令
if query.strip() == "/mcp":
    if mcp_router.clients:
        for server_name, mcp_client in mcp_router.clients.items():
            tool_count = len(mcp_client.get_agent_tools())
            alive = mcp_client.process and mcp_client.process.poll() is None
            status = "connected" if alive else "disconnected"
            print(f"  [{status}] {server_name}: {tool_count} tool(s)")
            for t in mcp_client.get_agent_tools():
                tname = t.get("function", {}).get("name", "")
                tdesc = t.get("function", {}).get("description", "")[:60]
                print(f"    - {tname}: {tdesc}")
    else:
        print("  (no MCP servers connected)")
    continue

# /mode 命令扩展：同时设置 native 和 mcp 权限模式
if query.startswith("/mode"):
    parts = query.split()
    if len(parts) == 2 and parts[1] in MODES:
        perms.mode = parts[1]
        mcp_gate.mode = parts[1] if parts[1] in PERMISSION_MODES else "default"
        print(f"[Switched to {parts[1]} mode] (native: {perms.mode}, mcp: {mcp_gate.mode})")
    else:
        print(f"Usage: /mode <{'|'.join(MODES)}>")
    continue

# /allow 命令扩展：同时更新 ALLOWED_PATHS 白名单
if query.startswith("/allow"):
    parts = query.split(maxsplit=1)
    if len(parts) == 2:
        target_dir = parts[1].strip()
        if not target_dir.endswith("*"):
            target_dir = target_dir.rstrip("/\\") + "/*"
        perms.rules.append({"tool": "*", "path": target_dir, "behavior": "allow"})
        perms.consecutive_denials = 0
        ALLOWED_PATHS.add(Path(target_dir.rstrip("/*")).resolve())
        print(f"\033[32m[Granted] 已主动授权框架操作目录：{target_dir}\033[0m")
        print(f"  当前 bash 白名单路径 ({len(ALLOWED_PATHS)}):")
        for ap in sorted(str(p) for p in ALLOWED_PATHS):
            print(f"    {ap}")
    else:
        print("Usage: /allow <path/to/folder>")
    continue
```

**清理逻辑Extend**：

```python
finally:
    # ... 原有清理逻辑 ...
    # [s19_v2] 清理 MCP 连接
    for _c in mcp_router.clients.values():
        try:
            _c.disconnect()
        except Exception:
            pass
    print("\n[Bye]")
```

**变化Description**：
- **MCP Plugin Initialization**：扫描 `.claude-plugin/plugin.json`，连接 MCP 服务器，Note册Tool
- **新增 `/tools` Commands**：Showall可用Tool（Native Tooland MCP Tool分ClassDisplay）
- **新增 `/mcp` Commands**：Show MCP 服务器连接StateandToolList
- **`/mode` CommandsExtend**：同时设置 native 权限模（`perms.mode`）and MCP 权限模（`mcp_gate.mode`）
- **`/allow` CommandsExtend**：同时Update权限Rules（`perms.rules`）and bash 白名单路径（`ALLOWED_PATHS`）
- **清理逻辑**：Exit时断开all MCP 客户端连接

---

## 演变Summary

### Architecture演进路线

1. **Stage 1（chapter_1-4）**：Basic Interactive Loop
 - Simple `while input()` 同步Loop
 - 无Runtime Commands，OnlySupport `q`/`exit` Exit

2. **Stage 2（chapter_5-9）**：FunctionEnhance期
 - 彩色Output（chapter_5）
 - Context Compression State Retention（chapter_6）
 - 权限模Control（chapter_7）
 - 动态Authorization（chapter_8）
 - Memory System（chapter_9）
 - 斜杠CommandsSystem逐步Establish

3. **Stage 3（chapter_10-13）**：System完善期
 - 动态Hint词Build（chapter_10）
 - Dynamic Prompt UI（chapter_11）
 - 任务System适配（chapter_12）
 - 斜杠Commands：`/mode`、`/rules`、`/allow`、`/memories`、`/clear`

4. **Stage 4（chapter_14）**：ArchitectureUpgrade
 - From同步LoopUpgradeforEvent-driven Architecture
 - Introduction多线程and事件队列
 - Support定时任务自动触发（无需UserInput）
 - 新增 `/cron`、`/test` Commands

5. **Stage 5（chapter_18_2-19_2）**：生态Extend
 - Worktree 任务Isolation（chapter_18_2）
 - MCP PluginSystem（chapter_19_2）
 - 斜杠Commands：`/tools`、`/mcp`

### 脚本层CommandsSummary

| Commands | IntroductionChapter | Function |
|------|----------|------|
| `q`/`exit` | chapter_1 | Exit会话 |
| `/mode <mode>` | chapter_7 | 切换权限模（default/plan/auto） |
| `/rules` | chapter_7 | 查看权限RulesList |
| `/allow <path>` | chapter_8 | 动态AuthorizationTable of Contents写权限 |
| `/memories` | chapter_9 | 列出已加载 记忆 |
| `/clear` | chapter_11 | 清空会话State（历史、任务、压缩State） |
| `/cron` | chapter_14 | 查看定时任务List |
| `/test` | chapter_14 | 触发Test cron 事件 |
| `/tools` | chapter_19_2 | Showall可用Tool（Native + MCP） |
| `/mcp` | chapter_19_2 | Show MCP 服务器连接State |

### 关键Technology点

1. **事件驱动Model**（chapter_14）：
 - 主Loop阻塞at事件队列on，No Longer主动轮询UserInput
 - Support多种事件源：UserInput、定时任务、Future可ExtendOther事件
 - through `_input_ready` 事件ControlHint符ShowTiming，避免Hint符打断 agent Output

2. **终端StateProtection**（chapter_14）：
 - 启动时保存 termios 设置
 - Exit时at `finally` 块in还原，防止 Ctrl+C Lead to终端Exception
 - Use `_Tee` ClassImplement日志File重定toward

3. **MCP PluginArchitecture**（chapter_19_2）：
 - Plugin扫描 → 服务器连接 → ToolNote册 初始化Process
 - Independent MCP 权限门控（`mcp_gate`）
 - 统一 Tool池Build（`build_mcp_tool_pool`）

---

## 结语

From chapter_1 to chapter_19_2，脚本层经历了FromSimple交互LooptoComplexEvent-driven Architecture 演变。核心改动Including：

1. 交互模：同步 `input()` → 异步事件队列
2. CommandsSystem：无Commands → 10+ 斜杠Commands
3. StateManage：Simple历史记录 → 压缩State、任务State、记忆State、worktree State
4. ExtendAbility：单体脚本 → MCP PluginSystem

脚本层asUserSame as核心逻辑 桥梁，逐步承担起State初始化、CommandsParse、事件分发、Resource清理etc.Duty，foron层FunctionProvide稳定 RunEnvironment。
