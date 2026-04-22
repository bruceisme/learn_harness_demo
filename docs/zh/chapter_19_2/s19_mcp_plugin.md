# s19_v2_mcp_plugin: MCP & Plugin 系统集成

## 概述

s19_v2 在 s18_v2_singleagent_worktree_task_isolation.py 的基础上集成了 **MCP (Model Context Protocol)** 和 **Plugin System**。核心改动是新增 MCP 客户端、插件发现机制、工具路由和统一权限门，使主代理能够调用外部 MCP 服务器提供的工具。

### 核心改进

1. **CapabilityPermissionGate 类** - 统一权限门，native 工具和 MCP 工具共享同一条控制通道
2. **MCPClient 类** - stdio MCP 客户端（JSON-RPC 2.0），支持 connect/list_tools/call_tool/disconnect
3. **PluginLoader 类** - `.claude-plugin/plugin.json` 插件发现，扫描工作目录中的插件清单
4. **MCPToolRouter 类** - MCP 工具路由，前缀路由 `mcp__{server_name}__{tool_name}`
5. **build_mcp_tool_pool() 函数** - 工具池合并，native 工具优先，MCP 工具附加到末尾
6. **execute_tool_calls() 扩展** - 自动检测 `mcp__` 前缀并路由到 MCPToolRouter，经过权限门检查

### 代码文件路径

- **源代码**：`v1_task_manager/chapter_19_2/s19_v2_mcp_plugin.py`
- **参考文档**：`v1_task_manager/chapter_18_2/s18_v2_singleagent_worktree_task_isolation_文档.md`
- **参考代码**：`v1_task_manager/chapter_18_2/s18_v2_singleagent_worktree_task_isolation.py`
- **插件清单**：`.claude-plugin/plugin.json`
- **MCP 工具命名**：`mcp__{server_name}__{tool_name}`

---

## 与 s18_v2 的对比（变更总览）

| 组件 | s18_v2 | s19_v2 | 变化说明 |
|------|--------|--------|----------|
| 权限门 | PermissionManager（仅 native 工具） | + CapabilityPermissionGate | 新增 MCP 工具权限检查 |
| MCP 客户端 | 无 | MCPClient 类 | 新增 stdio MCP 客户端 |
| 插件发现 | 无 | PluginLoader 类 | 新增 `.claude-plugin/plugin.json` 扫描 |
| 工具路由 | 无 | MCPToolRouter 类 | 新增 `mcp__` 前缀路由 |
| 工具池构建 | PARENT_TOOLS / CHILD_TOOLS | + build_mcp_tool_pool() | 新增 MCP 工具合并 |
| 工具执行 | 仅 native 工具 | + MCP 工具路由 | execute_tool_calls() 扩展 |
| 风险分级 | read/write | read/write/high | 新增 high 风险级别 |
| 权限模式 | default/plan/auto | default/plan/auto | 增加 MCP 特定逻辑 |

---

## s19_v2 新增内容详解（按代码执行顺序）

### PERMSSION_MODES 常量

**实现代码**：
```python
PERMISSION_MODES = ("default", "plan", "auto")
```

**说明**：
- 定义三种权限模式，与 s18_v2 的 MODES 保持一致
- `default`：非读操作均询问用户
- `plan`：只读操作允许，写/高风险操作拒绝
- `auto`：只询问高风险操作，其他自动允许

---

### CapabilityPermissionGate 类（统一权限门）

