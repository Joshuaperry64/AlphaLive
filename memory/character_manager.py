import os
import sqlite3
import datetime
from pathlib import Path

DB_PATH = Path(os.getenv("ALPHALIVE_DB_PATH", Path(__file__).parent / "memory.db"))

class CharacterManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self, timeout=10.0):
        conn = sqlite3.connect(self.db_path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        return conn

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
