from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # General Application
    PROJECT_NAME: str = "Connector AI Assistant"
    ENVIRONMENT: str = "development"
    API_V1_STR: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    # PostgreSQL Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:admin123@localhost:5432/connector_ai_db"
    DATABASE_SYNC_URL: str = "postgresql://postgres:admin123@localhost:5432/connector_ai_db"

    # Redis Cache & Rate Limiting
    REDIS_URL: str = "redis://localhost:6379/0"

    # Security & JWT Auth
    JWT_SECRET: str = "super_secret_jwt_key_connector_ai_2026_xyz987"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ADMIN_EMAIL: str = "admin@ctrlbooks.com"
    ADMIN_PASSWORD: str = "CtrlBooks@2026!Admin"
    SECURITY_IP_WHITELIST: str = "127.0.0.1,::1,191.44.87.1,191.44.87.206,210.56.147.234"

    # LLM Gateway
    AI_GATEWAY_BASE_URL: str = "https://api.mistral.ai/v1"
    AI_API_KEY: str = "CM4uYYlWCf8Ujg5D2Wrl2cFiYz8gVca1"
    AI_DEFAULT_MODEL: str = "open-mistral-nemo"
    AI_FALLBACK_MODEL: str = "ministral-8b-latest"
    AI_EMBEDDING_MODEL: str = "mistral-embed"

    # Connector / Tally Integration
    CONNECTOR_API_BASE_URL: str = "https://connector.cloudata.in/api"
    CONNECTOR_TIMEOUT_SECONDS: int = 10
    CONNECTOR_API_TOKEN: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2YWEwZTk1YjBkZDI0YmM1NThmZWVlZjEiLCJ0eXAiOiJ3ZWIiLCJpYXQiOjE3OTAzMTI0NTcsImV4cCI6MTc5MDkxNzI1N30.GOdMqwqJA2nMcLkN1_MG21qJ0uVv-Wl7Yk8UzhsOJYE"


settings = Settings()

