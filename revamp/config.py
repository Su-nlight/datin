"""
app/config.py
=============
Single source of configuration truth for the whole app.

Replaces every `load_dotenv("API.env")` call that used to live at the top
of pineconedb.py, database.py, evaluator.py, llm_provider.py, memory.py,
auth.py, ragroute.py, main.py, and everything under testing_folder/.

Nothing else in the codebase should call load_dotenv() or os.getenv()
directly after this migration — inject `Settings` (via get_settings())
wherever a value is needed instead.
"""
from functools import lru_cache
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="API.env", extra="ignore")

    # ---- LLM providers -----------------------------------------------
    LLM_PROVIDER: str = "gemini"
    GENAI_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1"
    XAI_API_KEY: str = ""
    GROK_MODEL: str = "grok-4-fast-reasoning"
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_API_KEY: str = "" 

    # Generation and evaluation providers are resolved independently now —
    # the repo added get_generation_llm()/get_evaluation_llm() so the judge
    # (used for RAG scoring, code-quality eval, and benchmark judging) can
    # be swapped without touching the model that actually generates
    # responses. Both default to "gemini" if unset, matching upstream.
    GENERATION_LLM_PROVIDER: str = "gemini"
    EVALUATION_LLM_PROVIDER: str = "gemini"

    # ---- Benchmark suite -------------------------------------------------
    # Comma-separated list of providers the benchmark suite should build a
    # generation scenario for (each becomes "<provider>_no_heal" /
    # "<provider>_heal"). Defaults to the historical gemini-vs-ollama pair
    # so existing runs/reports keep working, but any of "gemini", "ollama",
    # "grok", "groq" can be added/removed here — the benchmark runner reads
    # this instead of hardcoding two fixed providers.
    BENCHMARK_PROVIDERS: str = "gemini,ollama"

    @property
    def benchmark_provider_list(self) -> List[str]:
        return [p.strip().lower() for p in self.BENCHMARK_PROVIDERS.split(",") if p.strip()]

    # ---- Pinecone / embeddings ----------------------------------------
    PINECONE_API_KEY: str = ""
    INDEX_NAME: str = ""
    MODEL: str = "BAAI/bge-large-en-v1.5"
    SIMILARITY: str = "cosine"
    CLOUD: str = "aws"
    REGION: str = "us-west-2"
    MIN_SCORE: float = 0.75

    # NOTE: the old code split this concept across THREE separate names
    # (NAMESPACES / NAMESPACE / NAMESPACE_MITRE / NAMESPACE_EXDB). We keep
    # one canonical list here; the ingestion-specific namespaces are kept
    # separate on purpose because they really are different indices,
    # but application query code should only ever use NAMESPACES.
    NAMESPACES: str = "mitre_stix,exploit_db"
    NAMESPACE_MITRE: str = "mitre_stix"
    NAMESPACE_EXDB: str = "exploit_db"
    EMBED_FIELD: str = ""
    EMBED_FIELDS_EXDB: str = ""

    DATA_DIR_MITRE: Optional[str] = None
    DATA_DIR_EXDB: Optional[str] = None

    @property
    def namespace_list(self) -> List[str]:
        return [n.strip() for n in self.NAMESPACES.split(",") if n.strip()]

    # ---- MySQL ----------------------------------------------------------
    MYSQL_HOST: str = "localhost"
    MYSQL_DATABASE: str = ""
    MYSQL_USER: str = ""
    MYSQL_PASSWORD: str = ""

    # ---- Redis / chat memory --------------------------------------------
    REDIS_URL: str = "redis://localhost:6379"
    CHAT_SESSION_TTL: int = 86400
    CHAT_MAX_TURNS: int = 8

    # ---- JWT / auth -------------------------------------------------------
    JWT_SECRET_KEY: str
    JWT_REFRESH_SECRET_KEY: str
    JWT_ALGO: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ---- CORS -------------------------------------------------------------
    ALLOWED_ORIGINS: str = "*"

    @property
    def allowed_origins_list(self) -> List[str]:
        return self.ALLOWED_ORIGINS.split(",")

    # ---- Voice (Twilio/Deepgram) -------------------------------------------
    DEEPGRAM_API_KEY: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_ACCOUNT_SID: str = ""
    PUBLIC_BASE_URL: str = ""

    # ---- Testing / benchmarking ---------------------------------------------
    BENCHMARK_RESULTS_DIR: str = "benchmark_results"
    AB_RESULTS_FILE: str = "ab_results.json"

    @field_validator("LLM_PROVIDER")
    @classmethod
    def _validate_provider(cls, v: str) -> str:
        if v.lower() not in ("gemini", "ollama", "grok", 'groq'):
            raise ValueError("LLM_PROVIDER must be 'gemini', 'ollama', 'grok' & 'groq'.")
        return v.lower()


@lru_cache
def get_settings() -> Settings:
    """
    Cached singleton. Import this everywhere instead of calling
    Settings() directly — lru_cache means the .env file is parsed once
    for the whole process, and pydantic raises immediately at first
    access if a required var (JWT_SECRET_KEY etc.) is missing, instead
    of failing silently deep inside a request handler.
    """
    return Settings()