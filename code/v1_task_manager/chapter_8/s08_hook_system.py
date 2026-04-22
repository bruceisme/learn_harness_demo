#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s08_hook_system.py - Hook System

Reference: learn-claude-code (https://github.com/shareAI-lab/learn-claude-code)
License: MIT License

This module introduces a hook system for intercepting and extending framework events.
It demonstrates how to plugin custom logic at execution checkpoints without modifying core loops.

Features:
    - Event hooks: Intercept tool calls, model I/O, and other framework events
    - Plugin architecture: Register custom handlers for specific event types
    - Permission integration: Embed permission checks as hook plugins
    - Non-invasive extension: Add functionality without modifying main loop code
    - Configurable triggers: Define hook behavior through configuration

Documentation:
    - Chinese: docs/zh/chapter_8/s08_hook_system_文档.md
    - English: docs/en/chapter_8/s08_hook_system_doc.md
"""
import os
import os,json,re
import subprocess
from dataclasses import dataclass,field
from pathlib import Path
import time
from fnmatch import fnmatch
from openai import OpenAI
#############模型api调用接口准备##########

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
TRUST_MARKER = WORKDIR / ".claude" / ".claude_trusted"

# --- 配置参数 ---
CONTEXT_LIMIT = 60000
PERSIST_THRESHOLD = 40000
PREVIEW_CHARS = 10000
PLAN_REMINDER_INTERVAL = 3
KEEP_RECENT_TOOL_RESULTS = 3


#######s08新增
HOOK_EVENTS = ("PreToolUse", "PostToolUse", "SessionStart")
HOOK_TIMEOUT = 30  # seconds
# Real CC timeouts:
#   TOOL_HOOK_EXECUTION_TIMEOUT_MS = 600000 (10 minutes for tool hooks)
#   SESSION_END_HOOK_TIMEOUT_MS = 1500 (1.5 seconds for SessionEnd hooks)

###hook核心代码
class HookManager:
    """
    从 .hooks.json 配置文件中加载并执行钩子。钩子管理器主要完成三项简单工作：
    - 加载钩子定义
    - 为对应事件运行匹配的命令
    - 为调用方汇总代码块 / 消息执行结果
    统一的拦截器管线 (Interceptor Pipeline)。
    权限管理目前在代码形式上集成，没有以真正hook的形式集成到框架中
    包含内置的安全/权限检查 (Ring 0) 和 外部定义的脚本 Hook (Ring 1)。
    """
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
                
    def _check_workspace_trust(self) -> bool:
        if self._sdk_mode: return True
        return TRUST_MARKER.exists()

    def run_pre_tool_use(self, context: dict) -> dict:
        """
        统一的 PreToolUse 拦截管线。
        返回统一格式: {"blocked": bool, "block_reason": str, "messages": list}
        """
        result = {"blocked": False, "block_reason": "", "messages": []}
        tool_name = context.get("tool_name", "")
        tool_input = context.get("tool_input", {})

        # --- [阶段 1: 内置安全与权限 Hook (Ring 0)] ---
        decision = self.perms.check(tool_name, tool_input)
        
        if decision["behavior"] == "deny":
            return {"blocked": True, "block_reason": f"Permission denied: {decision['reason']}", "messages": []}
            
        elif decision["behavior"] == "ask":
            # 触发交互式询问
            if not self.perms.ask_user(tool_name, tool_input):
                return {"blocked": True, "block_reason": f"User denied execution for {tool_name}", "messages": []}

        # --- [阶段 2: 外部自定义 Hook (Ring 1)] ---
        # 只有在安全校验通过后，才执行外部脚本 Hook
        ext_result = self._run_external_hooks("PreToolUse", context)
        
        if ext_result["blocked"]:
            return ext_result # 如果外部 Hook 阻断，直接返回
        else:
            result["messages"].extend(ext_result["messages"])
            # 如果外部 Hook 修改了 input，更新到 context 中
            if "updated_input" in ext_result:
                context["tool_input"] = ext_result["updated_input"]
            return result

    def run_post_tool_use(self, context: dict) -> dict:
        """统一的 PostToolUse 拦截管线 (目前主要是外部 Hook)"""
        return self._run_external_hooks("PostToolUse", context)

    def _run_external_hooks(self, event: str, context: dict) -> dict:
        """执行原本 .hooks.json 中的外部脚本逻辑"""
        result = {"blocked": False, "block_reason": "", "messages": []}
        if not self._check_workspace_trust():
            return result
            
        hooks = self.hooks.get(event, [])
        for hook_def in hooks:
            # 如果hook定义了 matcher，则仅当 context 中的 tool_name 与 matcher 相等（或 matcher 为 "*" 通配）时，才执行该hook。这主要用于 PreToolUse / PostToolUse 事件，让hook只针对特定工具触发。
            matcher = hook_def.get("matcher")
            if matcher and context:
                tool_name = context.get("tool_name", "")
                if matcher != "*" and matcher != tool_name:
                    continue
            
            command = hook_def.get("command", "")
            if not command: 
                continue
            
            # (组装环境变量逻辑保持不变...)
            env = dict(os.environ)
            if context:
                env["HOOK_EVENT"] = event
                env["HOOK_TOOL_NAME"] = context.get("tool_name", "")
                env["HOOK_TOOL_INPUT"] = json.dumps(context.get("tool_input", {}), ensure_ascii=False)[:10000]
                if "tool_output" in context:
                    env["HOOK_TOOL_OUTPUT"] = str(context["tool_output"])[:10000]
                    
            try:
                r = subprocess.run(command, shell=True, cwd=WORKDIR, env=env, capture_output=True, text=True, timeout=HOOK_TIMEOUT)
                if r.returncode == 0:
                    try:
                        hook_output = json.loads(r.stdout)
                        if "updatedInput" in hook_output and context:
                            result["updated_input"] = hook_output["updatedInput"] # 提取更新的入参
                        if "additionalContext" in hook_output:
                            result["messages"].append(hook_output["additionalContext"])
                        if "permissionDecision" in hook_output:
                            result["permission_override"] = (
                                hook_output["permissionDecision"])
                    except: pass
                elif r.returncode == 1:
                    return {"blocked": True, "block_reason": r.stderr.strip() or "Blocked by external hook", "messages": []}
                elif r.returncode == 2:
                    msg = r.stderr.strip()
                    if msg:
                        result["messages"].append(msg)
                        print(f"  [hook:{event}] INJECT: {msg[:200]}")
            except subprocess.TimeoutExpired:
                print(f"  [hook:{event}] Timeout ({HOOK_TIMEOUT}s)")
            except Exception as e:
                print(f"  [hook:{event}] Error: {e}")
                
        return result


#######s07新增
MODES = ("default", "plan", "auto")
READ_ONLY_TOOLS = {"read_file", "bash_readonly"}
WRITE_TOOLS = {"write_file", "edit_file", "bash"}

# -- Bash security validation --
class BashSecurityValidator:
    """
    Validate bash commands for obviously dangerous patterns.
    The teaching version deliberately keeps this small and easy to read.
    First catch a few high-risk patterns, then let the permission pipeline
    decide whether to deny or ask the user.
    """
    VALIDATORS = [
        # ("shell_metachar", r"[;&|`$]"),       # shell metacharacters
        # ("shell_metachar", r"[;`$]"),
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
    # def __init__(self, mode: str = "default", rules: list = None):
    def __init__(self, rules: list = None):
        print("Permission modes: default, plan, auto")
        mode = input("Mode (default): ").strip().lower() or "default"
        if mode not in MODES:
            print(f"Unknown mode: {mode}. Choose from {MODES}. Default to auto.")
            mode = "auto"
        print(f"[Permission mode: {mode}]")
            
        # if mode not in MODES:
        #     raise ValueError(f"Unknown mode: {mode}. Choose from {MODES}")
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


def persist_large_output(tool_call_id: str, output: str) -> str:#这个函数实际上没有使用？
    if len(output) <= PERSIST_THRESHOLD:
        return output
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = TOOL_RESULTS_DIR / f"{tool_call_id}.txt"
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
    if not content:
        content = message.reasoning_content
    if content:
        print(f"{color_code}╭─── [{agent_name} 思考/输出] ──────────────────────────\033[0m")
        print(f"{content.strip()}")
        print(f"{color_code}╰─────────────────────────────────────────────────────\033[0m")
    
###########实例化
TODO = TodoManager()
SKILL_REGISTRY = SkillRegistry(SKILLS_DIR)
perms = PermissionManager()
hooks = HookManager(perms)




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

def run_bash(command: str, tool_call_id: str,) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"] 
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:

        result = subprocess.run(command, shell=True, cwd=str(WORKDIR),
                           capture_output=True, text=True, timeout=120) 
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    output = (result.stdout + result.stderr).strip() or f"{command} finished (no output)"

    return persist_large_output(tool_call_id, output)


def run_read(path: str, tool_call_id: str, limit: int | None = None) -> str:
    try:
        # track_recent_file(state, path)
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        output = "\n".join(lines)
        return persist_large_output(tool_call_id, output)
    except Exception as exc:
        return f"Error: {exc}"
        
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
    # "bash":       lambda **kw: run_bash(kw["command"]),
    # "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "bash":       lambda **kw: run_bash(kw["command"], kw["tool_call_id"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw["tool_call_id"], kw.get("limit")),
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
    print(f"\033[35m> Spawning Subagent : {prompt[:80]}...\033[0m")
    sub_messages = [{"role": "system", "content": build_system_prompt(SUBAGENT_SYSTEM)},
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
            results,_,manual_compact,compact_focus = execute_tool_calls(response_message)
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
    
    if response_message.content :
        return response_message.content
    elif response_message.reasoning_content:
        return response_message.reasoning_content
    else:
        return "Task finished (no summary provided)"

        

def run_one_turn(state: LoopState,compact_state: CompactState) -> bool:
    response = client.chat.completions.create(            
            model=MODEL, 
            tools=PARENT_TOOLS,        
            messages=state.messages,        
            max_tokens=10000,
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

        #执行工具
        results,reminder,manual_compact,compact_focus = execute_tool_calls(response_message)

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


def execute_tool_calls(response_message ) -> tuple[list[dict], str | None, bool, str | None]:
    global hooks
    used_todo = False
    manual_compact = False
    compact_focus = None
    results = []

    for tool_call in response_message.tool_calls:
        f_name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
            args['tool_call_id']=tool_call.id
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
            ctx = {"tool_name": tool_call.function.name, "tool_input": args}
            
            # 1. 统一拦截管线：权限检查 + 外部 Pre-Hook
            pre_result = hooks.run_pre_tool_use(ctx)
        
            # 如果被任何机制阻断（安全正则/用户拒绝/外部脚本返回1）
            if pre_result.get("blocked"):
                reason = pre_result.get("block_reason", "Blocked by pipeline/hook")
                output = f"Tool blocked by PreToolUse hook: {reason}"
                print(f"\033[31m  [BLOCKED] {f_name}: {reason}\033[0m")
                results.append({
                    "role": "tool", 
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name, #是否需保持一致？
                    "content": output,
                })
                continue
            else:
                # 注入 Hook 的附加上下文信息
                for msg in pre_result.get("messages", []):
                    results.append({
                        "role": "tool",  
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": f"[Hook message]: {msg}",
                    })
            ## 如果 Hook 修改了入参，这里拿到最新的 args
            args = ctx.get("tool_input", args)

            # 2. 执行工具本身
            try:
                handler = TOOL_HANDLERS.get(f_name)
                output = handler(**args) if handler else f"Unknown: {f_name}"
                output = str(output) # 确保返回的是字符串格式
                print(f"\033[33m[Tool: {f_name}]\033[0m:\t", output[:200])
            except Exception as e:
                error_msg = f"Tool Execution Error: {type(e).__name__} - {str(e)}. Please check the required parameters."
                print(f"\033[31m[执行报错返回给模型]: {error_msg}\033[0m")
                output = error_msg
            
            #压缩的额外步骤
            if f_name == "compact":
                manual_compact = True
                compact_focus = args.get("focus")
            
            # 3. 统一拦截管线：外部 Post-Hook
                
            post_ctx = {"tool_name": f_name, "tool_input": args, "tool_output": output}
            post_result = hooks.run_post_tool_use(post_ctx)

            # 处理 PostToolUse 返回的注入消息
            for msg in post_result.get("messages", []):
                results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": f_name,
                    "content": f"[PostHook message]: {msg}",
                })

            # 如果 PostToolUse 要求阻塞（一般不应该阻塞已完成的工具，但按规范处理）
            if post_result.get("blocked"):
                reason = post_result.get("block_reason", "Blocked by PostToolUse hook")
                print(f"  [hook:PostToolUse] BLOCKED after execution: {reason[:200]}")
                # 可选择修改 output 或追加警告
                output = f"{output}\n[WARNING: PostToolUse hook blocked further processing: {reason}]"
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

def agent_loop(state: LoopState, compact_state: CompactState ) -> None:
    while True:
        #1. 执行微型压缩 (Micro-Compact)
        state.messages = micro_compact(state.messages)

        #2. 检查是否触发全局压缩 (Auto-Compact)
        if estimate_context_size(state.messages) > CONTEXT_LIMIT:
            print("[auto compact]")
            state.messages = compact_history(state.messages, compact_state)
        
        # 3. 运行一轮对话
        has_next_step = run_one_turn(state,compact_state)
        
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
    compact_state = CompactState()
    history = [{"role": "system", "content": SYSTEM},]

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
        
        # >>> 新增：/allow 指令，主动授予特定文件夹权限 <<< 需要验证
        if query.startswith("/allow"):
            parts = query.split(maxsplit=1)
            if len(parts) == 2:
                target_dir = parts[1].strip()
                # 自动补全通配符，确保是授权该目录下的所有文件
                if not target_dir.endswith("*"):
                    # 转换路径格式，避免出现类似 src//* 的双斜杠
                    target_dir = target_dir.rstrip("/\\") + "/*" 
                
                # 注入一条全局工具对该路径的 allow 规则
                perms.rules.append({
                    "tool": "*",           # 不限制具体工具（读、写、编辑皆可）
                    "path": target_dir,    # 限制在目标目录下
                    "behavior": "allow"
                })
                # 重置拒绝计数器
                perms.consecutive_denials = 0
                print(f"\033[32m[Granted] 已主动授权框架操作目录: {target_dir}\033[0m")
            else:
                print("Usage: /allow <path/to/folder>")
            continue


        history.append({"role": "user", "content": query})
        state = LoopState(messages=history)
        agent_loop(state,compact_state)

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