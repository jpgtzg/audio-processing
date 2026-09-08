from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OPENAI_API_KEY: str
    DB_SERVER_URL: str
    DB_SERVER_PORT: str | None = None
    DB_SERVER_DATABASE: str
    DB_LOGIN: str
    DB_PASSWORD: str

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()  # pyright: ignore[reportCallIssue]
