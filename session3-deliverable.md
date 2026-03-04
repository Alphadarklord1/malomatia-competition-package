# Session 3 Deliverable: Domain-Specific RAG Assistant

## Product Upgrade
The prototype now includes a **Knowledge Assistant** page that answers operational questions using a retrieval pipeline over Malomatia public-service policy knowledge.

## Problem Solved
Operators and supervisors need fast, policy-grounded answers while triaging multilingual government cases. Manual lookup across SOPs delays decisions and causes inconsistent routing.

## Domain-Specific Data
- Knowledge corpus: `/Users/armankhan/Documents/malomatia-competition-package/domain_knowledge.json`
- Content scope:
  - Immigration urgency rules
  - Licensing and municipal routing policy
  - Human-review escalation policy
  - SLA policy
  - Privacy and audit controls

## Retrieval Pipeline (Session 3 Concepts)
- **Chunking**: token-window chunking with overlap (to preserve context continuity)
- **Vectorisation**: TF-IDF vectors per chunk
- **Retrieval**: cosine similarity over query and chunk vectors
- **Re-ranking**: score boosts for department hint, policy rule match, and keyword overlap
- **Grounding**: answer always includes retrieved citations (`DOC/CHUNK`)

Implementation:
- Engine: `/Users/armankhan/Documents/malomatia-competition-package/rag_engine.py`
- UI integration: `/Users/armankhan/Documents/malomatia-competition-package/gov_triage_dashboard.py` (`Knowledge Assistant` nav)

## LLM Limitation Controls
- Answers are constrained to retrieved chunks.
- If evidence is weak, assistant reports insufficient context.
- Retrieval trace is visible (base score, rerank score, keyword hits, reasons).
- Query audit logging stores query hash (not raw query) for privacy.

## Optional LLM Synthesis
- If `openai_api_key` is configured in secrets, the assistant uses an LLM to synthesize a grounded answer from retrieved chunks.
- Without key, deterministic grounded fallback is used.

## Validation Evidence
- Smoke validation includes RAG checks (`domain_knowledge.json` exists, index builds with chunks).
- Automated tests include retrieval/index behavior in `/Users/armankhan/Documents/malomatia-competition-package/tests/test_rag_engine.py`.
