"""Constants for the ZHA Bindings Manager Backend integration.

See the ZHA Bindings Manager delivery plan (in the card's own repo) for
the design this implements — this integration is intentionally the
smallest thing that makes "the card's data survives a reload and can be
shared across browsers" true: whole-state read/write, last-write-wins, no
revision numbers, no patch API, no live subscriptions.
"""

DOMAIN = "zha_bindings_manager"

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}/state"

BACKEND_VERSION = "0.2.0"
