# s03: Skill Loading - Code Documentation

---

## Overview

### Core Improvements

**From Fixed Tools to Dynamic Knowledge Expansion**

s03 introduces the **Skill System** on top of s02, allowing the model to dynamically load domain knowledge documents. This solves the contradiction between limited system prompt length and unlimited growth of domain knowledge.

### Design Philosophy

> **"Don't put everything in the system prompt. Load on demand."**

The core design philosophy of s03: **Knowledge-as-Code**. Domain knowledge is stored as Markdown documents in the `skills/` directory, with on-demand access implemented through a two-layer loading mechanism:

- **Layer 1 (Low Cost)**: System prompt contains only skill names and short descriptions (approximately 100 tokens/skill)
- **Layer 2 (On-Demand)**: When the model calls the `load_skill` tool, the complete skill document content is returned

### Code File Path

```
v1_task_manager/chapter_3/s03_skill_loading.py
```

### Core Architecture Diagram (Comparison with s02)

**s02 Architecture (Fixed Tool Set)**:
```
    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch    |
    |  prompt  |      |       |      | {bash, read,     |
    +----------|      +---+---+      |  write, edit}    |
                          ^          +------------------+
                          |                 |
                          +-----------------+
                               tool_result
```

**s03 Architecture (Dynamic Knowledge Injection)**:
```
    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch    |
    |  prompt  |      |       |      | {bash, read,     |
    +----------+      +---+---+      |  write, edit,    |
                          ^          |  load_skill}     |
                          |          +------------------+
                          |                 |
                    +-----+-----+           |
                    |  Skill    | <---------+
                    |  Prompt   |  load_skill("pdf")
                    |  (Layer 1)|
                    +-----+-----+
                          |
                    +-----v-----+
                    |  Skill    |
                    |  Document |  <--- skills/pdf/SKILL.md
                    |  (Layer 2)|       skills/jsonl_handler/SKILL.md
                    +-----------+
```

**Architecture Explanation**:
1. During system initialization, `SkillLoader` scans the `skills/` directory and parses frontmatter metadata from all `SKILL.md` files
2. Layer 1 metadata (name, description, tags) is injected into the SYSTEM prompt
3. LLM determines whether specific skills need to be loaded based on task requirements
4. Call `load_skill("skill_name")` tool to return the complete skill document (Layer 2)
5. Model executes tasks based on complete skill knowledge

---

## Comparison with s02

### Change Overview

| Component | s02 | s03 | Change Description |
|------|-----|-----|----------|
| **Import Modules** | Standard library | + `re` | New regex module for parsing frontmatter |
| **Skill Directory** | None | `SKILLS_DIR = WORKDIR / "skills"` | New skill document storage directory |
| **Data Structure** | None | `SkillLoader` class | New skill loader managing skill metadata and content |
| **Tool Set** | 4 tools | 5 tools | New `load_skill` tool |
| **SYSTEM Prompt** | Fixed text | Dynamically injected skill list | System prompt contains available skill descriptions |
| **Knowledge Management** | Hardcoded in prompt | External documents on-demand loading | Knowledge-as-Code implementation |

### New Component Architecture

```
    skills/
    ├── pdf_handler/
    │   └── SKILL.md      # Frontmatter + Complete skill document
    ├── jsonl_handler/
    │   └── SKILL.md
    └── code-review/
        └── SKILL.md

    SkillLoader Class
    ├── _load_all()       # Scan and parse all SKILL.md
    ├── _parse_frontmatter()  # Parse YAML frontmatter
    ├── get_descriptions()    # Layer 1: Get short descriptions
    └── get_content()         # Layer 2: Get complete content

    SYSTEM Prompt
    ┌─────────────────────────────────────┐
    │ You are a coding agent at WORKDIR.  │
    │ Use load_skill to access specialized│
    │ knowledge before tackling unfamiliar│
    │ topics.                             │
    │ Skills available:                   │
    │   - pdf_handler: ... [tags]         │  <-- Layer 1
    │   - jsonl_handler: ... [tags]       │
    └─────────────────────────────────────┘
```

