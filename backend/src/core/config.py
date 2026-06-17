from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # This is the connection string for your MySQL database.
    # It's best practice to set this from an environment variable.
    # Format: mysql+mysqlconnector://<user>:<password>@<host>:<port>/<dbname>
    DATABASE_URL: str
    GEMINI_API_KEY: Optional[str] = None

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()