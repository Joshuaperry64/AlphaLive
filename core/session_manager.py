import os
import re
import time
import json
from pathlib import Path
from typing import List, Dict, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT_DIR / "history"
CONFIG_FILE = ROOT_DIR / "config.json"

try:
    from memory.memory_manager import MemoryManager
except ImportError:
    MemoryManager = None

class SessionManager:
    """Manages conversation transcript files in history/ and context injection for AlphaLive."""

    def __init__(self, history_dir: Path = HISTORY_DIR):
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.mm = MemoryManager() if MemoryManager else None

    def get_active_session_name(self) -> str:
        """Read active session from config.json or default to 'alpha'."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    sess = cfg.get("Global", {}).get("Session", "alpha")
                    if sess and str(sess).strip():
                        return self.sanitize_name(str(sess).strip())
            except Exception:
                pass
        return "alpha"

    def set_active_session_name(self, session_name: str) -> bool:
        """Persist active session in config.json."""
        clean = self.sanitize_name(session_name)
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if "Global" not in cfg:
                    cfg["Global"] = {}
                cfg["Global"]["Session"] = clean
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4)
                return True
            except Exception as e:
                print(f"[SessionManager] Failed to update config.json: {e}")
        return False

    @staticmethod
    def sanitize_name(name: str) -> str:
        s = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
        return s.strip("._") or "default"

    def get_session_file(self, session_name: str) -> Path:
        clean = self.sanitize_name(session_name)
        return self.history_dir / f"{clean}.txt"

    def list_sessions(self) -> List[Dict]:
        """List all sessions in history/ with rich metadata."""
        sessions = []
        for file in self.history_dir.glob("*.txt"):
            session_name = file.stem
            try:
                stat = file.stat()
                mtime = stat.st_mtime
                size_bytes = stat.st_size
                size_kb = round(size_bytes / 1024, 1)

                # Format human readable time
                diff = time.time() - mtime
                if diff < 3600:
                    time_str = f"{int(diff / 60)}m ago" if diff >= 60 else "Just now"
                elif diff < 86400:
                    time_str = f"{int(diff / 3600)}h ago"
                else:
                    time_str = time.strftime("%b %d, %I:%M %p", time.localtime(mtime))

                # Read sample lines and preview
                turn_count = 0
                preview = "Empty session transcript."
                with open(file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
                    turn_count = sum(1 for ln in lines if ln.startswith("[You]:"))
                    matches = list(re.finditer(r"\[(You|Alpha)\]:\s*([^\n\r]+)", content))
                    if matches:
                        preview = " | ".join(f"[{m.group(1)}]: {m.group(2).strip()}" for m in matches[-2:])

                sessions.append({
                    "name": session_name,
                    "file_path": str(file),
                    "mtime": mtime,
                    "mtime_str": time_str,
                    "size_kb": size_kb,
                    "turn_count": turn_count,
                    "preview": preview,
                })
            except Exception as e:
                print(f"[SessionManager] Error reading {file}: {e}")

        # Sort by mtime descending (most recent first)
        sessions.sort(key=lambda s: s["mtime"], reverse=True)
        return sessions

    def create_session(self, session_name: str) -> str:
        """Create a new session file if it doesn't already exist."""
        clean = self.sanitize_name(session_name)
        file = self.get_session_file(clean)
        if not file.exists():
            with open(file, "w", encoding="utf-8") as f:
                f.write("=== Session Start ===\n\n")
        self.set_active_session_name(clean)
        return clean

    def delete_session(self, session_name: str) -> bool:
        """Delete a session file from disk."""
        clean = self.sanitize_name(session_name)
        file = self.get_session_file(clean)
        if file.exists():
            try:
                file.unlink()
                return True
            except Exception as e:
                print(f"[SessionManager] Failed to delete session {clean}: {e}")
                return False
        return False

    def append_turn(self, session_name: str, user_text: str, alpha_text: str):
        """Append user & Alpha turn to the session log and trigger memory learning."""
        clean = self.sanitize_name(session_name)
        file = self.get_session_file(clean)

        entry = f"[You]: {user_text.strip()}\n[Alpha]: {alpha_text.strip()}\n\n"
        try:
            with open(file, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"[SessionManager] Error writing to {file}: {e}")

        # Integrate with SQL memory
        if self.mm:
            try:
                self.mm.auto_extract_facts(user_text, source=f"session_{clean}")
            except Exception as e:
                print(f"[SessionManager] Auto extract facts error: {e}")

    def build_session_context(self, session_name: str, max_chars: int = 15000) -> str:
        """
        Build full structured session context including prior conversation and personal intelligence.
        """
        clean = self.sanitize_name(session_name)
        file = self.get_session_file(clean)

        prior_history = ""
        if file.exists():
            try:
                with open(file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                if content and content != "=== Session Start ===":
                    # Take up to max_chars from end
                    if len(content) > max_chars:
                        content = "...[truncated earlier turns]...\n" + content[-max_chars:]
                    prior_history = content
            except Exception as e:
                print(f"[SessionManager] Error reading history: {e}")

        # Fetch memory state
        memory_summary = ""
        if self.mm:
            try:
                user_prof = self.mm.get_user_profile()
                traits = self.mm.get_personality()
                episodes = self.mm.get_recent_episodes(3)

                parts = []
                if user_prof:
                    parts.append("User Profile (Josh):\n" + "\n".join(f"  - {k}: {v}" for k, v in user_prof.items()))
                if traits:
                    parts.append("Core Personality Traits:\n" + "\n".join(f"  - {k}: {v}" for k, v in traits.items()))
                if episodes:
                    parts.append("Recent Memories:\n" + "\n".join(f"  - [{ep['timestamp']}] {ep['content']}" for ep in episodes))
                if parts:
                    memory_summary = "\n\n=== Personal Intelligence & Memory State ===\n" + "\n".join(parts)
            except Exception as e:
                print(f"[SessionManager] Memory fetch error: {e}")

        if not prior_history and not memory_summary:
            return ""

        context_blocks = [
            f"[System Note - Active Session Context: '{clean}']",
            "You are resuming an existing AlphaLive conversation session with Josh. Below is the prior conversation history and personal memory:",
        ]

        if prior_history:
            context_blocks.append(f"\n=== Prior Conversation History ===\n{prior_history}")
        if memory_summary:
            context_blocks.append(memory_summary)

        context_blocks.append(
            "\n[System Directive]: Continue this session seamlessly with Josh. You have complete recall of all prior messages and actions above. Do not repeat greetings or announce that you've restored the session; immediately respond to Josh's latest instruction."
        )

        return "\n\n".join(context_blocks)
