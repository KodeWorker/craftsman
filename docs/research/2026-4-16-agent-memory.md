# Agent Memory

## How to manage agent memory
- Semantic Compression (The "Summary" Layer)
- Hierarchical RAG (Vector Embeddings)
- Entity-Relationship Mapping (Knowledge Graph)
- The "Last-In, First-Out" Context Sliding
- Explicit "Save" Triggers (`update_memory` tool)

## Seamlessly interaction with memory
1. Speculative Summarization (The Background Worker): updates profile every 5-10 messages
2. Contextual Prompt Pruning (small agent pre-flight): use small model to filter out unrelated history
3. Entity-Driven KV Caching

## Do we keep massive knowledge graph?
Dense beats massive
"Librarian" Agent: build graph @ 3AM

1. Entity Lifecycle (TTL)
2. The "Bridge" Node Pattern: only create nodes for Entities and States
3. Hierarchical Pruning
    - Global Layer: Permanent facts
    - Project Layer: Active builds
    - Session Layer: At the end of a session, the "Reflector" agent promotes only the Project Layer changes and discards the Session Layer.

- Gemini suggestion:
For a local agent, a graph exceeding 5,000–10,000 nodes often starts to introduce perceptible latency

## Infrustructures
- Structure DB: cold storage
- Vector DB: search information
- Knowledge Graph: context relationship
- State Storage: session-bound states

- What I overlooked:
    1. The Scratchpad (Short-Term State)
    2. The Tool Registry: Dynamic Tool Registry
    3. The Observation Log: tool result + meta-context
- Gemini sugguesion:
The Local Edge: In a hybrid setup, keeping the Scratchpad and Observation Log in a fast local file or Redis instance makes the agent feel snappy. If you forced these through a slow Cloud DB, you'd feel a "lag" between every thought.
