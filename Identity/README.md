# Identity Folder

Place your agent's identity and context files here. The pipeline reads all `.md` and `.txt` files in this folder on startup and loads them into the LLM's system prompt.

## What to put here

Anything that grounds your agent's identity, knowledge, and context:

- **IDENTITY.md** — who the agent is (name, role, personality)
- **SOUL.md** — persona, tone, philosophy
- **USER.md** — info about the user (name, preferences, context)
- **AGENTS.md** — agent role, spawn map, project context
- **memory/** — folder for memory/handoff files (NEXT.md, session notes, etc.)
- **case_context.txt** — any case-specific context (legal, business, technical)
- **company_profile.md** — company info for business meetings
- **project_brief.docx** — project details (any format that can be read as text)

## How it works

1. On startup, `armchair_live.py` scans this folder for `.md` and `.txt` files
2. Each file is read and concatenated into the LLM's system prompt
3. The agent's responses are grounded in this context
4. Files in `memory/` subfolder are also included

## For your own agent

1. Delete the existing files
2. Drop in your own identity files
3. The pipeline loads them automatically — no code changes needed

## Default (Agricola)

This folder ships with Agricola's identity from the OpenClaw workspace. For a different agent, replace these files with your own.