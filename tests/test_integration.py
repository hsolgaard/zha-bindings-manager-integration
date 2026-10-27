"""Setup, options, frontend and Repairs tests against real Home Assistant
core (pytest-homeassistant-custom-component). Not shipped."""
import json
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zha_bindings_manager.const import (
    BACKEND_VERSION,
    CARD_URL,
    DOMAIN,
    ISSUE_CARD_INSTALLED_TWICE,
    OLD_TITLE,
    PANEL_URL_PATH,
    TITLE,
)
from custom_components.zha_bindings_manager.card_frontend import bundled_card_version

ROOT = Path(__file__).parent.parent
INTEGRATION = ROOT / "custom_components" / DOMAIN


async def _setup(hass: HomeAssistant, options=None, title=TITLE):
    entry = MockConfigEntry(domain=DOMAIN, title=title, options=options or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _panels(hass):
    return hass.data.get("frontend_panels", {})


def _extra_js(hass):
    return {u for u in hass.data["frontend_extra_module_url"].urls}


def test_one_version_everywhere():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    assert manifest["version"] == BACKEND_VERSION
    assert bundled_card_version() == BACKEND_VERSION
    card = (INTEGRATION / "frontend" / "zha-binding-map-card.js").read_text()
    assert f'CARD_VERSION = "{BACKEND_VERSION}"' in card


async def test_defaults_register_panel_not_extra_js(hass: HomeAssistant):
    await _setup(hass)
    panel = _panels(hass)[PANEL_URL_PATH]
    assert panel.require_admin is True
    assert panel.sidebar_title == "ZHA Bindings"
    cfg = panel.config["_panel_custom"]
    assert cfg["name"] == "zha-bindings-manager-panel"
    assert cfg["module_url"] == f"{CARD_URL}?v={BACKEND_VERSION}"
    assert not any(CARD_URL in u for u in _extra_js(hass))


async def test_options_switch_panel_off_and_load_everywhere_on(hass: HomeAssistant):
    entry = await _setup(hass)
    hass.config_entries.async_update_entry(entry, options={"sidebar_panel": False, "load_card_everywhere": True})
    await hass.async_block_till_done()
    assert PANEL_URL_PATH not in _panels(hass)
    assert f"{CARD_URL}?v={BACKEND_VERSION}" in _extra_js(hass)
    # And back again, cleanly.
    hass.config_entries.async_update_entry(entry, options={"sidebar_panel": True, "load_card_everywhere": False})
    await hass.async_block_till_done()
    assert PANEL_URL_PATH in _panels(hass)
    assert not any(CARD_URL in u for u in _extra_js(hass))


async def test_unload_removes_panel_and_script(hass: HomeAssistant):
    entry = await _setup(hass, options={"load_card_everywhere": True})
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH not in _panels(hass)
    assert not any(CARD_URL in u for u in _extra_js(hass))


async def test_old_title_is_renamed(hass: HomeAssistant):
    entry = await _setup(hass, title=OLD_TITLE)
    assert entry.title == TITLE


async def test_capabilities_report_versions_and_features(hass: HomeAssistant, hass_ws_client):
    await _setup(hass, options={"shared_storage": False})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/get_capabilities"})
    res = (await client.receive_json())["result"]
    assert res["available"] is True
    assert res["version"] == BACKEND_VERSION
    assert res["bundled_card_version"] == BACKEND_VERSION
    assert res["features"] == {
        "shared_storage": False,
        "sidebar_panel": True,
        "load_card_everywhere": False,
        "removal_notices": True,
    }


async def test_options_flow_shows_and_saves_switches(hass: HomeAssistant):
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    keys = {str(k) for k in result["data_schema"].schema}
    assert keys == {"sidebar_panel", "load_card_everywhere", "shared_storage", "removal_notices"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"sidebar_panel": True, "load_card_everywhere": False, "shared_storage": True, "removal_notices": False},
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["removal_notices"] is False


async def test_repairs_issue_when_hacs_card_also_installed(hass: HomeAssistant):
    class FakeResources:
        loaded = True

        def __init__(self, items):
            self.items = items

        async def async_get_info(self):
            return {"resources": len(self.items)}

        def async_items(self):
            return self.items

    class FakeLovelace:
        def __init__(self, items):
            self.resources = FakeResources(items)

    entry = await _setup(hass)  # also sets up lovelace, so replace its resources afterwards
    hass.data["lovelace"] = FakeLovelace(
        [{"url": "/hacsfiles/zha-bindings-manager/zha-binding-map-card.js?hacstag=1", "type": "module"}]
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_CARD_INSTALLED_TWICE)
    assert issue is not None
    assert "hacsfiles" in issue.translation_placeholders["resource"]

    # Gone after the HACS card is removed and the check runs again (reload).
    hass.data["lovelace"] = FakeLovelace([])
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_CARD_INSTALLED_TWICE) is None


async def test_repairs_issue_with_real_lovelace_resources(hass: HomeAssistant):
    """Same check against Home Assistant's own storage-mode resource collection."""
    entry = await _setup(hass)
    resources = hass.data["lovelace"].resources
    await resources.async_get_info()
    await resources.async_create_item(
        {"res_type": "module", "url": "/hacsfiles/zha-bindings-manager/zha-binding-map-card.js?hacstag=2"}
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_CARD_INSTALLED_TWICE) is not None


async def test_existing_panel_at_same_address_does_not_break_setup(hass: HomeAssistant):
    """If something else already owns the sidebar address, setup still succeeds."""
    from homeassistant.components import frontend as ha_frontend
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "frontend", {})
    ha_frontend.async_register_built_in_panel(
        hass, "lovelace", sidebar_title="Someone else", sidebar_icon="mdi:home", frontend_url_path=PANEL_URL_PATH
    )
    entry = await _setup(hass)
    assert entry.state.value == "loaded"
    assert _panels(hass)[PANEL_URL_PATH].sidebar_title == "Someone else"
    # Unloading must not remove the other panel.
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert PANEL_URL_PATH in _panels(hass)


def test_panel_address_differs_from_old_yaml_dashboard():
    assert PANEL_URL_PATH != "zha-bindings"
