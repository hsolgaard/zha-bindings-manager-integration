# Changelog

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
