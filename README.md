# ⚡ Doc Agent

**An Agentic RAG system for engineering standards and technical documentation.**

Doc Agent ingests complex engineering standards and regulatory PDFs (such as ISO, IEEE, DIN, etc), normalizes their content, and makes it searchable through a hybrid vector database. It answers technical queries with exact citations, eliminating hallucinations.

---

## 🧱 Architecture: Two Independent Loops

### 1. Data Ingestion Pipeline (offline, heavy processing)
- **Handling Complex Layouts:** PDF slicing & orientation correction (`PP-LCNet`), followed by deep layout analysis (`Docling`) to extract raw tables, formulas, and figures from dense engineering standards.
- **LLM-Driven Deep Structuring & Normalization:** A Vision‑Language Model (VLM) performs the heavy semantic lifting. It "heals" raw Markdown and transforms chaotic text into strictly structured blocks. It explicitly identifies and tags semantic entities (e.g., definitions, regulatory requirements, lists), merges split multi-page tables, and converts formulas to LaTeX.
- **Intelligent Tagging & Structural Chunking:** Cleaned data is chunked dynamically based on document hierarchy (H1–H4). Each chunk is further enriched with metadata tags, preserving the global structure of the standard and explicitly guiding the LLM’s attention during retrieval.
- **Hybrid Vector Database:** Embedding with local `BGE‑M3` (ONNX, CPU‑only) and indexing into a hybrid `Qdrant` collection (dense + BM25).
- **State Management & Storage:** Idempotent execution backed by a state machine. Uses Local File System + JSON for local runs, and **AWS S3 + PostgreSQL (RDS)** for cloud-scale execution.

### 2. Query & Answer Pipeline (online, lightweight)
- **Context-Aware Retrieval:** Hybrid search (dense + BM25) fused with Reciprocal Rank Fusion, leveraging the injected metadata to filter noise.
- **Agentic Reasoning Loop:** Question decomposition, relevance judging, iterative retrieval, and strict faithfulness verification to ensure verbatim citations.
- **Streamlit UI:** Chat interface with clickable source citations.

> **Note:** All components are vendor‑agnostic. The entire stack can be run locally or deployed to AWS via Terraform.

---

## 📂 Project Structure (highlights)

```text
├── configs/                 ← Global configuration files
├── data/                    ← Working directory for runtime data
├── docker/                  ← Docker setups (local/AWS/test)
├── docs/                    ← Additional documentation and guides
├── models/                  ← Downloaded ONNX models
├── pipelines/               ← Entry points for batch processing
├── src/doc_agent/           ← Core application (agents, RAG, parsers, DB integration)
├── terraform/               ← AWS Infrastructure as Code (EC2, RDS, S3, ECR)
├── tests/                   ← Test suite
├── ui/                      ← Streamlit chat interface
└── makefile                 ← Automation (build, push, terraform deploy)
```
*(For a complete file tree, see the "Detailed Data" section below).*

---

## ⚙️ Key Design Decisions

- **VLM Cost & Accuracy Optimization:** By transitioning from forced JSON schemas to Native CoT and Semantic XML Tagging, the pipeline broke through the **20–30% error ceiling** typical for complex layout extraction. Crucially, this architecture enables the use of **lightweight, cost-effective models** (like GPT-4o-mini / NanoGPT) instead of expensive flagship LLMs, while simultaneously reducing output token consumption and response latency by **30–50%**.
- **Strict Data Contracts:** All downstream LLM/VLM outputs are validated against strictly typed Pydantic models. We completely bypass fragile free-form JSON parsing, ensuring 100% predictable system behavior.
- **Zero-Dependency Hybrid Retrieval:** Fuses semantic search with exact lexical matching (BM25) natively within Qdrant. This architecture achieves **91% recall@10** (compared to 78% for pure dense vectors), successfully capturing both conceptual intent and exact regulatory citations.
- **Concurrent & Thread-Safe:** Page isolation and VLM normalization run concurrently. Robust thread-locking mechanisms prevent race conditions during manifest updates, maximizing throughput.
- **Agentic Faithfulness Verification:** A dedicated post-generation verification loop cross-references the LLM's answer against the retrieved chunks, actively stripping out any claims not explicitly backed by the verbatim text to guarantee a hallucination-free response.
- **Idempotent ETL Execution:** Document processing state is tracked at the granular page level via a manifest (`ManifestManager`). Re-running the pipeline gracefully resumes from interruptions, processing only new or previously failed pages, which drastically reduces redundant API costs.
- **Infrastructure as Code (IaC):** Fully automated AWS deployment via Terraform (EC2, S3, RDS). The entire environment is orchestrated via a single `Makefile` command, ensuring repeatable and efficient environment setup.

