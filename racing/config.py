from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Betfair
    betfair_username: str = ""
    betfair_password: str = ""
    betfair_app_key: str = ""
    betfair_cert_path: str = "./certs/betfair.crt"
    betfair_key_path: str = "./certs/betfair.key"

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""

    # Punting Form (Phase 2)
    punting_form_api_key: str = ""

    # Live polling
    live_poll_interval_seconds: int = 60
    live_poll_near_jump_seconds: int = 15
    live_poll_near_jump_window_minutes: int = 10

    # Nightly batch
    nightly_batch_hour_aest: int = 18

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    @property
    def is_phase2(self) -> bool:
        return bool(self.punting_form_api_key)


settings = Settings()
