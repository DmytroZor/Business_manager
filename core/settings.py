from pydantic_settings import BaseSettings
from pathlib import Path
class Settings(BaseSettings):
    database_url: str
    jwt_secret: str
    jwt_algorithm: str
    jwt_expiration: int
    jwt_refresh_expiration: int
    internal_api_token: str | None = None
    auto_create_tables: bool = False

    class Config:
        env_file = Path(__file__).resolve().parent.parent/".env"


settings = Settings()
