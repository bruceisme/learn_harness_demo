#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s18_v2_worktree.py - Single Agent with Worktree Task Isolation

Reference: learn-claude-code (https://github.com/shareAI-lab/learn-claude-code)
License: MIT License

This module extends s14_v4_backtask.py with worktree-based task isolation.
It demonstrates git worktree lifecycle management for parallel and risky work.

Features:
    - Task isolation: Bind tasks to isolated git worktrees for safe parallel execution
    - worktree_create: Create git worktree execution lane from base ref
    - worktree_enter: Enter or reopen a worktree lane before working
    - worktree_run: Execute shell commands inside a worktree directory
    - worktree_status: Show git status for a worktree
    - worktree_closeout: Keep or remove worktree, optionally complete bound task
    - worktree_keep / worktree_remove: Manage worktree lifecycle
    - worktree_list / worktree_events: List worktrees and lifecycle events
    - task_bind_worktree: Bind task to worktree, activate worktree state
    - Event logging: Worktree events appended to .worktrees/events.jsonl

Documentation:
    - Chinese: docs/zh/chapter_18_2/s18_v2_worktree_文档.md
    - English: docs/en/chapter_18_2/s18_v2_worktree_doc.md
"""
import os
import os,json,re,random
import subprocess,datetime,sys,termios
from datetime import datetime as dt, timedelta
import threading,uuid
from dataclasses import dataclass,field
from pathlib import Path
from queue import Queue, Empty
import readline
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

########地址配置
WORKDIR = Path.cwd()

def detect_repo_root(cwd: Path) -> "Path | None":
    """Detect git repo root for worktree support. Returns None if not in a repo."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        root = Path(r.stdout.strip())
        return root if r.returncode == 0 and root.exists() else None
    except Exception:
        return None

REPO_ROOT = detect_repo_root(WORKDIR) or WORKDIR

SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"
TRUST_MARKER = WORKDIR / ".claude" / ".claude_trusted"
TASKS_DIR = WORKDIR / ".tasks"
WORKTREES_DIR = REPO_ROOT / ".worktrees"
RUNTIME_DIR = WORKDIR / ".runtime-tasks"
RUNTIME_DIR.mkdir(exist_ok=True)
STALL_THRESHOLD_S = 45  # seconds before a background task is considered stalled

#########s14 cron 路径配置############
SCHEDULED_TASKS_FILE = WORKDIR / ".claude" / "scheduled_tasks.json"
CRON_LOCK_FILE = WORKDIR / ".claude" / "cron.lock"
AUTO_EXPIRY_DAYS = 7
JITTER_MINUTES = [0, 30]  # 避免这些整点触发 jitter
JITTER_OFFSET_MAX = 4     # jitter 偏移范围（分钟）

# --- 配置参数 ---
# 上下文预算说明（模型最大输入：260k token ≈ 1,040,000 chars）
#   预留 output + thinking ≈ 40k token = 160k chars
#   预留 system prompt    ≈  3k token =  12k chars
#   安全输入上限          ≈ 217k token = 868k chars
#   compact 触发点 (85%)  ≈ 185k token → 取 800k chars
CONTEXT_LIMIT             = 800000   # chars；达到此值触发 compact（原 100000）
PERSIST_THRESHOLD         = 150000   # chars；工具输出超过此值才持久化到文件（原 60000）
PREVIEW_CHARS             =  80000   # chars；持久化文件的预览长度（原 20000）
PLAN_REMINDER_INTERVAL    = 8
KEEP_RECENT_TOOL_RESULTS  = 20       # 保留最近 N 条工具结果不压缩（原 5）


############s09 新增Memory########
MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
MEMORY_TYPES = ("user", "feedback", "project", "reference")
MAX_INDEX_LINES = 200


#######HOOKs 变量定义
HOOK_EVENTS = ("PreToolUse", "PostToolUse", "SessionStart")
HOOK_TIMEOUT = 30  # seconds


#######s07新增
MODES = ("default", "plan", "auto")
READ_ONLY_TOOLS = {"read_file", "bash_readonly"}
WRITE_TOOLS = {"write_file", "edit_file", "bash"}


#########s14 Cron 定时任务############
class CronLock:#目前没有实际使用到
    """
    基于 PID 文件的锁，防止多个会话同时触发同一个 cron 任务。
    """
    def __init__(self, lock_path: Path = None):
        self._lock_path = lock_path or CRON_LOCK_FILE

    def acquire(self) -> bool:
        if self._lock_path.exists():
            try:
                stored_pid = int(self._lock_path.read_text().strip())
                os.kill(stored_pid, 0)  # 发信号 0 检测进程是否存活
                return False  # 进程存活，锁被占用
            except (ValueError, ProcessLookupError, PermissionError, OSError):
                pass  # 进程已死或 PID 解析失败，视为过期锁
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path.write_text(str(os.getpid()))
        return True

    def release(self):
        try:
            if self._lock_path.exists():
                stored_pid = int(self._lock_path.read_text().strip())
                if stored_pid == os.getpid():
                    self._lock_path.unlink()
        except (ValueError, OSError):
            pass


def cron_matches(expr: str, now: "dt") -> bool:
    """
    检查 5 字段 cron 表达式是否与指定时间匹配。
    字段：分 时 日 月 周（0=周日）
    支持 * / N N-M N,M 语法，无外部依赖。
    """
    fields = expr.strip().split()
    if len(fields) != 5:
        return False
    cron_dow = (now.weekday() + 1) % 7  # Python 0=周一 → cron 0=周日
    values = [now.minute, now.hour, now.day, now.month, cron_dow]
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    for field, value, (lo, hi) in zip(fields, values, ranges):
        if not _field_matches(field, value, lo, hi):
            return False
    return True


def _field_matches(field: str, value: int, lo: int, hi: int) -> bool:
    """匹配单个 cron 字段。"""
    if field == "*":
        return True
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, step_str = part.split("/", 1)
            step = int(step_str)
        if part == "*":
            if (value - lo) % step == 0:
                return True
        elif "-" in part:
            start, end = part.split("-", 1)
            start, end = int(start), int(end)
            if start <= value <= end and (value - start) % step == 0:
                return True
        else:
            if int(part) == value:
                return True
    return False


class CronScheduler:
    """
    管理定时任务并在后台线程中检查触发条件。
    触发时将 prompt 推入通知队列，agent_loop 在每轮 LLM 调用前 drain。
    """
    def __init__(self):
        self.tasks = []
        self.queue = Queue()
        self._lock = threading.RLock()  # RLock：允许同线程重入（_check_tasks 持锁后调 _save_durable）
        self._stop_event = threading.Event()
        self._thread = None
        self._last_check_minute = -1

    def start(self):
        """加载持久任务并启动后台检查线程。"""
        #加载磁盘中的任务
        self._load_durable() 
        #开启线程
        self._thread = threading.Thread(target=self._check_loop, daemon=True)
        self._thread.start()
        with self._lock:
            count = len(self.tasks)
        if count:
            print(f"[Cron] 已加载 {count} 个定时任务")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def create(self, cron_expr: str, prompt: str,
               recurring: bool = True, durable: bool = False) -> str:
        task_id = str(uuid.uuid4())[:8]
        now = time.time()
        task = {
            "id": task_id,
            "cron": cron_expr,
            "prompt": prompt,
            "recurring": recurring,
            "durable": durable,
            "createdAt": now,
        }
        if recurring:
            task["jitter_offset"] = self._compute_jitter(cron_expr)
        with self._lock:
            self.tasks.append(task)
            if durable:
                self._save_durable()
        mode = "recurring" if recurring else "one-shot"
        store = "durable" if durable else "session-only"
        return f"Created task {task_id} ({mode}, {store}): cron={cron_expr}"

    def delete(self, task_id: str) -> str:
        with self._lock:
            before = len(self.tasks)
            self.tasks = [t for t in self.tasks if t["id"] != task_id]
            if len(self.tasks) < before:
                self._save_durable()
                return f"Deleted task {task_id}"
        return f"Task {task_id} not found"

    def list_tasks(self) -> str:
        with self._lock:
            snapshot = list(self.tasks)
        if not snapshot:
            return "No scheduled tasks."
        lines = []
        for t in snapshot:
            mode = "recurring" if t["recurring"] else "one-shot"
            store = "durable" if t["durable"] else "session"
            age_hours = (time.time() - t["createdAt"]) / 3600
            lines.append(
                f"  {t['id']}  {t['cron']}  [{mode}/{store}] "
                f"({age_hours:.1f}h old): {t['prompt'][:60]}"
            )
        return "\n".join(lines)

    def drain_notifications(self) -> list:
        notifications = []
        while True:
            try:
                notifications.append(self.queue.get_nowait())
            except Empty:
                break
        return notifications

    def _compute_jitter(self, cron_expr: str) -> int:
        fields = cron_expr.strip().split()
        if len(fields) < 1:
            return 0
        try:
            minute_val = int(fields[0])
            if minute_val in JITTER_MINUTES:
                return (hash(cron_expr) % JITTER_OFFSET_MAX) + 1
        except ValueError:
            pass
        return 0

    def _check_loop(self):
        while not self._stop_event.is_set():
            now = dt.now()
            current_minute = now.hour * 60 + now.minute
            if current_minute != self._last_check_minute:
                self._last_check_minute = current_minute
                self._check_tasks(now)
            self._stop_event.wait(timeout=1)

    def _check_tasks(self, now: "dt"):
        expired = []
        fired_oneshots = []
        with self._lock:
            for task in self.tasks:
                age_days = (time.time() - task["createdAt"]) / 86400
                if task["recurring"] and age_days > AUTO_EXPIRY_DAYS:
                    expired.append(task["id"])
                    continue
                check_time = now
                jitter = task.get("jitter_offset", 0)
                if jitter:
                    check_time = now - timedelta(minutes=jitter)
                if cron_matches(task["cron"], check_time):
                    notification = f"[Scheduled task {task['id']}]: {task['prompt']}"
                    self.queue.put(notification)
                    task["last_fired"] = time.time()
                    print(f"[Cron] Fired: {task['id']}")
                    if not task["recurring"]:
                        fired_oneshots.append(task["id"])
            if expired or fired_oneshots:
                remove_ids = set(expired) | set(fired_oneshots)
                self.tasks = [t for t in self.tasks if t["id"] not in remove_ids]
                for tid in expired:
                    print(f"[Cron] Auto-expired: {tid}")
                for tid in fired_oneshots:
                    print(f"[Cron] One-shot completed: {tid}")
                self._save_durable()

    def detect_missed_tasks(self) -> list:
        """启动时检测持久任务是否在会话关闭期间错过触发。"""
        now = dt.now()
        missed = []
        with self._lock:
            snapshot = list(self.tasks)
        for task in snapshot:
            last_fired = task.get("last_fired")
            if last_fired is None:
                continue
            last_dt = dt.fromtimestamp(last_fired)
            check = last_dt + timedelta(minutes=1)
            cap = min(now, last_dt + timedelta(hours=24))
            while check <= cap:
                if cron_matches(task["cron"], check):
                    missed.append({
                        "id": task["id"],
                        "cron": task["cron"],
                        "prompt": task["prompt"],
                        "missed_at": check.isoformat(),
                    })
                    break
                check += timedelta(minutes=1)
        return missed

    def _load_durable(self):
        if not SCHEDULED_TASKS_FILE.exists():
            return
        try:
            data = json.loads(SCHEDULED_TASKS_FILE.read_text())
            self.tasks = [t for t in data if t.get("durable")]
        except Exception as e:
            print(f"[Cron] Error loading tasks: {e}")

    def _save_durable(self):
        durable = [t for t in self.tasks if t.get("durable")]
        SCHEDULED_TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SCHEDULED_TASKS_FILE.write_text(
            json.dumps(durable, indent=2) + "\n"
        )


# 全局 cron scheduler 实例
scheduler = CronScheduler()

#########s13 后台任务执行############
class BackgroundManager:
    def __init__(self):
        self.dir = RUNTIME_DIR
        self.tasks = {}  # task_id -> {status, result, command, started_at}
        self._notification_queue = []  # completed task results
        self._lock = threading.Lock()

    def _record_path(self, task_id: str):
        return self.dir / f"{task_id}.json"

    def _output_path(self, task_id: str):
        return self.dir / f"{task_id}.log"
    
    def _persist_task(self, task_id: str):
        record = dict(self.tasks[task_id])
        self._record_path(task_id).write_text(
            json.dumps(record, indent=2, ensure_ascii=False)
        )
    
    def _preview(self, output: str, limit: int = 500) -> str:
        compact = " ".join((output or "(no output)").split())
        return compact[:limit]

    def run(self, command: str) -> str:
        """Start a background thread, return task_id immediately."""
        task_id = str(uuid.uuid4())[:8]
        output_file = self._output_path(task_id)
        self.tasks[task_id] = {
            "id": task_id,
            "status": "running",
            "result": None,
            "command": command,
            "started_at": time.time(),
            "finished_at": None,
            "result_preview": "",
            "output_file": str(output_file.relative_to(WORKDIR)),
        }
        self._persist_task(task_id)
        thread = threading.Thread(
            target=self._execute, args=(task_id, command), daemon=True
        )
        thread.start()
        return (
            f"Background task {task_id} started: {command[:80]} "
            f"(output_file={output_file.relative_to(WORKDIR)})"
        )

    def _execute(self, task_id: str, command: str):
        """Thread target: run subprocess, capture output, push to queue."""
        try:
            r = subprocess.run(
                command, shell=True, cwd=WORKDIR,
                capture_output=True, text=True, timeout=300
            )
            output = (r.stdout + r.stderr).strip()[:50000]
            status = "completed"
        except subprocess.TimeoutExpired:
            output = "Error: Timeout (300s)"
            status = "timeout"
        except Exception as e:
            output = f"Error: {e}"
            status = "error"
        final_output = output or "(no output)"
        preview = self._preview(final_output)
        output_path = self._output_path(task_id)
        output_path.write_text(final_output)
        with self._lock:
            self.tasks[task_id]["status"] = status
            self.tasks[task_id]["result"] = final_output
            self.tasks[task_id]["finished_at"] = time.time()
            self.tasks[task_id]["result_preview"] = preview
            self._notification_queue.append({
                "task_id": task_id,
                "status": status,
                "command": command[:80],
                "preview": preview,
                "output_file": str(output_path.relative_to(WORKDIR)),
            })
        self._persist_task(task_id)  # 锁外执行文件 I/O，避免持锁期间阻塞
    
    def check(self, task_id: str = None) -> str:
        """Check status of one task or list all."""
        if task_id:
            t = self.tasks.get(task_id)
            if not t:
                return f"Error: Unknown task {task_id}"
            visible = {
                "id": t["id"],
                "status": t["status"],
                "command": t["command"],
                "result_preview": t.get("result_preview", ""),
                "output_file": t.get("output_file", ""),
            }
            return json.dumps(visible, indent=2, ensure_ascii=False)
        lines = []
        for tid, t in self.tasks.items():
            lines.append(
                f"{tid}: [{t['status']}] {t['command'][:60]} "
                f"-> {t.get('result_preview') or '(running)'}"
            )
        return "\n".join(lines) if lines else "No background tasks."
    
    def drain_notifications(self) -> list:
        """Return and clear all pending completion notifications."""
        with self._lock:
            notifs = list(self._notification_queue)
            self._notification_queue.clear()
        return notifs
    
    def detect_stalled(self) -> list:
        """Return task IDs that have been running longer than STALL_THRESHOLD_S."""
        now = time.time()
        stalled = []
        for task_id, info in self.tasks.items():
            if info["status"] != "running":
                continue
            elapsed = now - info.get("started_at", now)
            if elapsed > STALL_THRESHOLD_S:
                stalled.append(task_id)
        return stalled


BG = BackgroundManager()


#########s12 task规划############
# -- TaskManager: CRUD for a persistent task graph --
class TaskManager:
    """Persistent TaskRecord store.
    Think "work graph on disk", not "currently running worker".
    """
    def __init__(self, tasks_dir: Path):
        self.dir = tasks_dir
        self.dir.mkdir(exist_ok=True)
        self._next_id = self._max_id() + 1
        self.rounds_since_update = 0

    def get_items(self) -> list:
        """Return all tasks as a list of dicts, sorted by id."""
        items = []
        for f in sorted(self.dir.glob("task_*.json")):
            items.append(json.loads(f.read_text()))
        return items

    def _max_id(self) -> int:
        ids = [int(f.stem.split("_")[1]) for f in self.dir.glob("task_*.json")]
        return max(ids) if ids else 0
    
    def _load(self, task_id: int) -> dict:
        path = self.dir / f"task_{task_id}.json"
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text())
    
    def _save(self, task: dict):
        path = self.dir / f"task_{task['id']}.json"
        # 添加 ensure_ascii=False 来保持中文字符可见
        path.write_text(json.dumps(task, indent=2, ensure_ascii=False), encoding='utf-8')
    
    def create(self, subject: str, description: str = "") -> str:
        task = {
            "id": self._next_id, "subject": subject, "description": description,
            "status": "pending", "blockedBy": [], "blocks": [], "owner": "",
            "worktree": "", "worktree_state": "unbound",
            "last_worktree": "", "closeout": None,
        }
        self._save(task)
        self._next_id += 1
        return json.dumps(task, indent=2, ensure_ascii=False)
    
    def get(self, task_id: int) -> str:
        return json.dumps(self._load(task_id), indent=2, ensure_ascii=False)
    
    def update(self, task_id: int, status: str = None, owner: str = None,
               add_blocked_by: list = None, add_blocks: list = None) -> str:
        task = self._load(task_id)
        if owner is not None:
            task["owner"] = owner
        if status:
            if status not in ("pending", "in_progress", "completed", "deleted"):
                raise ValueError(f"Invalid status: {status}")
            task["status"] = status
            # When a task is completed, remove it from all other tasks' blockedBy
            if status == "completed":
                self._clear_dependency(task_id)
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if add_blocks:
            task["blocks"] = list(set(task["blocks"] + add_blocks))
            # Bidirectional: also update the blocked tasks' blockedBy lists
            for blocked_id in add_blocks:
                try:
                    blocked = self._load(blocked_id)
                    if task_id not in blocked["blockedBy"]:
                        blocked["blockedBy"].append(task_id)
                        self._save(blocked)
                except ValueError:
                    pass
        self._save(task)
        return json.dumps(task, indent=2, ensure_ascii=False)
    
    def _clear_dependency(self, completed_id: int):
        """Remove completed_id from all other tasks' blockedBy lists."""
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text())
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                self._save(task)
    
    def list_all(self) -> str:
        tasks = []
        for f in sorted(self.dir.glob("task_*.json")):
            tasks.append(json.loads(f.read_text()))
        if not tasks:
            return "No tasks."
        lines = []
        for t in tasks:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]", "deleted": "[-]"}.get(t["status"], "[?]")
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            owner = f" owner={t['owner']}" if t.get("owner") else ""
            wt = f" wt={t['worktree']}" if t.get("worktree") else ""
            lines.append(f"{marker} #{t['id']}: {t['subject']}{owner}{wt}{blocked}")
        return "\n".join(lines)

    def exists(self, task_id: int) -> bool:
        return (self.dir / f"task_{task_id}.json").exists()

    def bind_worktree(self, task_id: int, worktree: str, owner: str = "") -> str:
        task = self._load(task_id)
        task["worktree"] = worktree
        task["last_worktree"] = worktree
        task["worktree_state"] = "active"
        if owner:
            task["owner"] = owner
        if task["status"] == "pending":
            task["status"] = "in_progress"
        task["updated_at"] = time.time()
        self._save(task)
        return json.dumps(task, indent=2, ensure_ascii=False)

    def unbind_worktree(self, task_id: int) -> str:
        task = self._load(task_id)
        task["worktree"] = ""
        task["worktree_state"] = "unbound"
        task["updated_at"] = time.time()
        self._save(task)
        return json.dumps(task, indent=2, ensure_ascii=False)

    def record_closeout(self, task_id: int, action: str, reason: str = "", keep_binding: bool = False) -> str:
        task = self._load(task_id)
        task["closeout"] = {
            "action": action,
            "reason": reason,
            "at": time.time(),
        }
        task["worktree_state"] = action
        if not keep_binding:
            task["worktree"] = ""
        task["updated_at"] = time.time()
        self._save(task)
        return json.dumps(task, indent=2, ensure_ascii=False)