---

## 🚀 Deployment & Quick Start

You can run Doc Agent completely locally or deploy it to AWS.

### Option A: Local Run

1. **Start infrastructure** (Qdrant, local Postgres, MinIO):
   ```bash
   docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml up -d
   ```

2. **Install dependencies**:
   ```bash
   pip install -e .
   ```

3. **Set environment variables** – create `.env` with:
   ```env
   DEPLOYMENT_MODE=local
   NANOGPT_API_KEY=your_key
   NANOGPT_BASE_URL=[https://api.openai.com/v1](https://api.openai.com/v1)
   ```

4. **Ingest documents**:
   ```bash
   python pipelines/pipeline.py
   ```
   PDFs from `data/01_raw/` will be processed, healed, chunked, and indexed into Qdrant.

5. **Launch the UI**:
   ```bash
   streamlit run ui/app.py
   ```

### Option B: Cloud Deployment (AWS & Terraform)

The project features a mature Infrastructure-as-Code (IaC) setup. Rather than running everything on a single monolithic server, the architecture enforces a strict separation of concerns to optimize compute costs and security.

#### 1. AWS Architecture Topology
When you trigger the deployment, Terraform automatically provisions the following resources within a dedicated VPC:
- **AWS S3:** Acts as the central data lake for raw PDFs and high-res rendered artifacts.
- **AWS RDS (PostgreSQL):** Hosts the state machine (`ManifestManager`) to track idempotent ETL execution.
- **Backend EC2 (Compute-Optimized):** An isolated instance dedicated to the offline, heavy-lifting Data Ingestion Pipeline (VLM normalization, chunking, and vector embedding).
- **Frontend EC2 (Lightweight):** Hosts the online Query Pipeline, including the Qdrant vector database and the Streamlit chat interface.

#### 2. Deployment Guide

**Step 1: Prerequisites & Authentication**
Ensure you have the AWS CLI and Terraform installed locally. Authenticate your terminal with your AWS environment:
```bash
aws configure
# Enter your AWS Access Key, Secret Key, and default region (e.g., eu-central-1)
```

**Step 2: Provision Infrastructure**
Initialize and apply the Terraform configuration via the provided Makefile. This step creates the network, security groups, database, storage, and compute instances.
```bash
make deploy
```

**Step 3: Configuration Injection & Backend Ingestion**
We avoid manual `.env` file management in the cloud. Once Terraform finishes provisioning, it dynamically parses the new infrastructure endpoints (S3 bucket name, RDS connection string, Qdrant IP) and generates a ready-to-use Docker execution command.

1. Terraform will output an SSH command to connect to your newly provisioned Backend EC2 instance.
2. It will also output a dynamically populated `docker run` command containing all the necessary environment variables.
3. Simply SSH into the Backend EC2, copy-paste the provided `docker run` command, and the idempotent ingestion pipeline will begin processing your documents.

**Step 4: Access the Application**
The Terraform output will explicitly provide the public URLs for your deployed services:
- **Streamlit UI:** `http://<frontend-public-ip>:8501`
- **Qdrant Dashboard:** `http://<frontend-public-ip>:6333/dashboard` (Secured via security groups).

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
| [009_retrieval_stack_rationale.ipynb](./notebooks/009_retrieval_stack_rationale.ipynb) | **Retrieval Stack Rationale & Integration Testing** | Documented the architectural decision for Qdrant (native hybrid search, automatic BM25, sub‑10 ms latency, strong payload filtering) and BGE‑M3 ONNX (dense 1024‑dim vectors). Performed hands‑on integration: downloaded and tested the BGE‑M3 ONNX model, created Qdrant collections (dense‑only and hybrid), upserted real payloads, executed dense and hybrid search with Reciprocal Rank Fusion, and validated the full retrieval chain through `HybridSearcher`, `AnswerGeneratorAgent`, and `AgenticAnswerAgent`. Confirmed end‑to‑end correctness and benchmarked hybrid retrieval quality |

