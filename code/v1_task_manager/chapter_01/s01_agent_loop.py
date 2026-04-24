#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s01_agent_loop.py - The Agent Loop

Reference: learn-claude-code (https://github.com/shareAI-lab/learn-claude-code)
License: MIT License

This module implements a minimal agent loop with a single bash tool.
It demonstrates the core interaction pattern between user, LLM, and tools.

Features:
    - Basic agent loop structure
    - Single bash tool implementation
    - Message history management

Documentation:
    - Chinese: docs/zh/chapter_01/s01_agent_loop_文档.md
    - English: docs/en/chapter_01/s01_agent_loop_doc.md
"""
import os,json
import subprocess
from dataclasses import dataclass
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

SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to inspect and change the workspace. Act first, then report clearly." 


TOOLS = [{
    "type": "function","function": {"name": "bash",
        "description": "Run a shell command.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute." }
            },
            "required": ["command"],
        }
    }
}]

@dataclass
class LoopState:
    # 尝试通过数据结构LOOPstate来控制每一个循环的状态和内容
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None

def run_bash(command: str) -> str:
    #不可执行操作，当agent试图执行列表中命令时打断，
    #表面上该操作可以防止模型出现执行危险操作，但是实际运行过程中模型会想办法跳过这些限制
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"] 
    if any(d in command for d in dangerous):
        return f"Error: Dangerous command blocked {command}"
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120) 
        out = (r.stdout + r.stderr).strip() 
        return out[:50000] if out else f"Command {command} executed successfully (no output)." 
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


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


def execute_tool_calls(response_content) -> list[dict]:
    results = []
    for tool_call in response_content.tool_calls:
        if tool_call.function.name == "bash":
            args = json.loads(tool_call.function.arguments)
            command = args.get("command")

            print(f"\033[33m$ {command}\033[0m")
            output = run_bash(command) 
            print(output[:200])

            results.append({
                "role": "tool", 
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": output
            })
        else:
            results.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": f"Error: Tool '{tool_call.function.name}' not found. Please use 'bash'."
            })
    return results

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
        final_text = extract_text(history[-1]["content"])
        if final_text:
            print(final_text)
        print()

