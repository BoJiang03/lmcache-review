# Coverage of t1m4723 on train

- comments checked: 1080 of 1517; explained by some entry: 46 (4%)
- entries used at least once: 2 of 2; cost $3.30

| entry | kind | train PRs | held-out comments explained | rule |
| --- | --- | --- | --- | --- |
| m4042-001 | principle | 3 | 44 | When A change makes shared, generic code (an integration layer, coordinator, API layer, transfer path, or other code meant to serve every feature, pluggable component or device) depend on one specific optional/experimental feature, pluggable component or accelerator vendor/device. Typical forms: importing or looking up that specific class or module; holding state named after it; branching on its presence or on device/vendor identity; adding a special-cased helper, code path or fallback for it; or inlining its logic or documentation into a shared hook or handler, including a hook that is a no-op on the core path.: Ask the author to move the specific behavior and its documentation into that feature's, component's  |
| m4723-001 | principle | 1 | 2 | When a change puts a capability (method, abstract hook or attribute) on a base class or shared base type because every current subclass happens to need it, although the capability is not inherent to what that base type represents or could also apply to classes outside that hierarchy: Ask the author to justify that every future subclass must have the capability and that no class outs |