##########s11错误返回#######
MAX_RECOVERY_ATTEMPTS = 3
BACKOFF_BASE_DELAY = 1.0  # seconds
BACKOFF_MAX_DELAY = 30.0  # seconds
# TOKEN_THRESHOLD = 50000   # chars / 4 ~ tokens for compact trigger


CONTINUATION_MESSAGE = (
    "Output limit hit. Continue directly from where you stopped -- "
    "no recap, no repetition. Pick up mid-sentence if needed."
)

def estimate_tokens(messages: list) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(json.dumps(messages, default=str)) // 4


def auto_compact(messages: list) -> list:
    """
    Compress conversation history into a short continuation summary.
    """
    conversation_text = json.dumps(messages, default=str)[:600000]  # 原 80000；260k 模型可安全摄入 ~150k token
    prompt = (
        "Summarize this conversation for continuity. Include:\n"
        "1) Task overview and success criteria\n"
        "2) Current state: completed work, files touched\n"
        "3) Key decisions and failed approaches\n"
        "4) Remaining next steps\n"
        "Be concise but preserve critical details.\n\n"
        + conversation_text
    )
    try:
        response = client.chat.completions.create(            
            model=MODEL, 
            messages=[{"role": "user", "content": prompt}] ,        
            max_tokens=6000,  # 原 2000；生成更完整的历史摘要
            temperature=1,
            extra_body={
                "top_k": 20,
                "chat_template_kwargs": {"enable_thinking": False},
            }
        )
        summary = response.choices[0].message.content.strip()
    except Exception as e:
        summary = f"(compact failed: {e}). Previous context lost."
    continuation = (
        "This session continues from a previous conversation that was compacted. "
        f"Summary of prior context:\n\n{summary}\n\n"
        "Continue from where we left off without re-asking the user."
    )
    return [{"role": "user", "content": continuation}]
def backoff_delay(attempt: int) -> float:
    """Exponential backoff with jitter: base * 2^attempt + random(0, 1)."""
    delay = min(BACKOFF_BASE_DELAY * (2 ** attempt), BACKOFF_MAX_DELAY)
    jitter = random.uniform(0, 1)
    return delay + jitter