---

## Detailed Explanation by Execution Order

### Phase 1: New Import Module

#### Introduction of re Module

**Mechanism Overview**:
s03 adds the `re` module (regular expressions) for parsing YAML frontmatter format in skill documents. Frontmatter is a convention for storing metadata at the top of Markdown files, using `---` delimiters to wrap YAML content.

```python
import re
```

**Design Philosophy**:
- Use regex instead of YAML parsing library to reduce external dependencies
- Frontmatter format is simple; regex is sufficient for handling `key: value` pairs
- Maintain project lightweight and portability

**Frontmatter Format Example**:
```markdown
---
name: pdf_handler
description: Comprehensive best practices for PDF files.
tags: python, pdf, document-processing
---

# PDF Handler Skill

Complete skill document content...
```

---

### Phase 2: Skill Directory Configuration

**Mechanism Overview**:
Define the `SKILLS_DIR` constant, pointing to the `skills/` subdirectory under the working directory. This directory stores all skill documents, with each skill occupying a subdirectory containing a `SKILL.md` file.

```python
WORKDIR = Path.cwd()
SKILLS_DIR = WORKDIR / "skills"
```

**Skill Directory Structure Design**:
```
skills/
├── pdf_handler/
│   └── SKILL.md
├── jsonl_handler/
│   └── SKILL.md
└── code-review/
    └── SKILL.md
```

**Design Philosophy**:
- Each skill has an independent directory for easy organization and management
- Uniformly named `SKILL.md` for automatic scanning
- Supports nested subdirectories (using `rglob` for recursive search)
- Use uppercase `SKILL.md` to highlight its特殊性

---

### Phase 3: Skill Data Structure Definition

#### SkillLoader Class

**Mechanism Overview**:
The `SkillLoader` class is responsible for scanning the `skills/` directory, parsing all `SKILL.md` files, and providing a two-layer access interface:
- Layer 1: `get_descriptions()` returns short descriptions for injecting into system prompts
- Layer 2: `get_content(name)` loads complete content of specified skills on demand

This class adopts an **eager loading** strategy: immediately scans and parses all skill metadata during initialization, but complete content is only read upon request.

```python
class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills = {}
        self._load_all()  # Scan all skills during initialization
    
    def _load_all(self):
        if not self.skills_dir.exists():
            return
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            text = f.read_text()
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}
```

**Data Structure Design**:
```python
self.skills = {
    "pdf_handler": {
        "meta": {
            "name": "pdf_handler",
            "description": "Comprehensive best practices...",
            "tags": "python, pdf, document-processing"
        },
        "body": "# PDF Handler Skill\n\nComplete content...",
        "path": "/path/to/skills/pdf_handler/SKILL.md"
    },
    "jsonl_handler": { ... }
}
```

**Nested Data Structure Design Philosophy**:
- `meta`: Stores metadata parsed from frontmatter, used for Layer 1
- `body`: Stores complete document content after frontmatter, used for Layer 2
- `path`: Stores file path for debugging and error reporting
- Use dictionary instead of dataclass for flexibility and simplicity

---

### Phase 4: SkillLoader Class Details

#### _parse_frontmatter() Method

**Mechanism Overview**:
Parse YAML frontmatter at the top of Markdown files. Use regular expressions to match content between `---` delimiters, parsing `key: value` pairs line by line.

```python
def _parse_frontmatter(self, text: str) -> tuple:
    """Parse YAML frontmatter between --- delimiters."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text  # No frontmatter, return empty metadata and full text
    meta = {}
    for line in match.group(1).strip().splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip()
    return meta, match.group(2).strip()
```


**Design Philosophy**:
- Simple YAML parsing: Only handle `key: value` format, no support for complex nesting
- Error tolerance: Return full text as body when no frontmatter exists
- Colon splitting: `split(":", 1)` ensures correct handling when values contain colons

---

#### get_descriptions() Method (Layer 1)

**Mechanism Overview**:
Generate skill description list for system prompts. Iterate through all loaded skills, extract `description` and `tags` fields from metadata, and format into a readable list.

