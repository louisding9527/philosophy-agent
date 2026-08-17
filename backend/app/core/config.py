from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_provider: str = "anthropic"  # anthropic | openai
    llm_model: str = "deepseek-v4-flash"
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "auto"  # auto | dml | cpu
    database_url: str = ""
    qdrant_url: str = ""
    neo4j_uri: str = ""
    neo4j_password: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
