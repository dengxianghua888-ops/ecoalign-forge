# Choosing an example

- `quickstart.py` runs the built-in recorded demo. After the external-evidence fix,
  it deliberately exits **3**: one completed case/pair, four abstentions. No API key.
- `contact_policy.en.json` is a current **PolicyPack**, accepted by the new kernel's
  `--policy` option. It declares its own labels/actions. Custom packs need a live
  configuration or an explicitly injected mock transport; `--demo` uses the built-in
  recorded pack only.
- `policies/chinese_content_safety.json` and `policies/social_media_community.json`
  are historical **PolicyInput metadata**, retained at their original paths for
  compatibility. They are not PolicyPacks and cannot be passed to the new `--policy`
  CLI. Their descriptions do not replace the built-in rule handbook.

See the [migration guide](../docs/iteration-b-migration.md) to move to PolicyPack.
Do not interpret a generation target, an example description or a candidate label
as independently verified truth.
