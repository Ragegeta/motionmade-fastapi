from typing import Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv
import os

# IMPORTANT: load .env BEFORE Settings() is created
load_dotenv()

class Settings(BaseSettings):
    DATABASE_URL: str
    OPENAI_API_KEY: str
    ADMIN_TOKEN: str
    JWT_SECRET: str = ""
    EMBED_MODEL: str = "text-embedding-3-small"
    CHAT_MODEL: str = "gpt-4o-mini"
    BUILD_ID: str = "local-dev"
    DEBUG: bool = False

    # ReviewMate: Google Business Profile OAuth (optional; required only for /reviews)
    REVIEW_GOOGLE_CLIENT_ID: Optional[str] = None
    REVIEW_GOOGLE_CLIENT_SECRET: Optional[str] = None
    REVIEW_GOOGLE_REDIRECT_URI: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
