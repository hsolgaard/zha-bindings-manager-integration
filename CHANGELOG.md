# Changelog

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
