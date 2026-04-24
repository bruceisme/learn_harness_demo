#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s05_subagent.py - Subagent

Reference: learn-claude-code (https://github.com/shareAI-lab/learn-claude-code)
License: MIT License

This module introduces a subagent system for delegating tasks to isolated agents.
It demonstrates tool separation between parent and child agents to maintain clean context.

Features:
    - Subagent spawning: Spawn subagents with fresh context for isolated task execution
    - Tool separation: Parent agent uses read_file/task/todo; Child agent uses bash/write_file/edit_file
    - Task delegation: Main agent delegates exploration and subtasks to subagents
    - 30-step safety limit: Prevents infinite loops in subagent execution
    - Detailed handover reports: Subagents must report files changed, functions implemented, verification results

Documentation:
    - Chinese: docs/zh/chapter_05/s05_subagent_文档.md
    - English: docs/en/chapter_05/s05_subagent_doc.md
"""
import os
import os,json,re
import subprocess
from dataclasses import dataclass,field
from pathlib import Path
import time
from openai import OpenAI

openai_api_key = os.getenv("OPENAI_API_KEY", "EMPTY")
openai_api_base = os.getenv("OPENAI_API_BASE", "http://localhost:8000/v1")
client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)

PLAN_REMINDER_INTERVAL = 3

try:
    MODEL = client.models.list().data[0].id
    print(f"✅ 连通成功，模型：{MODEL}")
except Exception as e:
    print(f"❌ 获取模型失败：{e}")
    quit()

WORKDIR = Path.cwd()
SKILLS_DIR = WORKDIR / "skills"

@dataclass
class LoopState:
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None

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
    id: str                     
    content: str                 
    status: str = "pending"      
    active_form: str = ""        


@dataclass
class PlanningState:
    items: list[PlanItem] = field(default_factory=list)
    rounds_since_update: int = 0  

class TodoManager:
    def __init__(self):
        self.state = PlanningState()
    
    def update(self, items: list) -> str:
        if len(items) > 20:
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

def print_agent_thought(agent_name: str, message, color_code: str):
    """提取并格式化打印 Agent 的思考过程和输出内容"""
    content = message.content
    if content:
        print(f"{color_code}╭─── [{agent_name} 思考/输出] ──────────────────────────\033[0m")
        print(f"{content.strip()}")
        print(f"{color_code}╰─────────────────────────────────────────────────────\033[0m")
 
TODO = TodoManager()
SKILL_REGISTRY = SkillRegistry(SKILLS_DIR)

SYSTEM = f"""You are a coding agent at {WORKDIR}. 
1.Use the task tool to delegate exploration or subtasks.
2.Use the todo tool to plan complex and multi-step tasks. Mark in_progress before starting, completed when done. Keep exactly one step in_progress when a task has multiple steps.
3.Do NOT immediately mark a task as 'completed' just because the subagent claims it is done. You MUST verify the subagent's work before calling the todo tool to mark it completed. If the work is flawed, explain the issue and spawn a new task to fix it."""
SUBAGENT_SYSTEM = f"""You are a coding subagent at {WORKDIR}. 
1.Complete the given task, then summarize your findings or your work.
2.Use tools to solve tasks. Act, after executing the command, tell me that it has been completed.
3.Use load_skill when a task needs specialized instructions before you act. Skills available: {SKILL_REGISTRY.describe_available()}
4.When finishing a task, you MUST provide a detailed handover report including: 1. Files created/modified. 2. Key functions implemented. 3. Output of any verification commands (e.g., test results or syntax checks) you ran.
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

TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_REGISTRY.load_full_text(kw["name"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),
    "task":       lambda **kw: run_subagent(kw["prompt"]),
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
    ]


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
]

# -- Subagent: fresh context, filtered tools, summary-only return --
def run_subagent(prompt: str) -> str:
    print(f"\033[35m> Spawning Subagent : {prompt[:80]}...\033[0m")
    

    sub_messages = [{"role": "system", "content": SUBAGENT_SYSTEM},
                    {"role": "user", "content": prompt}] 
    sub_state = LoopState(messages=sub_messages) #规范使用 LoopState 表示一个 agent 的状态
    for step in range(30):  # safety limit
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
            results,_ = execute_tool_calls(response_message)
            for tool_result in results:
                sub_state.messages.append(tool_result)
            sub_state.turn_count += 1
            sub_state.transition_reason = "tool_result"
        else:
            break
        
    if response_message.tool_calls:
        return f"[Subagent Warning: Task terminated after 30 steps. Last action was {response_message.tool_calls[0].function.name}]"
        
    return response_message.content or "Task finished (no summary provided)"

def normalize_assistant_content(content) -> str:
    """将模型的 content 转换为纯文本字符串，处理 None 和列表格式。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [block["text"] for block in content 
                 if isinstance(block, dict) and block.get("type") == "text"]
        return "\n".join(texts)
    return ""

def run_one_turn(state: LoopState) -> bool:
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
    print_agent_thought(f"Main Agent (第 {state.turn_count} 轮)", response_message, "\033[34m")
    state.messages.append(response_message)
    if response_message.tool_calls:
        results,reminder = execute_tool_calls(response_message)
        for tool_result in results: #插入正常工具调用结果
            state.messages.append(tool_result)
        if reminder:#发现好几个轮次没有更新任务 todo 了，插入一条信息催促一下
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


def execute_tool_calls(response_content) -> tuple[list[dict], str | None]:
    used_todo = False
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
            output = TOOL_HANDLERS[f_name](**args)
            print(f"\033[33m[Tool: {f_name}]\033[0m:\t",output[:200])
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
    
    return results, reminder

def agent_loop(state: LoopState) -> None:
    while run_one_turn(state):
        pass

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
    history = [{"role": "system", "content": SYSTEM},]
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        state = LoopState(messages=history)
        agent_loop(state)
        last_message = history[-1]
        if hasattr(last_message, "content"):
            raw_content = last_message.content
        else:
            raw_content = last_message.get("content", "")
            
        final_text = extract_text(raw_content)
        
        if final_text:
            print(f"\033[32m[最终回复]\033[0m {final_text}")
        print()
