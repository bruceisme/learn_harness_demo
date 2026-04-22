# s19_v2_mcp_plugin: MCP & Plugin System Integration

## Overview

s19_v2 integrates **MCP (Model Context Protocol)** and **Plugin System** based on s18_v2_worktree.py. The core changes are the addition of MCP client, plugin discovery mechanism, tool routing, and unified permission gate, enabling the main agent to call tools provided by external MCP servers.

### Core Improvements

1. **CapabilityPermissionGate class** - Unified permission gate, native tools and MCP tools share the same control channel
2. **MCPClient class** - stdio MCP client (JSON-RPC 2.0), supports connect/list_tools/call_tool/disconnect
3. **PluginLoader class** - `.claude-plugin/plugin.json` plugin discovery, scans plugin manifests in working directory
4. **MCPToolRouter class** - MCP tool routing, prefix routing `mcp__{server_name}__{tool_name}`
5. **build_mcp_tool_pool() function** - Tool pool merging, native tools have priority, MCP tools appended at end
6. **execute_tool_calls() extension** - Auto-detect `mcp__` prefix and route to MCPToolRouter, with permission gate check

### Code File Paths

- **Source code**: `v1_task_manager/chapter_19_2/s19_v2_mcp_plugin.py`
- **Reference document**: `v1_task_manager/chapter_18_2/s18_v2_worktree_文档.md`
- **Reference code**: `v1_task_manager/chapter_18_2/s18_v2_worktree.py`
- **Plugin manifest**: `.claude-plugin/plugin.json`
- **MCP tool naming**: `mcp__{server_name}__{tool_name}`

---

## Comparison with s18_v2 (Change Overview)

| Component | s18_v2 | s19_v2 | Change Description |
|-----------|--------|--------|-------------------|
| Permission gate | PermissionManager (native tools only) | + CapabilityPermissionGate | Added MCP tool permission check |
| MCP client | None | MCPClient class | Added stdio MCP client |
| Plugin discovery | None | PluginLoader class | Added `.claude-plugin/plugin.json` scanning |
| Tool routing | None | MCPToolRouter class | Added `mcp__` prefix routing |
| Tool pool building | PARENT_TOOLS / CHILD_TOOLS | + build_mcp_tool_pool() | Added MCP tool merging |
| Tool execution | Native tools only | + MCP tool routing | execute_tool_calls() extended |
| Risk levels | read/write | read/write/high | Added high risk level |
| Permission modes | default/plan/auto | default/plan/auto | Added MCP-specific logic |

---

## s19_v2 New Content Details (in Code Execution Order)

### PERMISSION_MODES Constant

**Implementation code**:
```python
PERMISSION_MODES = ("default", "plan", "auto")
```

**Description**:
- Defines three permission modes, consistent with s18_v2's MODES
- `default`: All non-read operations ask user
- `plan`: Read-only allowed, write/high-risk rejected
- `auto`: Only ask for high-risk operations, others auto-allowed

---

### CapabilityPermissionGate Class (Unified Permission Gate)

**Implementation code**:
```python
class CapabilityPermissionGate:
    """
    Unified permission gate: native tools and MCP tools share the same control channel.
    Core teaching goal: MCP tools do not bypass the permission plane.
    Risk levels: read (read-only) / write (write operations) / high (destructive operations).
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

**Core mechanisms**:

| Method | Function | Return Value |
|--------|----------|--------------|
| `normalize()` | Parse tool name, identify source (native/MCP) and risk level | `{source, server, tool, risk}` |
| `check()` | Decide behavior based on mode and risk level | `{behavior, reason, intent}` |
| `ask_user()` | Interactive user query | `bool` (whether allowed) |

**Risk level rules**:

| Risk Level | Criteria | Example Tools |
|------------|----------|---------------|
| read | Tool name is `read_file` or starts with READ_PREFIXES | `read_file`, `list_files`, `get_content` |
| high | bash command contains `rm -rf`/`sudo`/`shutdown`/`reboot`, or starts with HIGH_RISK_PREFIXES | `bash` (with dangerous commands), `delete_file`, `remove_server` |
| write | All other cases | `write_file`, `edit_file`, `bash` (normal commands) |

**Permission decision flow**:

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
    │ mode == auto?│───YES───→ allow (non-high)
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

**Permission mode behavior comparison**:

| Risk Level | default | plan | auto |
|------------|---------|------|------|
| read | allow | allow | allow |
| write | ask | deny | allow |
| high | ask | deny | ask |


---

### MCPClient Class (MCP Client)

**Implementation code**:
```python
class MCPClient:
    """
    Minimal MCP client over stdio (JSON-RPC 2.0).
    _call_lock protects _send/_recv sequence, thread-safe.
    Tool naming prefix: mcp__{server_name}__{tool_name}
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

**Core mechanisms**:

| Method | Function | Description |
|--------|----------|-------------|
| `__init__()` | Initialize client | Set server_name, command, args, env |
| `connect()` | Start MCP server process and handshake | Send initialize, receive response, send notifications/initialized |
| `list_tools()` | Get tool list | Send tools/list, parse response |
| `call_tool()` | Call tool | Send tools/call, return text result |
| `get_agent_tools()` | Convert to OpenAI format | Add `mcp__{server}__{tool}` prefix |
| `disconnect()` | Close connection | Send shutdown, terminate process |
| `_send()` | Send JSON-RPC message | Must hold `_call_lock`, notification mode has no id |
| `_recv()` | Receive JSON-RPC response | Must hold `_call_lock`, parse JSON |

**JSON-RPC 2.0 message format**:

```
Request (with response):
{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {...}}

Notification (no response):
{"jsonrpc": "2.0", "method": "notifications/initialized"}

Response:
{"jsonrpc": "2.0", "id": 1, "result": {...}}

Error:
{"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "..."}}
```

**Thread safety mechanism**:
- `_call_lock` protects `_send()` and `_recv()` call sequence
- All public methods (connect/list_tools/call_tool/disconnect) hold lock when calling _send/_recv
- Prevents message corruption from multi-thread concurrent stdin/stdout read/write

**Tool naming rule**:
- Original tool name: `list_files`
- Converted: `mcp__{server_name}__list_files`
- Example: `mcp__filesystem__list_files`

---

### PluginLoader Class (Plugin Discovery)

**Implementation code**:
```python
class PluginLoader:
    """
    Discover MCP server configuration from .claude-plugin/plugin.json.
    Teaching version: Minimal plugin discovery flow - read manifest -> extract MCP server config -> register.
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
        """Extract MCP server configuration from loaded plugins.
        Returns {server_name: {command, args, env}}
        """
        servers = {}
        for plugin_name, manifest in self.plugins.items():
            for server_name, config in manifest.get("mcpServers", {}).items():
                servers[f"{plugin_name}__{server_name}"] = config
        return servers
