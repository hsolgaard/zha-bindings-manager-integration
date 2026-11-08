# ZHA Bindings Manager — integration

The complete install of [ZHA Bindings Manager](https://github.com/hsolgaard/zha-bindings-manager), the visual topology, binding and endpoint diagnostic tool for Home Assistant's ZHA integration.

Install it once and you get the full ZHA Bindings Manager card on its own **ZHA Bindings** page in the sidebar, with your data shared across every browser and device, a heads-up when removing a device leaves bindings behind, and updates that always load fresh.

![release](https://img.shields.io/github/v/release/hsolgaard/zha-bindings-manager-integration)
![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5)
![license](https://img.shields.io/badge/license-MIT-blue)

> [!NOTE]
> ZHA Bindings Manager comes in two forms that run the same card and share one version number: this **integration**, and the [**card on its own**](https://github.com/hsolgaard/zha-bindings-manager). Install one or the other, not both. Not sure which? See [Card or integration?](#card-or-integration)

![ZHA Bindings Manager map view](https://github.com/user-attachments/assets/63a7c281-5043-40a2-a19c-23ec6ceab3cf)

## Why use it?

Direct Zigbee bindings let devices talk to each other without Home Assistant in the loop. That makes them fast and resilient, but also hard to see and troubleshoot. ZHA Bindings Manager answers questions such as:

- What does this switch control, and what controls this light?
- Did re-pairing a device leave an old binding behind?
- Is a binding missing, duplicated or pointing at something that no longer exists?
- Does the target device actually support the command the source sends?

The [card's README](https://github.com/hsolgaard/zha-bindings-manager#what-you-can-do) has the full tour. This integration delivers that same card, and adds what a card on its own can't do:

| | What you get |
|---|---|
| **A ZHA Bindings sidebar page** | The card full-page, one click away. No dashboard to build, no YAML. Visible to admins only. |
| **Shared storage** | Scans, floor plan, Map layout, endpoint notes and settings are saved in Home Assistant, so your phone, tablet and laptop all see the same thing. |
| **Removed-device notices** | Remove a device that other devices are still bound to and Home Assistant tells you which ones, so dead bindings don't quietly use up binding-table slots. |
| **Updates that just work** | The integration serves the card itself, with the version in its address. No stale browser caches and no Lovelace resource to manage. |

Every one of these can be switched off under **Configure**.

## Card or integration?

| | **Integration** (this repository) | **Card only** ([`zha-bindings-manager`](https://github.com/hsolgaard/zha-bindings-manager)) |
|---|---|---|
| Install | HACS → Integrations, restart, then **Add integration** | HACS → Frontend. No restart. |
| Where your data is saved | In Home Assistant, the same everywhere (can be switched off) | Only in the browser you're using |
| Sidebar page | Added automatically | Set up yourself with a dashboard |
| Removed-device notices | Yes | No |
| After an update | Restart Home Assistant | Hard-refresh each browser |

Choose the **integration** if you use Home Assistant on more than one device, or want the sidebar page without any setup. Choose the **card** if you'd rather not add an integration and are happy with per-browser data.

## Requirements

- Home Assistant **2024.7 or newer**, using the **ZHA** integration
- [`zha-toolkit`](https://github.com/mdeweerd/zha-toolkit) installed and working. The card uses it to read and change device binding tables.

## Installation

### HACS — recommended

The integration is not in the default HACS store yet, so add it as a custom repository first:

1. Open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/hsolgaard/zha-bindings-manager-integration` with type **Integration**.
3. Search HACS for **ZHA Bindings Manager** and open the entry of type **Integration** (not **ZHA Bindings Manager (card only)**, the Dashboard entry), then select **Download**.
4. **Restart Home Assistant.**
5. Go to **Settings → Devices & services → Add integration**, search for **ZHA Bindings Manager** and confirm. There's nothing to fill in.

**ZHA Bindings** now appears in the sidebar.

> [!IMPORTANT]
> Already have the ZHA Bindings Manager **card** installed from HACS? Remove it once the integration is set up: the integration includes the card. See [Installed the card from HACS too?](#installed-the-card-from-hacs-too)

### Manual installation

1. Download the latest release and copy `custom_components/zha_bindings_manager/` into the `custom_components/` folder of your Home Assistant config directory.
2. Restart Home Assistant.
3. Add the integration as in step 5 above.

### Updating

Update in HACS (or copy the folder again) and restart Home Assistant. The new card is picked up automatically. No hard refresh is needed, on any device.

## First use

1. Open **ZHA Bindings** in the sidebar. Your ZHA devices and groups load immediately.
2. The first time each browser opens it, you're asked once whether to use **shared storage**. Say yes, and anything this browser had saved before is copied in without overwriting what's already shared.
3. Select **Scan bindings** to read each device's binding table.
4. Explore the **Map**, **Bindings** and **Devices** views. Select a connection on the Map to inspect or remove it, or drag one device onto another to create a binding.

Reading binding tables is a real Zigbee operation. Battery-powered buttons and remotes may need to be woken (press a button) before they respond. If one device fails, wake it and use its own **Rescan** rather than scanning the whole network again.

The [card's README](https://github.com/hsolgaard/zha-bindings-manager#first-use) covers the views in detail, including endpoint inspection, supported-command checks and the Zigbee Capability Explorer.

## Options

Go to **Settings → Devices & services → ZHA Bindings Manager → Configure**. Changes apply straight away; refresh any open browser tabs afterwards.

| Option | Default | What it does |
|---|---|---|
| **Show the ZHA Bindings page in the sidebar** | On | The card full-page at `/zha-bindings-manager`, visible to admins only. The card is loaded only when you open the page. |
| **Load the card on every page** | Off | Needed only to put the card on your own dashboards. See below. |
| **Shared storage** | On | Saves the card's data in Home Assistant, the same in every browser. When off, each browser keeps its own copy. |
| **Notify when a removed device still has bindings pointing to it** | On | See [Removed-device notices](#removed-device-notices). |
| **Show bindings on each device's page** | On | See [Bindings on device pages](#bindings-on-device-pages). |
| **Watch for lost bindings** | On | See [Lost bindings](#lost-bindings). |
| **Say in the logbook which remote switched a light** | Off | See [Which remote switched it?](#which-remote-switched-it) |
| **Record address changes and missed presses** | On | See [Address changes and missed presses](#address-changes-and-missed-presses). |
| **Experimental features** | Off | A **Network** tab in the card (beta), a route check for each binding and a count of messages per device. See [Network tab (experimental)](#network-tab-experimental). |
| **Link quality: good from / weak below** | 150 / 80 | Thresholds for colouring links on the Network tab. **Reset** goes back to the recommended values. |

### Using the card on your own dashboards

The sidebar page works without any dashboard setup. If you also want the card on one of your own dashboards, turn on **Load the card on every page**, then add:

```yaml
type: custom:zha-binding-map-card
```

> [!TIP]
> This option is off by default for a reason. The card is about 380 KB (about 100 KB compressed), and with the option on, **every** dashboard page loads it, including on phones and tablets that never open it. If you only use the sidebar page, leave it off.

## Shared storage

A badge in the card's toolbar always shows which mode is active: 🔒 **This browser only** or ☁ **Shared in Home Assistant**.

- Each browser asks once before switching to shared storage. Nothing changes without confirming.
- If shared storage already has data from another device, it's never overwritten. Only what's missing is filled in from this browser.
- You can switch either way at any time in the card's ⚙ panel, under **Storage**.
- If two browsers save at nearly the same moment, the second save is refused and that browser reloads, rather than silently overwriting the first.

Data is saved with Home Assistant's own storage helper, in `.storage/zha_bindings_manager/state` in your config directory, so it's included in Home Assistant backups.

## Removed-device notices

When you remove a ZHA device that other devices still have bindings to, Home Assistant shows a notification naming those devices and how many bindings each still has. Those bindings use slots in each device's binding table (often only 8 to 16 slots) and send commands to nobody.

- **Pairing the device again?** Ignore the notice. A re-paired device keeps its address, so the bindings work again, and the notice is dismissed automatically.
- **Gone for good?** Open **ZHA Bindings**, go to the **Bindings** tab and select **Unbind all** in the banner above the table. Wake any battery-powered devices first.

The notice is based on the card's most recent scan of those devices. The integration never unbinds anything by itself.

The card also cleans up after removed devices on its own: a full **Scan bindings** forgets saved data for devices that are no longer in ZHA, and each leftover row has a **Forget** button until then.

## Bindings on device pages

Each ZHA device that controls, or is controlled by, another device or a group gets two extra entities on its normal Home Assistant device page (**Settings → Devices & services → ZHA → the device**), under **Diagnostic**:

- **Bindings**: how many devices or groups it controls and is controlled by, for example "Controls 2 · Controlled by 1". Click it and open **Attributes** for the names, for example "Kitchen spots (On/Off, Level Control)" or "Hall dimmer via group Kitchen (On/Off)", and for **Open in ZHA Bindings Manager**, a link to that device in the card. (The link needs Home Assistant's address under Settings → System → Network, and the sidebar page switched on.)
- **Rescan bindings**: reads the device's binding table again with zha-toolkit and updates the sensor. Battery devices are usually asleep: press a button on the device first.

The sensor uses the card's most recent scan of each device, or a newer rescan from the device page. The card also picks up those newer reads (and the nightly check's) the next time it opens, so both show the same bindings. Devices whose only bindings go to the coordinator (the routine reporting every device has) get nothing, to keep the number of entities down. To switch it off, untick **Show bindings on each device's page** under Configure.

## Lost bindings

Bindings can vanish without anyone noticing: a device is factory reset or re-paired, or loses its binding table after a firmware update. A remote then simply stops working. **Watch for lost bindings** (on by default) watches for this.

- **What it expects:** the bindings each device had, starting from the card's scans. Every later read of the device (any card scan, the nightly check, **Rescan bindings** on its device page, a check after a button press) is compared with that first. A binding missing from a successful read is **lost** straight away, and stays expected until it's put back or you say it was removed on purpose. A device that doesn't answer never makes anything lost.
- **Unbinding in the card** is reported to the integration and is never treated as lost.
- **When it checks:** at 03:17 every night it reads each watched device. Battery devices are usually asleep then, so they're checked at their next button press instead, at most once every 20 hours.
- **Where it tells you:** in the card (a banner on the Bindings tab, a **Lost** chip, dashed red lines on the Map, the device's side panel) and as one issue under **Settings → System → Repairs**, whose **Submit** puts them all back.
- **Putting back** binds them again with zha-toolkit and reads the device to check. A battery device that's asleep is queued and done at its next button press.
- **Per device** in the card's side panel: **Off**, **Tell me** (default) or **Put back automatically**. Automatic put-back happens straight away (or at the next button press), is logged, and stops after 3 times in a day with a Repairs issue instead: something keeps removing them.
- **Switch the lights from Home Assistant if a press doesn't reach them** (per remote, off by default): when the remote sends On, Off or Toggle and a light it's bound to directly hasn't changed within 2 seconds, Home Assistant switches it, logs it, and checks the remote's bindings straight away. Not for group bindings (a light missing one group message hasn't lost a binding), and Toggle only when the lights were all on or all off before the press. Needs lights that report their state promptly.

## Address changes and missed presses

Read-only evidence for bindings that stop working although they're still in the remote's table (one theory: the
light's short network address changed and a battery remote keeps sending to the old one).

- **Addresses:** every device's short network address is read from ZHA (in memory, no radio traffic) every 5 minutes,
  and straight away when zigpy reports a device joining or rejoining. Only changes are kept, for 90 days, in
  `.storage/zha_bindings_manager/evidence`.
- **Missed presses:** when a remote sends On, Off or Toggle (Home Assistant hears it through the remote's binding to
  the coordinator), each light bound to it directly is checked after 2 seconds. A light that didn't follow is logged
  with its address now, its address at the last press that worked, and whether the binding was in the remote's last
  read table. Needs lights that report their state; Toggle is only judged when the lights agreed before the press.
- The card shows it, and can prepare an anonymised report for the community database that you review before
  submitting. Websocket command `zha_bindings_manager/evidence_get` (admin).

## Replace a device

The card's **Replace this device…** uses three admin websocket commands, which other integrations can call too (feature `replace` in `get_capabilities`; Lighting Manager can use it for its own Replace):

- `zha_bindings_manager/replace_plan` `{old_ieee, new_ieee, old_clusters?, new_clusters?, endpoint_map?}`: what the old device did (bindings to it, its own bindings and its groups, from the saved scans, so a dead device works too), each item checked against the new device's clusters in the right role, and a verdict. Clusters are read from ZHA when not given.
- `zha_bindings_manager/replace_run` `{plan_id, items}`: binds the chosen items and reads each device back. A device that doesn't answer gets them through the lost-bindings queue, at its next button press. Group membership is changed by the card through ZHA's own group commands.
- `zha_bindings_manager/replace_cleanup` `{plan_id, unbind_old}`: removes the bindings still pointing at the old device and stops watching it.

## Which remote switched it?

A remote bound to a light switches it directly, so Home Assistant's logbook normally just says "Spots turned on", with no idea why. Most remotes are also bound to the coordinator when ZHA pairs them (that's how their button presses reach Home Assistant), and a remote sends each command to everything bound for that cluster. So Home Assistant hears the press as well.

Turn on **Say in the logbook which remote switched a light** under Configure, and when a light changes within 3 seconds of a press on a remote bound to it (directly or through a group), the logbook gets an entry such as **Spots turned on by Hall dimmer (direct binding)**.

- It uses the card's last scan of the remote (or a device-page rescan) to know which lights the remote is bound to.
- Only On/Off, Level Control and Colour Control presses count. Holding a dimmer gives one "dimmed" entry, not one per step.
- Changes Home Assistant made itself (from the UI, a script or an automation) are never attributed to a remote.
- A remote that isn't bound to the coordinator can't be heard, so its presses get no entry. The card's Bindings tab shows coordinator bindings when **Hide coordinator bindings** is off.

## Network tab (experimental)

Turn on **Experimental features** under Configure to get a **Network** tab in the card, marked *beta*. It reads the routing and neighbour tables of your routers with `zha_toolkit.get_routes_and_neighbours`, only when you click **Scan network** (or read one router from its side panel), and shows link quality on your floor plan, the routes your bindings take, battery devices with their parent router, and suggestions for weak spots. Nothing on the network is changed.

- The latest tables from each router are saved in `.storage/zha_bindings_manager/mesh`, so the map is the same in every browser and survives a reload.
- Links are coloured with the **Link quality** thresholds under Configure (good from 150, weak below 80 by default).
- **Messages to Home Assistant:** while Experimental features are on, the integration counts the messages each device sends to Home Assistant (per minute for the last hour, in memory only) and reads the coordinator's counters, so the card can flag a device flooding the network.
- Experimental features may change or go away in a later release. The card's README describes the [Network tab](https://github.com/hsolgaard/zha-bindings-manager#check-your-zigbee-network-beta-needs-the-integration) in detail.

## Installed the card from HACS too?

The integration already includes the card, so the separately installed card isn't needed. If both are installed, two copies of the card compete for the same page, and the one that runs may be out of date. The integration raises a **Repairs** notice (under Settings) when it finds both, and the card's ⚙ → **About** says which version is actually running.

To fix it:

1. If you use the card on your own dashboards, first turn on **Load the card on every page** (see [Options](#options)).
2. Remove **ZHA Bindings Manager** from **HACS → Frontend**. HACS also removes its Lovelace resource.
3. Restart Home Assistant. The Repairs notice disappears.

If you had set up the card's full-page YAML dashboard (the `zha-bindings` entry under `lovelace: dashboards:` in `configuration.yaml`), you can remove that too: the **ZHA Bindings** sidebar page replaces it.

## Upgrading from ZHA Bindings Manager Backend

This integration used to be **ZHA Bindings Manager Backend**, in the `zha-bindings-manager-backend` repository. GitHub redirects the old address, so HACS keeps finding it.

1. Update it in HACS and restart Home Assistant.
2. Your saved data stays exactly where it is, and the integration entry is renamed **ZHA Bindings Manager** automatically.
3. **ZHA Bindings** appears in the sidebar.
4. Follow [Installed the card from HACS too?](#installed-the-card-from-hacs-too) to remove the separate card.
5. Optional tidy-up: in HACS, remove the old custom repository and add `https://github.com/hsolgaard/zha-bindings-manager-integration` instead.

## Screenshots

<details>
<summary><strong>Map, bindings and health</strong></summary>

### Map overview

Every device and binding, colour-coded by cluster type.

![Map overview](https://github.com/user-attachments/assets/63a7c281-5043-40a2-a19c-23ec6ceab3cf)

### Bindings table

A searchable and sortable view of every binding, including Binding Health.

![Bindings view](https://github.com/user-attachments/assets/d8179c72-1c5f-40f8-9689-8194413b7017)

### Health details

Plain-English explanations of what is wrong, why it matters and what to do next.

![Binding Health details](https://github.com/user-attachments/assets/0e5b8a3d-172c-422e-a9f4-05466e427ee7)

</details>

<details>
<summary><strong>Devices and endpoints</strong></summary>

### Exploded device view

A live, per-endpoint view of the device's roles and relationships.

![Exploded device view](https://github.com/user-attachments/assets/96cc4e6c-7d0e-41ff-be4f-0d7dbb62b1ff)

</details>

More screenshots are in the [card's README](https://github.com/hsolgaard/zha-bindings-manager#screenshots).

## Important limitations

- The sidebar page is visible to **admins only**, because the card can create and remove Zigbee bindings.
- Removed-device notices only know about bindings the card has scanned. A binding added since a device's last scan isn't included until that device is rescanned.
- Every update needs a Home Assistant restart, as with any integration.
- Removing the integration doesn't copy shared data back into browsers. If you'll keep using the card on its own, scan again afterwards.
- Everything that applies to the card applies here too, for example sleepy battery devices and partial binding-table reads. See the [card's limitations](https://github.com/hsolgaard/zha-bindings-manager#important-limitations).

<details>
<summary><strong>Troubleshooting</strong></summary>

**The sidebar page is missing.** Check **Configure** → *Show the ZHA Bindings page in the sidebar* is on, and that you're signed in as an admin. If another dashboard already uses the address `/zha-bindings-manager`, the page isn't added and a warning is logged.

**The toolbar shows an older version than you installed.** Another copy of the card loaded first. Check **Settings → Repairs** and ⚙ → **About**, and see [Installed the card from HACS too?](#installed-the-card-from-hacs-too)

**Something fails in the card.** Open the browser's developer console and look for lines beginning `[ZHA Bindings Manager]`. They contain the full request and the raw `zha-toolkit` response.

**Something fails in the integration.** Turn on debug logging, restart, and include the log in your bug report. Add this to `configuration.yaml` (merge it into an existing `logger:` block if you have one):

```yaml
logger:
  default: warning
  logs:
    custom_components.zha_bindings_manager: debug
```

</details>

## Removing it

1. Go to **Settings → Devices & services → ZHA Bindings Manager → ⋮ → Delete**.
2. Remove it in HACS (or delete the `custom_components/zha_bindings_manager/` folder) and restart Home Assistant.

The sidebar page goes with it. Anything a browser had saved locally stays in that browser.

## Development

The card is developed in [`zha-bindings-manager`](https://github.com/hsolgaard/zha-bindings-manager). This repository carries a copy of a released card build in `custom_components/zha_bindings_manager/frontend/`, and both repositories always share one version number. When a new card release exists, the **Update bundled card** workflow opens a pull request that copies it in and sets this integration's version to match.

Tests run against a real Home Assistant core:

```bash
pip install -r requirements_test.txt
pytest
```

## Related projects

- [`zha-bindings-manager`](https://github.com/hsolgaard/zha-bindings-manager): the card on its own, and where the card is developed.
- [`zigbee-capabilities`](https://github.com/hsolgaard/zigbee-capabilities): the openly licensed community device-capability dataset behind the card's Zigbee Capability Explorer.

## Credits

Designed, specified and tested by [Hans Solgaard](https://github.com/hsolgaard) against a real ZHA network.

Development assisted by [Claude](https://www.anthropic.com/claude) (Anthropic).

Built on:

- [ZHA](https://www.home-assistant.io/integrations/zha/) in Home Assistant
- [`zha-toolkit`](https://github.com/mdeweerd/zha-toolkit) by mdeweerd and contributors

## Licence

ZHA Bindings Manager is open source and released under the [MIT Licence](LICENSE).
