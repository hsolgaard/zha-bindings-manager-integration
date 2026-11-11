# Changelog

## [1.10.5]

### Changed

- Bundles card 1.10.5: a light's own binding to a group can be removed from the Bindings tab, the coordinator-address
  warning says which router lists the device, and links use https://zigbee.solgaard.uk. No change to the integration
  itself.

## [1.10.4]

### Fixed

- **A light leaving a group isn't a lost binding.** When a device was a member of a ZHA group at the previous read and
  isn't any more (removed in the card, in ZHA's own group page or anywhere else), its missing binding to that group is
  no longer expected instead of being reported as lost. The same applies to a binding to a group that no longer exists.
  Remotes are never members of the groups they control, so their group bindings are still watched. Bundles card 1.10.4,
  which reports these removals straight away.

### Changed

- The lost-bindings Repairs notice explains that it's about bindings that disappeared without being removed in ZHA
  Bindings Manager, and its link opens the Bindings tab.

## [1.10.3]

### Changed

- Bundles card 1.10.3: after a setup where the devices didn't respond, **Remove what this set up** removes the bindings
  (and the group) it added (#41). No change to the integration itself.

## [1.10.2]

### Changed

- Bundles card 1.10.2: the sidebar page keeps the selected tab in the address (`/zha-bindings-manager#bindings`), so a
  reload stays on the same tab and you can link straight to one (#40). Includes 1.10.1's changes (it wasn't released
  on its own).

### Fixed

- Two problems Home Assistant's own check (hassfest) reports: the lost-bindings Repairs notice had its own description
  as well as a fix form, which a fixable notice can't have (its explanation is now in the fix form, including the note
  about devices whose automatic put-back was stopped), and logbook wasn't listed as a dependency although logbook
  entries are written (1.4.0).

## [1.10.1]

### Changed

- Bundles card 1.10.1: device questions have a new type for switch modules fitted behind a normal wall switch (no
  button questions for them), a new question on whether a device responds to remotes bound to it, and "It isn't a
  router" as an answer for end devices. No change to the integration itself.

## [1.10.0]

### Added

- **Record address changes and missed presses** (new option, on by default; read-only). Every device's short network
  address is read from ZHA every 5 minutes and when zigpy reports a join or rejoin, and only changes are kept (90
  days). When a remote sends On, Off or Toggle, each light bound to it directly is checked after 2 seconds; a missed
  press is logged with the light's address now and at the last press that worked. Websocket command `evidence_get`.
  Nothing is sent to any device. To find out whether address changes explain bindings that stop working although
  they're still in the table (reported by HarvsG).
