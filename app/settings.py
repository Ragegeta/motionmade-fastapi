from pydantic_settings import BaseSettings
from dotenv import load_dotenv
import os

# IMPORTANT: load .env BEFORE Settings() is created
load_dotenv()

class Settings(BaseSettings):
    DATABASE_URL: str
    OPENAI_API_KEY: str
    ADMIN_TOKEN: str
    EMBED_MODEL: str = "text-embedding-3-small"
    CHAT_MODEL: str = "gpt-4o-mini"
    BUILD_ID: str = "local-dev"
    DEBUG: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