---

# More detailed data

## 1. What the project does (in one paragraph)

Doc Agent ingests complex engineering PDFs, normalises their content with a Vision‑Language Model (VLM), stores them as searchable chunks in a hybrid vector database (Qdrant), and answers user questions by retrieving those chunks and generating verbatim citations. It has two independent loops: a heavy **offline pipeline** that processes documents and builds the index, and a lightweight **online pipeline** that answers queries via a Streamlit UI.

---

## 2. High‑level architecture

```text
[Raw PDFs] 
    ↓ offline pipeline
[Sliced pages → Tagged Markdown → Healed Markdown → Aggregated document]
    ↓ structural chunking + embedding
[Qdrant hybrid collection (dense + BM25)]
    ↓ online pipeline
[User query → Hybrid search → Answer generation (simple or agentic)]
    ↓
[Streamlit UI with clickable citations]
```

The offline pipeline is run once per document. The online pipeline is triggered by user questions in the UI. Both are designed to be idempotent – you can re‑run them without duplicating work.

---

## 3. Repository layout & what lives where

```text
project root
├── data/                             ← Runtime data workspace (git-ignored)
│   ├── 01_raw/                       ← Source PDFs placement
│   ├── 02_interim/                   ← Per-document workspaces (pages, tagged, healed)
│   └── 03_processed/                 ← Processed outputs (currently unused)
├── docker/                           ← Dockerfiles and Compose setups (local/AWS/test)
├── models/                           ← Downloaded ONNX models (BGE-M3, orientation)
├── pipelines/
│   └── pipeline.py                   ← ENTRY POINT for batch processing (offline loop)
├── src/
│   └── doc_agent/
│       ├── agents/
│       │   ├── agentic_answer_agent.py   ← Advanced agent (decompose + judge + verify)
│       │   ├── answer_generator.py       ← Simple RAG generator
│       │   └── ocr_healer.py             ← VLM normalisation agent
│       ├── configs/
│       │   └── settings.py               ← Global configuration (paths, keys, Qdrant, DB)
│       ├── indexing/
│       │   ├── embedder.py               ← BGE-M3 ONNX embedding service
│       │   ├── qdrant_manager.py         ← Qdrant collection creation and upsert
│       │   └── structural_chunker.py     ← H1-H4 text chunking logic
│       ├── infrastructure/
│       │   ├── index_manifest_manager.py ← Indexing state tracker
│       │   ├── manifest_manager.py       ← Local JSON page-level state machine
│       │   ├── sql_manifest_manager.py   ← PostgreSQL state machine for AWS
│       │   └── storage.py                ← Local & S3 storage implementations
│       ├── ingestion/
│       │   ├── content_extractor.py      ← Docling parsing with XML tagging
│       │   ├── document_aggregator.py    ← Merge healed pages into single JSON
│       │   ├── pdf_processor.py          ← Slicing and rotation detection
│       │   ├── semantic_tagger.py        ← AST to XML tag wrapping
│       │   └── workflow.py               ← COORDINATOR: process_document + step functions
│       ├── prompts/
│       │   ├── answer_generation.md      ← Final answer generation instructions
│       │   ├── faithfulness_check.md     ← Hallucination verification instructions
│       │   ├── ocr_healing.md            ← VLM markdown healing instructions
│       │   ├── query_decomposition.md    ← Question splitting instructions
│       │   └── relevance_evaluation.md   ← Chunk relevance grading instructions
│       ├── reasoning/
│       │   ├── faithfulness_checker.py   ← Checks output against chunks
│       │   ├── query_decomposer.py       ← Splits complex queries
│       │   └── relevance_judge.py        ← Scores retrieval relevance
│       ├── retrieval/
│       │   └── hybrid_searcher.py        ← Dense + BM25 search with RRF
│       ├── schemas/
│       │   ├── aggregated_doc.py         ← Aggregated document models
│       │   ├── index_manifest.py         ← Indexing tracker models
│       │   ├── llm_contracts.py          ← I/O models for LLMs
│       │   ├── manifest.py               ← Core state models (DocumentManifest, etc.)
│       │   └── vector_payload.py         ← Database chunk and metadata models
│       ├── utils/
│       │   └── logger.py                 ← Standardised logging setup
│       └── main.py                       ← Application entry point
├── terraform/                        ← AWS Infrastructure code (EC2, S3, RDS, ECR)
├── tests/                            ← Minimal test suite
├── ui/
│   └── app.py                        ← Streamlit UI (online query interface)
├── .env                              ← API keys and URLs (loaded by Pydantic)
├── makefile                          ← Automation (build, push, terraform deploy)
├── pyproject.toml                    ← Project metadata & dependencies
├── README.md                         ← Main documentation
└── ROADMAP.md                        ← Project milestones and future plans
```

