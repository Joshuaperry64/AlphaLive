import os
import sqlite3
import datetime
from pathlib import Path

# Connect to the local SQLite DB inside the AlphaLive workspace
DB_PATH = Path(os.getenv("ALPHALIVE_DB_PATH", Path(__file__).parent / "memory.db"))

class MemoryManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        # We enforce dict-like row access for convenience
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

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
            # Index for fast subject lookups
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_kg_subject ON knowledge_graph(subject)')

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
        """Save a discrete fact into the knowledge graph."""
        try:
            with self._get_conn() as conn:
                conn.execute('''
                    INSERT INTO knowledge_graph (subject, predicate, object, source)
                    VALUES (?, ?, ?, ?)
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

# Optional quick-test block
if __name__ == "__main__":
    mm = MemoryManager()
    print("Memory database initialized at:", mm.db_path)
    
    # Test Personality
    mm.update_personality("curiosity_level", "high")
    mm.update_personality("current_focus", "GUI Development")
    print("Personality:", mm.get_personality())
    
    # Test Facts
    mm.memorize_fact("josh", "likes", "cyberpunk aesthetic", "startup_script")
    print("Facts about Josh:", mm.recall_knowledge("josh"))
    
    # Test Diary
    mm.write_diary_entry("Completed the UI successfully and saved the memory skill.", session_name="deziree")
    print("Recent Episodes:", mm.get_recent_episodes(2))