- **Bundled card 1.10.0**, with the notice, details and the anonymised network report. See the
  [card changelog](https://github.com/hsolgaard/zha-bindings-manager/blob/main/CHANGELOG.md).

### Changed

- **Switch the lights from Home Assistant…** waits 2.2 seconds, so the missed-press check sees the light first.



Rolls up what was tested as 1.7.0, 1.8.0 and 1.9.0 betas.

### Added

- **Watch for lost bindings**, reworked and now **on by default** (existing installs are switched on when they
  update; turn it off under Configure). Every read of a device's binding table is compared with what it had before,
  so a card scan no longer quietly accepts a loss, and a binding missing from a successful read is lost straight away.
  One Repairs issue for the whole network, with **Put them all back**. Per device in the card: Off, Tell me or Put
  back automatically (at most 3 times a day). Battery devices are put back at their next button press. Requested by
  HarvsG.
- **Switch the lights from Home Assistant if a press doesn't reach them** (per remote, off by default): after On,
  Off or Toggle, a directly bound light that hasn't changed within 2 seconds is switched by Home Assistant, logged,
  and the remote's bindings are checked while it's awake.
- **Replace a device**: websocket commands `replace_plan`, `replace_run` and `replace_cleanup` plan the swap from the
  saved scans (a dead device too), check the new device's clusters in the right role, copy the bindings with a
  read-back and clean up. Reported as feature `replace` in `get_capabilities`, so Lighting Manager can use it.
- **Messages to Home Assistant** (Experimental features): counts the messages each device sends to Home Assistant,
  per minute for the last hour, plus the coordinator's counters, for the card's Network tab.

### Changed

- **Bundled card 1.9.0**, with lost bindings, Replace this device…, device questions and Groups only on devices.
  See the [card changelog](https://github.com/hsolgaard/zha-bindings-manager/blob/main/CHANGELOG.md).
- The option **Check bindings every night and tell me when one disappears** is now **Watch for lost bindings**.
- Tests run on Python 3.14 (Home Assistant 2026.11 needs it).

## [1.6.1]

### Fixed

- **Bundled card 1.6.1:** the guided setup's "What other users found" now only counts reports for the clusters
  being bound, so earlier Level Control reports for a remote no longer warn against setting it up with a blind.
  Thanks to HarvsG (zigbee-capabilities#387). See the
  [card changelog](https://github.com/hsolgaard/zha-bindings-manager/blob/main/CHANGELOG.md).

## [1.6.0]

### Changed

- **Bundled card 1.6.0:** **Control lights with this…** is now **Set up what this controls…**. It asks whether a
  remote controls the devices directly or through a group (and suggests one), can set up blinds and curtains
  (Window Covering), never puts a device without the Groups cluster in a group, and no longer limits direct
  binding to 4 devices. The Advanced tab no longer reports a failed bind that worked, and a battery remote's
  endpoints and clusters can be shared even when the command check doesn't finish. Thanks to HarvsG
  (zigbee-capabilities#384, #387). See the
  [card changelog](https://github.com/hsolgaard/zha-bindings-manager/blob/main/CHANGELOG.md).

## [1.5.2]

### Added

- **Bundled card 1.5.2:** with Experimental features on, the Network tab flags a device using the coordinator's
  network address (0x0000), or two devices sharing one, which can flood or confuse the whole network. See the
  [card changelog](https://github.com/hsolgaard/zha-bindings-manager/blob/main/CHANGELOG.md).

## [1.5.1]

### Changed

- **Bundled card 1.5.1:** manufacturer-specific clusters (0xFC00 and up) are no longer checked or warned about, and
  the check after the guided setup is quicker, with a button to skip straight to the button test. See the
  [card changelog](https://github.com/hsolgaard/zha-bindings-manager/blob/main/CHANGELOG.md).

## [1.5.0]

### Added

- **Experimental features** option (off by default). Turns on the card's **Network tab** (beta) and route check,
  which read your routers' routing and neighbour tables with zha-toolkit only when you ask. The latest tables are
  saved, so the map is the same in every browser.
- **Link quality thresholds** under Configure (good from 150, weak below 80), with a reset to the recommended values.
- **The Repairs issue for a missing binding links to the device in the card**, when the sidebar page is on.
- **The card uses the integration's newer binding reads** (device-page Rescan and the nightly check), so both show
  the same bindings.
- **Bundled card 1.5.0**, with a new **Groups** tab for adding and removing lights, binding remotes and deleting groups
  safely. See the
  [card changelog](https://github.com/hsolgaard/zha-bindings-manager/blob/main/CHANGELOG.md).

## [1.4.2]

### Fixed

- **Logbook attribution no longer misses a change when the light reports first.** A light's own report can reach Home
  Assistant a moment before the remote's press does, so a press now also claims a change from up to 1.5 seconds
  before it. Previously that change got no "by … (direct binding)" entry.
- **Bundled card 1.4.2:** the device side panel only lists real control under Controls and Controlled by. See the
  [card changelog](https://github.com/hsolgaard/zha-bindings-manager/blob/main/CHANGELOG.md).

## [1.4.1]

### Security

- **Only admins can save the card's shared data.** `zha_bindings_manager/save_state` now requires an admin, like the
  sidebar page and ZHA's own commands. Reading is unchanged.
- **Saved bindings are validated.** Only well-formed bindings (whole-number endpoints and cluster ids, colon-hex
  addresses, group ids) are stored; anything else is dropped. Data saved by earlier versions is checked the same way
  when it's read for the device-page entities, removal notices and the binding watch.
- **Bundled card 1.4.1**, which validates saved bindings when it loads them and escapes binding fields on the page.
- Together these close a way for a non-admin user to run script in an admin's browser. Thanks to Franck Nijhof
  (@frenck) for spotting it in the HACS review.

## [1.4.0]

### Added

- **Say in the logbook which remote switched a light** (option, off by default). When a remote is bound to a light,
  directly or through a group, and Home Assistant also hears the press (most remotes are bound to the coordinator
  too), a light that changes within 3 seconds gets a logbook entry such as "Spots turned on by Hall dimmer (direct
  binding)". It uses the card's last scan of the remote. Changes made from Home Assistant itself (UI, scripts,
  automations) are never attributed to a remote, and holding a dimmer gives one entry per light, not one per step.
  Suggested by HarvsG in the "Is device binding a second-class citizen?" WTH thread.
- **Bundled card 1.4.0:** a device side panel instead of the Explode dialog, and **Control lights with a remote…** in
  the toolbar with a clear new-or-existing group choice. See the
  [card changelog](https://github.com/hsolgaard/zha-bindings-manager/blob/main/CHANGELOG.md).

## [1.3.2]

### Fixed

- **Bundled card 1.3.2: more device photos.** The card now finds a device's photo on zigbee2mqtt.io by its product
  code, which often differs from the model ZHA shows (for example the Clipsal Wiser 2AX switch and the IKEA RODRET),
  and tells Tuya devices that share a model string apart by manufacturer. See the
  [card changelog](https://github.com/hsolgaard/zha-bindings-manager/blob/main/CHANGELOG.md).

## [1.3.1]

### Changed

- **The Bindings sensor is short now.** Its state is a count, for example "Controls 2 · Controlled by 1", instead of
  the full list, which was cut off on the device page and made a meaningless history graph. The names are in the
  sensor's attributes (click it, then **Attributes**), under **controls** and **controlled by**, and are kept out
  of the history database.
- **With "Check bindings every night" on, Rescan bindings also counts as a check.** Two rescans after a binding
  disappears raise the Repairs issue, so you don't have to wait for the nightly run.

- **The Bindings sensor says where it comes from and links to the card.** Its attributes now start with **Shown by:
  ZHA Bindings Manager** and include **Open in ZHA Bindings Manager**, a link that opens the card's page on that
  device (card 1.3.1). The link needs Home Assistant's address (Settings → System → Network) and the sidebar page
  switched on; otherwise it's left out. The "Bindings disappeared" Repairs issue's **Learn more** opens the device
  in the card too.

### Fixed

- With "Check bindings every night" on, a device that loses all its bindings keeps its Bindings sensor and Rescan
  button (showing "No bindings"), so it can still be rescanned and repaired. Before, both disappeared.

Includes card 1.3.1, which can open a device straight from a link (`/zha-bindings-manager?device=<address>`).

## [1.3.0]

### Added

- **Find out when a binding disappears, and put it back.** A new option, **Check bindings every night and tell me
  when one disappears** (off by default), reads the binding table of every device that controls another device or
  a group at 03:17 each night, and checks battery devices the next time they're used instead. When a binding the
  card last saw is missing in two checks in a row, an issue appears under Settings → System → Repairs, naming the
  device and the bindings. From there you can **put them back** (the integration binds them again and checks) or
  say **you removed them on purpose**. Unbinding in the card is never reported, a device that doesn't answer never
  counts as a miss, and nothing is re-bound automatically. This came out of the community thread "WTH: Is device
  binding a second-class citizen?".

### Fixed

- **Bindings and Rescan bindings now appear on the ZHA device itself.** On Home Assistant 2026.10 and later, 1.2.0
  put them on a separate "ZHA Bindings Manager" device shown under the ZHA device's **Linked devices**, because Home
  Assistant no longer merges devices from different integrations. They're now attached to ZHA's own device, and the
  extra devices 1.2.0 created are removed automatically.
- The device-page sensor no longer loses track of the coordinator after a small scan when Home Assistant's ZHA
  gateway can't be asked directly. Routine coordinator bindings could briefly count as device-to-device ones.

Includes card 1.3.0, which has no changes.

## [1.2.0]

### Added

- **Bindings on each device's own page.** Every ZHA device that controls, or is controlled by, another device or a
  group now has a **Bindings** sensor and a **Rescan bindings** button on its normal Home Assistant device page
  (under Diagnostic). The sensor says what the device controls and what controls it, including through groups, for
  example "Controlled by Hall dimmer via group Kitchen (On/Off)". The button reads the device's binding table again.
  Devices with only routine coordinator bindings get nothing. The sensor updates whenever the card saves a scan.
  Switch it off with **Show bindings on each device's page** under Configure. This came out of the community thread
  "WTH: Is device binding a second-class citizen?".

Includes card 1.2.0, which has no changes.

## [1.1.0]

Includes card [1.1.0](https://github.com/hsolgaard/zha-bindings-manager/releases/tag/v1.1.0): **Control lights with
this…**, a guided way to make a remote control several lights. It creates or reuses a ZHA group, binds the remote to
it, checks each step, asks you to test with the remote's buttons, and offers to share the result with the community
database so others know how that remote behaves. No integration changes.

## [1.0.5]

Includes card [1.0.5](https://github.com/hsolgaard/zha-bindings-manager/releases/tag/v1.0.5): when you bind to a group,
the card now says how many devices in the group support the selected cluster and names the ones that don't, and
Binding Health warns about group bindings that nothing in the group can act on, or that point at an empty group. No
integration changes.

## [1.0.4]

Includes card [1.0.4](https://github.com/hsolgaard/zha-bindings-manager/releases/tag/v1.0.4), with fixes from forum
testing by John_smith. Binding a battery remote that falls asleep before the check now shows "not confirmed yet" with
a Check again button, instead of "Bind failed". The Bindings table no longer says "No bindings loaded yet" when coordinator
bindings are hidden. "Check supported commands" shows its progress and stops waiting after 2 minutes. Binding Health
says "Valid" instead of "OK" and warns about Basic cluster bindings between devices. No integration changes.

## [1.0.3]

Includes card [1.0.3](https://github.com/hsolgaard/zha-bindings-manager/releases/tag/v1.0.3): a scan where nothing
responds now says zha-toolkit is the likely cause and shows the actual error, instead of blaming sleepy devices
([#2](https://github.com/hsolgaard/zha-bindings-manager-integration/issues/2)). Scanning without zha-toolkit stops with
a clear message, and the scan summary separates battery devices from mains-powered ones. No integration changes.

## [1.0.2]

### Fixed

- **No more deprecation warning in the Home Assistant log.** At startup the integration looked up existing ZHA
  devices in a way Home Assistant deprecated in 2026.10 (it logged "uses `device_registry.devices` as a mapping",
  and it would stop working in 2027.9). It now uses the supported lookup. Nothing else changes. Thanks to MattWestb
  for the report.

Includes card [1.0.2](https://github.com/hsolgaard/zha-bindings-manager/releases/tag/v1.0.2), which has no changes.

## [1.0.1]

Includes card [1.0.1](https://github.com/hsolgaard/zha-bindings-manager/releases/tag/v1.0.1): removing a device from ZHA is
now picked up straight away, without refreshing the browser, and removed devices keep their name in the Bindings
table. No integration changes.

## [1.0.0]

ZHA Bindings Manager Backend becomes the **ZHA Bindings Manager integration**. It now includes the card (1.0.0) and
shares its version number.

### Added

- **ZHA Bindings sidebar page** (admins only), running the card full-page. No dashboard YAML needed.
- **The card is served by the integration** with the version in its address, so updates always load fresh.
- **Configure** has four switches: sidebar page, load the card on every page (off by default), shared storage and
  removed-device notices.
- **Repairs notice** when the card is also installed from HACS.
- `get_capabilities` reports the bundled card version and which options are on.
- Brand icon, HACS and hassfest validation, and tests against real Home Assistant core.

### Changed

- Renamed to ZHA Bindings Manager (repository `zha-bindings-manager-integration`). Existing entries are renamed
  automatically; saved data is unchanged.
- Requires Home Assistant 2024.7 or newer.

## [0.2.0]

- Notification when a removed ZHA device still has bindings pointing to it.

## [0.1.0]

- Shared storage for the card.
