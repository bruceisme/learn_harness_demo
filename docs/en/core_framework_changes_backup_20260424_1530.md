# v1_task_manager Core Framework Changes Analysis

**Document Version**: v2 
**Generated Time**: 2026-04-22 
**Project Path**: `learn_harness_demo/`

---

## Table of Contents

- [Capiter 1: Basic Agent Loop](#capiter-1-Basic-agent-loop)
- [Capiter 2: Tool System Extension](#capiter-2-Tool System Extension)
- [Capiter 3: Skill System Introduction](#capiter-3-Skill System Introduction)
- [Capiter 4: Task Management System](#capiter-4-Task Management System)
- [Capiter 5: Sub-agent System](#capiter-5-Sub-agent System)
- [Capiter 6: Context Management](#capiter-6-Context Management)
- [Capiter 7: Permission System](#capiter-7-Permission System)
- [Capiter 8: Hook System](#capiter-8-hook-System)
- [Capiter 9: Memory System](#capiter-9-Memory System)
- [Capiter 10: Build System](#capiter-10-Build System)
- [Capiter 11: Resume System](#capiter-11-Resume System)
- [Capiter 12: Task System Enhancement](#capiter-12-Task System Enhancement)
- [Capiter 13: v2 Background Tasks](#capiter-13-v2-Background任务)
- [Capiter 14: Cron Scheduler](#capiter-14-cron-Scheduler)
- [Capiter 18_2: Worktree Isolation](#capiter-18_2-worktree-Isolation)
- [Capiter 19_2: MCP Plugin](#capiter-19_2-mcp-Plugin)

---

## Capiter 1: Basic Agent Loop

**File Path**: `code/v1_task_manager/chapter_01/s01_agent_loop.py` 
**Full Analysis**: [../zh/chapter_01/s01_agent_loop_文档.md](../zh/chapter_01/s01_agent_loop_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `LoopState` | dataclass | StoreConversation HistoryandRound Count，Manage messages Listand turn_count |
| `TOOLS` | list | Tool Definition List，Only Include bash Tool OpenAI function calling FormatDefinition |
| `run_one_turn()` | function | Single LLM Call + ToolExecute，ReturnwhetherContinueLoop |
| `agent_loop()` | function | Main Loop Entry，Continue ExecuteUntilModelNo LongerCallTool |
| `execute_tool_calls()` | function | Parse LLM Return tool_calls andExecuteCorresponding Tool |
| `run_bash()` | function | bash Tool Implementation，Execute Shell Commandand Return Output |

### Function Change Details

1. **Basic Agent Loop Structure**
 - Adopt `while run_one_turn(state): pass` Concise Loop Pattern
 - LoopState Manage messages Listand turn_count Counter
 - Each Loop：LLM Call → Parse tool_calls → ExecuteTool → InjectResult → Next Round

2. **Single Tool Support**
 - Only Implement bash Tool，Used forExecute Shell Command
 - Tool DefinitionAdopt OpenAI function calling Format
 - ParameterIncluding `command`（Required）String

3. **SimpleSecurity Filter**
 - Dangerous CommandCheck：`rm -rf /`、`sudo`、`shutdown`、`reboot` etc.
 - Timeout Protection：120 SecondsExecution TimeoutLimitation
 - Return Error Informationto ModelRather Than Directly Throw Exception

4. **Interactive Entry**
 - `if __name__ == "__main__"` Provide REPL-style Interaction
 - Support q/exit Exit andEmpty Input Exit
 - Support Multi-round Conversation，Continue RunningUntil User ExitsOr Model Completes

5. **Model Connection Configuration**
 - Use OpenAI Compatible API Interface
 - Support Thinking Model（enable_thinking=True）
 - Automatically Get Available Model List

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
# LoopState 实例
LoopState(
    messages=[
        {"role": "user", "content": "List files in current directory"},
        {"role": "assistant", "content": None, "tool_calls": [...]},
        {"role": "tool", "content": "file1.txt\nfile2.py", "tool_call_id": "..."}
    ],
    turn_count=2,
    transition_reason=None
)

# TOOLS 定义
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

### Same asbefore一章 Comparison

本章for初始版本，无ComparisonChapter。

### Architecture图

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

### ExecuteProcess

```
1. 用户输入 → 添加到 messages
2. 调用 LLM → 获取响应（可能包含 tool_calls）
3. 如果有 tool_calls:
   a. 解析每个 tool_call
   b. 执行对应工具函数
   c. 收集工具输出
   d. 将 tool_result 添加到 messages
4. 重复步骤 2-3，直到 LLM 不再调用工具
5. 返回最终响应给用户
```

### 本章小结

Capiter 1 Establish了最Basic Agent Loop Framework，Include单一 bash ToolSupportandSimpleSecurity Filter。LoopStructureAdopt经典 "LLM 决策 → ToolExecute → ResultFeedback" 模，forafter续Chapter Extend奠定Basic。核心设计保持简洁，便at理解andafter续Extend。

---

## Capiter 2: Tool System Extension

**File Path**: `code/v1_task_manager/chapter_02/s02_tool_use.py` 
**Full Analysis**: [../zh/chapter_02/s02_tool_use_文档.md](../zh/chapter_02/s02_tool_use_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `TOOL_HANDLERS` | dict | ToolNametoProcessFunction 映射，Support动态Extend |
| `safe_path()` | function | 路径SecurityCheck，防止Table of Contents穿越Attack |
| `run_read()` | function | read_file Tool Implementation，读取Fileinside容 |
| `run_write()` | function | write_file Tool Implementation，写入Fileinside容 |
| `run_edit()` | function | edit_file Tool Implementation，替换Filein 文本 |
| `execute_tool_calls()` | function | ToolCall分发Same asExecute，Support错误Process |

### Function Change Details

1. **ToolQuantityExtend**
 - 新增 `read_file`：读取Fileinside容，Support limit ParameterLimitation行数
 - 新增 `write_file`：写入Fileinside容，覆盖已hasinside容
 - 新增 `edit_file`：编辑File，替换指定 old_text for new_text
 - Tool总数From 1 个Extendto 4 个

2. **Tool分发Mechanism**
 - Introduction `TOOL_HANDLERS` Dictionary进行Tool路由
 - Support动态Extend新Toolwhile无需修改主Loop
 - 未知ToolReturn Error Informationto Model

3. **路径SecurityProtection**
 - `safe_path()` Use `is_relative_to()` Check路径whetherat工作Table of Contentsinside
 - 防止Table of Contents穿越Attack（Such as `../../etc/passwd`）
 - allFileOperationToolall必须through此Check

4. **JSON Parse错误Process**
 - ToolParameterParseFailure时Return Error Informationto Model
 - Use `continue` 跳过Failure ToolCall
 - Model可以根据Error Information修正Parameter重新Call

5. **Output长度Limitation**
 - ToolOutput统一Limitationfor 50000 字符
 - 防止过长 Output占用Context
 - 超出part被截断andHintModel

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

### ToolParameterDefinition

```python
# read_file 工具定义
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

# edit_file 工具定义
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

### Same asbefore一章 Comparison

| Feature | Capiter 1 | Capiter 2 |
|------|-----------|-----------|
| ToolQuantity | 1 (bash) | 4 (bash + FileOperation) |
| Tool路由 | if-else 硬编码 | TOOL_HANDLERS Dictionary |
| 路径Security | 无 | safe_path() Check |
| 错误Process | Simple | JSON Parse错误捕获 |
| OutputLimitation | 无 | 50000 字符Limitation |

### Architecture图

```
┌──────────┐      ┌───────┐      ┌──────────────────┐
│   User   │ ───> │  LLM  │ ───> │ Tool Dispatch    │
│  prompt  │      │       │      │ {                │
└──────────┘      └───┬───┘      │   bash: run_bash │
                      ↑          │   read: run_read │
                      │          │   write: run_wr  │
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

### 错误Process示例

```python
# 参数解析错误
try:
    tool_input = json.loads(tool_call.function.arguments)
except json.JSONDecodeError as e:
    results.append({
        "role": "tool",
        "content": f"Failed to parse arguments: {e}",
        "tool_call_id": tool_call.id
    })
    continue

# 路径安全检查错误
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

### 本章小结

Capiter 2 at保持 Agent Loop 不变 Prerequisitebelow，throughTool分发DictionaryExtend了ToolSystem。FileOperationTool Introductionmake Agent 能够直接读写工作区File，路径SecurityCheck防止了Table of Contents穿越Risk。Tool分发Mechanism 设计便atafter续添加新Tool。

---

## Capiter 3: Skill System Introduction

**File Path**: `code/v1_task_manager/chapter_03/s03_skill_loading.py` 
**Full Analysis**: [../zh/chapter_03/s03_skill_loading_文档.md](../zh/chapter_03/s03_skill_loading_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `SkillManifest` | dataclass | 技能元Data（name, description, path） |
| `SkillDocument` | dataclass | 技能完整Document（manifest + body） |
| `SkillRegistry` | class | 技能加载Same asManage，自动扫描 skills Table of Contents |
| `load_skill` | tool | 动态加载技能inside容toContext |
| `_parse_frontmatter()` | method | Parse Markdown frontmatter 元Data |

### Function Change Details

1. **技能DataStructure**
 - `SkillManifest` Store技能元Data：name、description、path
 - `SkillDocument` 组合 manifest and完整inside容 body
 - Support按Name索引and检索

2. **技能Note册表**
 - `SkillRegistry` 自动扫描 `skills/` Directory `SKILL.md` File
 - Use frontmatter Parse技能元Data（YAML Format）
 - 按技能NameEstablish索引，SupportFastFind

3. **技能加载Tool**
 - 新增 `load_skill` Tool供Model按需加载技能
 - ReturnFormat化 `<skill name="...">...</skill>` Label
 - 未知技能Return Error Informationand可用技能List

4. **SystemHintInject**
 - 启动时列出all可用技能to system prompt
 - Model可根据任务Requirement选择加载Related技能
 - 避免一次性Injectall技能占用Context

5. **FileOperation分Class**
 - `CONCURRENCY_SAFE = {"read_file"}` MarkSecurityand发Tool
 - `CONCURRENCY_UNSAFE = {"write_file", "edit_file"}` Mark不SecurityTool
 - forafter续and发ControlProvideBasic

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

### Frontmatter Format示例

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

### Same asbefore一章 Comparison

| Feature | Capiter 2 | Capiter 3 |
|------|-----------|-----------|
| KnowledgeManage | 无 | SkillRegistry |
| ContextInject | 静态 | 动态 load_skill |
| Tooland发Mark | 无 | CONCURRENCY_SAFE/UNSAFE |
| 技能Discover | 无 | 自动扫描 SKILL.md |

### Architecture图

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

### 技能加载Process

```
1. 模型调用 load_skill(name="jsonl_handler")
2. SkillRegistry 查找对应技能
3. 如果找到：
   - 返回 <skill name="jsonl_handler">...</skill>
4. 如果未找到：
   - 返回错误信息和可用技能列表
5. 结果注入到对话上下文
6. 模型根据技能内容执行任务
```

### 本章小结

Capiter 3 Introduction了技能System，允许将SpecificField KnowledgeandBest Practice封装for可加载 SKILL.md File。Model可以根据任务Requirement动态加载Related技能，避免一次性Inject过多inside容占用Context。Frontmatter FormatSupportStructure化 元Data，便at技能分Classand检索。

---

## Capiter 4: Task Management System

**File Path**: `code/v1_task_manager/chapter_04/s04_todo_write.py` 
**Full Analysis**: [../zh/chapter_04/s04_todo_write_文档.md](../zh/chapter_04/s04_todo_write_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `PlanItem` | dataclass | 单个Plan项（id, content, status, active_form） |
| `PlanningState` | dataclass | PlanState（items List + rounds_since_update） |
| `TodoManager` | class | 待办任务Manage，SupportUpdateand渲染 |
| `task_update` | tool | Update任务Plan |
| `render()` | method | Format化Output任务List |

### Function Change Details

1. **任务DataStructure**
 - `PlanItem` Include id、content、status、active_form 字段
 - status 限定for `pending`、`in_progress`、`completed`
 - active_form Used for进行时Describe（Such as "正at读取File"）

2. **单任务进行inConstraint**
 - 同一Time最多一个任务处at `in_progress` State
 - 防止任务and行Lead to Context混乱
 - 确保任务Execute has序性

3. **PlanUpdateVerify**
 - Limitation最多 20 个Plan项
 - VerifyRequired字段（id、content）andEffectiveState值
 - ReturnDetailed Error Information供Model修正

4. **轮次Track**
 - `rounds_since_update` 记录Plan未Update 轮次
 - 可Used for触发PlanReviewRemind
 - HelpModel保持Plan 时效性

5. **任务DisplayFormat化**
 - `render()` MethodGenerate带State图标 任务List
 - 区分已Complete（✅）、进行in（🔄）、待办（⏳）任务
 - 进行in 任务Show active_form Describe

```python
@dataclass
class PlanItem: 
    id: str                     # 标记任务 id，便于辨识
    content: str                # 这一步要做什么
    status: str = "pending"     # pending | in_progress | completed
    active_form: str = ""       # 进行时描述

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

### 任务State流转

```
pending ──────────────> in_progress ──────────────> completed
   │                         │                          │
   │                         │                          │
   └─────────────────────────┴──────────────────────────┘
                    (可以回退到任意状态)
```

### Same asbefore一章 Comparison

| Feature | Capiter 3 | Capiter 4 |
|------|-----------|-----------|
| 任务规划 | 无 | TodoManager |
| StateTrack | 无 | PlanItem.status |
| 进度Remind | 无 | rounds_since_update |
| 可视化 | 无 | State图标渲染 |

### Architecture图

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

### 任务List示例

```markdown
## Plan
- [1] ⏳ 读取项目结构
- [2] ⏳ 分析核心模块
- [3] 🔄 正在编写测试用例
- [4] ✅ 完成文档更新
```

### 本章小结

Capiter 4 Introduction了Task Management System，make Agent 能够将ComplexRequirement拆分for可Execute Plan项。单任务进行in Constraint确保任务Execute has序性，轮次Track可Used for触发PlanReview。State图标Provide直观 进度可视化。

---

## Capiter 5: Sub-agent System

**File Path**: `code/v1_task_manager/chapter_05/s05_subagent.py` 
**Full Analysis**: [../zh/chapter_05/s05_subagent_文档.md](../zh/chapter_05/s05_subagent_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `run_subagent()` | function | 启动子ProxyExecute子任务 |
| `PARENT_TOOLS` | dict | 主Proxy可用Tool集（任务ManageClass） |
| `CHILD_TOOLS` | dict | 子Proxy可用Tool集（ExecuteClass） |
| `task` | tool | 主Proxy委派任务给子Proxy |
| `CHILD_SYSTEM` | str | Sub-agent SystemHint词 |

### Function Change Details

1. **主副ProxyTool分离**
 - 主Proxy：`read_file`、`load_skill`、`task_*` 系列Tool
 - 子Proxy：`bash`、`write_file`、`edit_file` ExecuteTool
 - Tool分离确保主Proxy保持简洁Context

2. **子ProxyFunction**
 - `run_subagent()` CreateIndependentto话ContextExecute子任务
 - 子ProxyCompleteafterReturnAbstract给主Proxy
 - Support嵌套Call（but需NoteContextLimitation）

3. **任务委派Tool**
 - 新增 `task(prompt)` Tool供主Proxy委派任务
 - 主Proxy保持Context简洁，Only看toCommandsSame asResult
 - Execute细节不会污染主ProxyContext

4. **IndependentContext Management**
 - 子Proxy拥hasIndependent messages 历史
 - Execute细节不会污染主ProxyContext
 - 子Proxy可以hasIndependent system prompt

5. **Tool集Configuration化**
 - `PARENT_TOOLS` and `CHILD_TOOLS` DictionaryDefinitionTool权限
 - 便at调整主副Proxy AbilityBoundary
 - SupportDifferentScenario Tool集Configuration

```python
# 主代理工具集（任务管理类）
PARENT_TOOLS = {
    "read_file": {"type": "function", "function": {...}},
    "load_skill": {"type": "function", "function": {...}},
    "task_create": {"type": "function", "function": {...}},
    "task_update": {"type": "function", "function": {...}},
    "task_execute_ready": {"type": "function", "function": {...}}
}

# 子代理工具集（执行类）
CHILD_TOOLS = {
    "bash": {"type": "function", "function": {...}},
    "write_file": {"type": "function", "function": {...}},
    "edit_file": {"type": "function", "function": {...}}
}

def run_subagent(prompt: str) -> str:
    # 创建子代理独立对话
    child_history = [
        {"role": "system", "content": CHILD_SYSTEM},
        {"role": "user", "content": prompt}
    ]
    
    # 执行子代理循环
    child_state = LoopState(messages=child_history)
    while run_one_turn(child_state, tools=CHILD_TOOLS):
        pass
    
    # 提取摘要返回给主代理
    return extract_summary(child_state.messages)
```

### 主副ProxyDuty划分

| Duty | 主Proxy | 子Proxy |
|------|--------|--------|
| 任务规划 | ✅ | ❌ |
| 进度Track | ✅ | ❌ |
| File读取 | ✅ | ❌ |
| 技能加载 | ✅ | ❌ |
| Shell Execute | ❌ | ✅ |
| File写入 | ❌ | ✅ |
| File编辑 | ❌ | ✅ |

### Same asbefore一章 Comparison

| Feature | Capiter 4 | Capiter 5 |
|------|-----------|-----------|
| ExecuteModel | 单Proxy | 主Proxy + 子Proxy |
| Tool集 | 统一 | 主副分离 |
| Context | 共享 | Independent子Context |
| 任务委派 | 无 | task Tool |

### Architecture图

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

### 子ProxyExecuteProcess

```
1. 主代理调用 task(prompt="执行具体任务")
2. 创建子代理独立上下文：
   - system prompt: CHILD_SYSTEM
   - user prompt: 传入的 prompt
3. 执行子代理循环：
   - 使用 CHILD_TOOLS
   - 持续直到子代理完成
4. 提取执行摘要
5. 返回摘要给主代理
6. 主代理继续规划
```

### 本章小结

Capiter 5 IntroductionSub-agent System，将任务规划Same asExecute分离。主ProxyResponsible任务拆分and进度Track，子ProxyResponsibleSpecificExecute。Tool集分离确保主Proxy保持简洁 Context，只关Note高层决策。这种设计Decrease了主Context 污染，Improve了长会话 可Manage性。

---

## Capiter 6: Context Management

**File Path**: `code/v1_task_manager/chapter_06/s06_context.py` 
**Full Analysis**: [../zh/chapter_06/s06_context_文档.md](../zh/chapter_06/s06_context_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `CONTEXT_LIMIT` | const | Context长度on限（字符数） |
| `PERSIST_THRESHOLD` | const | Output持久化Threshold |
| `TOOL_RESULTS_DIR` | Path | ToolResultStoreTable of Contents |
| `compact()` | function | Context压缩（LLM Abstract） |
| `estimate_tokens()` | function | 估算 token Quantity |

### Function Change Details

1. **Context预算Manage**
 - `CONTEXT_LIMIT = 50000` 字符as紧凑触发点
 - 超出Limitation时自动触发Abstract压缩
 - 防止超出ModelContext窗口

2. **大Output持久化**
 - ToolOutput超过 `PERSIST_THRESHOLD = 30000` 字符时写入File
 - ContextinOnly保留预览andFile PathReference
 - DecreaseContext占用同时保留完整Output

3. **ToolResultTable of Contents**
 - `TOOL_RESULTS_DIR =.task_outputs/tool-results/`
 - every个ToolOutput保存forIndependentFile
 - File命名IncludeTime戳andTool信息

4. **LLM Abstract压缩**
 - `auto_compact()` Call LLM Generateto话Abstract
 - 替换原始历史forAbstractContinueto话
 - 保留关键决策andState信息

5. **最近Result保留**
 - `KEEP_RECENT_TOOL_RESULTS = 3` 保留最近 N 条完整Result
 - 较早 Result被压缩or持久化
 - 平衡Context完整性and长度

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

### 持久化OutputFormat

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

### Same asbefore一章 Comparison

| Feature | Capiter 5 | Capiter 6 |
|------|-----------|-----------|
| ContextLimitation | 无Process | 自动 compact |
| 大OutputProcess | 直接Inject | 持久化toFile |
| 历史Manage | 累积 | 压缩 + 保留最近 |
| Token 估算 | 无 | estimate_tokens() |

### Architecture图

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

当上下文 > 50000 chars:
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

### Context ManagementStrategy

```
1. 每次工具执行后检查输出大小
2. 如果输出 > PERSIST_THRESHOLD:
   - 保存到文件
   - 返回引用 + 预览
3. 每轮对话后估算上下文大小
4. 如果上下文 > CONTEXT_LIMIT:
   - 调用 auto_compact()
   - 用摘要替换历史
5. 保留最近 KEEP_RECENT_TOOL_RESULTS 条完整结果
```

### 本章小结

Capiter 6 Implement了Context ManagementMechanism，throughOutput持久化and LLM Abstract压缩ControlContext长度。大Output自动保存toDisk，历史to话可被压缩forAbstract，确保长会话不会超出ModelLimitation。Token 估算Provide近似 ContextUseSituation。

---

## Capiter 7: Permission System

**File Path**: `code/v1_task_manager/chapter_07/s07_permission_system.py` 
**Full Analysis**: [../zh/chapter_07/s07_permission_文档.md](../zh/chapter_07/s07_permission_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `BashSecurityValidator` | class | Bash CommandsSecurityVerify |
| `PermissionManager` | class | 权限决策Manage器 |
| `MODES` | tuple | 权限模（default/plan/auto） |
| `DEFAULT_RULES` | list | Default权限RulesList |
| `is_workspace_trusted()` | function | 工作区信任Check |

### Function Change Details

1. **Bash SecurityVerify**
 - `BashSecurityValidator` DetectDangerous Command模
 - VerifyRules：`sudo`、`rm -rf`、`$()`、`IFS=` etc.
 - 严重模（sudo、rm_rf）直接拒绝

2. **权限决策管线**
 - 四Stage：deny_rules → mode_check → allow_rules → ask_user
 - 首个匹配Rules决定行for（allow/deny/ask）
 - 流水线设计便atExtend新Rules

3. **三种权限模**
 - `default`：非只读Tool需UserConfirmation
 - `plan`：更严Format ConfirmationStrategy
 - `auto`：Only高RiskOperation需Confirmation

4. **Rules匹配System**
 - RulesFormat：`{tool, path/content, behavior}`
 - Support通配符 `*` 匹配
 - Rules按顺序Check，首个匹配生效

5. **Continuous拒绝Track**
 - `consecutive_denials` Counter防止无限询问
 - 达to `max_consecutive_denials` after自动Stop
 - 避免Model陷入询问Loop

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

### 权限Rules示例

```python
DEFAULT_RULES = [
    # 总是拒绝危险命令
    {"tool": "bash", "content": "rm -rf /", "behavior": "deny"},
    {"tool": "bash", "content": "sudo *", "behavior": "deny"},
    # 允许读取任何文件
    {"tool": "read_file", "path": "*", "behavior": "allow"},
    # 允许写入特定目录
    {"tool": "write_file", "path": "logs/*", "behavior": "allow"},
]
```

### Same asbefore一章 Comparison

| Feature | Capiter 6 | Capiter 7 |
|------|-----------|-----------|
| SecurityControl | Simple黑名单 | 多级权限管线 |
| User交互 | 无 | ask 模询问 |
| RulesSystem | 无 | 可ConfigurationRulesList |
| 模Support | 无 | default/plan/auto |

### Architecture图

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

### 权限决策Process

```
1. 工具调用发生
2. BashSecurityValidator 检查危险命令
   - 如果严重违规：直接 deny
3. PermissionManager 检查规则：
   a. deny_rules：匹配则 deny
   b. mode_check：根据模式决定
   c. allow_rules：匹配则 allow
   d. 默认：ask 用户
4. 返回决策给调用方
```

### 本章小结

Capiter 7 Establish了完整 Permission System，Include Bash CommandsSecurityVerifyand多级权限决策管线。三种模适应DifferentScenario，RulesSystemSupport灵活Configuration，Continuous拒绝Track防止无限询问。Permission SystemSame asToolCall深度集成，确保OperationSecurity。

---

## Capiter 8: Hook System

**File Path**: `code/v1_task_manager/chapter_08/s08_hook_system.py` 
**Full Analysis**: [../zh/chapter_08/s08_hook_文档.md](../zh/chapter_08/s08_hook_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `HookManager` | class | Hook Manage器，加载andExecute钩子 |
| `HOOK_EVENTS` | tuple | Support 事件Type（PreToolUse/PostToolUse/SessionStart） |
| `.hooks.json` | file | Hook ConfigurationFile，Definitionoutside部脚本 |
| `run_pre_tool_use()` | method | ToolCallbefore拦截，Execute权限Checkandoutside部 Hook |
| `run_post_tool_use()` | method | ToolCallafter拦截，Executeoutside部 Hook |
| `_run_external_hooks()` | method | Executeoutside部脚本 Hook |

### Function Change Details

1. **Hook 事件Type**
 - `PreToolUse`：ToolCallbefore触发，可Used for权限Review、Parameter修改
 - `PostToolUse`：ToolCallafter触发，可Used forResultProcess、日志记录
 - `SessionStart`：会话开始时触发，可Used for初始化

2. **统一拦截管线**
 - Ring 0：inside置Security/权限Check（PermissionManager）
 - Ring 1：outside部自Definition Hook 脚本
 - 两StageProcess确保Security优先

3. **ConfigurationFileFormat**
 - `.hooks.json` Definitionoutside部 Hook Commands
 - Support matcher 指定触发Tool（`*` IndicateallTool）
 - Commandsthrough subprocess Execute

4. **Environment变量Inject**
 - Hook Execute时Inject `HOOK_EVENT`、`HOOK_TOOL_NAME` etc.Environment变量
 - 脚本可访问ToolInputOutput
 - Support脚本修改ToolInput（updated_input）

5. **阻塞Ability**
 - Hook 可Return `{"blocked": true, "block_reason": "..."}` 阻止ToolExecute
 - Support修改ToolInput（updated_input）
 - Support添加Extra消息toContext

```python
HOOK_EVENTS = ("PreToolUse", "PostToolUse", "SessionStart")
HOOK_TIMEOUT = 30  # seconds

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
    
    def run_pre_tool_use(self, context: dict) -> dict:
        """统一的 PreToolUse 拦截管线。"""
        result = {"blocked": False, "block_reason": "", "messages": []}
        tool_name = context.get("tool_name", "")
        tool_input = context.get("tool_input", {})

        # Ring 0: 内置安全与权限 Hook
        decision = self.perms.check(tool_name, tool_input)
        if decision["behavior"] == "deny":
            return {"blocked": True, "block_reason": f"Permission denied: {decision['reason']}"}
        elif decision["behavior"] == "ask":
            if not self.perms.ask_user(tool_name, tool_input):
                return {"blocked": True, "block_reason": f"User denied execution for {tool_name}"}

        # Ring 1: 外部自定义 Hook
        ext_result = self._run_external_hooks("PreToolUse", context)
        if ext_result["blocked"]:
            return ext_result
        if "updated_input" in ext_result:
            context["tool_input"] = ext_result["updated_input"]
        return result
    
    def _run_external_hooks(self, event: str, context: dict) -> dict:
        result = {"blocked": False, "block_reason": "", "messages": []}
        hooks = self.hooks.get(event, [])
        for hook_def in hooks:
            matcher = hook_def.get("matcher")
            if matcher and context:
                tool_name = context.get("tool_name", "")
                if matcher != "*" and matcher != tool_name:
                    continue
            
            command = hook_def.get("command", "")
            if not command: continue
            
            env = dict(os.environ)
            env["HOOK_EVENT"] = event
            env["HOOK_TOOL_NAME"] = context.get("tool_name", "")
            env["HOOK_TOOL_INPUT"] = json.dumps(context.get("tool_input", {}))[:10000]
            
            r = subprocess.run(command, shell=True, cwd=WORKDIR, env=env,
                             capture_output=True, text=True, timeout=HOOK_TIMEOUT)
            if r.returncode != 0:
                result["messages"].append(f"Hook error: {r.stderr}")
        return result
```

### Hook Configuration示例

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "bash",
        "command": "echo 'Executing bash: $HOOK_TOOL_INPUT' >> .hook_log.txt"
      },
      {
        "matcher": "*",
        "command": "python scripts/audit_tool.py"
      }
    ],
    "PostToolUse": [
      {
        "matcher": "write_file",
        "command": "git add $HOOK_TOOL_INPUT_PATH"
      }
    ]
  }
}
```

### Same asbefore一章 Comparison

| Feature | Capiter 7 | Capiter 8 |
|------|-----------|-----------|
| 权限集成 | 直接Call | Hook 管线 Ring 0 |
| Extend点 | 无 | outside部脚本 Hook |
| ConfigurationWay | 代码 |.hooks.json |
| 事件Type | 无 | 3 种 Hook 事件 |

### Architecture图

```
┌─────────────┐
│ PreToolUse  │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│  Ring 0: Internal   │
│  PermissionManager  │
└──────┬──────────────┘
       │ passed
       ▼
┌─────────────────────┐
│  Ring 1: External   │
│  .hooks.json hooks  │
└──────┬──────────────┘
       │
   ┌───┴───┐
   ▼       ▼
 execute  blocked
```

### Hook ExecuteProcess

```
1. 工具调用触发 PreToolUse 事件
2. HookManager.run_pre_tool_use() 执行：
   a. Ring 0: PermissionManager 检查权限
      - deny: 直接返回 blocked
      - ask: 询问用户，拒绝则 blocked
      - allow: 继续
   b. Ring 1: 外部 Hook 脚本
      - 执行匹配的命令
      - 可修改输入或返回 blocked
3. 如果未 blocked，执行工具
4. 工具完成后触发 PostToolUse 事件
5. 执行 PostToolUse Hook
```

### 本章小结

Capiter 8 将权限Review集成to Hook Systemin，形成统一 拦截管线。Ring 0 Processinside置SecurityCheck，Ring 1 Supportoutside部脚本Extend。Hook SystemforFrameworkProvide了可插拔 事件ProcessAbility，SupportToolCallbeforeafter自Definition逻辑。

---

## Capiter 9: Memory System

**File Path**: `code/v1_task_manager/chapter_09/s09_memory_system.py` 
**Full Analysis**: [../zh/chapter_09/s09_memory_system_文档.md](../zh/chapter_09/s09_memory_system_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `MemoryManager` | class | 记忆Manage器，加载and保存记忆 |
| `MEMORY_TYPES` | tuple | 记忆Type（user/feedback/project/reference） |
| `MEMORY_DIR` | Path | 记忆StoreTable of Contents（.memory/） |
| `MEMORY_INDEX` | Path | 记忆索引File（MEMORY.md） |
| `load_memory_prompt()` | method | Build记忆Hint词Injectto system prompt |

### Function Change Details

1. **记忆DataStructure**
 - every条记忆forIndependent Markdown File
 - frontmatter Include name、description、type
 - inside容 body StoreSpecific记忆信息

2. **四种记忆Type**
 - `user`：User偏好and习惯（usually private）
 - `feedback`：UserFeedback（Default private）
 - `project`：项目SpecificKnowledge（usually team）
 - `reference`：参考Material（usually team）

3. **记忆索引**
 - `MEMORY.md` as记忆索引File
 - Limitation最多 200 行防止过长
 - 便atFast浏览all记忆

4. **SystemHintInject**
 - `load_memory_prompt()` at会话启动时加载记忆
 - 按Type分组Displayto system prompt
 - 记忆inside容at会话in持久可用

5. **记忆Store原then**
 - OnlyStore跨会话Effective Knowledge
 - 不Store可重新推导 信息（FileStructure、临时Stateetc.）
 - 避免Store敏感信息（密钥、密码etc.）

```python
MEMORY_TYPES = ("user", "feedback", "project", "reference")
MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
MAX_INDEX_LINES = 200

class MemoryManager:
    def __init__(self, memory_dir: Path = None):
        self.memory_dir = memory_dir or MEMORY_DIR
        self.memories = {}  # name -> {description, type, content}
    
    def load_all(self):
        """Load MEMORY.md index and all individual memory files."""
        self.memories = {}
        if not self.memory_dir.exists():
            return
        for md_file in sorted(self.memory_dir.glob("*.md")):
            if md_file.name == "MEMORY.md":
                continue
            parsed = self._parse_frontmatter(md_file.read_text())
            if parsed:
                name = parsed.get("name", md_file.stem)
                self.memories[name] = {
                    "description": parsed.get("description", ""),
                    "type": parsed.get("type", "project"),
                    "content": parsed.get("content", ""),
                    "file": md_file.name,
                }
    
    def load_memory_prompt(self) -> str:
        """Build a memory section for injection into the system prompt."""
        if not self.memories:
            return ""
        sections = ["# Memories (persistent across sessions)", ""]
        for mem_type in MEMORY_TYPES:
            typed = {k: v for k, v in self.memories.items() if v["type"] == mem_type}
            if not typed:
                continue
            sections.append(f"## [{mem_type}]")
            for name, mem in typed.items():
                sections.append(f"### {name}: {mem['description']}")
                if mem["content"].strip():
                    sections.append(mem["content"].strip())
                sections.append("")
        return "\n".join(sections)
    
    def save_memory(self, name: str, description: str, mem_type: str, content: str) -> str:
        if mem_type not in MEMORY_TYPES:
            return f"Error: type must be one of {MEMORY_TYPES}"
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower())
        file_name = f"{safe_name}.md"
        file_path = self.memory_dir / file_name
        
        frontmatter = f"---\nname: {name}\ndescription: {description}\ntype: {mem_type}\n---\n{content}\n"
        file_path.write_text(frontmatter)
        return f"Memory '{name}' saved to {file_name}"
```

### 记忆File示例

```markdown
---
name: user_coding_style
description: 用户偏好使用 snake_case 命名和详细注释
type: user
---

用户在编写 Python 代码时偏好：
- 使用 snake_case 命名变量和函数
- 添加详细的 docstring
- 类型注解使用 typing 模块
- 错误处理使用 try-except 显式捕获
```

### Same asbefore一章 Comparison

| Feature | Capiter 8 | Capiter 9 |
|------|-----------|-----------|
| 持久化Knowledge | 无 | MemoryManager |
| Type区分 | 无 | 4 种记忆Type |
| 会话继承 | 无 | 跨会话记忆 |
| 索引File | 无 | MEMORY.md |

### Architecture图

```
┌───────────────────┐
│ .memory/          │
│  user_pref.md     │
│  project_info.md  │
│  MEMORY.md        │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  MemoryManager    │
│  load_all()       │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  System Prompt    │
│  + Memories       │
│    (grouped by    │
│     type)         │
└──────────────────┘
```

### 记忆ManageProcess

```
1. 会话启动时：
   - MemoryManager.load_all() 扫描 .memory/ 目录
   - 解析每个 .md 文件的 frontmatter
   - 建立内存索引
2. 构建 system prompt:
   - load_memory_prompt() 按类型分组
   - 注入到 system prompt
3. 会话中：
   - 模型可查看记忆内容
   - 可根据记忆调整行为
4. 需要保存记忆时：
   - save_memory() 创建/更新 .md 文件
   - 下次会话自动加载
```

### 本章小结

Capiter 9 Implement了跨会话Memory System，SupportUser偏好、项目Knowledgeetc.持久化Store。记忆按Type分组，OnlyStore无法From当before工作重新推导 Knowledge，避免冗余and过时信息。frontmatter FormatSupportStructure化 元DataManage。

---

## Capiter 10: Build System

**File Path**: `code/v1_task_manager/chapter_10/s10_build_system.py` 
**Full Analysis**: [../zh/chapter_10/s10_build_system_文档.md](../zh/chapter_10/s10_build_system_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `SystemPromptBuilder` | class | SystemHintBuild器 |
| `build()` | method | 组装完整 system prompt |
| `_build_core()` | method | Build核心指令part |
| `_build_memory()` | method | Inject记忆part |
| `_build_claude_md_chain()` | method | 读取 CLAUDE.md Document链 |
| `_build_dynamic_context()` | method | Inject动态Context |

### Function Change Details

1. **Structure化Hint词**
 - 固定组：核心指令、ToolList、技能元Data
 - 动态组：记忆、CLAUDE.md 链、动态Context
 - Module化设计便at维护andExtend

2. **SystemHintBuild器**
 - `SystemPromptBuilder` ClassResponsible组装eachpart
 - Support主Proxyand子ProxyDifferentConfiguration
 - 按需InjectDifferentComponent

3. **Memory 集成**
 - `load_memory_prompt()` Inject持久化记忆
 - 按Type分组Display
 - Onlyat记忆Exists时Inject

4. **项目Document链**
 - 读取 `CLAUDE.md` 及其Reference链
 - Inject项目SpecificSpecificationtoHint词
 - Support相to路径andFileDoes Not ExistProcess

5. **动态Context**
 - 根据当beforeStateInjectExtra信息
 - Such as任务List、worktree Stateetc.
 - 保持Hint词Same as当beforeState同步

```python
class SystemPromptBuilder:
    def __init__(self, agent_type: str = "parent"):
        self.agent_type = agent_type
        self.tools = PARENT_TOOLS if agent_type == "parent" else CHILD_TOOLS
    
    def _build_core(self) -> str:
        return f"""You are a coding agent operating at {WORKDIR}.

## Core Principles
1. Use tools to complete tasks efficiently
2. Follow project guidelines and user preferences
3. Maintain context within limits

## Available Tools
{self._list_tools()}

## Skills Available
{self._list_skills()}
"""
    
    def _build_memory(self) -> str:
        return self.memory_manager.load_memory_prompt()
    
    def _build_claude_md_chain(self) -> str:
        parts = []
        claude_md = WORKDIR / "CLAUDE.md"
        if claude_md.exists():
            parts.append("## Project Guidelines (CLAUDE.md)")
            parts.append(claude_md.read_text()[:10000])
        return "\n\n".join(parts)
    
    def _build_dynamic_context(self) -> str:
        parts = ["## Dynamic Context"]
        # 添加任务状态
        if self.task_manager:
            parts.append(self.task_manager.list_all())
        # 添加 worktree 状态
        if self.worktree_manager:
            parts.append(self.worktree_manager.list())
        return "\n\n".join(parts) if len(parts) > 1 else ""
    
    def build(self) -> str:
        parts = [
            self._build_core(),
            self._build_memory(),
            self._build_claude_md_chain(),
            self._build_dynamic_context(),
        ]
        return "\n\n".join(p for p in parts if p)
```

### Hint词Structure

```
# System Prompt

## Core Instructions (固定)
- Agent 角色定义
- 核心原则
- 可用工具列表
- 可用技能列表

## Memories (动态)
- [user] 用户偏好
- [project] 项目知识
- ...

## Project Guidelines (动态)
- CLAUDE.md 内容

## Dynamic Context (动态)
- 当前任务列表
- Worktree 状态
- 其他运行时信息
```

### Same asbefore一章 Comparison

| Feature | Capiter 9 | Capiter 10 |
|------|-----------|------------|
| Hint词Organization | 拼接 | Structure化Build器 |
| Document链 | 无 | CLAUDE.md 链 |
| 动态Inject | 无 | 动态Context |
| 主副区分 | 无 | agent_type Parameter |

### Architecture图

```
┌─────────────────────┐
│ SystemPromptBuilder │
└──────────┬──────────┘
           │
    ┌──────┼──────┬──────────┬──────────────┐
    ▼      ▼      ▼          ▼              ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐  ┌────────────┐
│ Core │ │Memory│ │Skills│ │Claude│  │  Dynamic   │
│      │ │      │ │      │ │  MD  │  │  Context   │
└──────┘ └──────┘ └──────┘ └──────┘  └────────────┘
    │      │      │          │              │
    └──────┴──────┴──────────┴──────────────┘
                           │
                           ▼
                  ┌────────────────┐
                  │ System Prompt  │
                  └────────────────┘
```

### 本章小结

Capiter 10 Implement了Structure化 SystemHintBuild器，将Hint词分for固定组and动态组。Memory、Skills、CLAUDE.md 链etc.Component按需Inject，Support主副ProxyDifferentConfiguration，便at维护andExtend。动态Context确保Hint词Same asRun时State同步。

---

## Capiter 11: Resume System

**File Path**: `code/v1_task_manager/chapter_11/s11_Resume_system.py` 
**Full Analysis**: [../zh/chapter_11/s11_Resume_system_文档.md](../zh/chapter_11/s11_Resume_system_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `MAX_RECOVERY_ATTEMPTS` | const | 最大Resume尝试Count（3 次） |
| `BACKOFF_BASE_DELAY` | const | 指数退避BasicLatency（1 Seconds） |
| `auto_compact()` | function | 自动Context压缩 |
| `backoff_delay()` | function | 计算退避Latency |
| 多层错误捕获 | concept | UserInput/API/Tool错误Process |

### Function Change Details

1. **多层错误Process**
 - UserInput错误（EOF、键盘in断）
 - 主Loop错误（API Call、ToolExecute）
 - 子Loop错误（子ProxyExecute）
 - every层allhas相应 ResumeStrategy

2. **Output超限Resume**
 - Detect `max_tokens` StopReason
 - InjectContinue消息："Output limit hit. Continue directly."
 - 最多Retry `MAX_RECOVERY_ATTEMPTS = 3` 次
 - Counter防止无限Retry

3. **API 错误Resume**
 - `prompt_too_long`：触发 auto_compact + Retry
 - `connection/rate`：指数退避Retry
 - Other错误：Return Error Information

4. **指数退避Strategy**
 - `backoff_delay()`: base * 2^attempt + jitter
 - 最大Latency 30 Seconds，避免频繁Retry
 - 随机抖动防止and发冲突

5. **Context压缩触发**
 - 估算 token 数：`len(json.dumps(messages)) // 4`
 - 超限时Call LLM GenerateAbstract
 - Abstract保留关键信息

```python
MAX_RECOVERY_ATTEMPTS = 3
BACKOFF_BASE_DELAY = 1.0
BACKOFF_MAX_DELAY = 30.0

CONTINUATION_MESSAGE = (
    "Output limit hit. Continue directly from where you stopped -- "
    "no recap, no repetition. Pick up mid-sentence if needed."
)

def backoff_delay(attempt: int) -> float:
    """Exponential backoff with jitter: base * 2^attempt + random(0, 1)."""
    delay = min(BACKOFF_BASE_DELAY * (2 ** attempt), BACKOFF_MAX_DELAY)
    jitter = random.uniform(0, 1)
    return delay + jitter

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

# 主循环中的错误处理
def run_one_turn(state: LoopState) -> bool:
    for attempt in range(MAX_RECOVERY_ATTEMPTS):
        try:
            response = client.chat.completions.create(...)
            # 检查停止原因
            if response.choices[0].finish_reason == "max_tokens":
                state.messages.append({"role": "user", "content": CONTINUATION_MESSAGE})
                continue  # 重试
            # 正常处理...
            return True
        except APIError as e:
            if e.type == "prompt_too_long":
                state.messages = auto_compact(state.messages)
                continue
            elif e.type in ("connection", "rate_limit"):
                time.sleep(backoff_delay(attempt))
                continue
            raise
    return False
```

### 错误TypeSame asResumeStrategy

| 错误Type | DetectWay | ResumeStrategy |
|----------|----------|----------|
| max_tokens | finish_reason | InjectContinue消息 + Retry |
| prompt_too_long | API error type | auto_compact + Retry |
| connection | API error type | 指数退避 + Retry |
| rate_limit | API error type | 指数退避 + Retry |
| Other | - | 抛出Exception |

### Same asbefore一章 Comparison

| Feature | Capiter 10 | Capiter 11 |
|------|------------|------------|
| 错误Process | Basic | 多层ResumeStrategy |
| Output超限 | 无 | ContinueInjectResume |
| API Retry | 无 | 指数退避 |
| 压缩触发 | 无 | prompt_too_long |

### Architecture图

```
┌─────────────┐
│ LLM Response│
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│ Check stop_reason   │
└──────┬──────────────┘
       │
   ┌───┴───────────────┬─────────────┐
   ▼                   ▼             ▼
max_tokens          API error     end_turn
   │                   │             │
   ▼                   ▼             │
Continue inject    ┌──┴──────┐      │
   │               ▼         ▼      │
   │         prompt_too   conn/rate │
   │           long       │         │
   │           │          │         │
   │           ▼          ▼         │
   │       compact    backoff       │
   │           │          │         │
   └───────────┴──────────┴─────────┘
                       │
                       ▼
                  Retry loop
                  (max 3 times)
```

### ResumeProcess示例

```
1. LLM 返回 finish_reason="max_tokens"
2. 检测到输出超限
3. 注入 CONTINUATION_MESSAGE
4. 重试 LLM 调用
5. 如果成功，继续正常流程
6. 如果仍超限，计数器 +1
7. 达到 MAX_RECOVERY_ATTEMPTS 后放弃

API 错误流程：
1. 捕获 APIError
2. 检查错误类型
3. prompt_too_long → auto_compact → 重试
4. connection/rate → backoff_delay → 重试
5. 其他错误 → 抛出
```

### 本章小结

Capiter 11 Enhance了错误ResumeAbility，针toOutput超限、API 错误、连接Questionetc.DifferentScenarioImplement差异化ResumeStrategy。多层错误Process确保FrameworkatExceptionSituationbelow能够优雅降级andContinueExecute。指数退避andRetryLimitation防止无限Loop。

---

## Capiter 12: Task System Enhancement

**File Path**: `code/v1_task_manager/chapter_12/s12_task_system.py` 
**Full Analysis**: [../zh/chapter_12/s12_task_system_文档.md](../zh/chapter_12/s12_task_system_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `TaskManager` | class | 任务 CRUD Manage器 |
| `TASKS_DIR` | Path | 任务StoreTable of Contents（.tasks/） |
| task_create/update/list/get | tools | 任务OperationTool |
| blockedBy/blocks | fields | 任务Dependency关系字段 |
| `_clear_dependency()` | method | Complete任务时清除Dependency |

### Function Change Details

1. **持久化任务Store**
 - every个任务保存for `task_{id}.json` File
 - Support跨会话任务Track
 - File Path：`.tasks/task_1.json`、`.tasks/task_2.json` etc.

2. **任务Dependency关系**
 - `blockedBy`：当before任务被哪些任务阻塞
 - `blocks`：当before任务阻塞哪些任务
 - 双toward关联自动维护
 - Support任务图Structure

3. **任务StateManage**
 - State：`pending`、`in_progress`、`completed`、`deleted`
 - Complete任务时自动清除Dependency
 - State变更触发DependencyUpdate

4. **任务 CRUD Tool**
 - `task_create`：Create新任务
 - `task_update`：UpdateState/Dependency
 - `task_list`：列出all任务
 - `task_get`：获取单个任务详情

5. **任务 ID 自增**
 - `_max_id()` 读取现has任务计算below一个 ID
 - 确保 ID Unique性andContinuous性
 - Support删除after ID 复用（可选）

```python
class TaskManager:
    def __init__(self, tasks_dir: Path):
        self.dir = tasks_dir
        self.dir.mkdir(exist_ok=True)
        self._next_id = self._max_id() + 1
    
    def _max_id(self) -> int:
        ids = [int(f.stem.split("_")[1]) for f in self.dir.glob("task_*.json")]
        return max(ids) if ids else 0
    
    def _load(self, task_id: int) -> dict:
        path = self.dir / f"task_{task_id}.json"
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text())
    
    def _save(self, task: dict):
        path = self.dir / f"task_{task['id']}.json"
        path.write_text(json.dumps(task, indent=2, ensure_ascii=False))
    
    def create(self, subject: str, description: str = "") -> str:
        task = {
            "id": self._next_id, "subject": subject, "description": description,
            "status": "pending", "blockedBy": [], "blocks": [], "owner": "",
        }
        self._save(task)
        self._next_id += 1
        return json.dumps(task, indent=2, ensure_ascii=False)
    
    def update(self, task_id: int, status: str = None, owner: str = None,
               add_blocked_by: list = None, add_blocks: list = None) -> str:
        task = self._load(task_id)
        if status:
            task["status"] = status
            if status == "completed":
                self._clear_dependency(task_id)
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if add_blocks:
            task["blocks"] = list(set(task["blocks"] + add_blocks))
            for blocked_id in add_blocks:
                try:
                    blocked = self._load(blocked_id)
                    if task_id not in blocked["blockedBy"]:
                        blocked["blockedBy"].append(task_id)
                        self._save(blocked)
                except ValueError:
                    pass
        self._save(task)
        return json.dumps(task, indent=2, ensure_ascii=False)
    
    def _clear_dependency(self, completed_id: int):
        """Remove completed_id from all other tasks' blockedBy lists."""
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text())
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                self._save(task)
```

### 任务DataStructure

```json
{
  "id": 1,
  "subject": "实现用户认证模块",
  "description": "添加登录、注册、token 验证功能",
  "status": "in_progress",
  "blockedBy": [],
  "blocks": [2, 3],
  "owner": "agent_1"
}
```

### Same asbefore一章 Comparison

| Feature | Capiter 11 | Capiter 12 |
|------|------------|------------|
| 任务Manage | TodoManager（Memory） | TaskManager（持久化） |
| Dependency关系 | 无 | blockedBy/blocks |
| 跨会话 | 无 | FileStore |
| 任务图 | 无 | 双towardDependency |

### Architecture图

```
┌─────────────┐
│ TaskManager │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│ .tasks/             │
│  task_1.json        │
│  task_2.json        │
│  task_3.json        │
└─────────────────────┘

Task structure:
{
  "id": 1,
  "subject": "...",
  "status": "pending",
  "blockedBy": [2],  # 被 task_2 阻塞
  "blocks": [3],     # 阻塞 task_3
  "owner": ""
}

依赖关系示例:
task_1 (completed) ──blocks──> task_2 (pending)
                              │
                              └──blockedBy task_1 (自动清除)
```

### 任务DependencyProcess

```
1. 创建 task_1，blocks=[2]
2. 创建 task_2，blockedBy=[1]
   - 自动建立双向关联
3. 完成 task_1:
   - _clear_dependency(1) 遍历所有任务
   - 从 task_2.blockedBy 移除 1
4. task_2 不再被阻塞，可开始执行
```

### 本章小结

Capiter 12 将任务ManageFromMemoryUpgradeto持久化Store，Support跨会话任务Track。任务Dependency关系System（blockedBy/blocks）SupportComplex任务图，Complete任务时自动清理Dependency关系。双toward关联确保DependencyState一致性。

---

## Capiter 13: v2 Background Tasks

**File Path**: `code/v1_task_manager/chapter_13/s13_v2_backtask.py` 
**Full Analysis**: [../zh/chapter_13/s13_v2_backtask_文档.md](../zh/chapter_13/s13_v2_backtask_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `BackgroundManager` | class | Background任务Manage器 |
| `NotificationQueue` | class | 优先级Notify队列 |
| `run_subagent_background()` | function | Background子ProxyExecute |
| `check_background()` | function | QueryBackground任务State |
| `detect_stalled()` | method | Detect停滞任务 |

### Function Change Details

1. **Background子Proxy**
 - `run_subagent_background()` atBackground线程启动子Proxy
 - immediatelyReturn task_id（Format `sub_xxxxxxxx`）
 - Completeafter推送AbstracttoNotify队列
 - 主Proxy可ContinueOther工作

2. **Notify队列**
 - `NotificationQueue` Support优先级（immediate/high/medium/low）
 - 同 key 消息折叠，避免重复Notify
 - `drain()` Method供主Loop获取待ProcessNotify
 - 线程Security 队列Operation

3. **Tool变更**
 - 新增：`background_task(prompt)`、`check_background(task_id?)`
 - 删除：`task(prompt)`（串行子Proxy）
 - 主ProxyTool集调整for异步模

4. **任务StateTrack**
 - `RUNTIME_DIR/.runtime-tasks/` Store任务记录
 - State：`running`、`completed`、`stalled`
 - Output保存toIndependent日志File
 - Support任务QueryandStateCheck

5. **停滞Detect**
 - `STALL_THRESHOLD_S = 45` Seconds判定停滞
 - `detect_stalled()` CheckTimeout任务
 - 停滞任务可被清理or重新调度

```python
class NotificationQueue:
    PRIORITIES = {"immediate": 0, "high": 1, "medium": 2, "low": 3}
    def __init__(self):
        self._queue = []
        self._lock = threading.Lock()
    
    def push(self, message: str, priority: str = "medium", key: str = None):
        with self._lock:
            if key:
                self._queue = [(p, k, m) for p, k, m in self._queue if k != key]
            self._queue.append((self.PRIORITIES.get(priority, 2), key, message))
            self._queue.sort(key=lambda x: x[0])
    
    def drain(self) -> list:
        with self._lock:
            messages = [m for _, _, m in self._queue]
            self._queue.clear()
            return messages

class BackgroundManager:
    def __init__(self):
        self.dir = RUNTIME_DIR
        self.tasks = {}
        self._lock = threading.Lock()
    
    def run(self, command: str) -> str:
        task_id = str(uuid.uuid4())[:8]
        output_file = self.dir / f"{task_id}.log"
        
        with self._lock:
            self.tasks[task_id] = {
                "id": task_id, "status": "running", "command": command,
                "started_at": time.time(), "result": None
            }
        
        thread = threading.Thread(
            target=self._execute, args=(task_id, command, output_file), daemon=True
        )
        thread.start()
        return f"Background task started: {task_id}"
    
    def _execute(self, task_id: str, command: str, output_file: Path):
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            with self._lock:
                self.tasks[task_id]["status"] = "completed"
                self.tasks[task_id]["result"] = result.stdout[:500]
                self.tasks[task_id]["finished_at"] = time.time()
            # 推送通知
            BG_NOTIFICATIONS.push(f"Task {task_id} completed", priority="high", key=task_id)
        except Exception as e:
            with self._lock:
                self.tasks[task_id]["status"] = "failed"
                self.tasks[task_id]["result"] = str(e)

def run_subagent_background(prompt: str) -> str:
    task_id = str(uuid.uuid4())[:8]
    thread = threading.Thread(target=run_subagent, args=(prompt, task_id), daemon=True)
    thread.start()
    return f"Subagent started with task_id: {task_id}"
```

### Same asbefore一章 Comparison

| Feature | Capiter 12 | Capiter 13 |
|------|------------|------------|
| 子ProxyExecute | 串行阻塞 | Backgroundand行 |
| NotifyMechanism | 无 | 优先级队列 |
| 任务Query | 无 | check_background |
| 停滞Detect | 无 | detect_stalled |

### Architecture图

```
┌───────────────┐
│  Main Agent   │
│  agent_loop   │
└───────┬───────┘
        │ background_task()
        ▼
┌───────────────┐     ┌─────────────┐
│ BackgroundMgr │ ──> │  Thread 1   │
│               │     │ (subagent)  │
│               │     └──────┬──────┘
│               │            │
│               │     ┌──────┴──────┐
│               │     │  Thread 2   │
│               │     │ (subagent)  │
│               │     └──────┬──────┘
│               │            │
│               │     ┌──────▼──────┐
│               │     │ Notification│
│               │     │   Queue     │
│               │     └──────┬──────┘
└───────────────┘            │
        ▲                    │ drain()
        └────────────────────┘
```

### Background任务ExecuteProcess

```
1. 主代理调用 background_task(prompt)
2. BackgroundManager 创建任务记录
3. 启动后台线程执行子代理
4. 立即返回 task_id 给主代理
5. 主代理继续其他工作
6. 子代理完成后：
   a. 更新任务状态为 completed
   b. 推送通知到队列
7. 主循环 drain 通知队列
8. 注入通知到对话上下文
```

### 本章小结

Capiter 13 IntroductionBackground任务ExecuteAbility，子Proxy可atBackground线程and行Run。Notify队列Support优先级and消息折叠，主Loop定期 drain 获取CompleteNotify。停滞Detect防止任务无限期挂起。异步ExecuteModelImprove了Framework and发Ability。

---

## Capiter 14: Cron Scheduler

**File Path**: `code/v1_task_manager/chapter_14/s14_cron_scheduler.py` 
**Full Analysis**: [../zh/chapter_14/s14_cron_scheduler_文档.md](../zh/chapter_14/s14_cron_scheduler_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `CronScheduler` | class | Cron 定时任务Scheduler |
| `CronLock` | class | 基at PID File 锁（防止重复触发） |
| `cron_matches()` | function | Cron Express匹配Function |
| `SCHEDULED_TASKS_FILE` | const | 定时任务ConfigurationFile Path |
| `check_due()` | method | Checkto期任务 |
| `execute_task()` | method | Execute定时任务 |

### Function Change Details

1. **Cron ExpressSupport**
 - Standard 5 字段Format：`minute hour day month day_of_week`
 - SupportSpecial字符：`*`（任意）、`*/n`（every n）、`n,m`（多值）、`n-m`（Range）
 - 示例：`0 30 * * *`（every 30 分钟）、`0 2 * * *`（every天 2 点）

2. **CronLock 防重复触发**
 - 基at PID File 锁Mechanism
 - 任务Executebefore获取锁，Executeafter释放
 - 防止同一任务多次and发Execute

3. **任务持久化**
 - 任务Configuration保Exists `cron_state.json`
 - 记录lastExecuteTimeandbelow次PlanExecuteTime
 - SupportRestartafterResume调度State

4. **SchedulerLoop**
 - 定期Checkto期任务（Defaultevery分钟）
 - `check_due()` 比to当beforeTimeSame as Cron Express
 - `execute_task()` Execute任务andUpdateState

5. **Same asBackground任务集成**
 - 定时任务可Call `background_task()` Execute
 - Support长TimeRun 定时作业
 - 任务CompleteNotify推送to队列

```python
def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Check if datetime matches cron expression"""
    minute, hour, day, month, dow = cron_expr.split()
    
    matches_minute = _match_field(minute, dt.minute, 0, 59)
    matches_hour   = _match_field(hour, dt.hour, 0, 23)
    matches_day    = _match_field(day, dt.day, 1, 31)
    matches_month  = _match_field(month, dt.month, 1, 12)
    matches_dow    = _match_field(dow, dt.weekday(), 0, 6)
    
    return all([matches_minute, matches_hour, matches_day, matches_month, matches_dow])

class CronLock:
    def __init__(self, task_name: str):
        self.lock_file = LOCK_DIR / f"{task_name}.pid"
    
    def acquire(self) -> bool:
        if self.lock_file.exists():
            old_pid = int(self.lock_file.read_text().strip())
            if self._is_running(old_pid):
                return False  # 已有实例在运行
        self.lock_file.write_text(str(os.getpid()))
        return True
    
    def release(self):
        if self.lock_file.exists():
            self.lock_file.unlink()

class CronScheduler:
    def check_due(self, task: dict) -> bool:
        now = datetime.now()
        last_run = task.get("last_run")
        if last_run and (now - datetime.fromtimestamp(last_run)).seconds < 60:
            return False  # 1 分钟内不重复检查
        return cron_matches(task["cron"], now)
    
    def execute_task(self, task: dict):
        lock = CronLock(task["name"])
        if not lock.acquire():
            return  # 已有实例在运行
        try:
            # 执行任务（可能是 background_task）
            background_task(task["command"])
            self.update_state(task["name"], time.time())
        finally:
            lock.release()
```

### Same as Capiter 13 Comparison

| Feature | Capiter 13 | Capiter 14 |
|------|------------|------------|
| 触发Way | 手动Call | 定时自动 |
| 任务来源 | Run时传入 | 预DefinitionConfigurationFile |
| and发Control | 线程锁 | CronLock (PID File) |
| State持久化 | Memory | cron_state.json |

### Architecture图

```
┌─────────────────────────────────────────────────────┐
│                CronScheduler Loop                   │
│         (check_due(), execute_task())               │
└─────────────────────┬───────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
        ▼             ▼             ▼
   ┌─────────┐  ┌─────────┐  ┌─────────┐
   │ 0 30 *  │  │ 0 2 * * │  │ 0 0 1 * │
   │ * * *   │  │ * * *   │  │ * * *   │
   │ hourly  │  │ daily   │  │ monthly │
   └────┬────┘  └────┬────┘  └────┬────┘
        │            │            │
        ▼            ▼            ▼
   .cron/lock/     .cron/lock/     .cron/lock/
   hourly.pid      daily.pid       monthly.pid
```

### Cron Express匹配逻辑

```python
def _match_field(field: str, value: int, min_val: int, max_val: int) -> bool:
    """Match single cron field against value."""
    if field == "*":
        return True
    if field.startswith("*/"):
        step = int(field[2:])
        return value % step == 0
    if "," in field:
        return value in [int(x) for x in field.split(",")]
    if "-" in field:
        start, end = map(int, field.split("-"))
        return start <= value <= end
    return value == int(field)
```

### 本章小结

Capiter 14 Introduction定时任务Scheduler，SupportStandard Cron Express。CronLock 防止重复触发，State持久化SupportRestartResume。Scheduler定期Checkto期任务andExecute，Same asBackground任务System集成。

---

## Capiter 18_2: Worktree Isolation

**File Path**: `code/v1_task_manager/chapter_18_2/s18_v2_worktree.py` 
**Full Analysis**: [../zh/chapter_18_2/s18_v2_worktree_文档.md](../zh/chapter_18_2/s18_v2_worktree_文档.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `worktree_create` | function | Create Git Worktree IsolationExecuteEnvironment |
| `worktree_list` | function | 列出all tracked worktrees |
| `worktree_enter` | function | 进入or重新打开 worktree lane |
| `worktree_status` | function | Show git status for one worktree |
| `worktree_run` | function | at named worktree directory Run shell Commands |
| `worktree_closeout` | function | Close out worktree lane (keep/remove) |
| `task_bind_worktree` | function | 绑定 task to worktree name |
| `.worktrees/index.json` | file | Worktree State持久化 |

### Function Change Details

1. **Worktree CreateSame as Git 分支Manage**
 - 基at Git worktree MechanismCreateIsolationExecuteEnvironment
 - SupportFrom指定 base_ref 分支
 - 自动命名Specification（1-40 chars: letters, digits,., _, -）

2. **任务-Worktree 绑定Mechanism**
 - `task_bind_worktree(task_id, worktree, owner)` 
 - 设置 task worktree_state for 'active'
 - Support可选 owner Parameter

3. **Worktree IsolationExecute**
 - `worktree_run(name, command)` atIsolationTable of ContentsExecute
 - every个 worktree hasIndependent git State
 - Supportand行or risky work

4. **生命周期Manage**
 - `worktree_closeout(name, action, reason, force, complete_task)`
 - action: 'keep' 保留or 'remove' 删除
 - 可选 force remove（even ifhas uncommitted changes）
 - 可选 complete_task（Mark bound task Complete）

5. **State持久化Same as事件Track**
 - `.worktrees/index.json` Store worktree 元Data
 - `.worktrees/events.jsonl` 记录 lifecycle events
 - `worktree_events(limit)` Query最近事件

```python
# Worktree 创建示例
def worktree_create(name, task_id=None, base_ref="HEAD"):
    """Create git worktree execution lane"""
    # 验证 name 格式
    # 创建 worktree 目录
    # 更新 .worktrees/index.json
    # 可选绑定 task_id
```

### Same as Capiter 17 Comparison

| Dimension | Capiter 17 | Capiter 18_2 | 变化Description |
|------|------------|--------------|----------|
| ExecuteEnvironment | 单一Table of Contents | 多 worktree Isolation | Supportand行任务 |
| Git State | 共享 | Independent | 避免冲突 |
| 任务绑定 | 无 | worktree_state | ClearExecuteContext |
| 持久化 | Memory | index.json + events.jsonl | 可Resume |

### Architecture图

```
┌─────────────────────────────────────────────────────┐
│              Main Planner Agent                     │
│  (task_create, task_bind_worktree, task_update)    │
└─────────────────────┬───────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
        ▼             ▼             ▼
   ┌─────────┐  ┌─────────┐  ┌─────────┐
   │ WT: fea │  │ WT: fix │  │ WT: exp │
   │  ture1 │  │  _bug1  │  │  eriment│
   └────┬────┘  └────┬────┘  └────┬────┘
        │            │            │
        ▼            ▼            ▼
   .worktrees/index.json (状态持久化)
   .worktrees/events.jsonl (事件日志)
```

### 本章小结

- **核心变化**: From单Table of ContentsExecute → Git Worktree IsolationExecute
- **ArchitectureImprove**: every个 task 可绑定Independent worktree，Supportand行Develop
- **新增Mechanism**: worktree 生命周期Manage、事件Track
- **Duty分离**: Main Planner Responsible任务分配，worktree ResponsibleIsolationExecute

---

## Capiter 19_2: MCP Plugin（v2 MCP Plugin）

**File Path**: `code/v1_task_manager/chapter_19_2/s19_v2_mcp_plugin.py` 
**Full Analysis**: [../zh/chapter_19_2/s19_mcp_plugin.md](../zh/chapter_19_2/s19_mcp_plugin.md)

### Core Components

| Component | Type | Description |
|------|------|------|
| `MCPPlugin` | class | MCP PluginManageClass |
| `mcp__{server}__{tool}` | naming | MCP Tool命名Specification |
| MCP 服务器连接 | connection | Manageoutside部 MCP server 连接 |
| ToolDiscover | discovery | 动态加载outside部Tool |
| ToolNote册 | registry | Note册 MCP tools to agent |

### Function Change Details

1. **MCP Protocol集成**
 - Model Context Protocol (MCP) Standard化Interface
 - Support连接outside部 MCP 服务器
 - 统一 ToolCallSpecification

2. **outside部Tool命名Specification**
 - Format：`mcp__{server}__{tool}`
 - 示例：`mcp__github__list_issues`, `mcp__slack__send_message`
 - 避免Same as原生Tool命名冲突

3. **MCP 服务器连接生命周期**
 - 启动时Establish连接
 - Run时保持长连接
 - Exception时自动重连Mechanism

4. **ToolDiscoverSame asNote册Mechanism**
 - 连接时自动 discovery 可用 tools
 - 动态Note册to agent ToolList
 - Support tool schema Automatically Get

5. **Same as原生Tool 协同工作**
 - MCP tools Same as原生 tools 统一调度
 - `execute_tool_calls()` 透明Process
 - 无感知切换

```python
# MCP 工具调用示例
response = client.chat.completions.create(
    model=MODEL,
    tools=TOOLS + MCP_TOOLS,  # 合并原生和 MCP 工具
    messages=state.messages
)

# 执行时根据命名前缀区分
if tool_name.startswith("mcp__"):
    result = call_mcp_tool(tool_name, args)
else:
    result = call_native_tool(tool_name, args)
```

### Same as Capiter 18_2 Comparison

| Dimension | Capiter 18_2 | Capiter 19_2 | 变化Description |
|------|--------------|--------------|----------|
| ExtendWay | Git Worktree | MCP Protocol | FromIsolationto集成 |
| Tool来源 | inside置 | outside部服务器 | Support第三方 |
| 命名Specification | SimpleName | `mcp__{server}__{tool}` | 避免冲突 |
| 生命周期 | 手动Manage | 自动重连 | 更健壮 |

### Architecture图

```
┌─────────────────────────────────────────────────────┐
│                    Agent Loop                       │
│              execute_tool_calls()                   │
└─────────────────────┬───────────────────────────────┘
                      │
        ┌─────────────┴─────────────┐
        │                           │
        ▼                           ▼
┌───────────────┐          ┌───────────────┐
│ Native Tools  │          │  MCP Plugin   │
│ - bash        │          │               │
│ - read_file   │          │  mcp__github  │
│ - write_file  │          │  mcp__slack   │
│ - task_*      │          │  mcp__jira    │
└───────────────┘          └───────┬───────┘
                                   │
                          ┌────────┴────────┐
                          ▼                 ▼
                    ┌──────────┐     ┌──────────┐
                    │  GitHub  │     │  Slack   │
                    │   API    │     │   API    │
                    └──────────┘     └──────────┘
```

### 本章小结

- **核心变化**: From封闭Tool集 → 开放 MCP 生态集成
- **ArchitectureImprove**: `mcp__{server}__{tool}` 命名Specification，统一调度
- **新增Ability**: Support第三方服务（GitHub, Slack, Jira etc.）
- **Extend性**: 无需修改核心代码that is可接入新服务

---

## DocumentSummary

### 完整ChapterList（16 章）

| Chapter | Subject | 核心变化 |
|------|------|----------|
| 1 | Basic Agent Loop | 单一 bash Tool + 简洁Loop |
| 2 | Tool System Extension | 4 个FileOperationTool |
| 3 | Skill System Introduction | SkillRegistry + load_skill |
| 4 | Task Management System | Todo 持久化 |
| 5 | Sub-agent System | 主/子ProxyDuty分离 |
| 6 | Context Management | 消息历史压缩 |
| 7 | Permission System | FileOperation权限Check |
| 8 | Hook System | before置/after置 Hook |
| 9 | Memory System | MemoryStore 持久化 |
| 10 | Build System | BuildProcess自动化 |
| 11 | Resume System | 会话保存Same as加载 |
| 12 | Task System Enhancement | DependencyManage + 批量Operation |
| 13 | v2 Background Tasks | 异步Execute + Result回收 |
| 14 | Cron Scheduler | 定时任务调度 |
| 18_2 | Worktree Isolation | Git Worktree and行Execute |
| 19_2 | MCP Plugin | outside部服务集成 |

### Architecture演进路线

```
Capter 1-3:   基础能力（Agent Loop → 工具 → 技能）
    ↓
Capter 4-7:   任务与协作（Todo → Subagent → Context → Permission）
    ↓
Capter 8-12:  增强系统（Hook → Memory → Build → Resume → Task v2）
    ↓
Capter 13-14: 异步与调度（Backtask → Cron）
    ↓
Capter 18_2-19_2: 扩展与集成（Worktree → MCP）
```

---

**Document Version**: v2 
**总行数**: 约 2500 行 
**lastUpdate**: 2026-04-22