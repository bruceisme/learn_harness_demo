#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s04_todo_write.py - Todo Write

Reference: learn-claude-code (https://github.com/shareAI-lab/learn-claude-code)
License: MIT License

This module introduces a todo management system for planning and tracking multi-step tasks.
It demonstrates how to maintain task state and enforce single in_progress constraints.

Features:
    - todo tool: Create and manage multi-step session plans
    - PlanningState: Track plan items with status (pending/in_progress/completed)
    - Single in_progress constraint: Enforces one active task at a time
    - Plan reminder system: Prompts model to refresh plans after N rounds without updates
    - bash, read_file, write_file, edit_file, load_skill tools

Documentation:
    - Chinese: docs/zh/chapter_4/s04_todo_write_文档.md
    - English: docs/en/chapter_4/s04_todo_write_doc.md
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

##########本节新增##########
#单个
@dataclass
class PlanItem: 
    id: str                      
    content: str                
    status: str = "pending"     
    active_form: str = ""       

@dataclass
class PlanningState:
    #todo 任务管理数据结构
    items: list[PlanItem] = field(default_factory=list)
    rounds_since_update: int = 0   #连续多少轮过去了，模型还没有更新这份计划。

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
        return "<reminder>Refresh your current plan before continuing.</reminder>"
    
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

TODO = TodoManager()
SKILL_REGISTRY = SkillRegistry(SKILLS_DIR)

SYSTEM = f"""You are a coding agent at {WORKDIR}.
1.Use the todo tool to plan complex and multi-step tasks. Mark in_progress before starting, completed when done. Keep exactly one step in_progress when a task has multiple steps.
2.Use tools to solve tasks. Act, after executing the command, tell me that it has been completed.
3.Refresh the plan as work advances. Prefer tools over prose.
4.Use load_skill when a task needs specialized instructions before you act. Skills available: {SKILL_REGISTRY.describe_available()}
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
#工具映射字典，根据传入 TOOL_HANDLERS 中字段的 key，执行字段对应函数
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_REGISTRY.load_full_text(kw["name"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),
}

TOOLS = [
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
    {"type": "function","function": {"name": "todo",
        "description": "Create or Rewrite the current session plan for multi-step work.",
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
        }}}
    ]

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
    else:
        raise f"unknow type of model output {content}"
    # return ""

def run_one_turn(state: LoopState) -> bool:
    response = client.chat.completions.create(            
            model=MODEL, 
            tools=TOOLS,    
            messages=state.messages,        
            max_tokens=8000,
            temperature=1,
            extra_body={
                "top_k": 20,
                "chat_template_kwargs": {"enable_thinking": True},
                }
        )

    response_messages=response.choices[0].message
    state.messages.append(response_messages)

    if response_messages.tool_calls:
        results,reminder = execute_tool_calls(response_messages)
        if not results:
            state.transition_reason = None
            return False
        if reminder:
            state.messages.append({
                "role": "system",
                "content": reminder,
            })
        for tool_result in results:
            state.messages.append(tool_result)
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
            print(f"\033[33m[Tool: {f_name}]\033[0m\n",output[:200])
        else:
            output = f"Error: Tool {f_name} not found."

        results.append({"role": "tool","tool_call_id": tool_call.id,
            "name": tool_call.function.name,
            "content": output
            })
        
        if f_name == "todo":
            used_todo = True
    if used_todo:
        reminder = None
    else:
        TODO.note_round_without_update()
        reminder = TODO.reminder()
    
    return results, reminder

def agent_loop(state: LoopState) -> None:
    while run_one_turn(state):
        pass


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
        final_text = history[-1]["content"]
        if final_text:
            print(final_text)
        print()