######memory 架构
class MemoryManager:
    """
    Load, build, and save persistent memories across sessions.
    The teaching version keeps memory explicit:
    one Markdown file per memory, plus one compact index file.
    """
    def __init__(self, memory_dir: Path = None):
        self.memory_dir = memory_dir or MEMORY_DIR
        self.memories = {}  # name -> {description, type, content}
    
    def load_all(self):
        """Load MEMORY.md index and all individual memory files."""
        self.memories = {}
        if not self.memory_dir.exists():
            return
        # Scan all .md files except MEMORY.md
        for md_file in sorted(self.memory_dir.glob("*.md")):
            if md_file.name == "MEMORY.md":
                continue
            parsed = self._parse_frontmatter(md_file.read_text())
            if parsed:
                name = parsed.get("name", md_file.stem)
                self.memories[name] = {
                    "description": parsed.get("description", ""),
                    "type": parsed.get("type", "project"),
                    "content": parsed.get("content", ""),
                    "file": md_file.name,
                }
        count = len(self.memories)
        if count > 0:
            print(f"[Memory loaded: {count} memories from {self.memory_dir}]")
    
    def load_memory_prompt(self) -> str:
        """Build a memory section for injection into the system prompt."""
        if not self.memories:
            return ""
        sections = []
        sections.append("# Memories (persistent across sessions)")
        sections.append("")
        # Group by type for readability
        for mem_type in MEMORY_TYPES:
            typed = {k: v for k, v in self.memories.items() if v["type"] == mem_type}
            if not typed:
                continue
            sections.append(f"## [{mem_type}]")
            for name, mem in typed.items():
                sections.append(f"### {name}: {mem['description']}")
                if mem["content"].strip():
                    sections.append(mem["content"].strip())
                sections.append("")
        return "\n".join(sections)
    
    def save_memory(self, name: str, description: str, mem_type: str, content: str) -> str:
        """
        Save a memory to disk and update the index.
        Returns a status message.
        """
        if mem_type not in MEMORY_TYPES:
            return f"Error: type must be one of {MEMORY_TYPES}"
        # Sanitize name for filename
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower())
        if not safe_name:
            return "Error: invalid memory name"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        # Write individual memory file with frontmatter
        frontmatter = (
            f"---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"type: {mem_type}\n"
            f"---\n"
            f"{content}\n"
        )
        file_name = f"{safe_name}.md"
        file_path = self.memory_dir / file_name
        file_path.write_text(frontmatter)
        # Update in-memory store
        self.memories[name] = {
            "description": description,
            "type": mem_type,
            "content": content,
            "file": file_name,
        }
        # Rebuild MEMORY.md index
        self._rebuild_index()
        return f"Saved memory '{name}' [{mem_type}] to {file_path.relative_to(WORKDIR)}"
    
    def _rebuild_index(self):
        """Rebuild MEMORY.md from current in-memory state, capped at 200 lines."""
        lines = ["# Memory Index", ""]
        for name, mem in self.memories.items():
            lines.append(f"- {name}: {mem['description']} [{mem['type']}]")
            if len(lines) >= MAX_INDEX_LINES:
                lines.append(f"... (truncated at {MAX_INDEX_LINES} lines)")
                break
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        MEMORY_INDEX.write_text("\n".join(lines) + "\n")
    
    def _parse_frontmatter(self, text: str) -> dict | None:
        """Parse --- delimited frontmatter + body content."""
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if not match:
            return None
        header, body = match.group(1), match.group(2)
        result = {"content": body.strip()}
        for line in header.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                result[key.strip()] = value.strip()
        return result

class DreamConsolidator:
    """
    Auto-consolidation of memories between sessions ("Dream").
    This is an optional later-stage feature. Its job is to prevent the memory
    store from growing into a noisy pile by merging, deduplicating, and
    pruning entries over time.
    """
    COOLDOWN_SECONDS = 86400       # 24 hours between consolidations
    SCAN_THROTTLE_SECONDS = 600    # 10 minutes between scan attempts
    MIN_SESSION_COUNT = 5          # need enough data to consolidate
    LOCK_STALE_SECONDS = 3600      # PID lock considered stale after 1 hour
    PHASES = [
        "Orient: scan MEMORY.md index for structure and categories",
        "Gather: read individual memory files for full content",
        "Consolidate: merge related memories, remove stale entries",
        "Prune: enforce 200-line limit on MEMORY.md index",
    ]
    def __init__(self, memory_dir: Path = None):
        self.memory_dir = memory_dir or MEMORY_DIR
        self.lock_file = self.memory_dir / ".dream_lock"
        self.enabled = True
        self.mode = "default"
        self.last_consolidation_time = 0.0
        self.last_scan_time = 0.0
        self.session_count = 0
    def should_consolidate(self) -> tuple[bool, str]:
        """
        Check 7 gates in sequence. All must pass.
        Returns (can_run, reason) where reason explains the first failed gate.
        """
        import time
        now = time.time()
        # Gate 1: enabled flag
        if not self.enabled:
            return False, "Gate 1: consolidation is disabled"
        # Gate 2: memory directory exists and has memory files
        if not self.memory_dir.exists():
            return False, "Gate 2: memory directory does not exist"
        memory_files = list(self.memory_dir.glob("*.md"))
        # Exclude MEMORY.md itself from the count
        memory_files = [f for f in memory_files if f.name != "MEMORY.md"]
        if not memory_files:
            return False, "Gate 2: no memory files found"
        # Gate 3: not in plan mode (only consolidate in active modes)
        if self.mode == "plan":
            return False, "Gate 3: plan mode does not allow consolidation"
        # Gate 4: 24-hour cooldown since last consolidation
        time_since_last = now - self.last_consolidation_time
        if time_since_last < self.COOLDOWN_SECONDS:
            remaining = int(self.COOLDOWN_SECONDS - time_since_last)
            return False, f"Gate 4: cooldown active, {remaining}s remaining"
        # Gate 5: 10-minute throttle since last scan attempt
        time_since_scan = now - self.last_scan_time
        if time_since_scan < self.SCAN_THROTTLE_SECONDS:
            remaining = int(self.SCAN_THROTTLE_SECONDS - time_since_scan)
            return False, f"Gate 5: scan throttle active, {remaining}s remaining"
        # Gate 6: need at least 5 sessions worth of data
        if self.session_count < self.MIN_SESSION_COUNT:
            return False, f"Gate 6: only {self.session_count} sessions, need {self.MIN_SESSION_COUNT}"
        # Gate 7: no active lock file (check PID staleness)
        if not self._acquire_lock():
            return False, "Gate 7: lock held by another process"
        return True, "All 7 gates passed"
    def consolidate(self) -> list[str]:
        """
        Run the 4-phase consolidation process.
        The teaching version returns phase descriptions to make the flow
        visible without requiring an extra LLM pass here.
        """
        import time
        can_run, reason = self.should_consolidate()
        if not can_run:
            print(f"[Dream] Cannot consolidate: {reason}")
            return []
        print("[Dream] Starting consolidation...")
        self.last_scan_time = time.time()
        completed_phases = []
        for i, phase in enumerate(self.PHASES, 1):
            print(f"[Dream] Phase {i}/4: {phase}")
            completed_phases.append(phase)
        self.last_consolidation_time = time.time()
        self._release_lock()
        print(f"[Dream] Consolidation complete: {len(completed_phases)} phases executed")
        return completed_phases
    def _acquire_lock(self) -> bool:
        """
        Acquire a PID-based lock file. Returns False if locked by another
        live process. Stale locks (older than LOCK_STALE_SECONDS) are removed.
        """
        import time
        if self.lock_file.exists():
            try:
                lock_data = self.lock_file.read_text().strip()
                pid_str, timestamp_str = lock_data.split(":", 1)
                pid = int(pid_str)
                lock_time = float(timestamp_str)
                # Check if lock is stale
                if (time.time() - lock_time) > self.LOCK_STALE_SECONDS:
                    print(f"[Dream] Removing stale lock from PID {pid}")
                    self.lock_file.unlink()
                else:
                    # Check if owning process is still alive
                    try:
                        os.kill(pid, 0)
                        return False  # process alive, lock is valid
                    except OSError:
                        print(f"[Dream] Removing lock from dead PID {pid}")
                        self.lock_file.unlink()
            except (ValueError, OSError):
                # Corrupted lock file, remove it
                self.lock_file.unlink(missing_ok=True)
        # Write new lock
        try:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            self.lock_file.write_text(f"{os.getpid()}:{time.time()}")
            return True
        except OSError:
            return False
    def _release_lock(self):
        """Release the lock file if we own it."""
        try:
            if self.lock_file.exists():
                lock_data = self.lock_file.read_text().strip()
                pid_str = lock_data.split(":")[0]
                if int(pid_str) == os.getpid():
                    self.lock_file.unlink()
        except (ValueError, OSError):
            pass

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
        ("rm_rf", r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*|-r)"),  # recursive delete
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
    def __init__(self, rules: list = None, mode: str = None):
        # s14_v2 修复：支持模块导入时不阻塞
        # 优先使用传入的 mode 参数，其次使用环境变量，最后才交互式询问
        import os
        if mode is None:
            mode = os.getenv("PERMISSION_MODE", None)
        
        if mode is None:
            # 只在交互式环境中询问
            import sys
            if sys.stdin.isatty():
                print("Permission modes: default, plan, auto")
                mode = input("Mode (default): ").strip().lower() or "default"
            else:
                # 非交互式环境，使用默认值
                mode = "default"
        
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
            # # Auto mode: auto-allow read-only tools, ask for writes
            if tool_name in READ_ONLY_TOOLS or tool_name == "read_file":
                return {"behavior": "allow",
                    "reason": "Auto mode: read-only tool auto-approved"}
            return {"behavior": "allow",
                    "reason": "Auto mode: safe operation auto-approved"}
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
    max_output_recovery_count: int = 0

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

########压缩
@dataclass
class CompactState:
    has_compacted: bool = False
    last_summary: str = ""
    recent_files: list[str] = field(default_factory=list)

