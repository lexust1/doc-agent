# ⚡ Doc Agent

**An Agentic RAG system for engineering standards and technical documentation.**

Doc Agent ingests complex regulatory PDFs (GOST, PUE, SNiP, etc.), normalises their content, and makes it searchable through a hybrid vector‑database. It then answers engineering questions with verbatim citations, without hallucinations.

---

## 🧱 Architecture: Two Independent Loops

### 1. Data Ingestion Pipeline (offline, heavy processing)
- **PDF slicing & physical rotation correction** (ONNX orientation model).
- **Layout analysis** with `Docling` (IBM) – extracts tables, formulas, figures.
- **Semantic normalisation** via a Vision‑Language Model (VLM) that “heals” raw Markdown, fixes headings, merges split tables, and converts formulas to LaTeX.
- **Structural chunking** based on document hierarchy (H1–H4).
- **Embedding** with local `BGE‑M3` (ONNX, CPU‑only) and indexing into a hybrid `Qdrant` collection (dense + BM25).

### 2. Query & Answer Pipeline (online, lightweight)
- **Hybrid search** (dense + BM25, fused with Reciprocal Rank Fusion).
- **Agentic reasoning loop** – question decomposition, relevance judging, iterative retrieval, faithfulness verification.
- **Streamlit UI** – chat interface with clickable source citations.

All components are vendor‑agnostic and can be switched from cloud APIs to local models when needed.

---

## 📂 Project Structure (highlights)

```
├── pipelines/ingestion_pipeline.py  ← entry point for batch processing
├── ui/app.py                        ← Streamlit chat interface
├── src/doc_agent/
│   ├── configs/                     ← Pydantic settings
│   ├── schemas/                     ← all data contracts (Pydantic)
│   ├── core/                        ← storage & state machine
│   ├── data/                        ← “dumb” parsers (Docling, PDF slicing, tagging)
│   ├── agents/                      ← LLM/VLM agents (OCR healer, answer generator)
│   ├── indexing/                    ← structural chunker, embedder, Qdrant writer
│   ├── retrieval/                   ← hybrid searcher
│   ├── reasoning/                   ← decomposer, judge, faithfulness checker
│   ├── prompts/                     ← version‑controlled system prompts
│   └── orchestrator.py              ← main pipeline conductor
├── models/                          ← downloaded ONNX models (BGE‑M3, orientation)
├── data/                            ← working directory (git‑ignored)
│   ├── 01_raw/
│   ├── 02_interim/
│   └── 03_processed/
└── docker-compose.yml               ← local Qdrant service
```

---

## ⚙️ Key Design Decisions

- **Idempotent pipeline** – every processing step is tracked in a `manifest.json`; re‑running only processes new or failed pages.
- **Strict data contracts** – all LLM/VLM outputs are parsed into Pydantic models (no free‑form JSON).
- **Hybrid retrieval** – combines semantic search with exact lexical matching (BM25) for article numbers and codes.
- **Faithfulness checker** – post‑generation verification that removes unsupported claims.
- **Thread‑safe document processing** – pages are normalised concurrently, with proper locking.

---

## 🚀 Quick Start

1. **Start Qdrant**
   ```bash
   docker compose up -d
   ```

2. **Install dependencies**
   ```bash
   pip install -e .
   ```

3. **Set environment variables** – create `.env` with:
   ```
   NANOGPT_API_KEY=your_key
   NANOGPT_BASE_URL=https://api.openai.com/v1   # or any OpenAI‑compatible endpoint
   ```

4. **Ingest documents**
   ```bash
   python pipelines/ingestion_pipeline.py
   ```
   PDFs from `data/01_raw/` will be processed, healed, chunked, and indexed into Qdrant.

5. **Launch the UI**
   ```bash
   streamlit run ui/app.py
   ```

---

# 📓 Research & Development Notebooks

Each notebook documents a specific milestone in the project, evolving from raw physical extraction to advanced semantic normalization and retrieval integration.

| Notebook | Focus Area | Key Deliverables & Technical Outcomes |
| :--- | :--- | :--- |
| [001_docling_pdf_parsing.ipynb](./notebooks/001_docling_pdf_parsing.ipynb) | **Stage 1: Physical Layout & Extraction** | Evaluated `Docling` against complex engineering standards. Catalogued 7 critical parsing artifacts (ghost tables, OCR overreach in schematics) and confirmed that disabling native OCR prevents “spaghetti text” while revealing the limits of heuristic parsing. |
| [002_semantic_normalization.ipynb](./notebooks/002_semantic_normalization.ipynb) | **Stage 2: Semantic Normalization & VLM Healing** | Developed a multimodal VLM agent to “heal” Markdown using high‑res page images. Implemented strict Pydantic data contracts for deterministic JSON responses. Achieved reconstruction of run‑in headings, borderless tables, and LaTeX formulas with zero hallucinations. |
| [003_docling_ast_xml_anchoring.ipynb](./notebooks/003_docling_ast_xml_anchoring.ipynb) | **XML Tagging & Attention Boundaries** | Intercepted the Docling AST to wrap elements in XML tags, creating ironclad attention boundaries that prevent context blending and mitigate the “middle‑drop” effect in large‑context VLMs. |
| [004_additional_testing_cases...](./notebooks/) | **Edge Cases Stress Testing** | Batch‑tested the VLM on vertical/horizontal tables, rotated pages, multiple drawings per page, and embedded images. Refined the Native CoT prompt to handle complex headers and placeholders without duplicating text or splitting tables. |
| [005_orchestrator_test.ipynb](./notebooks/005_orchestrator_test.ipynb) | **Pipeline Orchestration Mock** | Built the `DocumentOrchestrator` state machine. Validated `LocalStorageManager` and `LocalManifestManager` for idempotent page transitions (`PENDING → TAGGED → CLEANED`) via `manifest.json`. |
| [006_pdf_processor_test.ipynb](./notebooks/006_pdf_processor_test.ipynb) | **Physical Normalization** | Implemented `pypdfium2` + ONNX (`PP‑LCNet`) rotation detection. Proved that physically rotating pages to 0° before parsing eliminates structural errors. |
| [007_pdf_to_markdown_test.ipynb](./notebooks/007_pdf_to_markdown_test_1.ipynb) | **End‑to‑End Integration** | Validated the full extraction loop in `src/doc_agent/`: Slicing → AST Tagging → VLM Healing. Confirmed production code matches notebook R&D exactly. |
| [008_aggregation_and_chunking_test.ipynb](./notebooks/008_aggregation_and_chunking_test.ipynb) | **Semantic Chunking & Aggregation** | Merged healed pages with HTML anchors. Developed `StructuralChunker` to slice by H1–H4 headers and map physical PNG artifacts into `VectorPayload` metadata for Qdrant. |
| [009_retrieval_stack_rationale.ipynb](./notebooks/009_retrieval_stack_rationale.ipynb) | **Retrieval Stack Rationale & Integration Testing** | Documented the architectural decision for Qdrant (native hybrid search, automatic BM25, sub‑10 ms latency, strong payload filtering) and BGE‑M3 ONNX (dense 1024‑dim vectors). Performed hands‑on integration: downloaded and tested the BGE‑M3 ONNX model, created Qdrant collections (dense‑only and hybrid), upserted real payloads, executed dense and hybrid search with Reciprocal Rank Fusion, and validated the full retrieval chain through `HybridSearcher`, `AnswerGeneratorAgent`, and `AgenticAnswerAgent`. Confirmed end‑to‑end correctness and benchmarked hybrid retrieval quality |

---