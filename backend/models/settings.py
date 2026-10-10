"""Settings of the user: location and stores (area of P4)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError

__all__ = [
    "AutoPickResult",
    "Location",
    "LocationRequest",
    "LocationResponse",
    "OnboardingState",
    "OnboardingStatus",
    "OnboardingUpdate",
    "RetailerInfo",
    "Settings",
    "SettingsUpdate",
    "StoreChoice",
    "StoreOption",
    "StoreSelection",
    "valid_store_id",
]


def valid_store_id(value: str | None) -> bool:
    """Store numbers of Intermarché (pdvRef) and Courses U: 2 to 8 digits."""
    return value is not None and value.isascii() and value.isdigit() and 2 <= len(value) <= 8


def _invalid(message: str) -> PydanticCustomError:
    # The message is shown as is by the frontend (422 « detail[].msg »)
    return PydanticCustomError("invalid", message)


class Location(BaseModel):
    postal_code: str
    city: str | None = None
    lat: float | None = None
    lon: float | None = None
    # Department of the town (geo.api.gouv.fr): « 34 », « Hérault »
    department_code: str | None = None
    department_name: str | None = None


class StoreSelection(BaseModel):
    id: str | None = None
    name: str | None = None
    url: str | None = None
    address: str | None = None
    # Chosen by PrixMalin (nearest store) rather than by the user
    auto: bool = False
    # Distance from the location of the user when it was chosen
    distance_km: float | None = None


class StoreChoice(BaseModel):
    """Body of ``PUT /api/retailers/{key}/store``: what a client may send."""

    id: str | None = None
    name: str | None = None
    url: str | None = None
    address: str | None = None
    distance_km: float | None = Field(default=None, ge=0, le=2000)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str | None) -> str | None:
        # The exact form (``valid_store_id``) is checked for the retailers that take a store
        if value is not None and len(value) > 40:
            raise _invalid("Identifiant de magasin invalide.")
        return value

    @field_validator("name", "address")
    @classmethod
    def _text(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 200:
            raise _invalid("Texte trop long (200 caractères au plus).")
        return value.strip() if value is not None else None

    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 300:
            raise _invalid("Adresse trop longue (300 caractères au plus).")
        return value.strip() if value is not None else None


class Settings(BaseModel):
    location: Location | None = None
    stores: dict[str, StoreSelection] = {}
    show_browser: bool = False


class LocationRequest(BaseModel):
    postal_code: str
    city: str | None = None

    @field_validator("postal_code")
    @classmethod
    def _postal_code(cls, value: str) -> str:
        value = value.strip()
        if not (len(value) == 5 and value.isascii() and value.isdigit()):
            raise _invalid("Saisissez 5 chiffres, par ex. 34000.")
        return value

    @field_validator("city")
    @classmethod
    def _city(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 100:
            raise _invalid("Nom de commune trop long (100 caractères au plus).")
        return value


class LocationResponse(BaseModel):
    settings: Settings
    communes: list[Location] = []
    # The geo services did not answer: the postal code is saved without its town
    geocoding_failed: bool = False


class SettingsUpdate(BaseModel):
    show_browser: bool | None = None


class StoreOption(BaseModel):
    id: str
    name: str
    address: str | None = None
    distance_km: float | None = None
    # Courses U: page of the store (https://www.coursesu.com/drive-…), services
    # offered (« Drive », « Livraison », « Retrait ») and where it is
    url: str | None = None
    services: list[str] = []
    postal_code: str | None = None
    city: str | None = None
    lat: float | None = None
    lon: float | None = None


class RetailerInfo(BaseModel):
    key: str
    label: str
    needs_store: bool
    store_hint: str
    home_url: str
    store: StoreSelection | None = None
    # Same prices everywhere in France (Aldi, Lidl)
    national: bool = False
    # PrixMalin can list the stores near the user (Intermarché, Courses U)
    finds_stores: bool = False


class AutoPickResult(BaseModel):
    """Outcome of ``POST /api/retailers/coursesu/store/auto`` (always HTTP 200)."""

    # chosen: nearest store saved; kept: a store chosen by the user stays;
    # no_location: no postal code (or no town) yet; none: no store found
    status: Literal["chosen", "kept", "no_location", "none", "blocked", "timeout", "error"]
    message: str | None = None
    store: StoreOption | None = None
    settings: Settings


class OnboardingState(BaseModel):
    """Preferences ``p4.onboarding`` (backend/services/prefs.py)."""

    seen: bool = False
    done: bool = False
    done_at: float | None = None


class OnboardingStatus(OnboardingState):
    # The assistant should open by itself (first launch, nothing set yet)
    needed: bool = False


class OnboardingUpdate(BaseModel):
    seen: bool | None = None
    done: bool | None = None