**实现代码**：
```python
class CapabilityPermissionGate:
    """
    统一权限门：native 工具和 MCP 工具共享同一条控制通道。
    核心教学目标：MCP 工具不绕过权限平面。
    风险分级：read（只读）/ write（写操作）/ high（破坏性操作）。
    """
    READ_PREFIXES = ("read", "list", "get", "show", "search", "query", "inspect")
    HIGH_RISK_PREFIXES = ("delete", "remove", "drop", "shutdown")

    def __init__(self, mode: str = "default"):
        self.mode = mode if mode in PERMISSION_MODES else "default"

    def normalize(self, tool_name: str, tool_input: dict) -> dict:
        if tool_name.startswith("mcp__"):
            parts = tool_name.split("__", 2)
            if len(parts) == 3:
                _, server_name, actual_tool = parts
                source = "mcp"
            else:
                # malformed mcp__ name — still an mcp source, not native
                server_name = None
                actual_tool = tool_name
                source = "mcp"
        else:
            server_name = None
            actual_tool = tool_name
            source = "native"
        lowered = actual_tool.lower()
        if actual_tool == "read_file" or lowered.startswith(self.READ_PREFIXES):
            risk = "read"
        elif actual_tool == "bash":
            command = tool_input.get("command", "")
            risk = "high" if any(
                token in command for token in ("rm -rf", "sudo", "shutdown", "reboot")
            ) else "write"
        elif lowered.startswith(self.HIGH_RISK_PREFIXES):
            risk = "high"
        else:
            risk = "write"
        return {
            "source": source,
            "server": server_name,
            "tool": actual_tool,
            "risk": risk,
        }

    def check(self, tool_name: str, tool_input: dict) -> dict:
        intent = self.normalize(tool_name, tool_input)
        if intent["risk"] == "read":
            return {"behavior": "allow", "reason": "Read capability", "intent": intent}
        if self.mode == "plan" and intent["risk"] in ("write", "high"):
            return {
                "behavior": "deny",
                "reason": "Plan mode blocks write/high-risk MCP tools",
                "intent": intent,
            }
        if self.mode == "auto" and intent["risk"] != "high":
            return {
                "behavior": "allow",
                "reason": "Auto mode for non-high-risk capability",
                "intent": intent,
            }
        if intent["risk"] == "high":
            return {
                "behavior": "ask",
                "reason": "High-risk capability requires confirmation",
                "intent": intent,
            }
        return {
            "behavior": "ask",
            "reason": "State-changing capability requires confirmation",
            "intent": intent,
        }

    def ask_user(self, intent: dict, tool_input: dict) -> bool:
        preview = json.dumps(tool_input, ensure_ascii=False)[:200]
        src  = intent.get("source", "unknown")
        tool = intent.get("tool", "unknown")
        source = (
            f"{src}:{intent['server']}/{tool}"
            if intent.get("server")
            else f"{src}:{tool}"
        )
        print(f"\n  [MCP Permission] {source} risk={intent['risk']}: {preview}")
        try:
            answer = input("  Allow? (y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("y", "yes")
```

**核心机制**：

| 方法 | 功能 | 返回值 |
|------|------|--------|
| `normalize()` | 解析工具名，识别来源（native/MCP）和风险级别 | `{source, server, tool, risk}` |
| `check()` | 根据模式和风险级别决定行为 | `{behavior, reason, intent}` |
| `ask_user()` | 交互式询问用户 | `bool`（是否允许） |

**风险分级规则**：

| 风险级别 | 判定条件 | 示例工具 |
|----------|----------|----------|
| read | 工具名为 `read_file` 或以 READ_PREFIXES 开头 | `read_file`, `list_files`, `get_content` |
| high | bash 命令含 `rm -rf`/`sudo`/`shutdown`/`reboot`，或以 HIGH_RISK_PREFIXES 开头 | `bash` (含危险命令), `delete_file`, `remove_server` |
| write | 其他所有情况 | `write_file`, `edit_file`, `bash` (普通命令) |

**权限决策流程**：

```
┌─────────────────────┐
│   tool_name + args  │
└──────────┬──────────┘
           │
           ▼
    ┌──────────────┐
    │  normalize() │ → {source, server, tool, risk}
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ risk == read?│───YES───→ allow
    └──────┬───────┘
           │ NO
           ▼
    ┌──────────────┐
    │ mode == plan?│───YES───→ deny (write/high)
    └──────┬───────┘
           │ NO
           ▼
    ┌──────────────┐
    │ mode == auto?│───YES───→ allow (非 high)
    └──────┬───────┘
           │ NO
           ▼
    ┌──────────────┐
    │ risk == high?│───YES───→ ask
    └──────┬───────┘
           │ NO
           ▼
              ask
```