```python
def get_descriptions(self) -> str:
    """Layer 1: short descriptions for the system prompt."""
    if not self.skills:
        return "(no skills available)"
    lines = []
    for name, skill in self.skills.items():
        desc = skill["meta"].get("description", "No description")
        tags = skill["meta"].get("tags", "")
        line = f"  - {name}: {desc}"
        if tags:
            line += f" [{tags}]"
        lines.append(line)
    return "\n".join(lines)
```

**Output Example**:
```
Skills available:
  - pdf_handler: Comprehensive best practices for PDF files. [python, pdf, document-processing]
  - jsonl_handler: Best practices for processing JSONL files. [python, data-processing]
```

**Design Philosophy**:
- Compact format: One skill per line to reduce token consumption
- Optional tags: Append tags when available for quick skill domain identification
- Empty skill handling: Return prompt text when no skills exist to avoid empty system prompt

---

#### get_content() Method (Layer 2)

**Mechanism Overview**:
Load complete document content of specified skills on demand. Receive skill name and return skill body wrapped in formatted XML tags. If skill does not exist, return error message with available skill list.

```python
def get_content(self, name: str) -> str:
    """Layer 2: full skill body returned in tool_result."""
    skill = self.skills.get(name)
    if not skill:
        return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
    return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"
```

**Output Example**:
```xml
<skill name="pdf_handler">
# PDF Handler Skill

This skill provides comprehensive patterns for handling PDF files...

## 1. Reading PDF Files
...
</skill>
```

**Design Philosophy**:
- XML tag wrapping: Use `<skill name="...">` to clearly identify skill content boundaries
- Error-friendly: Prompt available options when skill doesn't exist to guide correct usage
- On-demand loading: Complete content only returned upon call to avoid consuming大量 tokens at once

---

### Phase 5: New Tool - load_skill

#### Tool Definition

**Mechanism Overview**:
`load_skill` is the core new tool in s03, allowing the model to dynamically load complete documents of specific skills when needed. This tool receives a skill name and returns formatted skill content.

**JSON Schema Definition**:
```python
{"type": "function", "function": {
    "name": "load_skill",
    "description": "Load specialized knowledge by name.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name to load"
            }
        },
        "required": ["name"]
    }
}}
```

**Tool Handler Function**:
```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_LOADER.get_content(kw["name"]),  # New
}
```

**Collaboration Relationship with Other Tools**:
```
Task: Process PDF file and extract text

1. LLM receives task, views skill list in system prompt
   → Discovers "pdf_handler: Comprehensive best practices for PDF files"

2. LLM calls load_skill("pdf_handler")
   → Gets complete PDF processing skill document

3. LLM calls bash to install dependencies based on code examples in skill document
   → bash("pip install PyPDF2 pypdf reportlab")

4. LLM calls write_file to create processing script
   → write_file("process_pdf.py", "...code...")

5. LLM calls bash to execute script
   → bash("python process_pdf.py")
```

---

### Phase 6: SYSTEM Prompt Changes

#### s02 vs s03 Comparison

**s02 SYSTEM Prompt**:
```python
SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks. Act, don't explain."
```

**s03 SYSTEM Prompt**:
```python
SKILL_LOADER = SkillLoader(SKILLS_DIR)
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use load_skill to access specialized knowledge before tackling unfamiliar topics.
Skills available: {SKILL_LOADER.get_descriptions()}"""
```

**Change Description**:
1. **New skill usage guidance**: Explicitly inform model to use `load_skill` tool to access domain knowledge
2. **Dynamically inject skill list**: Generate available skill descriptions dynamically through `SKILL_LOADER.get_descriptions()`
3. **Behavior guidance**: Suggest model load relevant skills before handling unfamiliar topics

**Skill List Dynamic Injection Mechanism**:
```python
# Executed during initialization
SKILL_LOADER = SkillLoader(SKILLS_DIR)  # Scan skills/ directory

# Called when generating system prompt
SYSTEM = f"""...
Skills available: {SKILL_LOADER.get_descriptions()}"""

# get_descriptions() output example:
#   - pdf_handler: Comprehensive best practices... [python, pdf]
#   - jsonl_handler: Best practices for JSONL... [python, data]
```

