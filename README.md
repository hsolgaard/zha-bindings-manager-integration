# ZHA Bindings Manager Backend

Optional persistent, shared storage for the
[ZHA Bindings Manager](https://github.com/hsolgaard/zha-bindings-manager)
Lovelace card.

> This is a companion integration, not a replacement for anything. The
> card works completely on its own without this installed — its data just
> lives only in whichever browser you last used it from. Installing this
> gives the card somewhere to save that data so it survives across
> browsers and devices instead.

## What this is (and isn't)

This is a small Home Assistant **integration** (not a card, not a
dashboard resource) with exactly one job: give the ZHA Bindings Manager
card a place to read and write its state that isn't a single browser's
`localStorage`. It has no dashboard presence, no entities, and nothing to
configure beyond adding it.

- **Storage** → Home Assistant's own `homeassistant.helpers.storage.Store`
  (the same mechanism most core integrations use for their own state),
  written to your config directory's `.storage/` folder.
- **API** → three WebSocket commands the card calls: `get_capabilities`
  (feature detection — "is this installed?"), `get_state`, `save_state`.
- **Conflict handling** → last-write-wins, compared by a timestamp. If
  two browsers try to save at nearly the same time, the second save is
  rejected with a message telling that client to reload and retry, rather
  than silently overwriting the first save.

What it deliberately does **not** do yet: track revision history, merge
concurrent edits, push live updates to other open browsers, or support
more than one Home Assistant instance. See the card repo's delivery plan
for the reasoning — this is intentionally the smallest version that makes
"my data survives a reload and is shared across my devices" true, not a
general-purpose sync engine.

## Installing

### Via HACS (custom repository)

1. This project isn't in the default HACS store — add it as a custom
   repository instead: **HACS → ⋮ → Custom repositories**, add
   `https://github.com/hsolgaard/zha-bindings-manager-backend` with
   category **Integration**.
2. Install "ZHA Bindings Manager Backend" from HACS.
3. Restart Home Assistant.
4. **Settings → Devices & Services → Add Integration**, search "ZHA
   Bindings Manager Backend", confirm. There's nothing to fill in.

### Manual

1. Copy `custom_components/zha_bindings_manager/` into your Home
   Assistant config directory's `custom_components/` folder.
2. Restart Home Assistant.
3. Add it the same way as step 4 above.

## Using it

There's nothing to do here directly — this integration has no UI of its
own. Once it's installed and added, the ZHA Bindings Manager card detects
it automatically the next time it loads, and offers to import your
existing browser-local data into shared storage (or start fresh). From
then on the card shows whether it's using shared storage or browser-only
storage, right on the card itself.

## Notices when a bound device is removed

From version 0.2.0 the backend also watches for devices being removed from
ZHA. If other devices still have bindings to the removed one, according to
the card's last scan, Home Assistant shows a notification that names them.
Those bindings use slots in each device's binding table and send commands
to nobody.

- If you removed the device to pair it again, ignore the notice. Once the
  device is back with the same address its bindings work again, and the
  notice is dismissed automatically.
- If the device is gone for good, open the card's Bindings tab and click
  **Unbind all** in the banner above the table (card 0.36.4 or later).

The backend never unbinds anything itself and never changes the card's
saved data. It only reads it to write the notice.

## Removing it

Uninstalling this integration doesn't delete anything the card has saved
in your browser's local storage — the card simply falls back to
browser-only storage the next time it loads and finds this integration
gone. It does **not** automatically copy the shared data back down into
your browser first, so if you want to keep working from what was in
shared storage, note it down (or re-scan) before removing this.

## Related projects

- [ZHA Bindings Manager](https://github.com/hsolgaard/zha-bindings-manager) —
  the card this integration exists to support. Install that first; this
  repo is optional and does nothing on its own.

## Credits

Designed, specified, and tested by [H Solgaard](https://github.com/hsolgaard).
Development assisted by [Claude](https://www.anthropic.com/claude)
(Anthropic).
