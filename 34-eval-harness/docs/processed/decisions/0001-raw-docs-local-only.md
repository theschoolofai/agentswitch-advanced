# 0001 Raw notes stay on your own computer

- **Status:** Accepted, 7 Nov 2026
- **Context:** `docs/raw/` holds pasted chats, course notes and fetched web pages. Raw material like this may contain secrets, personal messages or platform detail, and the repository is public.
- **Decision:** `docs/raw/` is git-ignored. Only the cleaned wiki in `docs/processed/` is committed. Facts from raw notes are rewritten in plain English, without secrets, before they go into the wiki.
- **Consequences:** Each person keeps their own raw notes. Anything the team needs must be copied into the wiki, or it is lost to the others.