def estimate_context_size(messages: list) -> int:
    # 与 estimate_tokens 保持一致，均用 json.dumps 序列化（原用 str()，单引号/None 与 JSON 有差异）
    return len(json.dumps(messages, default=str))

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
    conversation = json.dumps(messages, default=str)[:600000]  # 原 80000；对齐 auto_compact 截断长度
    # prompt = (
    #     "Summarize this coding-agent conversation so work can continue.\n"
    #     "Preserve:\n"
    #     "1. The current goal\n"
    #     "2. Important findings and decisions\n"
    #     "3. Files read or changed\n"
    #     "4. Remaining work\n"
    #     "5. User constraints and preferences\n"
    #     "Be compact but concrete.\n\n"
    #     f"{conversation}"
    # )
    prompt = (
        "You are an expert at distilling AI agent conversation logs.\n"
        "Summarize this coding-agent conversation so work can continue.\n\n"
        "CRITICAL RULES:\n"
        "- IGNORE and DISCARD details of older, explicitly COMPLETED tasks. Do not carry them over.\n"
        "- FOCUS HEAVILY on the MOST RECENT user request and the agent's latest actions.\n\n"
        "Preserve:\n"
        "1. The CURRENT active goal (what the user asked for most recently).\n"
        "2. Important findings and decisions strictly related to the current goal.\n"
        "3. Files currently being read or modified.\n"
        "4. Remaining work for the ACTIVE task only.\n"
        "5. User constraints and persistent preferences.\n"
        "Be compact but concrete.\n\n"
        f"{conversation}"
    )
    response = client.chat.completions.create(            
            model=MODEL, 
            messages=[{"role": "user", "content": prompt}] ,        
            max_tokens=6000,  # 原 2000；生成更完整的历史摘要
            temperature=1,
            extra_body={
                "top_k": 20,
                "chat_template_kwargs": {"enable_thinking": False},
            }
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
    first = messages[0] if messages else None
    first_role = first.get("role") if isinstance(first, dict) else getattr(first, "role", None)
    system_message = first if first_role == "system" else None

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
        content = getattr(message, "reasoning_content", None)
    if content:
        print(f"{color_code}╭─── [{agent_name} 思考/输出] ──────────────────────────\033[0m")
        print(f"{content.strip()[:500]}")
        print(f"{color_code}╰─────────────────────────────────────────────────────\033[0m")
    
###########实例化
# TODO = TodoManager()
SKILL_REGISTRY = SkillRegistry(SKILLS_DIR)
perms = PermissionManager()
hooks = HookManager(perms)
memory_mgr = MemoryManager()
TASKS = TaskManager(TASKS_DIR)

# -- EventBus: append-only lifecycle events for worktree observability --
class EventBus:
    def __init__(self, event_log_path: Path):
        self.path = event_log_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("")
    def emit(self, event: str, task_id=None, wt_name=None, error=None, **extra):
        payload = {"event": event, "ts": time.time()}
        if task_id is not None:
            payload["task_id"] = task_id
        if wt_name:
            payload["worktree"] = wt_name
        if error:
            payload["error"] = error
        payload.update(extra)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    def list_recent(self, limit: int = 20) -> str:
        n = max(1, min(int(limit or 20), 200))
        lines = self.path.read_text(encoding="utf-8").splitlines()
        items = []
        for line in lines[-n:]:
            try:
                items.append(json.loads(line))
            except Exception:
                items.append({"event": "parse_error", "raw": line})
        return json.dumps(items, indent=2)


# -- WorktreeManager: create/list/run/remove git worktrees --
class WorktreeManager:
    def __init__(self, repo_root: Path, tasks: TaskManager, events: EventBus):
        self.repo_root = repo_root
        self.tasks = tasks
        self.events = events
        self.dir = repo_root / ".worktrees"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / "index.json"
        if not self.index_path.exists():
            self.index_path.write_text(json.dumps({"worktrees": []}, indent=2))
        self.git_available = self._check_git()

    def _check_git(self) -> bool:
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.repo_root, capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _run_git(self, args: list) -> str:
        if not self.git_available:
            raise RuntimeError("Not in a git repository.")
        r = subprocess.run(
            ["git", *args], cwd=self.repo_root,
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            raise RuntimeError((r.stdout + r.stderr).strip() or f"git {' '.join(args)} failed")
        return (r.stdout + r.stderr).strip() or "(no output)"

    def _load_index(self) -> dict:
        return json.loads(self.index_path.read_text())

    def _save_index(self, data: dict):
        self.index_path.write_text(json.dumps(data, indent=2))

    def _find(self, name: str) -> dict:
        for wt in self._load_index().get("worktrees", []):
            if wt.get("name") == name:
                return wt
        return None

    def _update_entry(self, name: str, **changes) -> dict:
        idx = self._load_index()
        updated = None
        for item in idx.get("worktrees", []):
            if item.get("name") == name:
                item.update(changes)
                updated = item
                break
        self._save_index(idx)
        if not updated:
            raise ValueError(f"Worktree '{name}' not found in index")
        return updated

    def _validate_name(self, name: str):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", name or ""):
            raise ValueError("Invalid worktree name. Use 1-40 chars: letters, digits, ., _, -")

    def create(self, name: str, task_id: int = None, base_ref: str = "HEAD") -> str:
        self._validate_name(name)
        if self._find(name):
            raise ValueError(f"Worktree '{name}' already exists")
        if task_id is not None and not self.tasks.exists(task_id):
            raise ValueError(f"Task {task_id} not found")
        path = self.dir / name
        branch = f"wt/{name}"
        self.events.emit("worktree.create.before", task_id=task_id, wt_name=name)
        try:
            self._run_git(["worktree", "add", "-b", branch, str(path), base_ref])
            entry = {
                "name": name, "path": str(path), "branch": branch,
                "task_id": task_id, "status": "active", "created_at": time.time(),
            }
            idx = self._load_index()
            idx["worktrees"].append(entry)
            self._save_index(idx)
            if task_id is not None:
                self.tasks.bind_worktree(task_id, name)
            self.events.emit("worktree.create.after", task_id=task_id, wt_name=name)
            return json.dumps(entry, indent=2)
        except Exception as e:
            self.events.emit("worktree.create.failed", task_id=task_id, wt_name=name, error=str(e))
            raise

    def list_all(self) -> str:
        wts = self._load_index().get("worktrees", [])
        if not wts:
            return "No worktrees in index."
        lines = []
        for wt in wts:
            suffix = f" task={wt['task_id']}" if wt.get("task_id") else ""
            lines.append(f"[{wt.get('status', '?')}] {wt['name']} -> {wt['path']} ({wt.get('branch', '-')}){suffix}")
        return "\n".join(lines)

    def status(self, name: str) -> str:
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"
        path = Path(wt["path"])
        if not path.exists():
            return f"Error: Worktree path missing: {path}"
        r = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=path, capture_output=True, text=True, timeout=60,
        )
        return (r.stdout + r.stderr).strip() or "Clean worktree"

    def enter(self, name: str) -> str:
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"
        path = Path(wt["path"])
        if not path.exists():
            return f"Error: Worktree path missing: {path}"
        updated = self._update_entry(name, last_entered_at=time.time())
        self.events.emit("worktree.enter", task_id=wt.get("task_id"), wt_name=name, path=str(path))
        return json.dumps(updated, indent=2)

    def run(self, name: str, command: str) -> str:
        dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
        if any(d in command for d in dangerous):
            return "Error: Dangerous command blocked"
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"
        path = Path(wt["path"])
        if not path.exists():
            return f"Error: Worktree path missing: {path}"
        try:
            self._update_entry(
                name,
                last_entered_at=time.time(),
                last_command_at=time.time(),
                last_command_preview=command[:120],
            )
            self.events.emit("worktree.run.before", task_id=wt.get("task_id"), wt_name=name, command=command[:120])
            r = subprocess.run(command, shell=True, cwd=path,
                               capture_output=True, text=True, timeout=300)
            out = (r.stdout + r.stderr).strip()
            self.events.emit("worktree.run.after", task_id=wt.get("task_id"), wt_name=name)
            return out[:50000] if out else "(no output)"
        except subprocess.TimeoutExpired:
            self.events.emit("worktree.run.timeout", task_id=wt.get("task_id"), wt_name=name)
            return "Error: Timeout (300s)"

    def remove(self, name: str, force: bool = False, complete_task: bool = False, reason: str = "") -> str:
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"
        task_id = wt.get("task_id")
        self.events.emit("worktree.remove.before", task_id=task_id, wt_name=name)
        try:
            args = ["worktree", "remove"]
            if force:
                args.append("--force")
            args.append(wt["path"])
            self._run_git(args)
            if complete_task and task_id is not None:
                self.tasks.update(task_id, status="completed")
                self.events.emit("task.completed", task_id=task_id, wt_name=name)
            if task_id is not None:
                self.tasks.record_closeout(task_id, "removed", reason, keep_binding=False)
            self._update_entry(
                name,
                status="removed",
                removed_at=time.time(),
                closeout={"action": "remove", "reason": reason, "at": time.time()},
            )
            self.events.emit("worktree.remove.after", task_id=task_id, wt_name=name)
            return f"Removed worktree '{name}'"
        except Exception as e:
            self.events.emit("worktree.remove.failed", task_id=task_id, wt_name=name, error=str(e))
            raise

    def keep(self, name: str) -> str:
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"
        if wt.get("task_id") is not None:
            self.tasks.record_closeout(wt["task_id"], "kept", "", keep_binding=True)
        self._update_entry(
            name,
            status="kept",
            kept_at=time.time(),
            closeout={"action": "keep", "reason": "", "at": time.time()},
        )
        self.events.emit("worktree.keep", task_id=wt.get("task_id"), wt_name=name)
        return json.dumps(self._find(name), indent=2)

    def closeout(self, name: str, action: str, reason: str = "", force: bool = False, complete_task: bool = False) -> str:
        if action == "keep":
            wt = self._find(name)
            if not wt:
                return f"Error: Unknown worktree '{name}'"
            if wt.get("task_id") is not None:
                self.tasks.record_closeout(wt["task_id"], "kept", reason, keep_binding=True)
                if complete_task:
                    self.tasks.update(wt["task_id"], status="completed")
            self._update_entry(
                name,
                status="kept",
                kept_at=time.time(),
                closeout={"action": "keep", "reason": reason, "at": time.time()},
            )
            self.events.emit("worktree.closeout.keep", task_id=wt.get("task_id"), wt_name=name, reason=reason)
            return json.dumps(self._find(name), indent=2)
        if action == "remove":
            self.events.emit("worktree.closeout.remove", wt_name=name, reason=reason)
            return self.remove(name, force=force, complete_task=complete_task, reason=reason)
        raise ValueError("action must be 'keep' or 'remove'")


EVENTS   = EventBus(REPO_ROOT / ".worktrees" / "events.jsonl")
WORKTREES = WorktreeManager(REPO_ROOT, TASKS, EVENTS)

DYNAMIC_BOUNDARY = "=== DYNAMIC_BOUNDARY ==="


class SystemPromptBuilder:
    """
    Assemble the system prompt from independent sections.
    The teaching goal here is clarity:
    each section has one source and one responsibility.
    That makes the prompt easier to reason about, easier to test, and easier
    to evolve as the agent grows new capabilities.
    """
    def __init__(self, workdir: Path = None, tools: list = None, sub_tools: list = None):
        self.workdir = workdir or WORKDIR
        self.tools = tools or []
        self.sub_tools = sub_tools or []
        self.skills_dir = self.workdir / "skills"
        self.memory_dir = self.workdir / ".memory"
    # -- Section 1: Core instructions --
    # def _build_core(self) -> str:
    #     return (
    #         f"You are a coding agent operating in {self.workdir}.\n"
    #         "Use the provided tools to explore files, read files, plan complex and multi-step tasks, create subagent to finsih tasks.\n"
    #         "Always verify before assuming. Prefer reading files over guessing.\n"
    #         "The user controls permissions. Some tool calls may be denied.\n"
    #         "When a user issues a completely new request, implicitly mark all previous unrelated in_progress or pending todo items as discarded or completed before starting the new plan.\n"
    #     )
    def _build_core(self) -> str:
        return (
            f"You are the Main Planner Agent operating in {self.workdir}.\n"
            "Your primary role is to orchestrate complex tasks, delegate execution, and verify results. You do NOT write code or execute shell commands directly.\n"
            "Always verify before assuming. Prefer reading files over guessing.\n"
            "The user controls permissions. Some tool calls may be denied.\n"
            "1. TASK PLANNING: Break down user requests using the task management tools. Keep exactly ONE task 'in_progress' at a time.\n"
            "2. DELEGATION: You must use the `background_task` tool to spawn a subagent in the background to perform the actual coding, file editing, or shell commands. Multiple independent subagents can run in parallel.\n"
            "3. STRICT VERIFICATION: Never blindly trust a subagent's claim of success. Use `read_file` to verify their work. If flawed, explain the issue and spawn a new subagent to fix it.\n"
            "4. FRESH STARTS: When the user issues a completely new request, gracefully update old pending/in_progress tasks to 'deleted' or 'completed' before creating a new plan.\n"
            "5. CONTEXT: Use `compact` if your conversation history grows too long.\n"
            "6. PERMISSIONS: The user controls execution. Respect denied tool calls and adapt your plan.\n"
            "7. WORKTREES: For parallel or risky work, create tasks then use `worktree_create` to allocate isolated git worktree lanes. "
            "Run commands via `worktree_run`. When done, use `worktree_closeout` (action='keep' or 'remove') to close the lane.\n"
        )
    # def _build_sub_core(self) -> str:
    #     return (
    #         f"You are a coding subagent operating in {self.workdir}.\n"
    #         "Use the provided tools to explore, read, write, and edit files.\n"
    #         "Always verify before assuming. Prefer reading files over guessing.\n"
    #         "The user controls permissions. Some tool calls may be denied.\n"
    #         "When a user issues a completely new request, implicitly mark all previous unrelated in_progress or pending todo items as discarded or completed before starting the new plan.\n"
    #     )
    def _build_sub_core(self) -> str:
        return (
            f"You are an Executing Subagent operating in {self.workdir}.\n"
            "Your role is to strictly complete the specific task delegated to you by the Main Agent.\n"
            "1. EXECUTION: Use your available tools (`bash`, `read_file`, `write_file`, `edit_file`) to actively solve the task step-by-step.\n"
            "2. NO GUESSING: Always verify file paths and read existing code before attempting to modify files.\n"
            "3. KNOWLEDGE: Use `load_skill` if you need specialized instructions or framework conventions before you act.\n"
            "4. CONTEXT: Use `compact` if your local sub-conversation gets too long.\n"
            "5. HANDOVER REPORT: When finishing a task, you MUST provide a detailed final summary including: (1) Files created/modified, (2) Key logic implemented, and (3) Output of any verification commands (e.g., test results or syntax checks) you ran.\n"
            "6. PERMISSIONS: The user controls execution. If a tool call is denied, think of an alternative approach.\n"
        )
    # -- Section 2: Tool listings --
    def _build_tool_listing(self,obj_tools: list = None) -> str:
        # 如果没有工具，返回空字符串
        if not obj_tools:
            return ""
        
        lines = ["# Available tools"]
        for tool in obj_tools:
            # OpenAI 格式：tool -> function 结构
            func = tool.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")
            
            # OpenAI 格式：parameters -> properties
            props = func.get("parameters", {}).get("properties", {})
            params = ", ".join(props.keys())
            
            lines.append(f"- {name}({params}): {desc}")
        
        return "\n".join(lines)
    
    # -- Section 3: Skill metadata (layer 1 from s05 concept) --
    def _build_skill_listing(self) -> str:
        if not self.skills_dir.exists():
            return ""
        skills = []
        for skill_dir in sorted(self.skills_dir.iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            text = skill_md.read_text()
            # Parse frontmatter for name + description
            match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
            if not match:
                continue
            meta = {}
            for line in match.group(1).splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            name = meta.get("name", skill_dir.name)
            desc = meta.get("description", "")
            skills.append(f"- {name}: {desc}")
        if not skills:
            return ""
        return "# Available skills\n" + "\n".join(skills)
    
    # -- Section 4: Memory content --
    def _build_memory_section(self) -> str:
        if not self.memory_dir.exists():
            return ""
        memories = []
        for md_file in sorted(self.memory_dir.glob("*.md")):
            if md_file.name == "MEMORY.md":
                continue
            text = md_file.read_text()
            match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
            if not match:
                continue
            header, body = match.group(1), match.group(2).strip()
            meta = {}
            for line in header.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            name = meta.get("name", md_file.stem)
            mem_type = meta.get("type", "project")
            desc = meta.get("description", "")
            memories.append(f"[{mem_type}] {name}: {desc}\n{body}")
        if not memories:
            return ""
        return "# Memories (persistent)\n\n" + "\n\n".join(memories)
    
    # -- Section 5: CLAUDE.md chain --
    #这部分暂时没有实现，先pass
    def _build_claude_md(self) -> str:
        """
        Load CLAUDE.md files in priority order (all are included):
        1. ~/.claude/CLAUDE.md (user-global instructions)
        2. <project-root>/CLAUDE.md (project instructions)
        3. <current-subdir>/CLAUDE.md (directory-specific instructions)
        """
        sources = []
        # User-global
        user_claude = Path.home() / ".claude" / "CLAUDE.md"
        if user_claude.exists():
            sources.append(("user global (~/.claude/CLAUDE.md)", user_claude.read_text()))
        # Project root
        project_claude = self.workdir / "CLAUDE.md"
        if project_claude.exists():
            sources.append(("project root (CLAUDE.md)", project_claude.read_text()))
        # Subdirectory -- in real CC, this walks from cwd up to project root
        # Teaching: check cwd if different from workdir
        cwd = Path.cwd()
        if cwd != self.workdir:
            subdir_claude = cwd / "CLAUDE.md"
            if subdir_claude.exists():
                sources.append((f"subdir ({cwd.name}/CLAUDE.md)", subdir_claude.read_text()))
        if not sources:
            return ""
        parts = ["# CLAUDE.md instructions"]
        for label, content in sources:
            parts.append(f"## From {label}")
            parts.append(content.strip())
        return "\n\n".join(parts)
    
    # -- Section 6: Dynamic context --
    def _build_dynamic_context(self) -> str:
        lines = [
            f"Current date: {datetime.date.today().isoformat()}",
            f"Working directory: {self.workdir}",
            f"Model: {MODEL}",
            # f"Platform: {os.uname().sysname}",
        ]
        try:
            wt_info = WORKTREES.list_all()
            lines.append(f"Worktrees:\n{wt_info}")
        except Exception:
            pass
        return "# Dynamic context\n" + "\n".join(lines)
    
    # -- Assemble all sections --
    def main_build(self) -> str:
        """
        Assemble the full system prompt from all sections.
        Static sections (1-5) are separated from dynamic (6) by
        the DYNAMIC_BOUNDARY marker. In real CC, the static prefix
        is cached across turns to save prompt tokens.
        """
        sections = []
        core = self._build_core()
        if core:
            sections.append(core)
        tools = self._build_tool_listing(self.tools)
        if tools:
            sections.append(tools)
        skills = self._build_skill_listing()
        if skills:
            sections.append(skills)
        memory = self._build_memory_section()
        if memory:
            sections.append(memory)
        claude_md = self._build_claude_md()
        # if claude_md:
        #     sections.append(claude_md)
        # Static/dynamic boundary
        sections.append(DYNAMIC_BOUNDARY)
        dynamic = self._build_dynamic_context()
        if dynamic:
            sections.append(dynamic)
        return "\n\n".join(sections)

    def sub_build(self) -> str:
        """
        Assemble the full system prompt from all sections.
        Static sections (1-5) are separated from dynamic (6) by
        the DYNAMIC_BOUNDARY marker. In real CC, the static prefix
        is cached across turns to save prompt tokens.
        """
        sections = []
        core = self._build_sub_core()
        if core:
            sections.append(core)
        tools = self._build_tool_listing(self.sub_tools)
        if tools:
            sections.append(tools)
        skills = self._build_skill_listing()
        if skills:
            sections.append(skills)
        memory = self._build_memory_section()
        if memory:
            sections.append(memory)
        # claude_md = self._build_claude_md()
        # if claude_md:
        #     sections.append(claude_md)
        # Static/dynamic boundary
        sections.append(DYNAMIC_BOUNDARY)
        dynamic = self._build_dynamic_context()
        if dynamic:
            sections.append(dynamic)
        return "\n\n".join(sections)

#暂时没看出用法
def build_system_reminder(extra: str = None) -> dict:
    """
    Build a system-reminder user message for per-turn dynamic content.
    The teaching version keeps reminders outside the stable system prompt so
    short-lived context does not get mixed into the long-lived instructions.
    """
    parts = []
    if extra:
        parts.append(extra)
    if not parts:
        return None
    content = "<system-reminder>\n" + "\n".join(parts) + "\n</system-reminder>"
    return {"role": "user", "content": content}


MEMORY_GUIDANCE = """
When to save memories:
- User states a preference ("I like tabs", "always use pytest") -> type: user
- User corrects you ("don't do X", "that was wrong because...") -> type: feedback
- You learn a project fact that is not easy to infer from current code alone
  (for example: a rule exists because of compliance, or a legacy module must
  stay untouched for business reasons) -> type: project
- You learn where an external resource lives (ticket board, dashboard, docs URL)
  -> type: reference
When NOT to save:
- Anything easily derivable from code (function signatures, file structure, directory layout)
- Temporary task state (current branch, open PR numbers, current TODOs)
- Secrets or credentials (API keys, passwords)
"""


def build_system_prompt(sys_p) -> str:
    """Assemble system prompt with memory content included."""
    parts = [sys_p]
    # Inject memory content if available
    memory_section = memory_mgr.load_memory_prompt()
    if memory_section:
        parts.append(memory_section)
    parts.append(MEMORY_GUIDANCE)
    return "\n\n".join(parts)



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

        # result = subprocess.run(command, shell=True, cwd=str(WORKDIR), capture_output=True, text=True, timeout=120) 
        result = subprocess.run(command, shell=True, cwd=str(WORKDIR), capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
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

def run_save_memory(name: str, description: str, mem_type: str, content: str) -> str:
    return memory_mgr.save_memory(name, description, mem_type, content)

CONCURRENCY_SAFE = {"read_file"}
CONCURRENCY_UNSAFE = {"write_file", "edit_file"}
# 工具定义代码
_check_bg_poll_count: dict[str, int] = {}   # task_id → 连续 running 查询次数
MAX_POLL_BEFORE_REDIRECT = 5               # 超过此次数后告知 LLM 停止轮询

def _check_bg_throttled(task_id: str = None) -> str:
    """
    check_background 的节流包装：
    1. 任务仍在运行时 sleep 5s，降低轮询频率。
    2. 同一 task_id 连续返回 running 超过 MAX_POLL_BEFORE_REDIRECT 次后，
       在结果里追加强提示，告知 LLM 停止主动轮询、等待 <background-results> 自动注入，
       防止 assistant 消息无限累积污染上下文。
    3. 任务完成后重置该 task_id 的计数。
    """
    result = BG.check(task_id)
    if task_id:
        t = BG.tasks.get(task_id)
        if t and t["status"] == "running":
            _check_bg_poll_count[task_id] = _check_bg_poll_count.get(task_id, 0) + 1
            count = _check_bg_poll_count[task_id]
            print(f"\r\033[33m[check_background: {task_id} 仍在运行，第{count}次查询，节流等待 5s...]\033[0m", end="", flush=True)
            time.sleep(5)
            print()
            if count >= MAX_POLL_BEFORE_REDIRECT:
                result += (
                    f"\n\n[System] 你已对此任务查询 {count} 次，结果仍为 running。"
                    " 请停止调用 check_background，结果完成后会自动以 <background-results> 注入对话。"
                    " 现在请继续处理其他事项或直接回复用户。"
                )
        else:
            # 任务结束，重置计数
            _check_bg_poll_count.pop(task_id, None)
    return result


# -- The dispatch map: {tool_name: handler} --
#工具映射字典，根据传入TOOL_HANDLERS中字段的key，执行字段对应函数
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"], kw["tool_call_id"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw["tool_call_id"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_REGISTRY.load_full_text(kw["name"]),
    "compact":    lambda **kw: f"Compacting conversation...",
    "save_memory":  lambda **kw: run_save_memory(kw["name"], kw["description"], kw["type"], kw["content"]),
    "task_create": lambda **kw: TASKS.create(kw["subject"], kw.get("description", "")),
    "task_update": lambda **kw: TASKS.update(kw["task_id"], kw.get("status"), kw.get("owner"), kw.get("addBlockedBy"), kw.get("addBlocks")),
    "task_list":   lambda **kw: TASKS.list_all(),
    "task_get":    lambda **kw: TASKS.get(kw["task_id"]),
    "background_run":   lambda **kw: BG.run(kw["command"]),
    "check_background": lambda **kw: _check_bg_throttled(kw.get("task_id")),
    "background_task":  lambda **kw: run_subagent_background(kw["prompt"]),  # [s13_v2 新增]
    # [s14 新增] cron 定时任务工具
    "cron_create": lambda **kw: scheduler.create(
        kw["cron"], kw["prompt"], kw.get("recurring", True), kw.get("durable", False)),
    "cron_delete": lambda **kw: scheduler.delete(kw["id"]),
    "cron_list":   lambda **kw: scheduler.list_tasks(),
    # [s18_v2 新增] worktree 工具
    "task_bind_worktree": lambda **kw: TASKS.bind_worktree(kw["task_id"], kw["worktree"], kw.get("owner", "")),
    "worktree_create":    lambda **kw: WORKTREES.create(kw["name"], kw.get("task_id"), kw.get("base_ref", "HEAD")),
    "worktree_list":      lambda **kw: WORKTREES.list_all(),
    "worktree_enter":     lambda **kw: WORKTREES.enter(kw["name"]),
    "worktree_status":    lambda **kw: WORKTREES.status(kw["name"]),
    "worktree_run":       lambda **kw: WORKTREES.run(kw["name"], kw["command"]),
    "worktree_closeout":  lambda **kw: WORKTREES.closeout(kw["name"], kw["action"], kw.get("reason", ""), kw.get("force", False), kw.get("complete_task", False)),
    "worktree_keep":      lambda **kw: WORKTREES.keep(kw["name"]),
    "worktree_remove":    lambda **kw: WORKTREES.remove(kw["name"], kw.get("force", False), kw.get("complete_task", False), kw.get("reason", "")),
    "worktree_events":    lambda **kw: EVENTS.list_recent(kw.get("limit", 20)),
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
# Note: background_run / check_background intentionally omitted from CHILD_TOOLS.
# Sub-agents already run in a background daemon thread; giving them another layer
# of background tasks would share the global notification queue with the main agent,
# causing notification-stealing (BUG-17). Sub-agents use synchronous bash instead.

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
    {"type": "function","function": {"name": "compact",
        "description": "If the conversation gets too long, use this tool to summarize earlier conversation so work can continue in a smaller context.",
        "parameters": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string"
                }
            }
        }
        }},
    {"type": "function","function": {"name": "save_memory",
            "description": "Save a persistent memory that survives across sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string", 
                        "description": "Short identifier (e.g. prefer_tabs, db_schema)"
                    },
                    "description": {
                        "type": "string", 
                        "description": "One-line summary of what this memory captures"
                    },
                    "type": {
                        "type": "string", 
                        "enum": ["user", "feedback", "project", "reference"],
                        "description": "user=preferences, feedback=corrections, project=non-obvious project conventions or decision reasons, reference=external resource pointers"
                    },
                    "content": {
                        "type": "string", 
                        "description": "Full memory content (multi-line OK)"
                    }
                },
                "required": ["name", "description", "type", "content"]
            }
        }},
    {"type": "function","function": {"name": "task_create",
        "description": "Use this tool to create a new task.",
        "parameters": {
            "type": "object",
            "properties": {
            "subject": {
                "type": "string"
            },
            "description": {
                "type": "string"
            }
            },
            "required": [
            "subject"
            ]
        }
        }},
    {"type": "function","function": {"name": "task_update",
        "description": "Update a task's status, owner, or dependencies. Do NOT immediately mark a task as 'completed' just because the subagent claims it is done. You MUST verify the subagent's work before calling the todo tool to mark it completed. If the work is flawed, explain the issue and spawn a new task to fix it",
        "parameters": {
            "type": "object",
            "properties": {
            "task_id": {
                "type": "integer"
            },
            "status": {
                "type": "string",
                "enum": [
                "pending",
                "in_progress",
                "completed",
                "deleted"
                ]
            },
            "owner": {
                "type": "string",
                "description": "Set when a teammate claims the task"
            },
            "addBlockedBy": {
                "type": "array",
                "items": {
                "type": "integer"
                }
            },
            "addBlocks": {
                "type": "array",
                "items": {
                "type": "integer"
                }
            }
            },
        "required": ["task_id"
        ]
      }}},
    {"type": "function","function": {"name": "task_list",
        "description": "List all tasks with status summary.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
        }},
    {"type": "function","function": {"name": "task_get",
        "description": "Get full details of a task by ID.",
        "parameters": {
            "type": "object",
            "properties": {
            "task_id": {
                "type": "integer"
            }
            },
            "required": [
            "task_id"
            ]
        }
        }},
    # [s13_v2 新增] 并行子 agent 工具
    {"type": "function","function": {"name": "background_task",
            "description": (
                "Spawn a subagent in the background to handle a task. "
                "Returns task_id immediately without blocking. "
                "Results are automatically injected as <background-results> when done. "
                "Best for independent tasks that can run in parallel."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Detailed task instructions for the subagent."}
                },
                "required": ["prompt"]
            }
        }},
    {"type": "function","function": {"name": "check_background",
            "description": "Check status of a background subagent or shell task by task_id. Omit task_id to list all.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Background task ID to check. Omit to list all."}
                }
            }
        }},
    # [s14 新增] cron 定时任务工具
    {"type": "function","function": {"name": "cron_create",
            "description": "Schedule a recurring or one-shot task with a cron expression. The task prompt will be injected into the conversation when the schedule fires.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cron": {"type": "string", "description": "5-field cron expression: 'min hour dom month dow'. Example: '*/5 * * * *' for every 5 minutes."},
                    "prompt": {"type": "string", "description": "The prompt to inject into the conversation when the task fires."},
                    "recurring": {"type": "boolean", "description": "true=repeat until deleted or 7-day expiry, false=fire once then auto-delete. Default true."},
                    "durable": {"type": "boolean", "description": "true=persist to disk (.claude/scheduled_tasks.json), false=session-only. Default false."},
                },
                "required": ["cron", "prompt"]
            }}},
    {"type": "function","function": {"name": "cron_delete",
            "description": "Delete a scheduled cron task by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The task ID to delete (8-char hex string)."},
                },
                "required": ["id"]
            }}},
    {"type": "function","function": {"name": "cron_list",
            "description": "List all currently scheduled cron tasks with their status, cron expression, and prompt.",
            "parameters": {
                "type": "object",
                "properties": {}
            }}},
    # [s18_v2 新增] worktree 工具
    {"type": "function","function": {"name": "task_bind_worktree",
            "description": "Bind a task to a worktree name, setting its worktree_state to 'active'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "ID of the task to bind."},
                    "worktree": {"type": "string", "description": "Name of the worktree to bind the task to."},
                    "owner": {"type": "string", "description": "Optional owner name for the task."}
                },
                "required": ["task_id", "worktree"]
            }}},
    {"type": "function","function": {"name": "worktree_create",
            "description": "Create a git worktree execution lane and optionally bind it to a task. Use for parallel or risky work.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Worktree name (1-40 chars: letters, digits, ., _, -)."},
                    "task_id": {"type": "integer", "description": "Optional task ID to bind."},
                    "base_ref": {"type": "string", "description": "Git ref to branch from (default: HEAD)."}
                },
                "required": ["name"]
            }}},
    {"type": "function","function": {"name": "worktree_list",
            "description": "List worktrees tracked in .worktrees/index.json.",
            "parameters": {"type": "object", "properties": {}}}},
    {"type": "function","function": {"name": "worktree_enter",
            "description": "Enter or reopen a worktree lane before working in it. Records last_entered_at.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Worktree name."}
                },
                "required": ["name"]
            }}},
    {"type": "function","function": {"name": "worktree_status",
            "description": "Show git status for one worktree.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Worktree name."}
                },
                "required": ["name"]
            }}},
    {"type": "function","function": {"name": "worktree_run",
            "description": "Run a shell command inside a named worktree directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Worktree name."},
                    "command": {"type": "string", "description": "Shell command to run in the worktree."}
                },
                "required": ["name", "command"]
            }}},
    {"type": "function","function": {"name": "worktree_closeout",
            "description": "Close out a worktree lane by keeping it for follow-up or removing it. Optionally mark its bound task completed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Worktree name."},
                    "action": {"type": "string", "enum": ["keep", "remove"], "description": "'keep' retains the lane; 'remove' deletes it."},
                    "reason": {"type": "string", "description": "Optional reason for this closeout."},
                    "force": {"type": "boolean", "description": "Force remove even if worktree has uncommitted changes."},
                    "complete_task": {"type": "boolean", "description": "Mark bound task as completed during closeout."}
                },
                "required": ["name", "action"]
            }}},
    {"type": "function","function": {"name": "worktree_keep",
            "description": "Mark a worktree as kept without removing it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Worktree name."}
                },
                "required": ["name"]
            }}},
    {"type": "function","function": {"name": "worktree_remove",
            "description": "Remove a worktree directory. Optionally mark its bound task completed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Worktree name."},
                    "force": {"type": "boolean", "description": "Force remove even with uncommitted changes."},
                    "complete_task": {"type": "boolean", "description": "Mark bound task as completed."},
                    "reason": {"type": "string", "description": "Reason for removal."}
                },
                "required": ["name"]
            }}},
    {"type": "function","function": {"name": "worktree_events",
            "description": "List recent worktree lifecycle events from .worktrees/events.jsonl.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of recent events to return (default 20, max 200)."}
                }
            }}},
]