```

**Core mechanisms**:

| Method | Function | Return Value |
|--------|----------|--------------|
| `scan()` | Scan `.claude-plugin/plugin.json` | List of found plugin names |
| `get_mcp_servers()` | Extract MCP server configuration | `{server_name: {command, args, env}}` |

**Plugin manifest format**:

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

**Directory structure**:
```
project/
+-- .claude-plugin/
|   +-- plugin.json
+-- ...
```

**Server naming rule**:
- Format: `{plugin_name}__{server_name}`
- Example: `my-plugin__filesystem`

---

### MCPToolRouter Class (MCP Tool Routing)

**Implementation code**:
```python
class MCPToolRouter:
    """
    Route tool calls with mcp__{server}__{tool} prefix to corresponding MCPClient.
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

**Core mechanisms**:

| Method | Function | Description |
|--------|----------|-------------|
| `register_client()` | Register MCP client | Store with server_name as key |
| `is_mcp_tool()` | Check if MCP tool | Check `mcp__` prefix |
| `call()` | Route tool call | Parse prefix, find client, call tool |
| `get_all_tools()` | Collect all tools | Aggregate all clients' tool lists |

**Tool name parsing rules**:

| Input | Parse Result | Description |
|-------|--------------|-------------|
| `mcp__filesystem__list_files` | server=filesystem, tool=list_files | Standard format |
| `mcp__db__query` | server=db, tool=query | Standard format |
| `mcp__malformed` | Error | Less than 3 parts |
| `read_file` | Not MCP tool | No prefix |

---

### build_mcp_tool_pool() Function (Tool Pool Merging)

**Implementation code**:
```python
def build_mcp_tool_pool(base_tools: list) -> list:
    """
    Append MCP tools to base tool pool (native priority, name conflicts: native wins).
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

**Core mechanism**:

| Step | Operation | Description |
|------|-----------|-------------|
| 1 | Get MCP tool list | `mcp_router.get_all_tools()` |
| 2 | Extract native tool name set | Extract function.name from base_tools |
| 3 | Copy base_tools | Keep native tools first |
| 4 | Append non-conflicting MCP tools | Only append if name not in native_names |

**Tool pool structure**:

```
base_tools: [task_create, task_list, read_file, write_file, bash, ...]
              |
              v
mcp_tools:    [mcp__filesystem__list_files, mcp__filesystem__read_file, ...]
              |
              v
merged:       [task_create, task_list, read_file, write_file, bash, ..., 
               mcp__filesystem__list_files, mcp__filesystem__read_file, ...]
```

**Name conflict handling**:
- If MCP tool name conflicts with native tool name, MCP tool is skipped
- Example: native has `read_file`, MCP has `mcp__fs__read_file`, both coexist (different prefixes)

---

### execute_tool_calls() MCP Extension

**MCP tool execution flow**:

