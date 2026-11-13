"""Integration-wide state shared by every config entry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import DOMAIN, SIGNAL_CATALOGUE_UPDATED, STORAGE_KEY, STORAGE_VERSION
from .gradients import Catalogue, Gradient, custom_from_dict, load_builtin, slugify
from .wled import WledController


@dataclass
class GradientEffectsData:
    hass: HomeAssistant
    store: Store
    builtin: list[Gradient]
    custom: list[dict[str, Any]] = field(default_factory=list)
    catalogue: Catalogue = field(init=False)
    controllers: dict[str, WledController] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._rebuild()

    @callback
    def _rebuild(self) -> None:
        custom: list[Gradient] = []
        for entry in self.custom:
            try:
                custom.append(custom_from_dict(entry))
            except (KeyError, ValueError, TypeError):
                continue
        self.catalogue = Catalogue(self.builtin, custom)

    def known_hashes(self) -> set[str]:
        return {g.content_hash() for g in self.catalogue}

    def controller(self, host: str) -> WledController:
        if host not in self.controllers:
            self.controllers[host] = WledController(async_get_clientsession(self.hass), host)
        return self.controllers[host]

    # --- custom gradients --------------------------------------------------------

    def custom_gradient(self, gradient_id: str) -> dict[str, Any] | None:
        return next((g for g in self.custom if g["id"] == gradient_id), None)

    async def async_save_custom(
        self, name: str, colours: list[list[int]], gradient_id: str | None = None
    ) -> str:
        """Add (gradient_id None) or replace a custom gradient; returns its id."""
        custom_from_dict({"id": "check", "name": name, "colours": colours})  # validates
        if gradient_id is None:
            base = slugify(name)
            gradient_id, n = base, 2
            while self.custom_gradient(gradient_id):
                gradient_id, n = f"{base}_{n}", n + 1
        entry = {"id": gradient_id, "name": name.strip(), "colours": colours}
        self.custom = [g for g in self.custom if g["id"] != gradient_id] + [entry]
        await self._async_commit()
        return gradient_id

    async def async_delete_custom(self, gradient_id: str) -> None:
        self.custom = [g for g in self.custom if g["id"] != gradient_id]
        await self._async_commit()

    async def _async_commit(self) -> None:
        await self.store.async_save({"gradients": self.custom})
        self._rebuild()
        async_dispatcher_send(self.hass, SIGNAL_CATALOGUE_UPDATED)


async def async_get_data(hass: HomeAssistant) -> GradientEffectsData:
    if DOMAIN not in hass.data:
        store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        saved = await store.async_load() or {}
        builtin = await hass.async_add_executor_job(load_builtin)
        hass.data[DOMAIN] = GradientEffectsData(
            hass=hass, store=store, builtin=builtin, custom=list(saved.get("gradients", []))
        )
    return hass.data[DOMAIN]