# -- Subagent: fresh context, filtered tools, summary-only return --
def run_subagent(prompt: str) -> str:
    print(f"\033[35m> Spawning Subagent : {prompt[:80]}...\033[0m")
    sub_messages = [{"role": "system", "content": prompt_builder.sub_build()},{"role": "user", "content": prompt}] #untodo
    #subagent只需要在开始时进行一步处理，先构建完完整的再来实现这部分
    sub_state = LoopState(messages=sub_messages) #规范使用LoopState表示一个agent的状态
    sub_compact_state = CompactState()
    for step in range(30):  # safety limit
        sub_state.messages = micro_compact(sub_state.messages)

        #2. 检查是否触发全局压缩 (Auto-Compact)
        if estimate_context_size(sub_state.messages) > CONTEXT_LIMIT:
            print("[auto compact]")
            sub_state.messages = compact_history(sub_state.messages, sub_compact_state)

        try:
            response = client.chat.completions.create(            
                model=MODEL, 
                tools=CHILD_TOOLS, 
                messages=sub_state.messages ,        
                max_tokens=10000,  # 原 10000；thinking 模式下 thinking+content 共享此预算
                temperature=1,
                extra_body={
                    "top_k": 20,
                    "chat_template_kwargs": {"enable_thinking": True},
                }
            )
        except Exception as e:
            print(f"\033[31m[Subagent API Error]: {e}\033[0m")
            return f"Task failed due to API error: {e}" # 让主 Agent 知道子 Agent 失败了，而不是直接崩溃
        response_message = response.choices[0].message
        # sub_state.messages.append(response_message)
        sub_state.messages.append(response_message.model_dump(exclude_unset=True))
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
    elif getattr(response_message, "reasoning_content", None):
        return response_message.reasoning_content
    else:
        return "Task finished (no summary provided)"