```
1. Tool call: mcp__filesystem__list_files(path="/test")
   |
   v
2. execute_tool_calls() receives response
   |
   v
3. mcp_router.is_mcp_tool("mcp__filesystem__list_files") -> True
   |
   v
4. mcp_gate.check("mcp__filesystem__list_files", {"path": "/test"})
   |
   v
5. normalize() parses:
   - source = "mcp"
   - server = "filesystem"
   - tool = "list_files"
   - risk = "read" (starts with list)
   |
   v
6. check() decides:
   - risk == "read" -> behavior = "allow"
   |
   v
7. mcp_router.call("mcp__filesystem__list_files", {"path": "/test"})
   |
   v
8. Parse prefix: server_name="filesystem", actual_tool="list_files"
   |
   v
9. clients["filesystem"].call_tool("list_files", {"path": "/test"})
   |
   v
10. Send JSON-RPC request -> receive response -> return result
```

**Permission decision and behavior mapping**:

| behavior | Condition | Action |
|----------|-----------|--------|
| deny | plan mode + write/high | Direct reject, inject error message |
| ask | high risk or default mode + write | Ask user, decide execution based on answer |
| allow | read risk or auto mode + write | Execute directly, return result |

**Interactive and non-interactive context**:
- `interactive=True`: Can ask user
- `interactive=False`: Cannot ask, operations requiring confirmation are directly rejected

---

### Global Instance Initialization

**Implementation code**:
```python
# MCP global instances (populated by plugin_loader.scan() in __main__)
mcp_router   = MCPToolRouter()
plugin_loader = PluginLoader()
# MCP permission gate (alongside native PermissionManager, only for MCP tool path)
mcp_gate = CapabilityPermissionGate(mode="default")
```

**Instance usage**:

| Instance | Type | Usage |
|----------|------|-------|
| `mcp_router` | MCPToolRouter | Tool routing and tool pool collection |
| `plugin_loader` | PluginLoader | Plugin scanning and server config extraction |
| `mcp_gate` | CapabilityPermissionGate | MCP tool permission check |

---

## Complete Execution Flow

### Startup Phase

```
1. Import modules
   |
   v
2. Create global instances
   - mcp_router = MCPToolRouter()
   - plugin_loader = PluginLoader()
   - mcp_gate = CapabilityPermissionGate(mode="default")
   |
   v
3. plugin_loader.scan() scans plugins
   |
   v
4. For each discovered MCP server:
   - Create MCPClient(server_name, command, args, env)
   - client.connect()
   - client.list_tools()
   - mcp_router.register_client(client)
   |
   v
5. build_mcp_tool_pool(PARENT_TOOLS)
   |
   v
6. Build system prompt (including MCP tool list)
```

### Tool Call Phase

```
1. Model outputs tool call: mcp__filesystem__list_files(path="/test")
   |
   v
2. execute_tool_calls() receives response
   |
   v
3. mcp_router.is_mcp_tool("mcp__filesystem__list_files") -> True
   |
   v
4. mcp_gate.check("mcp__filesystem__list_files", {"path": "/test"})
   |
   v
5. normalize() parses:
   - source = "mcp"
   - server = "filesystem"
   - tool = "list_files"
   - risk = "read" (starts with list)
   |
   v
6. check() decides:
   - risk == "read" -> behavior = "allow"
   |
   v
7. mcp_router.call("mcp__filesystem__list_files", {"path": "/test"})
   |
   v
8. Parse prefix: server_name="filesystem", actual_tool="list_files"
   |
   v
9. clients["filesystem"].call_tool("list_files", {"path": "/test"})
   |
   v
10. Send JSON-RPC request -> receive response -> return result
```

---

## Appendix: Key Data Structures

### normalize() Return Value

```python
{
    "source": "mcp",           # or "native"
    "server": "filesystem",    # MCP server name, None for native tools
    "tool": "list_files",      # Actual tool name
    "risk": "read"             # "read" / "write" / "high"
}
```

### check() Return Value

```python
{
    "behavior": "allow",       # "allow" / "deny" / "ask"
    "reason": "Read capability",
    "intent": {                # normalize() return value
        "source": "mcp",
        "server": "filesystem",
        "tool": "list_files",
        "risk": "read"
    }
}
```

### MCP Tool Format (OpenAI function calling)

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

## Summary

The core change in s19_v2 is the integration of MCP protocol and plugin system, enabling the main agent to call tools provided by external MCP servers. Main components include:

1. **CapabilityPermissionGate**: Unified permission gate, implementing same permission control for native and MCP tools
2. **MCPClient**: stdio MCP client, communicates with MCP server via JSON-RPC 2.0
3. **PluginLoader**: Discovers MCP server configuration from `.claude-plugin/plugin.json`
4. **MCPToolRouter**: Routes tool calls based on `mcp__{server}__{tool}` prefix
5. **build_mcp_tool_pool()**: Merges native and MCP tools, native has priority
6. **execute_tool_calls() extension**: Auto-detects MCP tools and executes with permission gate check

All MCP tool calls go through permission checks, ensuring MCP tools do not bypass the permission plane.

---

*Document version: v1.0*
*Based on code: v1_task_manager/chapter_19_2/s19_v2_mcp_plugin.py*
