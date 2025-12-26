"""
Production entrypoint.

DO NOT put business logic here.
All logic lives in app/main.py so onboarding stays data-only.
"""
from app.main import app  # uvicorn will load "main:app"