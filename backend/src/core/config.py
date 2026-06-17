from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # This is the connection string for your MySQL database.
    # It's best practice to set this from an environment variable.
    # Format: mysql+mysqlconnector://<user>:<password>@<host>:<port>/<dbname>
    DATABASE_URL: str

    class Config:
        env_file = ".env"

settings = Settings()