---

## 4. The offline pipeline (document processing + indexing)

**Entry point:** `python pipelines/pipeline.py`

This script runs the batch workflow for every PDF in `data/01_raw/`. Here’s how it operates step-by-step:

1. **Load the VLM system prompt** from `prompts/ocr_healing.md`.
2. **Discover PDFs** in `data/01_raw/`. *(If running in AWS mode, it automatically syncs source PDFs from the S3 bucket to the local EC2 workspace).*
3. **Initialize shared services**: `StructuralChunker`, `Embedder`, `QdrantManager`, and ensure the target Qdrant collection exists. *(In AWS mode, it also initializes the RDS PostgreSQL connection pool).*
4. **For each PDF:**
   - **Check indexing status** via `LocalIndexManifestManager`. If already indexed → skip.
   - **Call `process_document(pdf_path, system_prompt)`** from `ingestion/workflow.py`. This orchestrator function:
     - Creates an isolated workspace under `data/02_interim/<doc_id>/`.
     - Instantiates the appropriate Storage & Manifest Managers (`LocalStorageManager`/`LocalManifestManager` for local execution, or `S3StorageManager`/`SQLManifestManager` for AWS) and the `OCRHealerAgent`.
     - Builds a `PipelineContext` to bundle all shared state.
     - Runs the normalization steps **sequentially** (each step is idempotent, driven by the manifest):
       1. **`slice_pages(ctx)`** – physically slices the PDF into single‑page PDFs and high-res PNGs, correcting any physical rotation (`PP-LCNet`). Registers file paths in the manifest.
       2. **`tag_pages(ctx)`** – processes each page in parallel (via thread pool):
          - Reads the per‑page PDF, runs layout analysis via `content_extractor.parse_document` (Docling) to extract XML‑tagged Markdown.
          - Saves the tagged Markdown to `03_md_tagged/` and registers extracted figures.
          - Updates the page status to `TAGGED`.
       3. **`heal_pages(ctx)`** – processes pages with `TAGGED` status in parallel:
          - Reads the tagged Markdown and the corresponding high-res PNG.
          - Calls `agent.normalize_page(tagged_text, image, prompt)` (VLM API call via Native CoT) to produce clean, hallucination-free Markdown.
          - Saves the clean Markdown to `04_md_clean/` and updates the page status to `CLEANED`.
       4. **`aggregate_pages(ctx)`** – reads all `CLEANED` pages, merges them into a single `AggregatedDocument` (injecting HTML page anchors for exact citation tracking), saves as JSON, and marks the document status as `COMPLETED`.
     - Returns the `AggregatedDocument` or `None`.
   - **If aggregation succeeded**:
     - Reloads the manifest to fetch the latest artifact paths.
     - **Structural chunking**: `chunker.process_document(agg_doc, manifest.state)` splits the aggregated text into `VectorPayload` objects (bounded by H1‑H4 headers). Each payload carries hierarchical metadata, document IDs, page numbers, and PNG paths.
     - **Save payloads** as JSON under `06_payloads/` for debugging and potential re‑indexing without re-running the VLM.
     - **Embed & Upsert**: `QdrantManager.upsert_payloads` embeds the chunk text using local BGE‑M3 and inserts the dense vectors into Qdrant, which automatically generates and fuses sparse (BM25) vectors for the collection.
     - **Mark as indexed** via `LocalIndexManifestManager`.
