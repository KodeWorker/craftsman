# Agent Memory

## How to manage agent memory

Five core mechanisms, ordered from cheapest to most structured:

1. **Semantic Compression (The "Summary" Layer)** — compress old turns into a rolling summary; trade verbatim recall for token budget
2. **Hierarchical RAG (Vector Embeddings)** — retrieve relevant past context at query time; decouples memory size from context window size
3. **Entity-Relationship Mapping (Knowledge Graph)** — explicit nodes/edges for entities and their states; enables structured reasoning over history
4. **Context Sliding (FIFO)** — drop the oldest messages first when the window fills; simplest, but loses early context permanently
5. **Explicit "Save" Triggers (`update_memory` tool)** — agent decides what's worth keeping; highest precision, highest latency per save

## Seamless interaction with memory

Three patterns for making memory feel invisible to the user:

1. **Speculative Summarization (Background Worker)** — a background process updates the entity/profile summary every 5–10 messages, so the main agent never stalls on a "saving…" step
2. **Contextual Prompt Pruning (Pre-flight small model)** — run a cheap model before each LLM call to strip history that is unrelated to the current query; reduces noise without human involvement
3. **Entity-Driven KV Caching** — cache embeddings or summaries keyed by entity ID; avoids re-encoding the same entity on every turn

## Do we keep a massive knowledge graph?

**Dense beats massive.** A smaller, well-maintained graph outperforms a large, stale one — retrieval precision degrades as irrelevant nodes accumulate.

**"Librarian" Agent** — an offline process (e.g., nightly at 3 AM) that rebuilds or prunes the graph without blocking live requests.

Three graph-management strategies:

1. **Entity Lifecycle (TTL)** — nodes that haven't been referenced within a time window are expired; prevents unbounded growth
2. **Bridge Node Pattern** — only create nodes for Entities (people, projects, concepts) and States (current values); avoid nodes for individual events or utterances
3. **Hierarchical Pruning**
   - *Global Layer*: Permanent facts (user identity, long-term goals) — never pruned
   - *Project Layer*: Active build context — pruned when the project closes
   - *Session Layer*: Discarded at session end; only Project Layer changes are promoted by the "Reflector" agent

> **AI suggestion:** For a local agent, a graph exceeding 5,000–10,000 nodes often starts to introduce perceptible latency. Treat that as your hard ceiling before forcing a pruning run.

## Infrastructure

### Storage layers

| Layer | Technology | Role |
|-------|-----------|------|
| Structured DB | SQL / Document DB | Cold storage — facts, user profiles, long-term history |
| Vector DB | Pinecone, Qdrant, etc. | Semantic search — find relevant past context by meaning |
| Knowledge Graph | Neo4j, in-memory graph | Relational context — entity relationships and state transitions |
| State Storage | Redis / local file | Session-bound ephemeral state — cleared when the session ends |

### Commonly overlooked components

1. **The Scratchpad (Short-Term State)** — a fast, mutable workspace for the agent's in-progress reasoning; not persisted to long-term memory
2. **The Tool Registry (Dynamic)** — a live manifest of available tools; allows the agent to discover and invoke tools it wasn't explicitly given at startup
3. **The Observation Log** — records each tool result alongside meta-context (timestamp, which agent called it, confidence); enables replay and debugging

> **AI suggestion — The Local Edge:** In a hybrid setup, keep the Scratchpad and Observation Log in a fast local file or Redis instance. Routing these through a remote Cloud DB introduces per-thought latency that makes the agent feel sluggish.

## Why Redis?

Redis sits at the boundary between the two fundamental data paths in an agent system:

| Path | Flow | Purpose |
|------|------|---------|
| **User Path** | LLM → API → Streaming Tokens → Screen | Human-AI interaction — the words you read |
| **Action Path** | LLM → Tool Call → Redis Write → Local Agent | System-to-system coordination — where actual work executes |

Redis is the right choice for the Action Path because:

- **Sub-millisecond reads/writes** — keeps scratchpad and observation log from becoming bottlenecks
- **Pub/Sub** — lets the local agent subscribe to tool-call events without polling
- **TTL native support** — maps directly onto Session Layer and entity lifecycle expiry
- **Runs locally** — no network hop; critical for the snappiness of a local agent on a hybrid (e.g., WSL + Mac) setup
