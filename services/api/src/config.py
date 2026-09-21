from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://restock:restock_dev@127.0.0.1:5432/restock"
    )
    manager_username: str = "manager"
    manager_password: SecretStr = SecretStr("")
    agent_token: SecretStr = SecretStr("")
    allowed_origins: list[str] = ["http://localhost:8000", "http://localhost:3000"]
    cookie_secure: bool = True
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    session_hours: int = 8
    enable_development_calculator: bool = False
    llm_gateway_url: str = ""
    llm_gateway_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_gateway_timeout_seconds: int = 30
    llm_num_predict: int = 2048

    @model_validator(mode="after")
    def validate_access(self) -> "Settings":
        password = self.manager_password.get_secret_value()
        token = self.agent_token.get_secret_value()
        if password and password == token:
            raise ValueError("Manager password and agent token must differ")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("SameSite=None requires secure cookies")
        if "*" in self.allowed_origins:
            raise ValueError("Use explicit allowed origins")
        if not 1 <= self.session_hours <= 24:
            raise ValueError("session_hours must be between 1 and 24")
        return self
