# ZHA Bindings Manager (integration)

The Home Assistant integration for [ZHA Bindings Manager](https://github.com/hsolgaard/zha-bindings-manager), the visual manager for ZHA Zigbee direct bindings.

It includes the ZHA Bindings Manager card and adds:

- a **ZHA Bindings** page in the sidebar (admins only), so there's no dashboard to set up,
- **shared storage**, so the card's data (bindings, floor plan, settings) is the same in every browser and on every device,
- a **notice when you remove a device that others are bound to**, so leftover bindings don't use up binding-table slots unnoticed,
- **no stale-cache problems after updates**: the integration serves the card itself, and every update loads fresh.

Each of these can be switched off under **Configure**.

> **Card or integration?** ZHA Bindings Manager comes in two forms that run the same card and share one version number. The [card on its own](https://github.com/hsolgaard/zha-bindings-manager) needs no restart and keeps its data in each browser. This integration is the full version. Install one or the other, not both. See [Installed the card from HACS too?](#installed-the-card-from-hacs-too)

## Requirements

- Home Assistant **2024.7 or newer**, using the **ZHA** integration
- [`zha-toolkit`](https://github.com/mdeweerd/zha-toolkit) installed and working (the card uses it to read and change binding tables)

## Installing

### Via HACS

1. This integration isn't in the default HACS list yet, so add it as a custom repository: **HACS → ⋮ → Custom repositories**, add `https://github.com/hsolgaard/zha-bindings-manager-integration` with type **Integration**.
2. Install **ZHA Bindings Manager** from HACS.
3. Restart Home Assistant.
4. **Settings → Devices & services → Add integration**, search for **ZHA Bindings Manager**, confirm. There's nothing to fill in.

**ZHA Bindings** then appears in the sidebar.

### Manual

1. Copy `custom_components/zha_bindings_manager/` into your Home Assistant config directory's `custom_components/` folder.
2. Restart Home Assistant and add it as in step 4 above.

### Updating

Update in HACS (or copy the folder again) and restart Home Assistant. The new card is picked up automatically; no hard refresh is needed.

## Options

**Settings → Devices & services → ZHA Bindings Manager → Configure.** Changes apply straight away; refresh any open browser tabs afterwards.

| Option | Default | What it does |
|---|---|---|
| Show the ZHA Bindings page in the sidebar | On | A full-page **ZHA Bindings** page, visible to admins only. The card's file loads only when you open it. |
| Load the card on every page | **Off** | See below. |
| Shared storage | On | Saves the card's data in Home Assistant, the same in every browser. When off, each browser keeps its own copy. |
| Notify when a removed device still has bindings pointing to it | On | See [Removed-device notices](#removed-device-notices). |

### "Load the card on every page": when you need it

You **only** need this to put the card on your own dashboards (`type: custom:zha-binding-map-card`), for example a bindings card on a room dashboard. The sidebar page works without it.

It's off by default because the card is large: about 380 KB (about 100 KB compressed). With it on, **every** dashboard page loads the card, including on phones and tablets that never open it. If you only use the sidebar page, leave it off.

## Shared storage

A badge in the card's toolbar shows which mode is active: 🔒 **This browser only** or ☁ **Shared in Home Assistant**. The first time a browser finds shared storage, it asks once whether to use it. If shared storage already holds data from another device, it's never overwritten: only what's missing is filled in from this browser. You can switch either way in the card's ⚙ panel.

Data is stored with Home Assistant's own storage helper, in `.storage/zha_bindings_manager.state` in your config directory. If two browsers save at nearly the same moment, the second save is refused and that browser reloads, rather than silently overwriting the first.

## Removed-device notices

When you remove a ZHA device and other devices still have bindings to it (going by the card's last scan of those devices), Home Assistant shows a notification naming them. Those bindings use slots in each device's binding table and send commands to nobody.

- **Pairing the device again?** Ignore the notice. Once it's back with the same address, the bindings work again and the notice is dismissed automatically.
- **Gone for good?** Open **ZHA Bindings**, go to the Bindings tab and click **Unbind all** in the banner above the table.

The integration never unbinds anything itself, and only reads the card's saved data to write the notice.

## Installed the card from HACS too?

This integration already includes the card, so the separate ZHA Bindings Manager card from HACS isn't needed. If both are installed, two copies of the card compete for the page and the one that runs may be out of date. The integration raises a **Repairs** notice when it finds both, and the card's ⚙ → About says which version is running.

To fix it:

1. If you use the card on your own dashboards, turn on **Load the card on every page** first (see [Options](#options)).
2. Remove **ZHA Bindings Manager** from **HACS → Frontend**. HACS also removes its Lovelace resource.
3. Restart Home Assistant. The Repairs notice disappears.

If you set up the old `zha-binding-map-dashboard.yaml` sidebar dashboard, you can remove it from `configuration.yaml` too: the **ZHA Bindings** page replaces it.

## Moving from "ZHA Bindings Manager Backend"

This integration used to be called ZHA Bindings Manager Backend, in the `zha-bindings-manager-backend` repository (GitHub redirects the old address). Update it in HACS and restart: your saved data stays where it is, and the entry is renamed automatically. Then follow [Installed the card from HACS too?](#installed-the-card-from-hacs-too) if you also have the card.

## Removing it

Removing the integration removes the sidebar page. It doesn't delete anything the card saved in a browser. Data in shared storage isn't copied back into browsers first, so if you'll keep using the card on its own, re-scan afterwards.

## Development

The card is developed in [`zha-bindings-manager`](https://github.com/hsolgaard/zha-bindings-manager). This repository carries a copy of a released card build in `custom_components/zha_bindings_manager/frontend/`, and both share one version number. When a new card release exists, the **Update bundled card** workflow opens a pull request that copies it in and sets this integration's version to match.

Tests run against a real Home Assistant core:

```bash
pip install -r requirements_test.txt
pytest
```

## Related projects

- [`zha-bindings-manager`](https://github.com/hsolgaard/zha-bindings-manager): the card on its own.
- [`zigbee-capabilities`](https://github.com/hsolgaard/zigbee-capabilities): the community device-capability dataset behind the card's Zigbee Capability Explorer.

## Credits

Designed, specified, and tested by [H Solgaard](https://github.com/hsolgaard).
Development assisted by [Claude](https://www.anthropic.com/claude)
(Anthropic).