**权限模式行为对比**：

| 风险级别 | default | plan | auto |
|----------|---------|------|------|
| read | allow | allow | allow |
| write | ask | deny | allow |
| high | ask | deny | ask |

---

### MCPClient 类（MCP 客户端）

**实现代码**：
```python
class MCPClient:
    """
    Minimal MCP client over stdio (JSON-RPC 2.0).
    _call_lock 保护 _send/_recv 序列，多线程安全。
    工具命名前缀：mcp__{server_name}__{tool_name}
    """
    def __init__(self, server_name: str, command: str, args: list = None, env: dict = None):
        self.server_name = server_name
        self.command = command
        self.args = args or []
        self.env = {**os.environ, **(env or {})}
        self.process = None
        self._request_id = 0
        self._tools = []
        self._call_lock = threading.Lock()

    def connect(self) -> bool:
        """Start the MCP server process and perform initialization handshake."""
        try:
            self.process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                text=True,
            )
            with self._call_lock:
                self._send({"method": "initialize", "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "s19v2-agent", "version": "1.0"},
                }})
                response = self._recv()
                if response and "result" in response:
                    self._send({"method": "notifications/initialized"}, notification=True)
                    return True
        except FileNotFoundError:
            print(f"[MCP] Server command not found: {self.command}")
        except Exception as e:
            print(f"[MCP] Connection failed for '{self.server_name}': {e}")
        return False

    def list_tools(self) -> list:
        """Fetch available tools from the MCP server."""
        with self._call_lock:
            self._send({"method": "tools/list", "params": {}})
            response = self._recv()
        if response and "result" in response:
            self._tools = response["result"].get("tools", [])
        return self._tools

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool on the MCP server. Thread-safe via _call_lock."""
        with self._call_lock:
            self._send({"method": "tools/call", "params": {
                "name": tool_name,
                "arguments": arguments,
            }})
            response = self._recv()
        if response and "result" in response:
            content = response["result"].get("content", [])
            return "\n".join(c.get("text", str(c)) for c in content)
        if response and "error" in response:
            return f"MCP Error: {response['error'].get('message', 'unknown')}"
        return "MCP Error: no response"

    def get_agent_tools(self) -> list:
        """Convert MCP tools to OpenAI function calling format.
        Prefix: mcp__{server_name}__{tool_name}
        """
        agent_tools = []
        for tool in self._tools:
            prefixed_name = f"mcp__{self.server_name}__{tool['name']}"
            input_schema = tool.get("inputSchema", {"type": "object", "properties": {}})
            agent_tools.append({
                "type": "function",
                "function": {
                    "name": prefixed_name,
                    "description": tool.get("description", ""),
                    "parameters": input_schema,
                }
            })
        return agent_tools

    def disconnect(self):
        """Shut down the MCP server process."""
        if self.process:
            try:
                with self._call_lock:
                    self._send({"method": "shutdown"}, notification=True)
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def _send(self, message: dict, notification: bool = False):
        """Send JSON-RPC message. Caller must hold _call_lock (except during connect).
        notification=True: omit 'id' field (no response expected).
        """
        if not self.process or self.process.poll() is not None:
            return
        if notification:
            envelope = {"jsonrpc": "2.0", **message}
        else:
            self._request_id += 1
            envelope = {"jsonrpc": "2.0", "id": self._request_id, **message}
        line = json.dumps(envelope) + "\n"
        try:
            self.process.stdin.write(line)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def _recv(self) -> "dict | None":
        """Receive JSON-RPC response. Caller must hold _call_lock."""
        if not self.process or self.process.poll() is not None:
            return None
        try:
            line = self.process.stdout.readline()
            if line:
                return json.loads(line)
        except (json.JSONDecodeError, OSError):
            pass
        return None
```

**核心机制**：