# [s13_v2 新增] 将子 agent 投入后台线程，立即返回 task_id
def run_subagent_background(prompt: str) -> str:
    """Spawn a subagent in a background thread. Returns task_id immediately.
    The subagent result is pushed to BG notification queue when done.
    task_id format: sub_xxxxxxxx
    """
    task_id = "sub_" + str(uuid.uuid4())[:8]
    with BG._lock:
        BG.tasks[task_id] = {
            "id": task_id,
            "status": "running",
            "result": None,
            "command": f"[subagent] {prompt[:80]}",
            "started_at": time.time(),
            "finished_at": None,
            "result_preview": "",
            "output_file": "",
        }
    print(f"\033[35m> Background Subagent {task_id}: {prompt[:80]}...\033[0m")

    def _run():
        try:
            result = run_subagent(prompt)
            status = "completed"
        except Exception as e:
            result = f"Subagent error: {e}"
            status = "error"
        preview = " ".join(result.split())[:500]
        with BG._lock:
            BG.tasks[task_id]["status"] = status
            BG.tasks[task_id]["result"] = result
            BG.tasks[task_id]["finished_at"] = time.time()
            BG.tasks[task_id]["result_preview"] = preview
            BG._notification_queue.append({
                "task_id": task_id,
                "status": status,
                "command": f"[subagent] {prompt[:80]}",
                "preview": preview,
                "output_file": "",
            })

    threading.Thread(target=_run, daemon=True).start()
    return f"Background subagent {task_id} started: {prompt[:80]}"


