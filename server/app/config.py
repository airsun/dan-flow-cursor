from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://danflow:danflow@localhost:5432/danflow"
    DATABASE_URL_SYNC: str = "postgresql://danflow:danflow@localhost:5432/danflow"
    DANFLOW_CLAUDE_API_KEY: str = ""

    model_config = {"env_prefix": "", "case_sensitive": True}


settings = Settings()