| 方法 | 功能 | 说明 |
|------|------|------|
| `__init__()` | 初始化客户端 | 设置 server_name、command、args、env |
| `connect()` | 启动 MCP 服务端进程并握手 | 发送 initialize，接收响应，发送 notifications/initialized |
| `list_tools()` | 获取工具列表 | 发送 tools/list，解析响应 |
| `call_tool()` | 调用工具 | 发送 tools/call，返回文本结果 |
| `get_agent_tools()` | 转换为 OpenAI 格式 | 添加 `mcp__{server}__{tool}` 前缀 |
| `disconnect()` | 关闭连接 | 发送 shutdown，终止进程 |
| `_send()` | 发送 JSON-RPC 消息 | 需持有 `_call_lock`，notification 模式无 id |
| `_recv()` | 接收 JSON-RPC 响应 | 需持有 `_call_lock`，解析 JSON |

**JSON-RPC 2.0 消息格式**：

```
请求（有响应）：
{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {...}}

通知（无响应）：
{"jsonrpc": "2.0", "method": "notifications/initialized"}

响应：
{"jsonrpc": "2.0", "id": 1, "result": {...}}

错误：
{"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "..."}}
```

**线程安全机制**：
- `_call_lock` 保护 `_send()` 和 `_recv()` 的调用序列
- 所有公共方法（connect/list_tools/call_tool/disconnect）在调用 _send/_recv 时持有锁
- 防止多线程并发读写 stdin/stdout 导致消息错乱

**工具命名规则**：
- 原始工具名：`list_files`
- 转换后：`mcp__{server_name}__list_files`
- 示例：`mcp__filesystem__list_files`

---

### PluginLoader 类（插件发现）

**实现代码**：
```python
class PluginLoader:
    """
    从 .claude-plugin/plugin.json 发现 MCP server 配置。
    教学版：最小插件发现流程——读清单 → 提取 MCP server 配置 → 注册。
    """
    def __init__(self, search_dirs: list = None):
        self.search_dirs = search_dirs or [WORKDIR]
        self.plugins = {}  # name -> manifest

    def scan(self) -> list:
        """Scan directories for .claude-plugin/plugin.json manifests."""
        found = []
        for search_dir in self.search_dirs:
            plugin_dir = Path(search_dir) / ".claude-plugin"
            manifest_path = plugin_dir / "plugin.json"
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text())
                    name = manifest.get("name", plugin_dir.parent.name)
                    self.plugins[name] = manifest
                    found.append(name)
                except (json.JSONDecodeError, OSError) as e:
                    print(f"[Plugin] Failed to load {manifest_path}: {e}")
        return found

    def get_mcp_servers(self) -> dict:
        """从已加载插件中提取 MCP server 配置。
        返回 {server_name: {command, args, env}}
        """
        servers = {}
        for plugin_name, manifest in self.plugins.items():
            for server_name, config in manifest.get("mcpServers", {}).items():
                servers[f"{plugin_name}__{server_name}"] = config
        return servers
```

**核心机制**：

| 方法 | 功能 | 返回值 |
|------|------|--------|
| `scan()` | 扫描 `.claude-plugin/plugin.json` | 找到的插件名列表 |
| `get_mcp_servers()` | 提取 MCP server 配置 | `{server_name: {command, args, env}}` |

**插件清单格式**：

```json
{
  "name": "my-plugin",
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem"],
      "env": {}
    },
    "database": {
      "command": "python",
      "args": ["mcp_server_db.py"],
      "env": {"DB_HOST": "localhost"}
    }
  }
}
```

**目录结构**：
```
project/
├── .claude-plugin/
│   └── plugin.json
└── ...
```

**服务器命名规则**：
- 格式：`{plugin_name}__{server_name}`
- 示例：`my-plugin__filesystem`

---

### MCPToolRouter 类（MCP 工具路由）

