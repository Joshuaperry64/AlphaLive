---
name: alphalive-memory-architecture
description: >-
  Architectural blueprint and implementation guidelines for AlphaLive's structured SQL memory system.
  Use this skill whenever working on memory features, databases, or state persistence in AlphaLive.
---

# AlphaLive SQL Memory Architecture

AlphaLive utilizes a hybrid memory system combining ChromaDB (for semantic/vector search) and an SQL database (for structured state, facts, and episodic memory).

## Core Storage
- **Database:** SQLite (local, serverless, fast) stored at `C:\Users\josh6\Workspace\AlphaLive\memory.db`.
- **Manager Module:** `memory_manager.py` handles all DB connections and migrations.

## Database Schema (SQL)

### 1. `core_identity` (Personality & State)
Stores dynamic parameters about Alpha's current personality or ongoing directives.
- `id` (PK), `trait_name` (UNIQUE), `trait_value`, `updated_at`

### 2. `knowledge_graph` (Facts & Rules)
Stores absolute facts Alpha has learned about the user, the world, or specific projects.
- `id` (PK), `subject`, `predicate`, `object`, `confidence_score`, `source`, `created_at`

### 3. `episodic_memory` (Memories & Diary)
Stores summaries of past sessions, significant events, and daily logs.
- `id` (PK), `session_name`, `timestamp`, `event_type` (e.g., 'diary', 'milestone', 'insight'), `content`, `sentiment_score`

## Agent Interaction (Tools)
To interface with this memory, Alpha is provided with MCP or native Gemini tools (defined in `mcp_handler.py` or similar):
1. `memorize_fact(subject, predicate, object)`: Saves a hard fact.
2. `recall_knowledge(query)`: Searches structured SQL facts.
3. `write_diary_entry(content)`: Saves a summary of the current session upon closing.
4. `update_personality(trait, value)`: Modifies core identity parameters dynamically.

## Integration Rules
- Only initialize or query the SQL database if the global `Memory` config is set to `enabled`.
- Database operations must be asynchronous or off-main-thread to prevent blocking the audio/websocket loops.
