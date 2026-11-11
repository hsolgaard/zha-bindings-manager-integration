"""Constants for the ZHA Bindings Manager integration.

The integration started as an optional storage backend for the
zha-binding-map-card Lovelace card ("ZHA Bindings Manager Backend"). From
1.0.0 it also ships the card itself, serves it, and adds a sidebar page.
The card is still developed in hsolgaard/zha-bindings-manager; this
integration carries a copy of a released build in frontend/, and both
share one version number.
"""

DOMAIN = "zha_bindings_manager"

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}/state"

# Kept equal to manifest.json "version" and to the bundled card's version
# (frontend/card_version.json). A test fails if they ever differ.
BACKEND_VERSION = "1.10.4"

TITLE = "ZHA Bindings Manager"
OLD_TITLE = "ZHA Bindings Manager Backend"

# Frontend
CARD_FILENAME = "zha-binding-map-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILENAME}"
# Not "zha-bindings": that is the address the card README suggested for the
# YAML dashboard, and two sidebar entries can't share an address.
PANEL_URL_PATH = "zha-bindings-manager"


def device_link_path(ieee: str) -> str:
    """The card's page opened on one device (card 1.3.1+)."""
    return f"/{PANEL_URL_PATH}?device={ieee}"
PANEL_COMPONENT = "zha-bindings-manager-panel"
PANEL_TITLE = "ZHA Bindings"
PANEL_ICON = "mdi:led-strip-variant"
# The card when installed separately from HACS (repo hsolgaard/zha-bindings-manager).
HACS_CARD_URL_FRAGMENT = "/hacsfiles/zha-bindings-manager/"

# Options (Settings → Devices & services → ZHA Bindings Manager → Configure)
OPT_SIDEBAR_PANEL = "sidebar_panel"
OPT_LOAD_EVERYWHERE = "load_card_everywhere"
OPT_SHARED_STORAGE = "shared_storage"
OPT_REMOVAL_NOTICES = "removal_notices"
OPT_DEVICE_PAGE = "device_page_bindings"
OPT_WATCH = "binding_watch"
OPT_LOGBOOK = "logbook_attribution"
OPT_EXPERIMENTAL = "experimental_features"
OPT_EVIDENCE = "record_evidence"
OPT_LQI_GOOD = "lqi_good"
OPT_LQI_WEAK = "lqi_weak"
# Recommended link-quality thresholds (experimental route check / network map).
LQI_GOOD_DEFAULT = 150
LQI_WEAK_DEFAULT = 80
DEFAULT_OPTIONS = {
    OPT_SIDEBAR_PANEL: True,
    OPT_LOAD_EVERYWHERE: False,
    OPT_SHARED_STORAGE: True,
    OPT_REMOVAL_NOTICES: True,
    OPT_DEVICE_PAGE: True,
    OPT_WATCH: True,
    OPT_LOGBOOK: False,
    OPT_EXPERIMENTAL: False,
    OPT_EVIDENCE: True,
    OPT_LQI_GOOD: LQI_GOOD_DEFAULT,
    OPT_LQI_WEAK: LQI_WEAK_DEFAULT,
}

# Fired when binding data changes (the card saved a scan, or a device-page
# rescan finished), so the device-page entities update.
SIGNAL_BINDINGS_UPDATED = f"{DOMAIN}_bindings_updated"
PLATFORMS = ["sensor", "button"]

ISSUE_CARD_INSTALLED_TWICE = "card_installed_twice"