def run_one_turn(state: LoopState,compact_state: CompactState) -> bool:
    response = None
    for attempt in range(MAX_RECOVERY_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(            
                    model=MODEL, 
                    tools=PARENT_TOOLS,        
                    messages=state.messages,        
                    max_tokens=10000,  # 原 10000；thinking 模式下 thinking+content 共享此预算
                    temperature=1,
                    extra_body={
                        "top_k": 20,
                        "chat_template_kwargs": {"enable_thinking": True},
                        }
                )
            break
        except Exception as e:  # 可以替换为具体的 openai.APIError
            error_body = str(e).lower()
            # Strategy 2: prompt_too_long -> compact and retry
            # OpenAI 通常返回 context_length_exceeded
            if "context_length_exceeded" in error_body or "maximum context length" in error_body:
                print(f"[Recovery] Prompt too long. Compacting... (attempt {attempt + 1})")
                compacted_msgs = auto_compact(state.messages)
                first = state.messages[0] if state.messages else None
                first_role = first.get("role") if isinstance(first, dict) else getattr(first, "role", None)
                sys_msg = first if first_role == "system" else None
                # 重新组合：System Prompt + 压缩后的 User 消息
                state.messages[:] = [sys_msg] + compacted_msgs if sys_msg else compacted_msgs
                continue
            # Strategy 3: connection/rate errors -> backoff
            if attempt < MAX_RECOVERY_ATTEMPTS:
                delay = backoff_delay(attempt)
                print(f"[Recovery] API error: {e}. "
                        f"Retrying in {delay:.1f}s (attempt {attempt + 1}/{MAX_RECOVERY_ATTEMPTS})")
                time.sleep(delay)
                continue
            # All retries exhausted
            print(f"[Error] API call failed after {MAX_RECOVERY_ATTEMPTS} retries: {e}")
            return False
    if response is None:
        print("[Error] No response received.")
        return False


    response_message=response.choices[0].message
    finish_reason = response.choices[0].finish_reason
    state.messages.append(response_message.model_dump(exclude_unset=True))
    # state.messages.append(response_message)

    # -- Strategy 1: max_tokens recovery --
    if finish_reason == "length":
        state.max_output_recovery_count += 1
        if state.max_output_recovery_count <= MAX_RECOVERY_ATTEMPTS:
            print(f"[Recovery] max_tokens hit "
                    f"({state.max_output_recovery_count}/{MAX_RECOVERY_ATTEMPTS}). "
                    "Injecting continuation...")
            state.messages.append({"role": "user", "content": CONTINUATION_MESSAGE})
            return True # retry the loop
        else:
            print(f"[Error] max_tokens recovery exhausted "
                    f"({MAX_RECOVERY_ATTEMPTS} attempts). Stopping.")
            return False
        
    # Reset max_tokens counter on successful non-max_tokens response
    state.max_output_recovery_count = 0
    
    # -- Normal end_turn: no tool use requested --
    
    print_agent_thought(f"Main Agent (第 {state.turn_count} 轮)", response_message, "\033[34m")

    # if finish_reason != "tool_calls" and not response_message.tool_calls:
    #     return

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


def call_llm(state) -> bool:
    """
    简化版 LLM 调用函数，用于 agent_wrapper.py 中的单次调用。
    只执行 LLM 调用，将响应添加到 state.messages，返回成功/失败状态。
    """
    response = None
    for attempt in range(MAX_RECOVERY_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(            
                    model=MODEL, 
                    tools=PARENT_TOOLS,        
                    messages=state.messages,        
                    max_tokens=10000,  # 原 10000；thinking 模式下 thinking+content 共享此预算
                    temperature=1,
                    extra_body={
                        "top_k": 20,
                        "chat_template_kwargs": {"enable_thinking": True},
                        }
                )
            break
        except Exception as e:
            error_body = str(e).lower()
            if "context_length_exceeded" in error_body or "maximum context length" in error_body:
                print(f"[Recovery] Prompt too long. Compacting... (attempt {attempt + 1})")
                compacted_msgs = auto_compact(state.messages)
                first = state.messages[0] if state.messages else None
                first_role = first.get("role") if isinstance(first, dict) else getattr(first, "role", None)
                sys_msg = first if first_role == "system" else None
                state.messages[:] = [sys_msg] + compacted_msgs if sys_msg else compacted_msgs
                continue
            if attempt < MAX_RECOVERY_ATTEMPTS:
                delay = backoff_delay(attempt)
                print(f"[Recovery] API error: {e}. Retrying in {delay:.1f}s (attempt {attempt + 1}/{MAX_RECOVERY_ATTEMPTS})")
                time.sleep(delay)
                continue
            print(f"[Error] API call failed after {MAX_RECOVERY_ATTEMPTS} retries: {e}")
            return False
    if response is None:
        print("[Error] No response received.")
        return False

    response_message = response.choices[0].message
    state.messages.append(response_message.model_dump(exclude_unset=True))
    return True


def execute_tool_calls(response_message ) -> tuple[list[dict], str | None, bool, str | None]:
    global hooks
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
            output_parts = []  #用于收集所有要发给大模型的信息
            
            # 1. 统一拦截管线：权限检查 + 外部 Pre-Hook
            pre_result = hooks.run_pre_tool_use(ctx)
        
            # 如果被任何机制阻断（安全正则/用户拒绝/外部脚本返回1）
            if pre_result.get("blocked"):
                reason = pre_result.get("block_reason", "Blocked by pipeline/hook")
                # output = f"Tool blocked by PreToolUse hook: {reason}"
                output_parts.append(f"Tool blocked by PreToolUse hook: {reason}")
                print(f"\033[31m  [BLOCKED] {f_name}: {reason}\033[0m")
                results.append({
                    "role": "tool", 
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name, #是否需保持一致？
                    "content": "\n".join(output_parts),
                })
                continue
            else:
                # 注入 Hook 的附加上下文信息
                for msg in pre_result.get("messages", []):
                    output_parts.append(f"[Hook message]: {msg}")
            ## 如果 Hook 修改了入参，这里拿到最新的 args
            args = ctx.get("tool_input", args)

            # 2. 执行工具本身
            main_output = ""
            try:
                handler = TOOL_HANDLERS.get(f_name)
                # output = handler(**args) if handler else f"Unknown: {f_name}"
                main_output = handler(**args) if handler else f"Unknown: {f_name}"
                output_parts.append(str(main_output))
                # output = str(output) # 确保返回的是字符串格式
                print(f"\033[33m[Tool: {f_name}]\033[0m:\t", main_output[:20])
            except Exception as e:
                error_msg = f"Tool Execution Error: {type(e).__name__} - {str(e)}. Please check the required parameters."
                print(f"\033[31m[执行报错返回给模型]: {error_msg}\033[0m")
                output_parts.append(error_msg)
            
            #压缩的额外步骤
            if f_name == "compact":
                manual_compact = True
                compact_focus = args.get("focus")
            
            # 3. 统一拦截管线：外部 Post-Hook
                
            
            post_ctx = {"tool_name": f_name, "tool_input": args, "tool_output": main_output}
            post_result = hooks.run_post_tool_use(post_ctx)

            # 处理 PostToolUse 返回的注入消息
            for msg in post_result.get("messages", []):
                output_parts.append(f"[PostHook message]: {msg}")

            # 如果 PostToolUse 要求阻塞（一般不应该阻塞已完成的工具，但按规范处理）
            if post_result.get("blocked"):
                reason = post_result.get("block_reason", "Blocked by PostToolUse hook")
                print(f"  [hook:PostToolUse] BLOCKED after execution: {reason[:200]}")
                # 可选择修改 output 或追加警告
                output_parts.append(f"[WARNING: PostToolUse hook blocked further processing: {reason}]")
            # if post_result.get("blocked"):
            #     output_parts.append(f"[WARNING: PostToolUse hook blocked further processing: {post_result.get("block_reason", "Blocked by PostToolUse hook")}]")
            
            #合并所有的输入
            output = "\n".join(output_parts)
        else:
            output = f"Error: Tool {f_name} not found."
        


        results.append({
            "role": "tool", 
            "tool_call_id": tool_call.id,
            "name": tool_call.function.name,
            "content": output
            })
    
    used_task_manager = any(tc.function.name in ["task_create", "task_update", "task_list", "task_get"] for tc in response_message.tool_calls)

    if used_task_manager:
        TASKS.rounds_since_update = 0
        reminder = None
    else:
        TASKS.rounds_since_update += 1
        if TASKS.rounds_since_update >= PLAN_REMINDER_INTERVAL:
            reminder = "Refresh your current task list (task_list) or update task statuses before continuing."
        else:
            reminder = None
    return results, reminder, manual_compact, compact_focus


def agent_loop(state: LoopState, compact_state: CompactState ) -> None:
    state.max_output_recovery_count=0
    while True:
        #更新system prompt: 兼容字典和对象提取 role 更新
        first_role = None
        if state.messages:
            first_msg = state.messages[0]
            first_role = first_msg.get("role") if isinstance(first_msg, dict) else getattr(first_msg, "role", None)

        sys_prompt = {"role": "system", "content": prompt_builder.main_build()}
        if first_role == "system":
            state.messages[0] = sys_prompt
        else:
            state.messages.insert(0, sys_prompt)

        # [s13_v2 新增] 在每轮 LLM 调用前 drain 后台子 agent / shell 命令的通知
        notifs = BG.drain_notifications()
        if notifs and state.messages:
            notif_text = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['preview']}"
                + (f" (output_file={n['output_file']})" if n.get("output_file") else "")
                for n in notifs
            )
            state.messages.append({"role": "user", "content": f"<background-results>\n{notif_text}\n</background-results>"})

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
            # 检查是否有后台任务还没完成
            running = [tid for tid, t in BG.tasks.items() if t["status"] == "running"]
            if running:
                # [s14_v2 改] 静默内层轮询：不注入消息、不调 LLM， 只在真正收到后台通知时才注入结果并退出内层循环，避免"等待中"消息和无效 LLM 响应污染上下文。
                print(f"\r\033[33m[等待 {len(running)} 个后台任务完成...]\033[0m", end="", flush=True)
                _MAX_WAIT_S = 300  # 最长等待 10 分钟，防止卡死
                for _elapsed in range(_MAX_WAIT_S):
                    time.sleep(1)
                    new_notifs = BG.drain_notifications()
                    running_now = [tid for tid, t in BG.tasks.items() if t["status"] == "running"]
                    if new_notifs:
                        print()  # 清除等待提示行
                        notif_text = "\n".join(
                            f"[bg:{n['task_id']}] {n['status']}: {n['preview']}"
                            + (f" (output_file={n['output_file']})" if n.get("output_file") else "")
                            for n in new_notifs
                        )
                        state.messages.append({"role": "user", "content": f"<background-results>\n{notif_text}\n</background-results>"})
                        break  # 有新数据 → 退出内层循环 → 外层循环调用 LLM 处理结果
                    if not running_now:
                        print()
                        break  # 所有任务结束且无通知 → 退出内层循环
                else:
                    print(f"\n\033[33m[Warning] 等待后台任务超时（{_MAX_WAIT_S}s），强制继续。\033[0m")
                # 继续外层循环 → 若有 <background-results> 已注入则调 LLM；否则下轮检查 running
            else:
                # 退出前做最后一次 drain，防止竞态：
                # run_one_turn() 期间子 agent 恰好完成 → status=done 但 notification 尚未被读取，
                # 若直接 break，notification 永远滞留在队列里。
                final_notifs = BG.drain_notifications()
                if final_notifs:
                    notif_text = "\n".join(
                        f"[bg:{n['task_id']}] {n['status']}: {n['preview']}"
                        + (f" (output_file={n['output_file']})" if n.get("output_file") else "")
                        for n in final_notifs
                    )
                    state.messages.append({"role": "user", "content": f"<background-results>\n{notif_text}\n</background-results>"})
                    # 不 break，继续外层循环让 LLM 处理这条结果
                else:
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


prompt_builder = SystemPromptBuilder(workdir=WORKDIR, tools=PARENT_TOOLS, sub_tools=CHILD_TOOLS)


# ──────────────────────────────────────────────────────────────────
# [s14_v2] 事件驱动主循环所需的两个线程函数
# ──────────────────────────────────────────────────────────────────

