from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OPENAI_API_KEY: str
    DB_SERVER_URL: str
    DB_SERVER_PORT: str | None = None
    DB_SERVER_DATABASE: str
    DB_LOGIN: str
    DB_PASSWORD: str

    # Optional second database (same schema) used by db_test. Login/password
    # fall back to the main DB's when unset.
    TEST_DB_SERVER_URL: str | None = None
    TEST_DB_SERVER_PORT: str | None = None
    TEST_DB_SERVER_DATABASE: str | None = None
    TEST_DB_LOGIN: str | None = None
    TEST_DB_PASSWORD: str | None = None

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()  # pyright: ignore[reportCallIssue]