**Design Philosophy**:
- Skill discovery: Model learns available skills through system prompt
- On-demand decision: Model determines whether skills need loading based on task requirements
- Low cost: Skill descriptions consume approximately 100 tokens/skill, far less than complete documents

---

## Complete Framework Flowchart

```
┌─────────────┐
│    User     │  Input task: "Process this PDF file, extract all text"
└──────┬──────┘
       │
       ▼
┌─────────────┐
│     LLM     │  View skill list in system prompt
│ (Initial)   │  → Discover "pdf_handler: ..."
└──────┬──────┘
       │
       │ Need skill knowledge?
       ├─────────────────┐
       │ Yes             │ No
       ▼                 │
┌─────────────┐          │
│  load_skill │          │
│ ("pdf_      │          │
│  handler")  │          │
└──────┬──────┘          │
       │                 │
       ▼                 │
┌─────────────┐          │
│ SkillLoader │          │
│ .get_content│          │
└──────┬──────┘          │
       │                 │
       ▼                 │
┌─────────────┐          │
│ tool_result │          │
│ <skill>     │          │
│ Complete    │          │
│ document    │          │
│ </skill>    │          │
└──────┬──────┘          │
       │                 │
       └────────┬────────┘
                │
                ▼
         ┌─────────────┐
         │     LLM     │  Generate execution plan based on
         │ (Enhanced)  │  guidance in skill document
         └──────┬──────┘
                │
                ▼
         ┌─────────────┐
         │ Tool Call   │  bash, write_file, etc.
         └─────────────┘
```

---

## Skill Document Format Specification

### SKILL.md File Structure

````markdown
---
name: Skill name (used for load_skill calls)
description: Short description (for system prompt, recommended 50-100 characters)
tags: Comma-separated tags (optional, for classification)
---

# Skill Title

## Section 1: Topic

Detailed explanation...

```python
# Code example
def example():
    pass
```

## Section 2: Topic

...
````

### Frontmatter Format

**Required Fields**:
- `name`: Unique skill identifier, used for `load_skill("skill_name")` calls
- `description`: Short description, injected into system prompt

**Optional Fields**:
- `tags`: Comma-separated tags to help model quickly identify skill domain

**Format Requirements**:
- Use `---` delimiters to wrap YAML content
- Each field occupies one line, format is `key: value`
- Frontmatter must be at the beginning of the file

### Content Writing Standards

1. **Clear structure**: Use Markdown headers to organize content (`##`, `###`)
2. **Code examples**: Provide directly usable code snippets
3. **Best practices**: Include common pitfalls and solutions
4. **Quick reference**: Can add tables summarizing key information
5. **Language neutral**: Write in English for internationalization

---

## Design Points Summary

### Knowledge-as-Code Principle

**Core Idea**: Manage domain knowledge as code documents rather than hardcoding in system prompts.

**Advantages**:
- **Maintainability**: Skill documents are independent of code, easy to update and version control
- **Scalability**: Adding new skills only requires new files in `skills/` directory
- **Modularity**: Each skill is self-contained, easy to reuse and combine
- **Token Efficiency**: On-demand loading avoids system prompt bloat

### Dynamic Knowledge Injection Mechanism

**Two-Layer Architecture**:
- **Layer 1 (Metadata)**: System prompt contains skill names and descriptions (low cost)
- **Layer 2 (Complete Content)**: Tool calls return complete skill documents (on-demand)

**Workflow**:
```
Initialization → Scan skills → Inject metadata → Model decision → On-demand loading → Execute task
```

### Separation Design of Skills and Tools

**Tools**:
- Execute specific operations (bash, file read/write, etc.)
- Change external state
- Limited quantity (usually 5-10)

**Skills**:
- Provide domain knowledge
- Do not directly execute operations
- Quantity is scalable (theoretically unlimited)

