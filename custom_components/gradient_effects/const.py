"""Constants for Gradient Effects."""

from __future__ import annotations

DOMAIN = "gradient_effects"

# Config entry kinds: one entry per wrapped strip, plus a single gradient library.
CONF_KIND = "kind"
KIND_STRIP = "strip"
KIND_LIBRARY = "library"

CONF_SOURCE = "source"  # wrapped light entity_id
CONF_BACKEND = "backend"
BACKEND_HUE_Z2M = "hue_z2m"
BACKEND_WLED = "wled"

CONF_SCENE_SELECT = "scene_select"  # z2m gradient_scene select entity
CONF_MQTT_TOPIC = "mqtt_topic"  # z2m device topic, e.g. zigbee2mqtt/Headboard
CONF_HOST = "host"  # WLED controller host
CONF_SEGMENT = "segment"  # WLED segment id
CONF_REVERSE = "reverse"

DEFAULT_Z2M_BASE_TOPIC = "zigbee2mqtt"

EFFECT_SOLID = "Solid"

# Z2M Hue effects that are controls, not looks.
HUE_HIDDEN_EFFECTS = {"none", "finish_effect", "stop_effect", "stop_hue_effect"}

# Colour changes reported within this window after we set an effect are the strip
# settling into it, not someone changing it.
SETTLE_SECONDS = 5.0

STORAGE_KEY = f"{DOMAIN}.custom_gradients"
STORAGE_VERSION = 1

SIGNAL_CATALOGUE_UPDATED = f"{DOMAIN}_catalogue_updated"
