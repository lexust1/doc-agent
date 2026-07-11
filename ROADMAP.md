## 📈 Roadmap

Current status: ingestion & indexing complete; agentic answer loop implemented;  
UI with advanced reasoning checkbox available; AWS cloud deployment (IaC) established.  
Next steps: cross‑encoder reranker, golden‑dataset evaluation, multimodal retrieval (ColPali).

---

## 🧪 Research & Development

All experiments are recorded in the `notebooks/` directory, covering:
- Docling baseline evaluation (artifacts, ghost tables)
- VLM healing prompts & Pydantic output contracts
- XML tagging for attention boundaries
- Page rotation detection and physical correction
- Aggregation and structural chunking

These notebooks document the journey from raw PDF to a fully queryable knowledge base, but they are not part of the production code.

---

## 📜 License

This project is an internal research tool. All normative documents remain the property of their respective publishers. The code is provided for educational and demonstrative purposes.

---

## Milestone 1: Foundation & Physical Parsing
- [x] Project architecture with isolated `src/` and `notebooks/`.
- [x] Stress‑test page selection from PUE (heavy tables, formulas, schematics).
- [x] Docling baseline – artifact catalog, no‑OCR decision.
- [x] Physical rotation correction with ONNX (`PP‑LCNet`).

## Milestone 2: Semantic Normalisation (OCR Healing)
- [x] VLM‑based healing agent (zero hallucinations).
- [x] Pydantic structured output for deterministic parsing.
- [x] Restoration of ghost tables, run‑in headings, LaTeX formulas.
- [x] Prompt versioning & finalisation.

## Milestone 3: Edge Cases & Smart Routing
- [x] Multi‑scenario stress tests (dense schematics, nested tables, image placeholders).
- [x] Benchmark across VLM models (cost / speed / accuracy).
- [ ] Heuristic smart router to skip VLM for simple text pages.

## Milestone 4: Aggregation & Structural Chunking
- [x] State‑machine manifest (`manifest.json`) for idempotent execution.
- [x] Document aggregation with HTML page anchors.
- [x] Structural chunker based on H1‑H4 headers.
- [x] Vector payload data contracts for Qdrant.

## Milestone 5: Retrieval Engine & Agentic Workflow
- [x] Qdrant hybrid collection (dense + BM25).
- [x] Local BGE‑M3 embeddings (ONNX, CPU).
- [x] Hybrid searcher with Reciprocal Rank Fusion.
- [x] Agentic answer loop (question decomposition → relevance judging → retrieval retries).
- [x] Faithfulness checker (unsupported claim removal).
- [x] Streamlit chat UI with source citations and advanced reasoning checkbox.
- [x] Pipeline refactored into functional per‑document workflow (`pipelines/pipeline.py` + `ingestion/workflow.py`).
- [ ] Cross‑encoder reranker (improve top‑k precision).
- [ ] Golden‑dataset evaluation (50 real engineering questions).

## Milestone 6: Cloud Infrastructure & DevOps (IaC)
- [x] Dockerization of Streamlit UI and pipeline services.
- [x] AWS infrastructure provisioning via Terraform (EC2, S3, RDS, ECR).
- [x] PostgreSQL backend for `ManifestManager` state tracking.
- [x] S3 integration for robust artifact storage.
- [x] Automated deployment workflow via `Makefile`.

## Milestone 7: Multimodal RAG (Future)
- [ ] ColPali integration for direct image‑based retrieval of schematics.
- [ ] Figure‑to‑answer pipeline with visual context.
- [ ] Local LLM fallback (Qwen / Llama) for offline mode.