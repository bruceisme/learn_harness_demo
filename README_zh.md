[中文版](README_zh.md) | [English Version](README.md)

# learn_harness_demo

基于 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 实现的教学项目，逐步构建符合 harness engineering 概念的 agent demo。

> **说明：** 本项目采用 OpenAI 兼容的 API 格式进行模型调用。
> 运行前请设置 `OPENAI_API_KEY` 和 `OPENAI_API_BASE` 环境变量。

## 环境要求

- Python >= 3.10

## 项目特点

- **逐步演进**：19 个章节从基础 Agent Loop 到完整的多代理系统
- **教学性质**：每章包含详细的代码分析和设计说明
- **完整体系**：涵盖工具、技能、任务管理、子代理、上下文管理等核心组件
- **中英双语**：提供完整的中英文档

## 目录结构

```
learn_harness_demo/
├── code/v1_task_manager/    # 代码实现（19 个章节）
│   ├── chapter_1/           # 基础 Agent Loop
│   ├── chapter_2/           # 工具系统扩展
│   └── ...
├── docs/zh/                 # 中文文档
├── docs/en/                 # 英文文档
├── README.md
└── LICENSE
```

## 文档链接

- **中文文档**：[核心框架变化分析](docs/zh/核心框架变化分析.md)
- **英文文档**：[Core Framework Changes](docs/en/core_framework_changes.md)

## 章节概览

| 章节 | 主题 | 内容简述 | Python 文件 | 中文文档 | 英文文档 |
|------|------|----------|-------------|----------|----------|
| Chapter 1 | 基础 Agent Loop | 单一 bash 工具 + 简洁循环 | `agent_loop.py` | [文档](docs/zh/chapter_1/agent_loop_文档.md) | [Doc](docs/en/chapter_1/agent_loop_doc.md) |
| Chapter 2 | 工具系统扩展 | 4 个文件操作工具 | `s02_tool_use.py` | [文档](docs/zh/chapter_2/s02_tool_use_文档.md) | [Doc](docs/en/chapter_2/s02_tool_use_doc.md) |
| Chapter 3 | 技能系统引入 | SkillRegistry + load_skill | `s03_skill_loading.py` | [文档](docs/zh/chapter_3/s03_skill_loading_文档.md) | [Doc](docs/en/chapter_3/s03_skill_loading_doc.md) |
| Chapter 4 | 任务管理系统 | Todo 持久化 | `s04_todo_write.py` | [文档](docs/zh/chapter_4/s04_todo_write_文档.md) | [Doc](docs/en/chapter_4/s04_todo_write_doc.md) |
| Chapter 5 | 子代理系统 | 主/子代理职责分离 | `s05_subagent.py` | [文档](docs/zh/chapter_5/s05_subagent_文档.md) | [Doc](docs/en/chapter_5/s05_subagent_doc.md) |
| Chapter 6 | 上下文管理 | 消息历史压缩 | `s06_context.py` | [文档](docs/zh/chapter_6/s06_context_文档.md) | [Doc](docs/en/chapter_6/s06_context_doc.md) |
| Chapter 7 | 权限系统 | 文件操作权限检查 | `s07_permission_system.py` | [文档](docs/zh/chapter_7/s07_permission_system_文档.md) | [Doc](docs/en/chapter_7/s07_permission_system_doc.md) |
| Chapter 8 | Hook 系统 | 前置/后置 Hook | `s08_hook_system.py` | [文档](docs/zh/chapter_8/s08_hook_system_文档.md) | [Doc](docs/en/chapter_8/s08_hook_system_doc.md) |
| Chapter 9 | 记忆系统 | MemoryStore 持久化 | `s09_memory_system.py` | [文档](docs/zh/chapter_9/s09_memory_system_文档.md) | [Doc](docs/en/chapter_9/s09_memory_system_doc.md) |
| Chapter 10 | 构建系统 | 项目构建和打包 | `test_chapter_10.py` | [文档](docs/zh/chapter_10/test_chapter_10_文档.md) | [Doc](docs/en/chapter_10/test_chapter_10_doc.md) |
| Chapter 11 | 恢复系统 | 状态恢复机制 | `s11_Resume_system.py` | [文档](docs/zh/chapter_11/s11_Resume_system_文档.md) | [Doc](docs/en/chapter_11/s11_Resume_system_doc.md) |
| Chapter 12 | 任务系统 | 任务调度管理 | `s12_task_system.py` | [文档](docs/zh/chapter_12/s12_task_system_文档.md) | [Doc](docs/en/chapter_12/s12_task_system_doc.md) |
| Chapter 13 | 知识系统 | 知识库管理 | `s13_v2_backtask.py` | [文档](docs/zh/chapter_13/s13_v2_backtask_文档.md) | [Doc](docs/en/chapter_13/s13_v2_backtask_doc.md) |
| Chapter 14 | 计划系统 | 规划和执行 | `s14_cron_scheduler.py` | [文档](docs/zh/chapter_14/s14_cron_scheduler_文档.md) | [Doc](docs/en/chapter_14/s14_cron_scheduler_doc.md) |
| Chapter 18.2 | Worktree 任务隔离系统 | git worktree 全生命周期管理 | `s18_v2_singleagent_worktree_task_isolation.py` | [文档](docs/zh/chapter_18_2/s18_v2_singleagent_worktree_task_isolation_文档.md) | [Doc](docs/en/chapter_18_2/s18_v2_singleagent_worktree_task_isolation_doc.md) |
| Chapter 19.2 | MCP & Plugin 系统集成 | MCP 和插件系统集成 | `s19_v2_mcp_plugin.py` | [文档](docs/zh/chapter_19_2/s19_mcp_plugin.md) | [Doc](docs/en/chapter_19_2/s19_mcp_plugin.md) |

## 快速开始

```bash
# 设置环境变量（替换为实际值）
export OPENAI_API_KEY="your-api-key-here"
export OPENAI_API_BASE="http://your-server-ip:8000/v1"

# 进入 Chapter 1 目录
cd code/v1_task_manager/chapter_1

# 运行 Agent Loop
python agent_loop.py
```

## 说明

- 每个章节独立运行，展示不同的功能特性
- 建议按顺序学习，从基础到复杂逐步深入
- 详细文档请参考上方的中英文档链接
## 许可证

本项目采用 [MIT 许可证](LICENSE)。