**实现代码**：
```python
class MCPToolRouter:
    """
    将 mcp__{server}__{tool} 前缀的工具调用路由到对应 MCPClient。
    """
    def __init__(self):
        self.clients = {}  # server_name -> MCPClient

    def register_client(self, mcp_client: MCPClient):
        self.clients[mcp_client.server_name] = mcp_client

    def is_mcp_tool(self, tool_name: str) -> bool:
        return tool_name.startswith("mcp__")

    def call(self, tool_name: str, arguments: dict) -> str:
        """Route an MCP tool call to the correct MCPClient."""
        parts = tool_name.split("__", 2)
        if len(parts) != 3:
            return f"Error: Invalid MCP tool name: {tool_name}"
        _, server_name, actual_tool = parts
        mcp_client = self.clients.get(server_name)
        if not mcp_client:
            return f"Error: MCP server not found: {server_name}"
        return mcp_client.call_tool(actual_tool, arguments)

    def get_all_tools(self) -> list:
        """Collect all registered MCP tools in OpenAI function calling format."""
        tools = []
        for mcp_client in self.clients.values():
            tools.extend(mcp_client.get_agent_tools())
        return tools
```

**核心机制**：

| 方法 | 功能 | 说明 |
|------|------|------|
| `register_client()` | 注册 MCP 客户端 | 以 server_name 为键存储 |
| `is_mcp_tool()` | 判断是否为 MCP 工具 | 检查 `mcp__` 前缀 |
| `call()` | 路由工具调用 | 解析前缀，找到对应客户端，调用工具 |
| `get_all_tools()` | 收集所有工具 | 汇总所有客户端的工具列表 |

**路由解析流程**：

```
工具调用：mcp__filesystem__list_files

        │
        ▼
┌───────────────────┐
│ split("__", 2)    │
└─────────┬─────────┘
          │
          ▼
  ["mcp", "filesystem", "list_files"]
          │
          ▼
  server_name = "filesystem"
  actual_tool = "list_files"
          │
          ▼
  clients["filesystem"].call_tool("list_files", args)
```

**工具名解析规则**：

| 输入 | 解析结果 | 说明 |
|------|----------|------|
| `mcp__filesystem__list_files` | server=filesystem, tool=list_files | 标准格式 |
| `mcp__db__query` | server=db, tool=query | 标准格式 |
| `mcp__malformed` | 错误 | 不足 3 部分 |
| `read_file` | 非 MCP 工具 | 无前缀 |

---

### build_mcp_tool_pool() 函数（工具池合并）

**实现代码**：
```python
def build_mcp_tool_pool(base_tools: list) -> list:
    """
    将 MCP 工具追加到基础工具池（native 优先，名称冲突时 native 获胜）。
    base_tools: PARENT_TOOLS / CHILD_TOOLS
    """
    mcp_tools = mcp_router.get_all_tools()
    if not mcp_tools:
        return base_tools
    native_names = {
        t.get("function", {}).get("name", t.get("name", ""))
        for t in base_tools
    }
    result = list(base_tools)
    for tool in mcp_tools:
        name = tool.get("function", {}).get("name", "")
        if name not in native_names:
            result.append(tool)
    return result
```

**核心机制**：

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1 | 获取 MCP 工具列表 | `mcp_router.get_all_tools()` |
| 2 | 提取 native 工具名集合 | 从 base_tools 提取 function.name |
| 3 | 复制 base_tools | 保持 native 工具在前 |
| 4 | 追加不冲突的 MCP 工具 | 名称不在 native_names 中的才追加 |

**工具池结构**：

```
base_tools: [task_create, task_list, read_file, write_file, bash, ...]
              │
              ▼
mcp_tools:    [mcp__filesystem__list_files, mcp__filesystem__read_file, ...]
              │
              ▼
merged:       [task_create, task_list, read_file, write_file, bash, ..., 
               mcp__filesystem__list_files, mcp__filesystem__read_file, ...]
```

**名称冲突处理**：
- 如果 MCP 工具名与 native 工具名相同，MCP 工具被跳过
- 例如：native 有 `read_file`，MCP 有 `mcp__fs__read_file`，两者共存（前缀不同）

---

### execute_tool_calls() 的 MCP 扩展

