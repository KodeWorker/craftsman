# Roadmap

1. Overview: [overview.md](plan/overview.md)
2. Phase 1: basic chat [phase1.md](plan/phase1.md)
3. Phase 2: user registry & auth [phase2.md](plan/phase2.md)
4. Phase 3: multimodal support [phase3.md](plan/phase3.md)
5. Phase 4: wire telegram bot [phase4.md](plan/phase4.md)
6. Phase 5: tool use [phase5.md](plan/phase5.md)
7. Phase 6: web & browser & plan tools [phase6.md](plan/phase6.md)
8. Phase 7: memory (LightRAG, vector, knowledge graph) [phase7.md](plan/phase7.md)
   - upgrade `tool:find` from SQLite LIKE to sqlite-vec semantic search

---

## TODO / Revisit

- **Plan tools** — full rewrite of plan/task system; human-gated intercepts
  for `task:start`, `task:done`, `task:cancel`, `task:update`; `depends_on`
  enforcement; `agent:run` auto-revoke when plan enabled. Was originally
  phase 6.3 — dropped to revisit later.
