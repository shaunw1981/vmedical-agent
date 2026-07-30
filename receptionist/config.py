"""Configuration loaded from environment (.env in dev)."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    ghl_location_id: str
    ghl_private_token: str
    ghl_api_base: str
    ghl_api_version: str

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            ghl_location_id=os.environ.get("GHL_LOCATION_ID", ""),
            ghl_private_token=os.environ.get("GHL_PRIVATE_TOKEN", ""),
            ghl_api_base=os.environ.get(
                "GHL_API_BASE", "https://services.leadconnectorhq.com"
            ),
            ghl_api_version=os.environ.get("GHL_API_VERSION", "2021-07-28"),
        )


settings = Settings.load()