**实现代码**（MCP 相关部分）：
```python
def execute_tool_calls(response_message, interactive: bool = True,
                       track_tasks: bool = True) -> tuple[list[dict], str | None, bool, str | None]:
    # ... (native 工具处理代码) ...
    
    elif mcp_router.is_mcp_tool(f_name):
        # [s19_v2 新增] MCP 工具路由：经过 CapabilityPermissionGate 权限门
        # Strip tool_call_id before passing to MCP (it's internal bookkeeping)
        mcp_args = {k: v for k, v in args.items() if k != "tool_call_id"}
        decision = mcp_gate.check(f_name, mcp_args)
        intent = decision.get("intent", {})
        if decision["behavior"] == "deny":
            # plan 模式：直接拒绝，不询问用户
            reason = decision.get("reason", "Denied by permission gate")
            output = f"Permission denied (plan mode): MCP tool {f_name} blocked. {reason}"
            print(f"\033[31m  [MCP DENIED] {f_name}: {reason}\033[0m")
        elif decision["behavior"] == "ask":
            if not interactive:
                output = f"Permission denied: non-interactive context, cannot confirm MCP tool {f_name}"
            elif mcp_gate.ask_user(intent, mcp_args):
                try:
                    output = mcp_router.call(f_name, mcp_args)
                    print(f"\033[33m[MCP Tool: {f_name}]\033[0m:\t{str(output)[:20]}")
                except Exception as e:
                    output = f"MCP Tool Execution Error: {type(e).__name__} - {str(e)}"
                    print(f"\033[31m[MCP 执行报错返回给模型]: {output}\033[0m")
            else:
                output = f"Permission denied by user for MCP tool: {f_name}"
        else:
            # behavior == "allow" (read-only or auto-mode non-high-risk)
            try:
                output = mcp_router.call(f_name, mcp_args)
                print(f"\033[33m[MCP Tool: {f_name}]\033[0m:\t{str(output)[:20]}")
            except Exception as e:
                output = f"MCP Tool Execution Error: {type(e).__name__} - {str(e)}"
                print(f"\033[31m[MCP 执行报错返回给模型]: {output}\033[0m")
    else:
        output = f"Error: Tool {f_name} not found."
```

**MCP 工具执行流程**：

```
┌─────────────────────────────┐
│  tool_call: mcp__fs__read   │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ mcp_router.is_mcp_tool()?   │───NO───→ native/unknown
└─────────────┬───────────────┘
              │ YES
              ▼
┌─────────────────────────────┐
│ mcp_gate.check()            │
│ → {behavior, reason, intent}│
└─────────────┬───────────────┘
              │
        ┌─────┴─────┐
        │ behavior  │
        └─────┬─────┘
              │
    ┌─────────┼─────────┐
    │         │         │
    ▼         ▼         ▼
  deny      ask       allow
    │         │         │
    │    ┌────┴────┐    │
    │    │  用户   │    │
    │    │  确认？ │    │
    │    └────┬────┘    │
    │         │         │
    │    ┌────┴────┐    │
    │    │         │    │
    ▼    ▼         ▼    ▼
  拒绝  是        否   执行
  注入  │         │    │
  错误  │         │    │
  消息  ▼         ▼    ▼
      执行    拒绝    返回
      │       注入    结果
      │       消息    │
      │       │       │
      └───────┴───────┘
              │
              ▼
      返回工具结果
```

**权限决策与行为映射**：

| behavior | 条件 | 操作 |
|----------|------|------|
| deny | plan 模式 + write/high | 直接拒绝，注入错误消息 |
| ask | high 风险 或 default 模式 + write | 询问用户，根据回答决定是否执行 |
| allow | read 风险 或 auto 模式 + write | 直接执行，返回结果 |

**交互式与非交互式上下文**：
- `interactive=True`：可以询问用户
- `interactive=False`：不能询问，需要确认的操作直接拒绝

---

### 全局实例初始化

**实现代码**：
```python
# MCP 全局实例（在 __main__ 中由 plugin_loader.scan() 后填充）
mcp_router   = MCPToolRouter()
plugin_loader = PluginLoader()
# MCP 权限门（与 native PermissionManager 并列，仅用于 MCP 工具路径）
mcp_gate = CapabilityPermissionGate(mode="default")
```

**实例关系**：