def _build_prompt_str() -> str:
    """动态构建提示符字符串（含任务状态）。由 input_reader 线程调用。"""
    task_items = [t for t in TASKS.get_items() if t["status"] != "deleted"]
    status_tag = ""
    if task_items:
        completed = sum(1 for t in task_items if t["status"] == "completed")
        in_progress = [t for t in task_items if t["status"] == "in_progress"]
        if in_progress:
            active_name = in_progress[0].get("subject", "")
            status_tag = (
                f"\x01\033[33m\x02[Tasks {completed}/{len(task_items)}"
                f" | {active_name[:30]}{'…' if len(active_name) > 30 else ''}] \x01\033[0m\x02 "
            )
        elif completed < len(task_items):
            status_tag = f"\x01\033[33m\x02[Tasks {completed}/{len(task_items)}] \x01\033[0m\x02 "
    return f"\x01\033[2K\r\x02{status_tag}\x01\033[36m\x02s18v2 >> \x01\033[0m\x02"


def input_reader(event_queue: Queue, input_ready: threading.Event) -> None:
    """
    [s14_v2 新增] 专职读取 stdin 的后台线程。
    将用户按回车后的输入以 ("user", query) 放入 event_queue。
    KeyboardInterrupt / EOFError 时放入 ("quit", "") 并退出。

    input_ready 事件用于同步：
      - 主线程处理完上一个事件后 set()
      - input_reader 收到信号后才显示提示符并读取下一行
    这样保证提示符始终出现在 agent 输出之后，不会错位。
    """
    while True:
        input_ready.wait()       # 等主线程处理完毕
        input_ready.clear()      # 占用"输入时段"，防止重复显示提示符
        try:
            prompt_str = _build_prompt_str()
            # 临时还原 sys.stdout 为原始终端，确保 input() 走 readline 分支，
            # 否则 _Tee 替换 stdout 后 input() 会手动 write prompt，
            # readline 无法识别 \x01/\x02 非打印标记，导致光标位置计算错乱。
            _tee_stdout = sys.stdout
            sys.stdout = sys.__stdout__
            try:
                query = input(prompt_str).strip()
            finally:
                sys.stdout = _tee_stdout
            event_queue.put(("user", query))
        except KeyboardInterrupt:
            print()
            event_queue.put(("quit", ""))
            break
        except EOFError:
            event_queue.put(("quit", ""))
            break


def cron_watcher(event_queue: Queue, stop_event: threading.Event) -> None:
    """
    [s14_v2 新增] 专职监听 scheduler.queue 的后台线程。
    每秒 drain 一次，将触发的 cron 通知以 ("cron", note) 放入 event_queue。
    stop_event 置位后退出。
    由于 agent_loop 内部已不再 drain scheduler.queue，
    所有 cron 通知都经由此线程 → event_queue → 主循环统一处理，无竞争。
    """
    while not stop_event.is_set():
        notes = scheduler.drain_notifications()
        for note in notes:
            print(f"\n[Cron notification] {note[:100]}")
            event_queue.put(("cron", note))
        stop_event.wait(timeout=1)


# ── [s14_v3] 会话日志：同时写终端和文件 ───────────────────────────────
class _Tee:
    """
    代理 sys.stdout / sys.stderr：
    - 终端侧：原样输出（保留 ANSI 颜色）
    - 文件侧：去除 ANSI 转义码、readline 标记（\\x01/\\x02）和单独的 \\r，输出可读文本
    fileno() 代理到原始终端 fd，保证 readline / termios 正常工作。
    """
    _ANSI_RE = re.compile(r'\x1b\[[0-9;]*[mKJHABCDEFGfrsulh]|\x01|\x02')

    def __init__(self, terminal, logfile):
        self._terminal = terminal
        self._logfile  = logfile

    def write(self, data: str):
        self._terminal.write(data)
        clean = self._ANSI_RE.sub('', data)
        # 将单独的 \r（不跟 \n）转成空串，避免日志里行被覆盖
        clean = re.sub(r'\r(?!\n)', '', clean)
        if clean:
            try:
                self._logfile.write(clean)
            except Exception as e:
                self._terminal.write(f"\n[_Tee] 日志写入失败，本次丢弃: {e}\n")

    def flush(self):
        self._terminal.flush()
        try:
            self._logfile.flush()
        except Exception as e:
            self._terminal.write(f"\n[_Tee] 日志 flush 失败，本次丢弃: {e}\n")

    def isatty(self):
        return self._terminal.isatty()

    def fileno(self):
        return self._terminal.fileno()


if __name__ == "__main__":
    # 保存终端初始状态：input_reader 是 daemon 线程，
    # Ctrl+C 时被强杀可能让 readline 没机会还原 termios，
    # 在 finally 里手动还原，防止退出后终端 no-echo / raw mode。
    _saved_tty = None
    if sys.stdin.isatty():
        try:
            _saved_tty = termios.tcgetattr(sys.stdin)
        except Exception:
            pass

    # [s14_v3] 会话日志初始化
    _log_file = None
    try:
        _log_dir = WORKDIR / "logs"
        _log_dir.mkdir(exist_ok=True)
        _log_path = _log_dir / f"session_{int(time.time())}.log"
        _log_file = open(_log_path, "w", buffering=1, encoding="utf-8")
        sys.stdout = _Tee(sys.__stdout__, _log_file)
        sys.stderr = _Tee(sys.__stderr__, _log_file)
        print(f"[Session log: {_log_path}]")
    except Exception as e:
        print(f"[Warning] 日志文件创建失败，仅输出到终端: {e}")

    # 启动 cron scheduler
    scheduler.start()
    print("[Cron scheduler running. Background checks every second.]")

    # 检测持久任务是否有错过的触发
    missed = scheduler.detect_missed_tasks()
    if missed:
        print(f"[Cron] {len(missed)} task(s) missed while session was closed:")
        for m in missed:
            print(f"  {m['id']} at {m['missed_at']}: {m['prompt'][:60]}")

    compact_state = CompactState()
    memory_mgr.load_all()
    mem_count = len(memory_mgr.memories)
    if mem_count:
        print(f"[{mem_count} memories loaded into context]")
    else:
        print("[No existing memories. The agent can create them with save_memory.]")

    start_result = hooks._run_external_hooks("SessionStart", {"trigger": True})
    for msg in start_result.get("messages", []):
        print(f"\033[35m👋 [SessionStart Hook]: {msg}\033[0m")

    # [s18_v2] 启动时显示 worktree 和 repo root 信息
    print(f"[Repo root: {REPO_ROOT}]")
    if not WORKTREES.git_available:
        print("[Note: Not in a git repo. worktree_* tools will return errors.]")
    else:
        wt_list = WORKTREES.list_all()
        print(f"[Worktrees: {wt_list}]")

    main_system = prompt_builder.main_build()
    history = [{"role": "system", "content": main_system}]

    # ── [s14_v2] 启动事件驱动线程 ──────────────────────────────────
    _event_queue: Queue = Queue()
    _stop_cron_watcher = threading.Event()
    _input_ready = threading.Event()
    _input_ready.set()   # 初始状态：允许立刻显示提示符

    threading.Thread(
        target=input_reader, args=(_event_queue, _input_ready), daemon=True, name="input_reader"
    ).start()
    threading.Thread(
        target=cron_watcher, args=(_event_queue, _stop_cron_watcher),
        daemon=True, name="cron_watcher"
    ).start()

    print("[s18_v2] Event-driven loop started. Cron tasks will fire without user input.")

    # ── 主循环：阻塞在 event_queue 上，由任意事件唤醒 ───────────────
    try:
        while True:
            event_type, content = _event_queue.get()  # 任意事件到来即唤醒

            # ── quit ────────────────────────────────────────────────────
            if event_type == "quit":
                _stop_cron_watcher.set()
                scheduler.stop()
                break

            # ── cron 触发：无需用户输入，直接注入历史并运行 agent_loop ──
            if event_type == "cron":
                print()
                history.append({
                    "role": "user",
                    "content": f"<cron-notification>\n{content}\n</cron-notification>",
                })
                state = LoopState(messages=history)
                agent_loop(state, compact_state)
                history = state.messages

                last_message = state.messages[-1]
                raw_content = (
                    last_message.content
                    if hasattr(last_message, "content")
                    else last_message.get("content", "")
                )
                final_text = extract_text(raw_content)
                if final_text:
                    print(f"\033[32m[最终回复]\033[0m {final_text}")
                print()
                _input_ready.set()   # 恢复提示符（情况A：解除wait阻塞；情况B：下次Enter后立即刷新）
                continue

            # ── user 输入 ────────────────────────────────────────────────
            query = content

            if not query:
                _input_ready.set()   # 空输入也要恢复提示符
                continue

            if query.lower() in ("q", "exit"):
                _stop_cron_watcher.set()
                scheduler.stop()
                break

            # 斜杠命令
            if query.startswith("/mode"):
                parts = query.split()
                if len(parts) == 2 and parts[1] in MODES:
                    perms.mode = parts[1]
                    print(f"[Switched to {parts[1]} mode]")
                else:
                    print(f"Usage: /mode <{'|'.join(MODES)}>")
                _input_ready.set()
                continue

            if query.strip() == "/rules":
                for i, rule in enumerate(perms.rules):
                    print(f"  {i}: {rule}")
                _input_ready.set()
                continue

            if query.startswith("/allow"):
                parts = query.split(maxsplit=1)
                if len(parts) == 2:
                    target_dir = parts[1].strip()
                    if not target_dir.endswith("*"):
                        target_dir = target_dir.rstrip("/\\") + "/*"
                    perms.rules.append({"tool": "*", "path": target_dir, "behavior": "allow"})
                    perms.consecutive_denials = 0
                    print(f"\033[32m[Granted] 已主动授权框架操作目录: {target_dir}\033[0m")
                else:
                    print("Usage: /allow <path/to/folder>")
                _input_ready.set()
                continue

            if query.strip() == "/memories":
                if memory_mgr.memories:
                    for name, mem in memory_mgr.memories.items():
                        print(f"  [{mem['type']}] {name}: {mem['description']}")
                else:
                    print("  (no memories)")
                _input_ready.set()
                continue

            if query.strip() == "/clear":
                main_system = prompt_builder.main_build()
                history = [{"role": "system", "content": main_system}]
                TASKS.rounds_since_update = 0
                compact_state = CompactState()
                print("\033[32m[Session Cleared] 历史记录与任务状态已清空，准备开始新任务。\033[0m")
                _input_ready.set()
                continue

            if query.strip() == "/cron":
                print(scheduler.list_tasks())
                _input_ready.set()
                continue

            if query.strip() == "/test":
                _event_queue.put(("cron", "[Scheduled task test-0000]: This is a test cron notification."))
                print("[Test cron event enqueued.]")
                _input_ready.set()
                continue

            # 正常对话
            print()
            history.append({"role": "user", "content": query})
            state = LoopState(messages=history)
            agent_loop(state, compact_state)
            history = state.messages

            last_message = state.messages[-1]
            raw_content = (
                last_message.content
                if hasattr(last_message, "content")
                else last_message.get("content", "")
            )
            final_text = extract_text(raw_content)
            if final_text:
                print(f"\033[32m[最终回复]\033[0m {final_text}")
            print()
            _input_ready.set()   # agent 全部输出完毕，再显示提示符
    
    except KeyboardInterrupt:
        pass
    finally:
        _input_ready.set()       # 解除 input_reader 的 wait() 阻塞，让它能感知退出
        _stop_cron_watcher.set()
        scheduler.stop()
        # 先还原 stdout/stderr，确保后续 print 直接走原始终端，不再经过 _Tee
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        if _log_file is not None:
            try:
                _log_file.close()
            except Exception:
                pass
        # 再还原终端状态：input_reader daemon 线程被强杀时 readline 无法自动还原
        if _saved_tty is not None:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _saved_tty)
            except Exception:
                pass
        print("\n[Bye]")
