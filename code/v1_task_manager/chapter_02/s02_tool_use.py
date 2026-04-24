#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s02_tool_use.py - Tools

Reference: learn-claude-code (https://github.com/shareAI-lab/learn-claude-code)
License: MIT License

This module extends s01_agent_loop with multiple file operation tools.
It demonstrates the tool dispatch pattern for handling different tool types.

Features:
    - bash: Execute shell commands
    - read_file: Read file contents with optional line limit
    - write_file: Write content to files (create directories if needed)
    - edit_file: Replace specific text in files

Documentation:
    - Chinese: docs/zh/chapter_02/s02_tool_use_文档.md
    - English: docs/en/chapter_02/s02_tool_use_doc.md
"""
import os
import os,json
import subprocess
from dataclasses import dataclass
from pathlib import Path
WORKDIR = Path.cwd()
import time
from openai import OpenAI

openai_api_key = os.getenv("OPENAI_API_KEY", "EMPTY")
openai_api_base = os.getenv("OPENAI_API_BASE", "http://localhost:8000/v1")
client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)

try:
    MODEL = client.models.list().data[0].id
    print(f"✅ 连通成功，模型：{MODEL}")
except Exception as e:
    print(f"❌ 获取模型失败：{e}")
    quit()


SYSTEM = f"You are a coding agent at {os.getcwd()}. Use the tool to finish tasks. Act first, then report clearly." 

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

@dataclass
class LoopState:
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None


# 工具定义代码
# -- The dispatch map: {tool_name: handler} --
#工具映射字典，根据传入 TOOL_HANDLERS 中字段的 key，执行字段对应函数
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
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
        }}
    ]


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
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as e:
            # 跳过本次工具执行，错误信息已返回给模型
            print(f"\033[31m[JSON Parse Error in {f_name}]\033[0m")
            output = f"Error: Failed to parse tool arguments. Invalid JSON format. {e}"
            results.append({"role": "tool", "tool_call_id": tool_call.id, "name": f_name, "content": output})
            continue   
    
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
