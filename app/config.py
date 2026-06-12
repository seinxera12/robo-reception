from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # LLM
    llm_model: str = "groq/llama-4-scout"
    llm_fallback: str = "groq/llama-4-scout"
    groq_api_key: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://reception:reception@postgres:5433/reception"
    alembic_database_url: str | None = None 

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Notifications
    ntfy_host: str = "http://ntfy:8080"

    # Kiosk
    kiosk_id: str = "kiosk-01"
    base_url: str = "http://localhost:8000"

    model_config = {"env_file": ".env", "case_sensitive": False}
    
settings = Settings()