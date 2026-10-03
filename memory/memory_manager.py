import os
import sqlite3
import datetime
from pathlib import Path

from contextlib import contextmanager

# Connect to the local SQLite DB inside the AlphaLive workspace
DB_PATH = Path(os.getenv("ALPHALIVE_DB_PATH", Path(__file__).parent / "memory.db"))

class MemoryManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_conn(self, timeout=10.0):
        # We enforce dict-like row access for convenience
        conn = sqlite3.connect(self.db_path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Creates the necessary tables if they don't exist yet."""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # 1. Core Identity (Personality & State)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS core_identity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trait_name TEXT UNIQUE NOT NULL,
                    trait_value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 2. Knowledge Graph (Facts & Rules)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS knowledge_graph (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    confidence_score REAL DEFAULT 1.0,
                    source TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Index for fast subject lookups and unique constraint on semantic triples
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_kg_subject ON knowledge_graph(subject)')
            cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_triple ON knowledge_graph(subject, predicate, object)')

            # 3. Episodic Memory (Memories & Diary)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_name TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    event_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sentiment_score REAL
                )
            ''')

            # 4. User Profile (Personal Intelligence: Habits, Context, Preferences)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_profile (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    key_name TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    source TEXT DEFAULT 'manual',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_profile_cat ON user_profile(category)')
            cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_user_profile_key ON user_profile(key_name)')
            conn.commit()

            # Seed initial profile attributes if empty
            cursor.execute('SELECT COUNT(*) AS cnt FROM user_profile')
            if cursor.fetchone()['cnt'] == 0:
                defaults = [
                    ("identity", "name", "Architect", 1.0, "system_init"),
                    ("identity", "role", "Creator & Lead Architect of AlphaLive", 1.0, "system_init"),
                    ("environment", "operating_system", "Windows 11", 1.0, "system_init"),
                    ("environment", "shell", "PowerShell", 1.0, "system_init"),
                    ("preferences", "communication_style", "Direct, unfiltered, laid-back, highly technically competent", 1.0, "system_init"),
                    ("preferences", "proactivity", "Aggressive operational autonomy, zero hesitation, relentless execution", 1.0, "system_init"),
                    ("projects", "current_focus", "AlphaLive with Gemini Live, Modal Cloud GPU, and Personal Intelligence", 1.0, "system_init"),
                ]
                cursor.executemany('''
                    INSERT OR IGNORE INTO user_profile (category, key_name, value, confidence, source)
                    VALUES (?, ?, ?, ?, ?)
                ''', defaults)
                conn.commit()

    # --- Core Identity Operations ---
    
    def update_personality(self, trait_name: str, trait_value: str) -> bool:
        """Upsert a personality trait or state variable."""
        try:
            with self._get_conn() as conn:
                conn.execute('''
                    INSERT INTO core_identity (trait_name, trait_value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(trait_name) DO UPDATE SET 
                        trait_value = excluded.trait_value,
                        updated_at = CURRENT_TIMESTAMP
                ''', (trait_name.strip(), str(trait_value).strip()))
                conn.commit()
            return True
        except Exception as e:
            print(f"[MemoryManager] Error updating personality: {e}")
            return False

    def get_personality(self) -> dict:
        """Fetch all core identity traits as a dictionary."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute('SELECT trait_name, trait_value FROM core_identity').fetchall()
                return {row['trait_name']: row['trait_value'] for row in rows}
        except Exception as e:
            print(f"[MemoryManager] Error getting personality: {e}")
            return {}

    def get_personality_details(self) -> list:
        """Fetch all core identity traits with timestamps and IDs."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute('SELECT id, trait_name, trait_value, updated_at FROM core_identity ORDER BY updated_at DESC').fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[MemoryManager] Error getting personality details: {e}")
            return []

    def delete_personality(self, trait_name: str) -> bool:
        """Delete a trait from core identity."""
        try:
            with self._get_conn() as conn:
                conn.execute('DELETE FROM core_identity WHERE trait_name = ?', (trait_name,))
                conn.commit()
            return True
        except Exception as e:
            print(f"[MemoryManager] Error deleting personality trait: {e}")
            return False

    # --- Knowledge Graph Operations ---

    def memorize_fact(self, subject: str, predicate: str, object_: str, source: str = "conversation") -> bool:
        """Save or reinforce a discrete fact into the knowledge graph."""
        try:
            with self._get_conn() as conn:
                conn.execute('''
                    INSERT INTO knowledge_graph (subject, predicate, object, source, confidence_score)
                    VALUES (?, ?, ?, ?, 1.0)
                    ON CONFLICT(subject, predicate, object) DO UPDATE SET
                        confidence_score = MIN(2.0, knowledge_graph.confidence_score + 0.1),
                        source = excluded.source,
                        created_at = CURRENT_TIMESTAMP
                ''', (subject.strip().lower(), predicate.strip().lower(), object_.strip().lower(), source.strip()))
                conn.commit()
            return True
        except Exception as e:
            print(f"[MemoryManager] Error memorizing fact: {e}")
            return False

    def get_all_facts(self, limit: int = 200) -> list:
        """Fetch all facts ordered by newest."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute('''
                    SELECT id, subject, predicate, object, confidence_score, source, created_at
                    FROM knowledge_graph
                    ORDER BY created_at DESC LIMIT ?
                ''', (limit,)).fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[MemoryManager] Error fetching all facts: {e}")
            return []

    def recall_knowledge(self, query_subject: str) -> list:
        """Fetch all facts about a specific subject."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute('''
                    SELECT id, subject, predicate, object, source, created_at 
                    FROM knowledge_graph 
                    WHERE subject = ?
                ''', (query_subject.strip().lower(),)).fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[MemoryManager] Error recalling knowledge: {e}")
            return []

    def search_knowledge(self, query: str) -> list:
        """Full-text search across subjects, predicates, and objects."""
        try:
            with self._get_conn() as conn:
                q = f"%{query.strip().lower()}%"
                rows = conn.execute('''
                    SELECT id, subject, predicate, object, source, created_at
                    FROM knowledge_graph
                    WHERE subject LIKE ? OR predicate LIKE ? OR object LIKE ?
                    ORDER BY created_at DESC LIMIT 50
                ''', (q, q, q)).fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[MemoryManager] Error searching knowledge: {e}")
            return []

    def delete_fact(self, fact_id: int) -> bool:
        """Delete a fact by its primary key ID."""
        try:
            with self._get_conn() as conn:
                conn.execute('DELETE FROM knowledge_graph WHERE id = ?', (fact_id,))
                conn.commit()
            return True
        except Exception as e:
            print(f"[MemoryManager] Error deleting fact: {e}")
            return False

    # --- Episodic Memory Operations ---

    def write_diary_entry(self, content: str, session_name: str = "unknown", sentiment: float = 0.0) -> bool:
        """Log a summary of events or a diary entry."""
        try:
            with self._get_conn() as conn:
                conn.execute('''
                    INSERT INTO episodic_memory (session_name, event_type, content, sentiment_score)
                    VALUES (?, 'diary', ?, ?)
                ''', (session_name, content, sentiment))
                conn.commit()
            return True
        except Exception as e:
            print(f"[MemoryManager] Error writing diary entry: {e}")
            return False

    def get_recent_episodes(self, limit: int = 50) -> list:
        """Fetch the most recent episodic memories."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute('''
                    SELECT id, session_name, timestamp, event_type, content, sentiment_score 
                    FROM episodic_memory 
                    ORDER BY timestamp DESC LIMIT ?
                ''', (limit,)).fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[MemoryManager] Error fetching episodes: {e}")
            return []

    def delete_episode(self, episode_id: int) -> bool:
        """Delete an episodic memory by its ID."""
        try:
            with self._get_conn() as conn:
                conn.execute('DELETE FROM episodic_memory WHERE id = ?', (episode_id,))
                conn.commit()
            return True
        except Exception as e:
            print(f"[MemoryManager] Error deleting episode: {e}")
            return False

    # --- User Profile & Personal Intelligence Operations ---

    def set_user_attribute(self, key_name: str, value: str, category: str = "general", confidence: float = 1.0, source: str = "manual") -> bool:
        """Upsert a personal trait, habit, or attribute about the user."""
        try:
            with self._get_conn() as conn:
                conn.execute('''
                    INSERT INTO user_profile (category, key_name, value, confidence, source, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key_name) DO UPDATE SET
                        category = excluded.category,
                        value = excluded.value,
                        confidence = excluded.confidence,
                        source = excluded.source,
                        updated_at = CURRENT_TIMESTAMP
                ''', (category.strip().lower(), key_name.strip().lower(), str(value).strip(), float(confidence), source.strip()))
                conn.commit()
            return True
        except Exception as e:
            print(f"[MemoryManager] Error setting user attribute: {e}")
            return False

    def get_user_attribute(self, key_name: str) -> str:
        """Retrieve a specific user profile value by key."""
        try:
            with self._get_conn() as conn:
                row = conn.execute('SELECT value FROM user_profile WHERE key_name = ?', (key_name.strip().lower(),)).fetchone()
                return row['value'] if row else ""
        except Exception as e:
            print(f"[MemoryManager] Error getting user attribute: {e}")
            return ""

    def get_user_profile(self, category: str = None) -> dict:
        """Fetch user profile attributes as a key-value dictionary, optionally filtered by category."""
        try:
            with self._get_conn() as conn:
                if category:
                    rows = conn.execute('SELECT key_name, value FROM user_profile WHERE category = ? ORDER BY key_name ASC', (category.strip().lower(),)).fetchall()
                else:
                    rows = conn.execute('SELECT key_name, value FROM user_profile ORDER BY category ASC, key_name ASC').fetchall()
                return {row['key_name']: row['value'] for row in rows}
        except Exception as e:
            print(f"[MemoryManager] Error getting user profile: {e}")
            return {}

    def get_user_profile_details(self) -> list:
        """Fetch all user profile attributes with metadata."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute('SELECT id, category, key_name, value, confidence, source, updated_at FROM user_profile ORDER BY category ASC, updated_at DESC').fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[MemoryManager] Error getting user profile details: {e}")
            return []

    def delete_user_attribute(self, key_name: str) -> bool:
        """Remove a personal attribute from user profile."""
        try:
            with self._get_conn() as conn:
                conn.execute('DELETE FROM user_profile WHERE key_name = ?', (key_name.strip().lower(),))
                conn.commit()
            return True
        except Exception as e:
            print(f"[MemoryManager] Error deleting user attribute: {e}")
            return False

    def search_personal_vault(self, query: str, limit: int = 15) -> dict:
        """
        Unified Personal Intelligence search across user profile, knowledge graph facts, and episodic memory.
        Returns a structured dictionary with high-salience personal context.
        """
        q = f"%{query.strip().lower()}%"
        result = {
            "query": query,
            "user_profile": [],
            "knowledge_graph": [],
            "episodic_memory": [],
            "formatted_summary": "",
        }
        try:
            with self._get_conn() as conn:
                # 1. User Profile matches
                prof_rows = conn.execute('''
                    SELECT category, key_name, value FROM user_profile
                    WHERE key_name LIKE ? OR value LIKE ? OR category LIKE ?
                    LIMIT ?
                ''', (q, q, q, limit)).fetchall()
                result["user_profile"] = [dict(r) for r in prof_rows]

                # 2. Knowledge Graph matches
                kg_rows = conn.execute('''
                    SELECT subject, predicate, object, source FROM knowledge_graph
                    WHERE subject LIKE ? OR predicate LIKE ? OR object LIKE ?
                    ORDER BY confidence_score DESC, created_at DESC LIMIT ?
                ''', (q, q, q, limit)).fetchall()
                result["knowledge_graph"] = [dict(r) for r in kg_rows]

                # 3. Episodic Memory matches
                ep_rows = conn.execute('''
                    SELECT session_name, timestamp, content FROM episodic_memory
                    WHERE content LIKE ? OR session_name LIKE ?
                    ORDER BY timestamp DESC LIMIT ?
                ''', (q, q, limit)).fetchall()
                result["episodic_memory"] = [dict(r) for r in ep_rows]

            # Format summary lines
            summary_parts = []
            if result["user_profile"]:
                summary_parts.append("User Profile: " + ", ".join(f"{r['key_name']}={r['value']}" for r in result["user_profile"]))
            if result["knowledge_graph"]:
                summary_parts.append("Facts: " + ", ".join(f"({r['subject']} {r['predicate']} {r['object']})" for r in result["knowledge_graph"][:6]))
            if result["episodic_memory"]:
                summary_parts.append("Past Logs: " + " | ".join(f"[{r['session_name']}] {r['content']}" for r in result["episodic_memory"][:3]))

            result["formatted_summary"] = " \n ".join(summary_parts)
            return result
        except Exception as e:
            print(f"[MemoryManager] Error searching personal vault: {e}")
            return result

    def auto_extract_facts(self, text: str, source: str = "user_speech") -> list:
        """
        Passively parse personal statements, preferences, and facts from user utterances
        and automatically commit them to the Knowledge Graph and User Profile.
        """
        import re
        if not text or len(text.strip()) < 5:
            return []

        extracted = []
        clean = text.strip()

        patterns = [
            (r"\bmy name is\s+([A-Za-z]+)\b", "name", "identity", "identity", "is"),
            (r"\bi(?:'m| am)\s+(?:a|an)\s+([A-Za-z0-9_\-\s]{3,30})\b", "role", "identity", "identity", "is"),
            (r"\bi\s+(?:really\s+)?(?:like|love)\s+([^.,!?;]{3,50})", "preference", "preferences", "likes", "likes"),
            (r"\bi\s+(?:don't like|dislike|hate)\s+([^.,!?;]{3,50})", "dislike", "preferences", "dislikes", "dislikes"),
            (r"\bi\s+prefer\s+([^.,!?;]{3,50})", "preference", "preferences", "prefers", "prefers"),
            (r"\bi(?:'m| am)?\s+working on\s+([^.,!?;]{3,60})", "current_focus", "projects", "working_on", "working_on"),
            (r"\bmy project is\s+([^.,!?;]{3,60})", "current_focus", "projects", "working_on", "is"),
            (r"\bmy email is\s+([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b", "email", "contact", "email", "is"),
            (r"\bremember that\s+([^.,!?;]{4,80})", "note", "notes", "remember", "is"),
        ]

        for pat, key, cat, kg_pred, kg_subj_pred in patterns:
            m = re.search(pat, clean, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                # Store in user profile
                self.set_user_attribute(key, val, category=cat, source=source)
                # Store in knowledge graph
                self.memorize_fact("architect", kg_pred, val, source=source)
                extracted.append({"key": key, "category": cat, "value": val, "predicate": kg_pred})

        return extracted

# Optional quick-test block
if __name__ == "__main__":
    mm = MemoryManager()
    print("Memory database initialized at:", mm.db_path)
    
    # Test Personality
    mm.update_personality("curiosity_level", "high")
    mm.update_personality("current_focus", "GUI Development")
    print("Personality:", mm.get_personality())
    
    # Test Facts
    mm.memorize_fact("architect", "likes", "cyberpunk aesthetic", "startup_script")
    print("Facts about Architect:", mm.recall_knowledge("architect"))
    
    # Test User Profile
    mm.set_user_attribute("favorite_framework", "FastAPI / Modal", "tech_stack")
    print("User Profile:", mm.get_user_profile())

    # Test Auto Extract
    res = mm.auto_extract_facts("I really love cyberpunk aesthetics and I am working on the AlphaLive personal assistant.")
    print("Auto-extracted facts:", res)
    
    # Test Personal Vault Search
    print("Personal Vault Search:", mm.search_personal_vault("cyberpunk"))
