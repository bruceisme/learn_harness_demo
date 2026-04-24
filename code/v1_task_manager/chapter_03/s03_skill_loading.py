#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s03_skill_loading.py - Skill Loading

Reference: learn-claude-code (https://github.com/shareAI-lab/learn-claude-code)
License: MIT License

This module introduces a skill registry system that loads skill manifests from SKILL.md files.
It demonstrates how to extend agent capabilities through dynamically loadable skills.

Features:
    - Skill registry: Dynamically load skill manifests from SKILL.md files
    - load_skill tool: Load full skill instructions into context
    - bash, read_file, write_file, edit_file: File and shell operations
    - Concurrent-safe tool tracking for read operations

Documentation:
    - Chinese: docs/zh/chapter_03/s03_skill_loading_文档.md
    - English: docs/en/chapter_03/s03_skill_loading_doc.md
"""
import os
import os,json,re
import subprocess
from dataclasses import dataclass
from pathlib import Path
import time
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

@dataclass
class LoopState:
    # The minimal loop state: history, loop count, and why we continue.
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None

#嵌套式的skill数据结构
@dataclass
class SkillManifest:
    name: str
    description: str
    path: Path

@dataclass
class SkillDocument:
    manifest: SkillManifest
    body: str

#SKILLRegistry将所有skills先加载到数据结构中，后期可能会导致不必要的开销
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

SKILL_REGISTRY = SkillRegistry(SKILLS_DIR)

SYSTEM = f"""You are a coding agent at {WORKDIR}.
1. Use the tool to finish tasks. Act first, then report clearly.
2. Use load_skill when a task needs specialized instructions before you act.
Skills available:
{SKILL_REGISTRY.describe_available()}
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

        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
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
        }}
    ]


def run_one_turn(state: LoopState) -> bool:
    response = client.chat.completions.create(            
            model=MODEL, 
            tools=TOOLS, 
            # messages=normalize_messages(state.messages),        
            messages=state.messages,        
            max_tokens=8000,
            temperature=1,
            extra_body={
                "top_k": 20,
                "chat_template_kwargs": {"enable_thinking": True},
                }
        )

    response_messages=response.choices[0].message
    state.messages.append({"role": "assistant", "content": response_messages.content})

    if response_messages.tool_calls:
        results = execute_tool_calls(response_messages)
        if not results:
            state.transition_reason = None
            return False
        for tool_result in results:
            state.messages.append(tool_result)
        state.turn_count += 1
        state.transition_reason = "tool_result"
        return True
    else:
        state.transition_reason = None
        return False



def execute_tool_calls(response_content) -> list[dict]:
    results = []
    for tool_call in response_content.tool_calls:
        f_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        if f_name in TOOL_HANDLERS:
            print(f"\033[33m[Tool: {f_name}]\033[0m")
            output = TOOL_HANDLERS[f_name](**args)
            print(output[:200])
        else:
            output = f"Error: Tool {f_name} not found."

        results.append({
            "role": "tool", 
            "tool_call_id": tool_call.id,
            "name": tool_call.function.name,
            "content": output
            })
    return results

def agent_loop(state: LoopState) -> None:
    while run_one_turn(state):
        pass

def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    elif not isinstance(content, list):
        return ""
    texts = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    return "\n".join(texts).strip()



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
        final_text = extract_text(history[-1]["content"])
        if final_text:
            print(final_text)
        print()