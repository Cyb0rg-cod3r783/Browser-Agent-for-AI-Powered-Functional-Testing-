from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # LLM providers — at least one should be set for AI test generation
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL:   Optional[str] = "llama-3.1-8b-instant"
    GEMINI_API_KEY: Optional[str] = None

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