**Design Advantages**:
- Tools remain streamlined, focusing on core capabilities
- Skills expand independently without modifying core code
- Model clearly distinguishes "what to do" (tools) and "how to do" (skills)

### Lazy Loading Optimization

**Implementation Strategy**:
- Only load metadata during initialization (lightweight)
- Complete content returned upon `get_content()` call
- Avoid loading all skill documents at once

**Token Savings**:
```
Assuming 10 skills, each skill document 2000 tokens

❌ All in system prompt: 20,000 tokens
✅ Layer 1 metadata: 1,000 tokens (100 tokens/skill)
✅ Layer 2 on-demand: Only load actually used skills
```

---

## Practice Guide

### How to Create New Skills

**Step 1: Create skill directory**
```bash
mkdir -p skills/your-skill-name
```

**Step 2: Create SKILL.md file**
```markdown
---
name: your-skill-name
description: Briefly describe the functionality of this skill
tags: Related tags, such as python, web, api
---

# Your Skill Name

## Overview

Skill overview...

## Usage

Usage methods and code examples...

## Best Practices

Best practices and notes...
```

**Step 3: Verify skill loading**
```bash
# Run s03, call load_skill("your-skill-name")
python v1_task_manager/chapter_3/s03_skill_loading.py
```

### Skill Directory Structure Example

```
skills/
├── pdf_handler/
│   └── SKILL.md          # PDF processing skill
├── jsonl_handler/
│   └── SKILL.md          # JSONL processing skill
├── code-review/
│   └── SKILL.md          # Code review skill
├── web-scraping/
│   └── SKILL.md          # Web scraping skill
└── database/
    └── SKILL.md          # Database operation skill
```

### Test Example

**Test Script**:
```python
from pathlib import Path
from s03_skill_loading import SkillLoader

# Initialize skill loader
SKILLS_DIR = Path.cwd() / "skills"
loader = SkillLoader(SKILLS_DIR)

# Test Layer 1: Get skill descriptions
print("=== Available Skills ===")
print(loader.get_descriptions())

# Test Layer 2: Load complete skill
print("\n=== Loading pdf_handler skill ===")
content = loader.get_content("pdf_handler")
print(content[:500])  # Print first 500 characters

# Test error handling
print("\n=== Testing non-existent skill ===")
print(loader.get_content("non-existent"))
```

**Expected Output**:
```
=== Available Skills ===
  - pdf_handler: Comprehensive best practices... [python, pdf]
  - jsonl_handler: Best practices for JSONL... [python, data]

=== Loading pdf_handler skill ===
<skill name="pdf_handler">
# PDF Handler Skill

This skill provides comprehensive patterns...
</skill>

=== Testing non-existent skill ===
Error: Unknown skill 'non-existent'. Available: pdf_handler, jsonl_handler
```

---

## Overall Design Philosophy Summary

### 1. Separation of Concerns

Separate **tool execution** from **domain knowledge**:
- Tools are responsible for "what to do" (execute operations)
- Skills are responsible for "how to do" (provide methods)
- Both evolve independently without affecting each other

### 2. Lazy Loading

Avoid pre-loading all knowledge:
- System prompt contains only lightweight metadata
- Complete content loaded when needed
- Reduce initial token consumption, improve response speed

### 3. Knowledge-as-Code

Manage knowledge with code engineering methods:
- Skill document version control (Git)
- Code review process
- Automated test verification
- Treat documents equally with code

### 4. Scalability First

Design supports unlimited scaling:
- New skills require no core code changes
- Skill directory automatically scanned
- Unified tool call interface

### 5. UX Optimization

Provide friendly knowledge acquisition experience for the model:
- Clearly list available skills in system prompt
- Skill descriptions are concise and clear
- Error messages provide available options

### 6. Token Economics

Optimize token usage efficiency:
- Layer 1 metadata approximately 100 tokens/skill
- Layer 2 on-demand loading avoids waste
- Saves 90%+ tokens compared to full injection

---

*Document Version: v1.0*
*Based on Code: v1_task_manager/chapter_3/s03_skill_loading.py*
