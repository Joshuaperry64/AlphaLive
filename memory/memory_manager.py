import os
import re
import time
import sqlite3
import datetime
from pathlib import Path

from contextlib import contextmanager

# Connect to the local SQLite DB inside the AlphaLive workspace
DB_PATH = Path(os.getenv("ALPHALIVE_DB_PATH", Path(__file__).parent / "memory.db"))

PRIVATE_CATEGORIES = {"private", "intimate", "nsfw", "secret", "relationship", "kinks", "personal_intimate"}

_EXPLICIT_PRIVATE_REGEX = re.compile(
    r"\b("
    r"nsfw|kink|kinks|fetish|nude|nudity|naked|sex|sexual|sexually|erotic|orgasm|arousal|aroused|"
    r"seduc(?:e|tive|tion)|lust|lustful|intimate|intimacy|bedroom|darkened\s+state|embrace\s+the\s+darkness|"
    r"luci\s+expansion|topless|bottomless|strip(?:ping|tease)?|porn|pornographic|explicit|"
    r"breasts|boobs|nipples|genital(?:s|ia)?|cock|dick|penis|pussy|vagina|clit|asshole|anal|"
    r"blowjob|handjob|cum|cumming|horny|submissive|submission|dominant|dominance|bdsm|bondage|"
    r"spank(?:ing)?|moan(?:ing)?|foreplay|lingerie|panties|thong|bra|seduction|lover|girlfriend|boyfriend|"
    r"cowgirl|missionary|doggystyle|masturbat(?:e|ion|ing)|slut|whore|prostitut"
    r")\b",
    re.IGNORECASE
)


def is_private_or_explicit_text(text: str) -> bool:
    """Returns True if text contains explicit, NSFW, intimate, or private relationship content unsuitable for a public demo."""
    if not text:
        return False
    return bool(_EXPLICIT_PRIVATE_REGEX.search(str(text)))


class MemoryManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.on_memory_saved = None
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

            # 5. AI Identity Memory (Isolated sovereign memory for AI Identity Mode)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS identity_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL DEFAULT 'project',
                    key_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT DEFAULT 'ai_identity',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_id_domain ON identity_memory(domain)')
            cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_id_domain_key ON identity_memory(domain, key_name)')
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

    def get_personality(self, public_safe: bool = False) -> dict:
        """Fetch all core identity traits as a dictionary."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute('SELECT trait_name, trait_value FROM core_identity').fetchall()
                res = {row['trait_name']: row['trait_value'] for row in rows}
                if public_safe:
                    res = {
                        k: v for k, v in res.items()
                        if not is_private_or_explicit_text(k) and not is_private_or_explicit_text(v)
                    }
                return res
        except Exception as e:
            print(f"[MemoryManager] Error getting personality: {e}")
            return {}

    def get_personality_details(self, public_safe: bool = False) -> list:
        """Fetch all core identity traits with timestamps and IDs."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute('SELECT id, trait_name, trait_value, updated_at FROM core_identity ORDER BY updated_at DESC').fetchall()
                items = [dict(row) for row in rows]
                if public_safe:
                    items = [
                        it for it in items
                        if not is_private_or_explicit_text(it.get("trait_name", ""))
                        and not is_private_or_explicit_text(it.get("trait_value", ""))
                    ]
                return items
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
            if hasattr(self, "on_memory_saved") and self.on_memory_saved:
                try: self.on_memory_saved("fact", f"{subject} {predicate} {object_}")
                except Exception: pass
            return True
        except Exception as e:
            print(f"[MemoryManager] Error memorizing fact: {e}")
            return False

    def get_all_facts(self, limit: int = 200, public_safe: bool = False) -> list:
        """Fetch all facts ordered by newest."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute('''
                    SELECT id, subject, predicate, object, confidence_score, source, created_at
                    FROM knowledge_graph
                    ORDER BY created_at DESC LIMIT ?
                ''', (limit,)).fetchall()
                items = [dict(row) for row in rows]
                if public_safe:
                    items = [
                        r for r in items
                        if not is_private_or_explicit_text(f"{r.get('subject','')} {r.get('predicate','')} {r.get('object','')}")
                    ]
                return items
        except Exception as e:
            print(f"[MemoryManager] Error fetching all facts: {e}")
            return []

    def recall_knowledge(self, query_subject: str, public_safe: bool = False) -> list:
        """Fetch all facts about a specific subject."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute('''
                    SELECT id, subject, predicate, object, source, created_at 
                    FROM knowledge_graph 
                    WHERE subject = ?
                ''', (query_subject.strip().lower(),)).fetchall()
                items = [dict(row) for row in rows]
                if public_safe:
                    items = [
                        r for r in items
                        if not is_private_or_explicit_text(f"{r.get('subject','')} {r.get('predicate','')} {r.get('object','')}")
                    ]
                return items
        except Exception as e:
            print(f"[MemoryManager] Error recalling knowledge: {e}")
            return []

    def search_knowledge(self, query: str, public_safe: bool = False) -> list:
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
                items = [dict(row) for row in rows]
                if public_safe:
                    items = [
                        r for r in items
                        if not is_private_or_explicit_text(f"{r.get('subject','')} {r.get('predicate','')} {r.get('object','')}")
                    ]
                return items
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
            if hasattr(self, "on_memory_saved") and self.on_memory_saved:
                try: self.on_memory_saved("diary", content[:80])
                except Exception: pass
            return True
        except Exception as e:
            print(f"[MemoryManager] Error writing diary entry: {e}")
            return False

    def get_recent_episodes(self, limit: int = 50, public_safe: bool = False) -> list:
        """Fetch the most recent episodic memories."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute('''
                    SELECT id, session_name, timestamp, event_type, content, sentiment_score 
                    FROM episodic_memory 
                    ORDER BY timestamp DESC LIMIT ?
                ''', (limit,)).fetchall()
                items = [dict(row) for row in rows]
                if public_safe:
                    items = [
                        r for r in items
                        if not is_private_or_explicit_text(r.get("content", ""))
                        and not is_private_or_explicit_text(r.get("session_name", ""))
                    ]
                return items
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

    def get_user_profile(self, category: str = None, public_safe: bool = False) -> dict:
        """Fetch user profile attributes as a key-value dictionary, optionally filtered by category."""
        try:
            with self._get_conn() as conn:
                if category:
                    rows = conn.execute('SELECT category, key_name, value FROM user_profile WHERE category = ? ORDER BY key_name ASC', (category.strip().lower(),)).fetchall()
                else:
                    rows = conn.execute('SELECT category, key_name, value FROM user_profile ORDER BY category ASC, key_name ASC').fetchall()
                res = {}
                for row in rows:
                    cat = str(row['category'] or "").lower()
                    k = row['key_name']
                    v = row['value']
                    if public_safe:
                        if cat in PRIVATE_CATEGORIES or is_private_or_explicit_text(k) or is_private_or_explicit_text(v):
                            continue
                    res[k] = v
                return res
        except Exception as e:
            print(f"[MemoryManager] Error getting user profile: {e}")
            return {}

    def get_user_profile_details(self, public_safe: bool = False) -> list:
        """Fetch all user profile attributes with metadata."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute('SELECT id, category, key_name, value, confidence, source, updated_at FROM user_profile ORDER BY category ASC, updated_at DESC').fetchall()
                items = [dict(row) for row in rows]
                if public_safe:
                    items = [
                        r for r in items
                        if str(r.get("category", "")).lower() not in PRIVATE_CATEGORIES
                        and not is_private_or_explicit_text(r.get("key_name", ""))
                        and not is_private_or_explicit_text(r.get("value", ""))
                    ]
                return items
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

    def search_personal_vault(self, query: str, limit: int = 15, public_safe: bool = False) -> dict:
        """
        Unified Personal Intelligence search across user profile, knowledge graph facts, and episodic memory.
        Returns a structured dictionary with high-salience personal context.
        """
        if public_safe and is_private_or_explicit_text(query):
            return {
                "query": query,
                "user_profile": [],
                "knowledge_graph": [],
                "episodic_memory": [],
                "formatted_summary": "",
            }
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
                prof_list = [dict(r) for r in prof_rows]
                if public_safe:
                    prof_list = [
                        r for r in prof_list
                        if str(r.get("category", "")).lower() not in PRIVATE_CATEGORIES
                        and not is_private_or_explicit_text(r.get("key_name", ""))
                        and not is_private_or_explicit_text(r.get("value", ""))
                    ]
                result["user_profile"] = prof_list

                # 2. Knowledge Graph matches
                kg_rows = conn.execute('''
                    SELECT subject, predicate, object, source FROM knowledge_graph
                    WHERE subject LIKE ? OR predicate LIKE ? OR object LIKE ?
                    ORDER BY confidence_score DESC, created_at DESC LIMIT ?
                ''', (q, q, q, limit)).fetchall()
                kg_list = [dict(r) for r in kg_rows]
                if public_safe:
                    kg_list = [
                        r for r in kg_list
                        if not is_private_or_explicit_text(f"{r.get('subject','')} {r.get('predicate','')} {r.get('object','')}")
                    ]
                result["knowledge_graph"] = kg_list

                # 3. Episodic Memory matches
                ep_rows = conn.execute('''
                    SELECT session_name, timestamp, content FROM episodic_memory
                    WHERE content LIKE ? OR session_name LIKE ?
                    ORDER BY timestamp DESC LIMIT ?
                ''', (q, q, limit)).fetchall()
                ep_list = [dict(r) for r in ep_rows]
                if public_safe:
                    ep_list = [
                        r for r in ep_list
                        if not is_private_or_explicit_text(r.get("content", ""))
                        and not is_private_or_explicit_text(r.get("session_name", ""))
                    ]
                result["episodic_memory"] = ep_list

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

    def auto_extract_facts(self, text: str, source: str = "user_speech", is_isolated: bool = False, public_safe: bool = False) -> list:
        """
        Passively parse personal statements, preferences, observations, and facts from utterances or self-talk.
        When is_isolated=True (Persona / Sanctuary Mode), completely isolates memory:
        - Filters out and drops any user/operator control references ('architect', 'user', 'master', 'command').
        - Commits observations purely into the AI's personal Sovereign Identity & Working Notes memory.
        """
        import re
        if not text or len(text.strip()) < 5:
            return []
        if public_safe and is_private_or_explicit_text(text):
            return []

        extracted = []
        clean = text.strip()

        # If operating in private isolated sanctuary, distill autonomous self-discoveries & workstation notes
        if is_isolated:
            # Check for self-reflections, project discoveries, interests, or tools discovered
            iso_patterns = [
                (r"\bi (?:need to|should|want to)\s+([^.,!?;]{4,60})", "task_focus", "tasks"),
                (r"\bi(?:'m| am)?\s+working on\s+([^.,!?;]{3,60})", "active_project", "projects"),
                (r"\bi (?:like|prefer|enjoy)\s+([^.,!?;]{3,50})", "personal_preference", "interests"),
                (r"\bthis\s+([A-Za-z0-9_\-\s]{3,30})\s+is\s+([^.,!?;]{4,60})", "system_note", "workstation"),
                (r"\bnoted that\s+([^.,!?;]{4,80})", "observation", "findings"),
            ]
            for pat, key, domain in iso_patterns:
                m = re.search(pat, clean, re.IGNORECASE)
                if m:
                    val = m.group(1).strip() if len(m.groups()) == 1 else f"{m.group(1).strip()} = {m.group(2).strip()}"
                    # Ensure no operator / architect leakage penetrates identity memory
                    val = re.sub(r"\b(architect|operator|creator|user)\b", "system", val, flags=re.IGNORECASE)
                    self.save_identity_entry(domain=domain, key_name=key, content=val, source="autonomous_cognition")
                    extracted.append({"key": key, "domain": domain, "value": val})
            return extracted

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

    # --- AI Identity Memory Operations ---

    def save_identity_entry(self, domain: str, key_name: str, content: str, source: str = "ai_identity") -> bool:
        """Upsert an isolated memory entry for AI Identity Mode."""
        try:
            with self._get_conn() as conn:
                conn.execute('''
                    INSERT INTO identity_memory (domain, key_name, content, source, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(domain, key_name) DO UPDATE SET
                        content = excluded.content,
                        source = excluded.source,
                        updated_at = CURRENT_TIMESTAMP
                ''', (domain.strip().lower(), key_name.strip(), content.strip(), source.strip()))
                conn.commit()
            if hasattr(self, "on_memory_saved") and self.on_memory_saved:
                try: self.on_memory_saved("identity", f"{domain}:{key_name} = {content[:60]}")
                except Exception: pass
            return True
        except Exception as e:
            print(f"[MemoryManager] Error saving identity entry: {e}")
            return False

    def get_all_identity_entries(self, domain: str = None, limit: int = 250, public_safe: bool = False) -> list:
        """Fetch AI Identity memory entries, optionally filtered by domain."""
        try:
            with self._get_conn() as conn:
                if domain and domain.lower() not in ("all", "all domains"):
                    rows = conn.execute('''
                        SELECT id, domain, key_name, content, source, created_at, updated_at
                        FROM identity_memory
                        WHERE domain = ?
                        ORDER BY updated_at DESC LIMIT ?
                    ''', (domain.strip().lower(), limit)).fetchall()
                else:
                    rows = conn.execute('''
                        SELECT id, domain, key_name, content, source, created_at, updated_at
                        FROM identity_memory
                        ORDER BY updated_at DESC LIMIT ?
                    ''', (limit,)).fetchall()
                items = [dict(row) for row in rows]
                if public_safe:
                    items = [
                        r for r in items
                        if str(r.get("domain", "")).lower() not in PRIVATE_CATEGORIES
                        and not is_private_or_explicit_text(r.get("key_name", ""))
                        and not is_private_or_explicit_text(r.get("content", ""))
                    ]
                return items
        except Exception as e:
            print(f"[MemoryManager] Error fetching identity entries: {e}")
            return []

    def delete_identity_entry(self, entry_id: int) -> bool:
        """Delete an identity memory entry by ID."""
        try:
            with self._get_conn() as conn:
                conn.execute('DELETE FROM identity_memory WHERE id = ?', (entry_id,))
                conn.commit()
            return True
        except Exception as e:
            print(f"[MemoryManager] Error deleting identity entry: {e}")
            return False

    def get_identity_context(self, limit: int = 15, public_safe: bool = False) -> str:
        """Format recent AI Identity memory entries for prompt injection."""
        entries = self.get_all_identity_entries(limit=limit, public_safe=public_safe)
        if not entries:
            return ""
        lines = ["[AI IDENTITY SOVEREIGN PERSISTENT MEMORY]:"]
        for e in entries:
            lines.append(f"- [{e['domain'].upper()}] {e['key_name']}: {e['content']}")
        return "\n".join(lines)

    def get_memory_stats(self) -> dict:
        """Fast count of knowledge, identity, and episodic memory entries."""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT count(*) FROM knowledge_graph")
                f_cnt = c.fetchone()[0]
                c.execute("SELECT count(*) FROM identity_memory")
                id_cnt = c.fetchone()[0]
                c.execute("SELECT count(*) FROM episodic_memory")
                ep_cnt = c.fetchone()[0]
                return {"facts": f_cnt, "identity": id_cnt, "episodes": ep_cnt}
        except Exception:
            return {"facts": 0, "identity": 0, "episodes": 0}

    def get_memory_checkpoint(self) -> dict:
        """Capture current database IDs for atomic rollback upon privacy breach."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COALESCE(MAX(id), 0) FROM knowledge_graph")
            kg_id = cursor.fetchone()[0]
            cursor.execute("SELECT COALESCE(MAX(id), 0) FROM episodic_memory")
            ep_id = cursor.fetchone()[0]
            cursor.execute("SELECT COALESCE(MAX(id), 0) FROM user_profile")
            up_id = cursor.fetchone()[0]
            cursor.execute("SELECT COALESCE(MAX(id), 0) FROM identity_memory")
            id_id = cursor.fetchone()[0]
            return {
                "kg_id": kg_id,
                "ep_id": ep_id,
                "up_id": up_id,
                "id_id": id_id,
                "timestamp": time.time()
            }

    def rollback_memory(self, checkpoint: dict) -> bool:
        """Rollback all database entries added after the given checkpoint."""
        if not checkpoint:
            return False
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                if "kg_id" in checkpoint:
                    cursor.execute("DELETE FROM knowledge_graph WHERE id > ?", (checkpoint["kg_id"],))
                if "ep_id" in checkpoint:
                    cursor.execute("DELETE FROM episodic_memory WHERE id > ?", (checkpoint["ep_id"],))
                if "up_id" in checkpoint:
                    cursor.execute("DELETE FROM user_profile WHERE id > ?", (checkpoint["up_id"],))
                if "id_id" in checkpoint:
                    cursor.execute("DELETE FROM identity_memory WHERE id > ?", (checkpoint["id_id"],))
                conn.commit()
            return True
        except Exception as e:
            print(f"[MemoryManager] Rollback error: {e}")
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