```
plugin_loader.scan()
      │
      ▼
发现 .claude-plugin/plugin.json
      │
      ▼
plugin_loader.get_mcp_servers()
      │
      ▼
创建 MCPClient 实例
      │
      ▼
mcp_router.register_client()
      │
      ▼
MCP 工具可用
```

**实例用途**：

| 实例 | 类型 | 用途 |
|------|------|------|
| `mcp_router` | MCPToolRouter | 工具路由和工具池收集 |
| `plugin_loader` | PluginLoader | 插件扫描和 server 配置提取 |
| `mcp_gate` | CapabilityPermissionGate | MCP 工具权限检查 |

---

## 完整执行流程

### 启动阶段

```
1. 导入模块
   │
   ▼
2. 创建全局实例
   - mcp_router = MCPToolRouter()
   - plugin_loader = PluginLoader()
   - mcp_gate = CapabilityPermissionGate(mode="default")
   │
   ▼
3. plugin_loader.scan() 扫描插件
   │
   ▼
4. 对每个发现的 MCP server：
   - 创建 MCPClient(server_name, command, args, env)
   - client.connect()
   - client.list_tools()
   - mcp_router.register_client(client)
   │
   ▼
5. build_mcp_tool_pool(PARENT_TOOLS)
   │
   ▼
6. 构建系统提示（含 MCP 工具列表）
```

### 工具调用阶段

```
1. 模型输出工具调用：mcp__filesystem__list_files(path="/test")
   │
   ▼
2. execute_tool_calls() 接收响应
   │
   ▼
3. mcp_router.is_mcp_tool("mcp__filesystem__list_files") → True
   │
   ▼
4. mcp_gate.check("mcp__filesystem__list_files", {"path": "/test"})
   │
   ▼
5. normalize() 解析：
   - source = "mcp"
   - server = "filesystem"
   - tool = "list_files"
   - risk = "read" (以 list 开头)
   │
   ▼
6. check() 决策：
   - risk == "read" → behavior = "allow"
   │
   ▼
7. mcp_router.call("mcp__filesystem__list_files", {"path": "/test"})
   │
   ▼
8. 解析前缀：server_name="filesystem", actual_tool="list_files"
   │
   ▼
9. clients["filesystem"].call_tool("list_files", {"path": "/test"})
   │
   ▼
10. 发送 JSON-RPC 请求 → 接收响应 → 返回结果
```

---

## 附录：关键数据结构

### normalize() 返回值

```python
{
    "source": "mcp",           # 或 "native"
    "server": "filesystem",    # MCP server 名，native 工具为 None
    "tool": "list_files",      # 实际工具名
    "risk": "read"             # "read" / "write" / "high"
}
```

### check() 返回值

```python
{
    "behavior": "allow",       # "allow" / "deny" / "ask"
    "reason": "Read capability",
    "intent": {                # normalize() 的返回值
        "source": "mcp",
        "server": "filesystem",
        "tool": "list_files",
        "risk": "read"
    }
}
```

### MCP 工具格式（OpenAI function calling）

```json
{
    "type": "function",
    "function": {
        "name": "mcp__filesystem__list_files",
        "description": "List files in a directory",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            }
        }
    }
}
```

---

## 总结

s19_v2 的核心改动是集成 MCP 协议和插件系统，使主代理能够调用外部 MCP 服务器提供的工具。主要组件包括：

1. **CapabilityPermissionGate**：统一权限门，对 native 和 MCP 工具实施相同的权限控制
2. **MCPClient**：stdio MCP 客户端，通过 JSON-RPC 2.0 与 MCP 服务器通信
3. **PluginLoader**：从 `.claude-plugin/plugin.json` 发现 MCP 服务器配置
4. **MCPToolRouter**：基于 `mcp__{server}__{tool}` 前缀路由工具调用
5. **build_mcp_tool_pool()**：合并 native 和 MCP 工具，native 优先
6. **execute_tool_calls() 扩展**：自动检测 MCP 工具并经过权限门执行

所有 MCP 工具调用均经过权限检查，确保 MCP 工具不绕过权限平面。
