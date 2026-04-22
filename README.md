[中文版](README_zh.md) | [English Version](README.md)

# learn_harness_demo

A teaching project based on [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code), progressively building an agent demo that conforms to harness engineering concepts.

> **Note:** This project uses OpenAI-compatible API format for model calls.
> Set the `OPENAI_API_KEY` and `OPENAI_API_BASE` environment variables before running.

## Requirements

- Python >= 3.10

## Project Features

- **Progressive Evolution**: 19 chapters from basic Agent Loop to complete multi-agent system
- **Educational Nature**: Each chapter includes detailed code analysis and design explanations
- **Complete System**: Covers core components including tools, skills, task management, sub-agents, context management, etc.
- **Bilingual**: Provides complete Chinese and English documentation

## Directory Structure

```
learn_harness_demo/
├── code/v1_task_manager/    # Code implementation (19 chapters)
│   ├── chapter_1/           # Basic Agent Loop
│   ├── chapter_2/           # Tool System Extension
│   └── ...
├── docs/zh/                 # Chinese documentation
├── docs/en/                 # English documentation
├── README.md
└── LICENSE
```

## Documentation

- **Chinese Documentation**: [核心框架变化分析](docs/zh/核心框架变化分析.md)
- **English Documentation**: [Core Framework Changes](docs/en/core_framework_changes.md)

## Chapter Overview

| Chapter | Topic | Content Description | Python File | Chinese Doc | English Doc |
|---------|-------|---------------------|-------------|-------------|-------------|
| Chapter 1 | Basic Agent Loop | Single bash tool + concise loop | `agent_loop.py` | [文档](docs/zh/chapter_1/agent_loop_文档.md) | [Doc](docs/en/chapter_1/agent_loop_doc.md) |
| Chapter 2 | Tool System Extension | 4 file operation tools | `s02_tool_use.py` | [文档](docs/zh/chapter_2/s02_tool_use_文档.md) | [Doc](docs/en/chapter_2/s02_tool_use_doc.md) |
| Chapter 3 | Skill System Integration | SkillRegistry + load_skill | `s03_skill_loading.py` | [文档](docs/zh/chapter_3/s03_skill_loading_文档.md) | [Doc](docs/en/chapter_3/s03_skill_loading_doc.md) |
| Chapter 4 | Task Management System | Todo persistence | `s04_todo_write.py` | [文档](docs/zh/chapter_4/s04_todo_write_文档.md) | [Doc](docs/en/chapter_4/s04_todo_write_doc.md) |
| Chapter 5 | Sub-agent System | Main/sub-agent responsibility separation | `s05_subagent.py` | [文档](docs/zh/chapter_5/s05_subagent_文档.md) | [Doc](docs/en/chapter_5/s05_subagent_doc.md) |
| Chapter 6 | Context Management | Message history compression | `s06_context.py` | [文档](docs/zh/chapter_6/s06_context_文档.md) | [Doc](docs/en/chapter_6/s06_context_doc.md) |
| Chapter 7 | Permission System | File operation permission checks | `s07_permission_system.py` | [文档](docs/zh/chapter_7/s07_permission_system_文档.md) | [Doc](docs/en/chapter_7/s07_permission_system_doc.md) |
| Chapter 8 | Hook System | Pre/post Hooks | `s08_hook_system.py` | [文档](docs/zh/chapter_8/s08_hook_system_文档.md) | [Doc](docs/en/chapter_8/s08_hook_system_doc.md) |
| Chapter 9 | Memory System | MemoryStore persistence | `s09_memory_system.py` | [文档](docs/zh/chapter_9/s09_memory_system_文档.md) | [Doc](docs/en/chapter_9/s09_memory_system_doc.md) |
| Chapter 10 | Build System | Project build and packaging | `test_chapter_10.py` | [文档](docs/zh/chapter_10/test_chapter_10_文档.md) | [Doc](docs/en/chapter_10/test_chapter_10_doc.md) |
| Chapter 11 | Resume System | State recovery mechanism | `s11_Resume_system.py` | [文档](docs/zh/chapter_11/s11_Resume_system_文档.md) | [Doc](docs/en/chapter_11/s11_Resume_system_doc.md) |
| Chapter 12 | Task System | Task scheduling management | `s12_task_system.py` | [文档](docs/zh/chapter_12/s12_task_system_文档.md) | [Doc](docs/en/chapter_12/s12_task_system_doc.md) |
| Chapter 13 | Knowledge System | Knowledge base management | `s13_v2_backtask.py` | [文档](docs/zh/chapter_13/s13_v2_backtask_文档.md) | [Doc](docs/en/chapter_13/s13_v2_backtask_doc.md) |
| Chapter 14 | Planning System | Planning and execution | `s14_cron_scheduler.py` | [文档](docs/zh/chapter_14/s14_cron_scheduler_文档.md) | [Doc](docs/en/chapter_14/s14_cron_scheduler_doc.md) |
| Chapter 18.2 | Worktree Task Isolation System | git worktree full lifecycle management | `s18_v2_singleagent_worktree_task_isolation.py` | [文档](docs/zh/chapter_18_2/s18_v2_singleagent_worktree_task_isolation_文档.md) | [Doc](docs/en/chapter_18_2/s18_v2_singleagent_worktree_task_isolation_doc.md) |
| Chapter 19.2 | MCP & Plugin System Integration | MCP and plugin system integration | `s19_v2_mcp_plugin.py` | [文档](docs/zh/chapter_19_2/s19_mcp_plugin.md) | [Doc](docs/en/chapter_19_2/s19_mcp_plugin.md) |

## Quick Start

```bash
# Set environment variables (replace with your actual values)
export OPENAI_API_KEY="your-api-key-here"
export OPENAI_API_BASE="http://your-server-ip:8000/v1"

# Enter Chapter 1 directory
cd code/v1_task_manager/chapter_1

# Run Agent Loop
python agent_loop.py
```

## Notes

- Each chapter runs independently, demonstrating different functional features
- Recommended to learn in order, progressing from basic to complex
- For detailed documentation, please refer to the Chinese/English documentation links above

## License

This project uses the [MIT License](LICENSE).
