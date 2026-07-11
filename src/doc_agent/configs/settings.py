from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """
    Project configuration manager using Pydantic Settings.
    
    This class acts as a central hub for environment variables and 
    system paths, providing validation and auto-loading from .env files.
    """

    # --- DEPLOYMENT MODE ---
    # Switches between local and cloud (AWS) environments.
    # Valid values: "local" (default) or "aws".
    DEPLOYMENT_MODE: str = "local"

    # --- PROJECT PATHS ---
    # Automatically resolve the project root (3 levels up from this file)
    PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

    # Core data directories based on the project manifest structure
    RAW_DIR: Path = PROJECT_ROOT / "data" / "01_raw"
    PROCESSING_DIR: Path = PROJECT_ROOT / "data" / "02_interim"
    PROCESSED_DIR: Path = PROJECT_ROOT / "data" / "03_processed"

    # Directory to LLM prompts
    PROMPTS_DIR: Path = PROJECT_ROOT / "src" / "doc_agent" / "prompts"

    # --- API CONFIGURATION ---
    # Authentication keys for the LLM provider (Loaded from .env)
    NANOGPT_API_KEY: str
    NANOGPT_BASE_URL: str
    # Model selection for semantic normalization
    TARGET_MODEL: str = "openai/gpt-5-mini"

    # --- PIPELINE CONFIGURATION ---
    # Maximum number of concurrent threads for page processing
    MAX_WORKERS: int = 3

    # --- QDRANT CONFIGURATION ---
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None   

    # Directory to the local ONNX embedding model (BGE-M3)
    EMBEDDING_MODEL_DIR: Path = PROJECT_ROOT / "models" / "bge_m3_onnx" / "onnx"

    # Default Qdrant collection to use for ingestion
    QDRANT_COLLECTION_NAME: str = "pue_chunks"

    # Maximum number of texts passed to the ONNX embedder in one call
    EMBED_BATCH_SIZE: int = 8

    # Configuration for environment variable loading and behavior
    model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding='utf-8',
            extra="ignore"
        )

    # --- AGENTIC RAG CONFIGURATION ---
    # Maximum retrieval attempts per sub‑query before giving up.
    AGENT_MAX_RETRIEVAL_ATTEMPTS: int = 3

    # Minimum relevance score (1‑5) required to accept a retrieved chunk set.
    AGENT_RELEVANCE_THRESHOLD: int = 3
    
    # --- AWS / CLOUD SETTINGS (used only when DEPLOYMENT_MODE = "aws") ---
    # S3 bucket for artifact storage (pages, PNGs, markdown).
    AWS_S3_BUCKET: Optional[str] = None
    # AWS region where resources are located.
    AWS_REGION: str = "us-east-1"
    # PostgreSQL connection string for RDS (e.g. "postgresql://user:pass@host:5432/db").
    DATABASE_URL: Optional[str] = None
     
    # Configuration for environment variable loading and behavior
    model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding='utf-8',
            extra="ignore"
        )
    
# Instantiate a global settings object for project-wide use
# We use # type: ignore to satisfy static checkers like Pylance 
# since values are injected at runtime from the .env file.
settings = Settings()  # type: ignore