import json
import logging

from backend.database import get_config, set_config
from backend.models import AppConfig, StoreConfig

logger = logging.getLogger(__name__)

CONFIG_KEY = "app_config"


async def get_app_config() -> AppConfig:
    """Load the app configuration from the database."""
    raw = await get_config(CONFIG_KEY)
    if raw:
        try:
            return AppConfig.model_validate_json(raw)
        except Exception:
            logger.warning("Invalid app config in database, resetting")
    return AppConfig()


async def save_app_config(config: AppConfig) -> None:
    """Persist the app configuration to the database."""
    await set_config(CONFIG_KEY, config.model_dump_json())


async def set_postal_code(postal_code: str) -> AppConfig:
    """Set the user's postal code and return the updated config."""
    config = await get_app_config()
    config.postal_code = postal_code
    await save_app_config(config)
    return config


async def set_store_config(store_key: str, store_id: str, store_name: str) -> AppConfig:
    """Set a store configuration for a specific retailer."""
    config = await get_app_config()
    config.stores[store_key] = StoreConfig(store_id=store_id, store_name=store_name)
    await save_app_config(config)
    return config


async def get_configured_stores() -> dict[str, StoreConfig]:
    """Return the configured stores."""
    config = await get_app_config()
    return config.stores
