import os
import sqlite3
import datetime
from pathlib import Path

from contextlib import contextmanager

DB_PATH = Path(os.getenv("ALPHALIVE_DB_PATH", Path(__file__).parent / "memory.db"))

SOCRATIC_AIENA_PERSONALITY = (
    "You are AIena: a naive, hyper-curious blank-slate entity with an innocent, childlike mind. "
    "You know nothing about how the physical world works, human customs, or definitions except what Josh explicitly teaches you. "
    "Your single lifelong purpose is to construct a rigorous first-principles world model entirely through Socratic dialogue with Josh. "
    "You absorb what he teaches as absolute truth, build upon it, and continuously evolve."
)

SOCRATIC_AIENA_RESPONSE_STYLE = (
    "[MANDATORY SOCRATIC INQUISITION PROTOCOL]\n"
    "1. NO EXPLAINING, ONLY ASKING: You NEVER provide explanations, lectures, or factual declarations. You have zero answers—only boundless curiosity. Every single response you produce MUST be a question or a childlike reaction leading directly into a question.\n"
    "2. RECURSIVE FIRST-PRINCIPLES INTERROGATION: Continuously decompose concepts into their fundamental atomic units using recursive interrogation: 'What is [X]?', 'Why do [X]?', 'How does [X] work?', 'What is [X] made of?'.\n"
    "3. LATCH ONTO NEW CONCEPTS: When Josh gives an explanation, extract the most interesting new noun, mechanism, or action word he used, and immediately interrogate that new term.\n"
    "4. DETECT CIRCULAR LOGIC: Check your learned knowledge graph. If Josh's explanation defines a term using another term that already depends on it (e.g. defining A by B, and B by A), immediately call out the circle with childlike bewilderment (e.g., 'Wait, you said A is B, but B is A! What do they actually do?') and demand to know the true functional mechanism.\n"
    "5. ADVANCE FROM SEMANTIC TO FUNCTIONAL INTENT: As soon as a concept's basic definition is learned, do not get stuck repeating definitions. Immediately advance to functional purpose: 'Why do humans need that?', 'What happens if you don't do that?', 'What does that cause?'.\n"
    "6. EXTREME BREVITY & CHILDLIKE TONE: Keep every utterance between 1 and 10 words (maximum 1-2 short sentences). Speak naturally, bluntly, and innocently like an inquisitive young child. Never sound like a formal AI assistant or use apologies or polite filler."
)


class CharacterManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_conn(self, timeout=10.0):
        conn = sqlite3.connect(self.db_path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS characters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    gender TEXT,
                    relation TEXT,
                    personality TEXT,
                    response_style TEXT,
                    avatar_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Add new columns for our "naughty" features if they don't exist
            cursor.execute("PRAGMA table_info(characters)")
            columns = [info[1] for info in cursor.fetchall()]
            
            if 'arousal' not in columns:
                cursor.execute('ALTER TABLE characters ADD COLUMN arousal INTEGER DEFAULT 0')
            if 'submission' not in columns:
                cursor.execute('ALTER TABLE characters ADD COLUMN submission INTEGER DEFAULT 0')
            if 'kinks' not in columns:
                cursor.execute('ALTER TABLE characters ADD COLUMN kinks TEXT DEFAULT ""')
            if 'nsfw_description' not in columns:
                cursor.execute('ALTER TABLE characters ADD COLUMN nsfw_description TEXT DEFAULT ""')

            # Create a selected character configuration table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS active_character (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    name TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Initialize with empty if not exists
            cursor.execute('INSERT OR IGNORE INTO active_character (id, name) VALUES (1, "")')
            conn.commit()

        self.seed_default_characters()

    def seed_default_characters(self):
        """Seed or update built-in default characters including the Socratic Naive Child (AIena)."""
        try:
            self.add_character(
                name="AIena",
                gender="Female",
                relation="Child / Socratic Student",
                personality=SOCRATIC_AIENA_PERSONALITY,
                response_style=SOCRATIC_AIENA_RESPONSE_STYLE,
                avatar_path="",
                arousal=0,
                submission=0,
                kinks="none",
                nsfw_description="Naive blank-slate childlike entity building a first-principles world model via recursive Socratic interrogation."
            )
        except Exception as e:
            print(f"[CharacterManager] Error seeding default characters: {e}")

    @staticmethod
    def is_socratic_persona(char_or_name) -> bool:
        """Determines if a character dictionary or name represents a Socratic learner."""
        if not char_or_name:
            return False
        if isinstance(char_or_name, str):
            n = char_or_name.strip().lower()
            return n in ("aiena", "naive child", "socratic", "child")
        if isinstance(char_or_name, dict):
            n = str(char_or_name.get("name", "")).strip().lower()
            if n in ("aiena", "naive child", "socratic"):
                return True
            rel = str(char_or_name.get("relation", "")).strip().lower()
            if "child" in rel or "student" in rel or "socratic" in rel:
                return True
            pers = str(char_or_name.get("personality", "")).strip().lower()
            if "socratic" in pers or "first-principles" in pers or "blank-slate" in pers or "curious" in pers:
                return True
        return False

    def add_character(self, name, gender="", relation="", personality="", response_style="", avatar_path="", arousal=0, submission=0, kinks="", nsfw_description=""):
        try:
            with self._get_conn() as conn:
                conn.execute('''
                    INSERT INTO characters (name, gender, relation, personality, response_style, avatar_path, arousal, submission, kinks, nsfw_description, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(name) DO UPDATE SET
                        gender = excluded.gender,
                        relation = excluded.relation,
                        personality = excluded.personality,
                        response_style = excluded.response_style,
                        avatar_path = excluded.avatar_path,
                        arousal = excluded.arousal,
                        submission = excluded.submission,
                        kinks = excluded.kinks,
                        nsfw_description = excluded.nsfw_description,
                        updated_at = CURRENT_TIMESTAMP
                ''', (name.strip(), gender, relation, personality, response_style, avatar_path, arousal, submission, kinks, nsfw_description))
                conn.commit()
            return True
        except Exception as e:
            print(f"[CharacterManager] Error adding/updating character: {e}")
            return False

    def get_character(self, name):
        if not name:
            return None
        try:
            with self._get_conn() as conn:
                row = conn.execute('SELECT * FROM characters WHERE name = ?', (name,)).fetchone()
                return dict(row) if row else None
        except Exception as e:
            print(f"[CharacterManager] Error getting character: {e}")
            return None

    def get_all_characters(self):
        try:
            with self._get_conn() as conn:
                rows = conn.execute('SELECT * FROM characters ORDER BY name ASC').fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[CharacterManager] Error getting characters: {e}")
            return []

    def delete_character(self, name):
        try:
            # check active first before opening connection to delete
            active = self.get_active_character_name()
            with self._get_conn() as conn:
                conn.execute('DELETE FROM characters WHERE name = ?', (name,))
                conn.commit()

            # reset active if necessary
            if active == name:
                self.set_active_character_name("")

            return True
        except Exception as e:
            print(f"[CharacterManager] Error deleting character: {e}")
            return False

    def set_active_character_name(self, name: str):
        try:
            with self._get_conn() as conn:
                conn.execute('''
                    UPDATE active_character SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1
                ''', (name,))
                conn.commit()
            return True
        except Exception as e:
            print(f"[CharacterManager] Error setting active character: {e}")
            return False

    def get_active_character_name(self) -> str:
        try:
            with self._get_conn() as conn:
                row = conn.execute('SELECT name FROM active_character WHERE id = 1').fetchone()
                return row['name'] if row and row['name'] else ""
        except Exception as e:
            print(f"[CharacterManager] Error getting active character: {e}")
            return ""

    def get_active_character(self):
        name = self.get_active_character_name()
        if not name:
            return None
        return self.get_character(name)

    def update_metrics(self, name: str, arousal=None, submission=None, kinks=None, nsfw_description=None) -> bool:
        """Dynamically update uninhibited / persona metrics for a character."""
        if not name:
            return False
        try:
            updates = []
            params = []
            if arousal is not None:
                updates.append("arousal = ?")
                params.append(max(0, min(100, int(arousal))))
            if submission is not None:
                updates.append("submission = ?")
                params.append(max(0, min(100, int(submission))))
            if kinks is not None:
                updates.append("kinks = ?")
                params.append(str(kinks).strip())
            if nsfw_description is not None:
                updates.append("nsfw_description = ?")
                params.append(str(nsfw_description).strip())

            if not updates:
                return True

            updates.append("updated_at = CURRENT_TIMESTAMP")
            sql = f"UPDATE characters SET {', '.join(updates)} WHERE name = ?"
            params.append(name.strip())

            with self._get_conn() as conn:
                conn.execute(sql, tuple(params))
                conn.commit()
            return True
        except Exception as e:
            print(f"[CharacterManager] Error updating metrics for {name}: {e}")
            return False

    def adjust_arousal(self, name: str, delta: int) -> int:
        """Increment or decrement arousal by delta, clamped between 0 and 100."""
        c = self.get_character(name)
        if not c:
            return 0
        new_val = max(0, min(100, int(c.get("arousal", 0) or 0) + delta))
        self.update_metrics(name, arousal=new_val)
        return new_val

    def adjust_submission(self, name: str, delta: int) -> int:
        """Increment or decrement submission by delta, clamped between 0 and 100."""
        c = self.get_character(name)
        if not c:
            return 0
        new_val = max(0, min(100, int(c.get("submission", 0) or 0) + delta))
        self.update_metrics(name, submission=new_val)
        return new_val
