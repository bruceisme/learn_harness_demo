#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s07_permission_system.py - Permission System

Reference: learn-claude-code (https://github.com/shareAI-lab/learn-claude-code)
License: MIT License

This module introduces a permission system for controlling tool execution.
It demonstrates deny/allow rules, operation modes, and user approval workflows.

Features:
    - Deny rules: Block dangerous commands (rm -rf, sudo, shutdown, etc.)
    - Mode check: Support default, plan, and auto execution modes
    - Allow rules: Whitelist safe commands and file patterns
    - User approval: Interactive confirmation for sensitive operations
    - File operation restrictions: Limit write/edit access to specific directories

Documentation:
    - Chinese: docs/zh/chapter_7/s07_permission_system_文档.md
    - English: docs/en/chapter_7/s07_permission_system_doc.md
"""
import os
import os,json,re
import subprocess
from dataclasses import dataclass,field
from pathlib import Path
import time
from fnmatch import fnmatch
from openai import OpenAI

openai_api_key = os.getenv("OPENAI_API_KEY", "EMPTY")
openai_api_base = os.getenv("OPENAI_API_BASE", "http://localhost:8000/v1")
client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)

try:
    MODEL = client.models.list().data[0].id
    print(f"✅ 连通成功，模型: {MODEL}")
except Exception as e:
    print(f"❌ 获取模型失败: {e}")
    quit()

WORKDIR = Path.cwd()
SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"
# TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True) # 创建日志目录

# --- 配置参数 ---
CONTEXT_LIMIT = 50000
PERSIST_THRESHOLD = 30000
PREVIEW_CHARS = 2000
PLAN_REMINDER_INTERVAL = 3
KEEP_RECENT_TOOL_RESULTS = 3



MODES = ("default", "plan", "auto")
READ_ONLY_TOOLS = {"read_file", "bash_readonly"}
WRITE_TOOLS = {"write_file", "edit_file", "bash"}

class BashSecurityValidator:
    """
    Validate bash commands for obviously dangerous patterns.
    The teaching version deliberately keeps this small and easy to read.
    First catch a few high-risk patterns, then let the permission pipeline
    decide whether to deny or ask the user.
    """
    VALIDATORS = [
        ("sudo", r"\bsudo\b"),                 # privilege escalation
        ("rm_rf", r"\brm\s+(-[a-zA-Z]*)?r"),  # recursive delete
        ("cmd_substitution", r"\$\("),          # command substitution
        ("ifs_injection", r"\bIFS\s*="),        # IFS manipulation
    ]
    def validate(self, command: str) -> list:
        """
        Check a bash command against all validators.
        Returns list of (validator_name, matched_pattern) tuples for failures.
        An empty list means the command passed all validators.
        """
        failures = []
        for name, pattern in self.VALIDATORS:
            if re.search(pattern, command):
                failures.append((name, pattern))
        return failures
    def is_safe(self, command: str) -> bool:
        """Convenience: returns True only if no validators triggered."""
        return len(self.validate(command)) == 0
    def describe_failures(self, command: str) -> str:
        """Human-readable summary of validation failures."""
        failures = self.validate(command)
        if not failures:
            return "No issues detected"
        parts = [f"{name} (pattern: {pattern})" for name, pattern in failures]
        return "Security flags: " + ", ".join(parts)

# -- Workspace trust --
def is_workspace_trusted(workspace: Path = None) -> bool:
    """
    Check if a workspace has been explicitly marked as trusted.
    The teaching version uses a simple marker file. A more complete system
    can layer richer trust flows on top of the same idea.
    """
    ws = workspace or WORKDIR
    trust_marker = ws / ".claude" / ".claude_trusted"
    return trust_marker.exists()

# Singleton validator instance used by the permission pipeline
bash_validator = BashSecurityValidator()
# -- Permission rules --
# Rules are checked in order: first match wins.
# Format: {"tool": "<tool_name_or_*>", "path": "<glob_or_*>", "behavior": "allow|deny|ask"}
DEFAULT_RULES = [
    # Always deny dangerous patterns
    {"tool": "bash", "content": "rm -rf /", "behavior": "deny"},
    {"tool": "bash", "content": "sudo *", "behavior": "deny"},
    # Allow reading anything
    {"tool": "read_file", "path": "*", "behavior": "allow"},
]

class PermissionManager:
    """
    Manages permission decisions for tool calls.
    Pipeline: deny_rules -> mode_check -> allow_rules -> ask_user
    The teaching version keeps the decision path short on purpose so readers
    can implement it themselves before adding more advanced policy layers.
    """
    def __init__(self, mode: str = "default", rules: list = None):
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode}. Choose from {MODES}")
        self.mode = mode
        self.rules = rules or list(DEFAULT_RULES)
        # Simple denial tracking helps surface when the agent is repeatedly
        # asking for actions the system will not allow.
        self.consecutive_denials = 0
        self.max_consecutive_denials = 3
    def check(self, tool_name: str, tool_input: dict) -> dict:
        """
        Returns: {"behavior": "allow"|"deny"|"ask", "reason": str}
        """
        # Step 0: Bash security validation (before deny rules)
        # Teaching version checks early for clarity.
        if tool_name == "bash":
            command = tool_input.get("command", "")
            failures = bash_validator.validate(command)
            if failures:
                # Severe patterns (sudo, rm_rf) get immediate deny
                severe = {"sudo", "rm_rf"}
                severe_hits = [f for f in failures if f[0] in severe]
                if severe_hits:
                    desc = bash_validator.describe_failures(command)
                    return {"behavior": "deny",
                            "reason": f"Bash validator: {desc}"}
                # Other patterns escalate to ask (user can still approve)
                desc = bash_validator.describe_failures(command)
                return {"behavior": "ask",
                        "reason": f"Bash validator flagged: {desc}"}
        # Step 1: Deny rules (bypass-immune, checked first always)
        for rule in self.rules:
            if rule["behavior"] != "deny":
                continue
            if self._matches(rule, tool_name, tool_input):
                return {"behavior": "deny",
                        "reason": f"Blocked by deny rule: {rule}"}
        # Step 2: Mode-based decisions
        if self.mode == "plan":
            # Plan mode: deny all write operations, allow reads
            if tool_name in WRITE_TOOLS:
                return {"behavior": "deny",
                        "reason": "Plan mode: write operations are blocked"}
            return {"behavior": "allow", "reason": "Plan mode: read-only allowed"}
        if self.mode == "auto":
            return {"behavior": "allow",
                    "reason": "Auto mode: safe operation auto-approved"}
            # # Auto mode: auto-allow read-only tools, ask for writes
            # if tool_name in READ_ONLY_TOOLS or tool_name == "read_file":
            #     return {"behavior": "allow",
            #             "reason": "Auto mode: read-only tool auto-approved"}
            # Teaching: fall through to allow rules, then ask
            pass
        # Step 3: Allow rules
        for rule in self.rules:
            if rule["behavior"] != "allow":
                continue
            if self._matches(rule, tool_name, tool_input):
                self.consecutive_denials = 0
                return {"behavior": "allow",
                        "reason": f"Matched allow rule: {rule}"}
        # Step 4: Ask user (default behavior for unmatched tools)
        return {"behavior": "ask",
                "reason": f"No rule matched for {tool_name}, asking user"}
    def ask_user(self, tool_name: str, tool_input: dict) -> bool:
        """Interactive approval prompt. Returns True if approved."""
        preview = json.dumps(tool_input, ensure_ascii=False)[:200]
        print(f"\n  [Permission] {tool_name}: {preview}")
        try:
            answer = input("  Allow? (y/n/always): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if answer == "always":
            # Add permanent allow rule for this tool
            self.rules.append({"tool": tool_name, "path": "*", "behavior": "allow"})
            self.consecutive_denials = 0
            return True
        if answer in ("y", "yes"):
            self.consecutive_denials = 0
            return True
        # Track denials for circuit breaker
        self.consecutive_denials += 1
        if self.consecutive_denials >= self.max_consecutive_denials:
            print(f"  [{self.consecutive_denials} consecutive denials -- "
                  "consider switching to plan mode]")
        return False
    def _matches(self, rule: dict, tool_name: str, tool_input: dict) -> bool:
        """Check if a rule matches the tool call."""
        # Tool name match
        if rule.get("tool") and rule["tool"] != "*":
            if rule["tool"] != tool_name:
                return False
        # Path pattern match
        if "path" in rule and rule["path"] != "*":
            path = tool_input.get("path", "")
            if not fnmatch(path, rule["path"]):
                return False
        # Content pattern match (for bash commands)
        if "content" in rule:
            command = tool_input.get("command", "")
            if not fnmatch(command, rule["content"]):
                return False
        return True




@dataclass
class LoopState:
    # 用于存储历史记录和轮次，为后期管理做准备但是目前作用存疑，可能会阻碍下一节的上下文压缩
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None

########skill
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
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.documents: dict[str, SkillDocument] = {}
        self._load_all()
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
    
    def describe_available(self) -> str:
        if not self.documents:
            return "(no skills available)"
        lines = []
        for name in sorted(self.documents):
            manifest = self.documents[name].manifest
            lines.append(f"- {manifest.name}: {manifest.description}")
        return "\n".join(lines)
    
    def load_full_text(self, name: str) -> str:
        document = self.documents.get(name)
        if not document:
            known = ", ".join(sorted(self.documents)) or "(none)"
            return f"Error: Unknown skill '{name}'. Available skills: {known}"
        return (
            f"<skill name=\"{document.manifest.name}\">\n"
            f"{document.body}\n"
            "</skill>"
        )

##########todo
@dataclass
class PlanItem: 
    id: str                     #标记任务id，便于辨识
    content: str                #这一步要做什么
    status: str = "pending"     #这一步现在处在什么状态 "pending" | "in_progress" | "completed",
    active_form: str = ""       #当它正在进行中时，可以用更自然的进行时描述

@dataclass
class PlanningState:
    #todo任务管理数据结构
    items: list[PlanItem] = field(default_factory=list)
    rounds_since_update: int = 0  #连续多少轮过去了，模型还没有更新这份计划。

class TodoManager:
    def __init__(self):
        self.state = PlanningState()
    
    def update(self, items: list) -> str:
        if len(items) > 20:
            # raise ValueError("Keep the session plan short (max 12 items)")
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
    
    def note_round_without_update(self) -> None:
        self.state.rounds_since_update += 1
    
    def reminder(self) -> str | None:
        if not self.state.items:
            return None
        if self.state.rounds_since_update < PLAN_REMINDER_INTERVAL:
            return None
        return "Refresh your current plan before continuing."
    
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


########压缩
@dataclass
class CompactState:
    has_compacted: bool = False
    last_summary: str = ""
    recent_files: list[str] = field(default_factory=list)

def estimate_context_size(messages: list) -> int:
    return len(str(messages))

def track_recent_file(state: CompactState, path: str) -> None:
    if path in state.recent_files:
        state.recent_files.remove(path)
    state.recent_files.append(path)
    if len(state.recent_files) > 5:
        state.recent_files[:] = state.recent_files[-5:]

def persist_large_output(tool_use_id: str, output: str) -> str:
    if len(output) <= PERSIST_THRESHOLD:
        return output
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    if not stored_path.exists():
        stored_path.write_text(output)
    preview = output[:PREVIEW_CHARS]
    rel_path = stored_path.relative_to(WORKDIR)
    return (
        "<persisted-output>\n"
        f"Full output saved to: {rel_path}\n"
        "Preview:\n"
        f"{preview}\n"
        "</persisted-output>"
    )

def collect_tool_result_blocks(messages: list) -> list[int]:
    tool_message_indices = []
    for index, message in enumerate(messages):
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        if role == "tool":
            tool_message_indices.append(index)
            
    return tool_message_indices


def micro_compact(messages: list) -> list:
    tool_indices = collect_tool_result_blocks(messages)
    if len(tool_indices) <= KEEP_RECENT_TOOL_RESULTS:
        return messages
    for index in tool_indices[:-KEEP_RECENT_TOOL_RESULTS]:
        message = messages[index]
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
        
        if isinstance(content, str) and len(content) > 120:
            compact_text = "[Earlier tool result compacted. Re-run the tool if you need full detail.]"
            if isinstance(message, dict):
                message["content"] = compact_text
            else:
                # 某些 SDK 版本的对象可能不允许直接修改属性，如果报错，建议在 agent_loop 层统一转 dict
                try:
                    message.content = compact_text
                except AttributeError:
                    # 备选方案：将对象强制转换为字典覆盖原位置
                    messages[index] = message.model_dump(exclude_none=True) if hasattr(message, "model_dump") else message.dict(exclude_none=True)
                    messages[index]["content"] = compact_text
    return messages

def write_transcript(messages: list) -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with path.open("w") as handle:
        for message in messages:
            handle.write(json.dumps(message, default=str) + "\n")
    return path

def summarize_history(messages: list) -> str:
    conversation = json.dumps(messages, default=str)[:80000]
    prompt = (
        "Summarize this coding-agent conversation so work can continue.\n"
        "Preserve:\n"
        "1. The current goal\n"
        "2. Important findings and decisions\n"
        "3. Files read or changed\n"
        "4. Remaining work\n"
        "5. User constraints and preferences\n"
        "Be compact but concrete.\n\n"
        f"{conversation}"
    )
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    return response.choices[0].message.content.strip()

def compact_history(messages: list, state: CompactState, focus: str | None = None) -> list:
    transcript_path = write_transcript(messages)
    print(f"[transcript saved: {transcript_path}]")
    summary = summarize_history(messages)
    if focus:
        summary += f"\n\nFocus to preserve next: {focus}"
    if state.recent_files:
        recent_lines = "\n".join(f"- {path}" for path in state.recent_files)
        summary += f"\n\nRecent files to reopen if needed:\n{recent_lines}"
    state.has_compacted = True
    state.last_summary = summary
    system_message = messages[0] if messages and messages[0].get("role") == "system" else None

    compacted_message = {
        "role": "user",
        "content": (
            "This conversation was compacted so the agent can continue working.\n\n"
            f"{summary}"
        ),
    }
    return [system_message, compacted_message] if system_message else [compacted_message]

def print_agent_thought(agent_name: str, message, color_code: str):
    """提取并格式化打印 Agent 的思考过程和输出内容"""
    # 打印正常的文本输出
    content = message.content
    if content:
        print(f"{color_code}╭─── [{agent_name} 思考/输出] ──────────────────────────\033[0m")
        print(f"{content.strip()}")
        print(f"{color_code}╰─────────────────────────────────────────────────────\033[0m")
###########实例化
TODO = TodoManager()
SKILL_REGISTRY = SkillRegistry(SKILLS_DIR)

SYSTEM = f"""You are a coding agent at {WORKDIR}. 
1.Use the task tool to delegate exploration or subtasks.
2.Use the todo tool to plan complex and multi-step tasks. Mark in_progress before starting, completed when done. Keep exactly one step in_progress when a task has multiple steps.
3.Keep working step by step, and use compact if the conversation gets too long.
4.Do NOT immediately mark a task as 'completed' just because the subagent claims it is done. You MUST verify the subagent's work before calling the todo tool to mark it completed. If the work is flawed, explain the issue and spawn a new task to fix it.
5.The user controls permissions. Some tool calls may be denied.
"""
SUBAGENT_SYSTEM = f"""You are a coding subagent at {WORKDIR}. 
1.Complete the given task, then summarize your findings or your work.
2.Use tools to solve tasks. Act, after executing the command, tell me that it has been completed.
3.Keep working step by step, and use compact if the conversation gets too long.
4.Use load_skill when a task needs specialized instructions before you act. Skills available: {SKILL_REGISTRY.describe_available()}
5.When finishing a task, you MUST provide a detailed handover report including: 1. Files created/modified. 2. Key functions implemented. 3. Output of any verification commands (e.g., test results or syntax checks) you ran.
6.The user controls permissions. Some tool calls may be denied.
"""


def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"] 
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:

        r = subprocess.run(command, shell=True, cwd=str(WORKDIR),
                           capture_output=True, text=True, timeout=120) 
        out = (r.stdout + r.stderr).strip() 
        return out[:50000] if out else f"Command {command} executed successfully (no output)." 
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(path: str, limit: int = None) -> str:
    try:
        text = safe_path(path).read_text() 
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"
        
def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path) 
        fp.parent.mkdir(parents=True, exist_ok=True) 
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"



CONCURRENCY_SAFE = {"read_file"}
CONCURRENCY_UNSAFE = {"write_file", "edit_file"}
# 工具定义代码
# -- The dispatch map: {tool_name: handler} --
#工具映射字典，根据传入TOOL_HANDLERS中字段的key，执行字段对应函数
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_REGISTRY.load_full_text(kw["name"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),
    "task":       lambda **kw: run_subagent(kw["prompt"]),
    "compact":    lambda **kw: f"Compacting conversation...",
}

CHILD_TOOLS = [
    {"type": "function","function": {"name": "bash",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to execute." }
                },
                "required": ["command"],
            }
        }},
    {"type": "function","function": {"name": "read_file",
            "description": "Read file contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to read."},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read."}
                },
                "required": ["path"],
            }
        }},
    {"type": "function","function": {"name": "write_file",
            "description": "Write content to a file. Overwrites existing content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file."},
                    "content": {"type": "string", "description": "The full content to write."}
                },
                "required": ["path", "content"]
            }
        }},
    {"type": "function","function": {"name": "edit_file",
            "description": "Replace specific text in a file with new text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file."},
                    "old_text": {"type": "string", "description": "The exact text to be replaced."},
                    "new_text": {"type": "string", "description": "The new text to insert."}
                },
                "required": ["path", "old_text", "new_text"]
            }
        }},
    {"type": "function","function": {"name": "load_skill",
            "description": "Load the full body of a named skill into the current context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name to load"}
                },
                "required": ["name"]
            }
        }},
    {"type": "function","function": {"name": "compact",
        "description": "Summarize earlier conversation so work can continue in a smaller context.",
        "parameters": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string"
                }
            }
        }
        }},
    ]

# -- Parent tools: base tools + task dispatcher --
PARENT_TOOLS =  [
    {"type": "function","function": {"name": "read_file",
            "description": "Read file contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to read."},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read."}
                },
                "required": ["path"],
            }
        }},
    {"type": "function","function": {"name": "task", 
            "description": "Spawn a subagent with fresh context to finish. It shares the filesystem but not conversation history.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "prompt": {"type": "string", "description": "The specific task instructions for the subagent."}, 
                    "description": {"type": "string", "description": "Short description of the task"}
                }, 
                "required": ["prompt"]
            }
        }},
    {"type": "function","function": {"name": "todo",
        "description": "Rewrite the current session plan for multi-step work.",
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
                            "status": {"type": "string","enum": ["pending", "in_progress", "completed"]},
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
        }}},
    {"type": "function","function": {"name": "compact",
        "description": "Summarize earlier conversation so work can continue in a smaller context.",
        "parameters": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string"
                }
            }
        }
        }},
    
    ]

# -- Subagent: fresh context, filtered tools, summary-only return --
def run_subagent(prompt: str) -> str:
    global perms # 声明使用全局的权限管理器，使其继承当前模式
    print(f"\033[35m> Spawning Subagent : {prompt[:80]}...\033[0m")
    sub_messages = [{"role": "system", "content": SUBAGENT_SYSTEM},
                    {"role": "user", "content": prompt}] 
    sub_state = LoopState(messages=sub_messages) #规范使用LoopState表示一个agent的状态
    sub_compact_state = CompactState()
    for step in range(30):  # safety limit
        sub_state.messages = micro_compact(sub_state.messages)

        #2. 检查是否触发全局压缩 (Auto-Compact)
        if estimate_context_size(sub_state.messages) > CONTEXT_LIMIT:
            print("[auto compact]")
            sub_state.messages = compact_history(sub_state.messages, sub_compact_state)

        response = client.chat.completions.create(            
            model=MODEL, 
            tools=CHILD_TOOLS, 
            messages=sub_state.messages ,        
            max_tokens=8000,
            temperature=1,
            extra_body={
                "top_k": 20,
                "chat_template_kwargs": {"enable_thinking": True},
            }
        )
        response_message = response.choices[0].message
        sub_state.messages.append(response_message)
        print_agent_thought(f"Sub Agent (步骤 {step+1})", response_message, "\033[36m")

        if response_message.tool_calls:
            results,_,manual_compact,compact_focus = execute_tool_calls(response_message, perms)
            for tool_result in results:
                sub_state.messages.append(tool_result)
            if manual_compact:
                print("[manual compact]")
                sub_state.messages = compact_history(sub_state.messages, sub_compact_state, focus=compact_focus)
            sub_state.turn_count += 1
            sub_state.transition_reason = "tool_result"
        else:
            break
        
    if response_message.tool_calls:
        return f"[Subagent Warning: Task terminated after 30 steps. Last action was {response_message.tool_calls[0].function.name}]"
        
    return response_message.content or "Task finished (no summary provided)"

def run_one_turn(state: LoopState,compact_state: CompactState, perms: PermissionManager) -> bool:
    response = client.chat.completions.create(            
            model=MODEL, 
            tools=PARENT_TOOLS,        
            messages=state.messages,        
            max_tokens=8000,
            temperature=1,
            extra_body={
                "top_k": 20,
                "chat_template_kwargs": {"enable_thinking": True},
                }
        )

    response_message=response.choices[0].message
    state.messages.append(response_message)
    
    print_agent_thought(f"Main Agent (第 {state.turn_count} 轮)", response_message, "\033[34m")

    if response_message.tool_calls:

        
        results,reminder,manual_compact,compact_focus = execute_tool_calls(response_message,perms)
        for tool_result in results: #插入正常工具调用结果
            state.messages.append(tool_result)

        if manual_compact:
            print("[manual compact]")
            state.messages = compact_history(state.messages, compact_state, focus=compact_focus)

        if reminder:#发现好几个轮次没有更新任务todo了，插入一条信息催促一下
            state.messages.append({
                "role": "user",
                "content": f"[System Reminder] {reminder}",
            })
        state.turn_count += 1
        state.transition_reason = "tool_result"
        return True
    else:
        state.transition_reason = None
        return False

def execute_tool_calls(response_content, perms ) -> tuple[list[dict], str | None, bool, str | None]:
    used_todo = False
    manual_compact = False
    compact_focus = None
    results = []
    for tool_call in response_content.tool_calls:
        f_name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as e:
            print(f"\033[31m[JSON Parse Error in {f_name}]\033[0m")
            output = f"Error: Failed to parse tool arguments. Invalid JSON format. {e}"
            results.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": f_name,
                "content": output})
            continue   # 跳过本次工具执行，错误信息已返回给模型

        
        if f_name in TOOL_HANDLERS:
            #权限判断
            decision = perms.check(f_name, args)
            if decision["behavior"] == "deny":
                output = f"Permission denied: {decision['reason']}"
                print(f"  [DENIED] {f_name}: {decision['reason']}")
            
            elif decision["behavior"] == "ask":
                if perms.ask_user(f_name, args):
                    handler = TOOL_HANDLERS.get(f_name)
                    output = handler(**args) if handler else f"Unknown: {f_name}"
                    print(f"> {f_name}: {str(output)[:200]}")
                else:
                    output = f"Permission denied by user for {f_name}"
                    print(f"  [USER DENIED] {f_name}")
            
            else:  # allow
                try:
                    # 尝试执行工具
                    output = TOOL_HANDLERS[f_name](**args)
                    output = str(output) # 确保返回的是字符串格式
                    print(f"\033[33m[Tool: {f_name}]\033[0m:\t",output[:200])
                except Exception as e:
                    error_msg = f"Tool Execution Error: {type(e).__name__} - {str(e)}. Please check the required parameters."
                    print(f"\033[31m[执行报错返回给模型]: {error_msg}\033[0m")
                    output = error_msg
                
                #压缩的额外步骤
                if f_name == "compact":
                    manual_compact = True
                    compact_focus = args.get("focus")
        else:
            output = f"Error: Tool {f_name} not found."

        results.append({
            "role": "tool", 
            "tool_call_id": tool_call.id,
            "name": tool_call.function.name,
            "content": output
            })
        if f_name == "todo":
            used_todo = True
    
    if used_todo:
        TODO.state.rounds_since_update = 0
        reminder = None
    else:
        TODO.note_round_without_update()
        reminder = TODO.reminder()
    
    return results, reminder, manual_compact,compact_focus

def agent_loop(state: LoopState, compact_state: CompactState,perms: PermissionManager) -> None:
    while True:
        #1. 执行微型压缩 (Micro-Compact)
        state.messages = micro_compact(state.messages)

        #2. 检查是否触发全局压缩 (Auto-Compact)
        if estimate_context_size(state.messages) > CONTEXT_LIMIT:
            print("[auto compact]")
            state.messages = compact_history(state.messages, compact_state)
        
        # 3. 运行一轮对话
        has_next_step = run_one_turn(state,compact_state, perms)
        
        # 如果模型没有调用工具（任务结束或需要用户输入），退出自动循环
        if not has_next_step:
            break

def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", "")
                if text:
                    texts.append(text)
            elif hasattr(block, "text"):
                texts.append(block.text)
        return "\n".join(texts)
    return ""



if __name__ == "__main__":
    print("Permission modes: default, plan, auto")
    mode_input = input("Mode (default): ").strip().lower() or "default"
    if mode_input not in MODES:
        mode_input = "default"
    perms = PermissionManager(mode=mode_input)
    print(f"[Permission mode: {mode_input}]")

    history = [{"role": "system", "content": SYSTEM},]
    compact_state = CompactState()
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        
        
        # /mode command to switch modes at runtime
        if query.startswith("/mode"):
            parts = query.split()
            if len(parts) == 2 and parts[1] in MODES:
                perms.mode = parts[1]
                print(f"[Switched to {parts[1]} mode]")
            else:
                print(f"Usage: /mode <{'|'.join(MODES)}>")
            continue
        
        # /rules command to show current rules
        if query.strip() == "/rules":
            for i, rule in enumerate(perms.rules):
                print(f"  {i}: {rule}")
            continue


        history.append({"role": "user", "content": query})
        state = LoopState(messages=history)
        agent_loop(state,compact_state,perms)
        history = state.messages

        last_message = state.messages[-1] # 取最后一条消息
        if hasattr(last_message, "content"):
            raw_content = last_message.content
        else:
            raw_content = last_message.get("content", "")
            
        final_text = extract_text(raw_content)
        
        if final_text:
            print(f"\033[32m[最终回复]\033[0m {final_text}")
        print()