5. **If any document fails**, the error is safely logged, and the pipeline proceeds to the next PDF.

**Key design points:**
- The entire per‑document normalization is **strictly idempotent**: per-page status is recorded in the manifest. Re‑running the pipeline resumes exactly where it left off, avoiding redundant API costs.
- Concurrency is managed via `ThreadPoolExecutor` within each step. The Manifest Manager uses thread locks (and PostgreSQL transactions in AWS mode) to prevent race conditions.
- The `pipeline.py` script serves as a thin execution loop; the heavy orchestration and error handling reside cleanly within `ingestion/workflow.py`.

---

## 5. The online pipeline (query & answer)

**Entry point:** `streamlit run ui/app.py`

The Streamlit UI loads heavy resources (embedder model, Qdrant client, agent configurations) once into the session cache. User queries follow two distinct paths:

### 5.1 Simple mode (default)
1. User types a question and submits.
2. `AnswerGeneratorAgent.generate(question, system_prompt)` is triggered:
   - **Hybrid search**: `HybridSearcher.search` performs a single-pass search, fusing dense (BGE-M3) and sparse (BM25) results using Reciprocal Rank Fusion (RRF).
   - **Context building**: Retrieved chunks are formatted into a structured context block.
   - **LLM call**: The context and question are sent to the LLM (`TARGET_MODEL`) using the `answer_generation.md` prompt.
   - **Parsing**: The response is strictly parsed into an `AnswerResult` model (containing the answer text and source citations).
3. The answer, along with clickable citations pointing to the exact document pages, is rendered in the chat UI.

### 5.2 Advanced mode (checkbox “🧠 Advanced reasoning”)
When enabled, the pipeline switches to `AgenticAnswerAgent.generate`, executing a multi-step verification loop:
1. **Question decomposition**: `QueryDecomposer.decompose` uses the LLM to break complex questions into multiple distinct sub‑queries.
2. **For each sub‑query**:
   - **Iterative retrieval**: `HybridSearcher.search` fetches candidate chunks.
   - **Relevance judging**: `RelevanceJudge.evaluate` scores the chunks. If relevance is low, the agent autonomously rewrites the query and retries (up to `AGENT_MAX_RETRIEVAL_ATTEMPTS`).
3. **Aggregation**: All highly relevant chunks across all sub-queries are deduplicated and passed to the Answer Generator.
4. **Faithfulness check (Hallucination Guard)**: `FaithfulnessChecker.check` cross-references the generated answer against the retrieved chunks. Any claims not explicitly supported by the verbatim text are actively removed.
5. The final, verified answer is displayed to the user.

*Note: This loop adds inference latency and API cost but significantly improves accuracy and safety for complex, multi‑section engineering questions.*

---

## 6. Key schemas (data contracts)

To ensure system predictability, all data flowing between components bypasses fragile JSON parsing and is strictly validated using Pydantic models:

- **`DocumentManifest`** (`schemas/manifest.py`): Tracks a document’s global status and granular per‑page state (`PENDING → TAGGED → CLEANED`). Acts as the source of truth for the state machine and stores page artifact paths.
- **`AggregatedDocument`** (`schemas/aggregated_doc.py`): The final output of the ingestion pipeline. Contains a list of page contents and a continuous `full_text` string injected with HTML anchors for exact retrieval mapping.
- **`VectorPayload`** (`schemas/vector_payload.py`): Represents a text chunk and its `PayloadMetadata` (document ID, specific page numbers, H1-H4 headers, and associated artifacts). This is the exact object embedded and stored in Qdrant.
- **`AnswerResult`** (`schemas/llm_contracts.py`): The structured answer returned from the online LLM, containing the final answer string and a validated list of `SourceInfo` objects for UI citation mapping.
- **`NormalizationResult`** (`schemas/llm_contracts.py`): The structured output contract for the offline VLM step, ensuring the healed Markdown is properly encapsulated and separated from the model's internal reasoning or metadata.
