Requires **Indico 3.3 or newer**. The plugin has no frontend build, so the wheel
below is all there is to install — no Node.js and no Indico source checkout.

```bash
pip install https://github.com/@REPO@/releases/download/@TAG@/@WHEEL@
indico db --plugin eventsponsors upgrade
```

Add `eventsponsors` to `PLUGINS` in `indico.conf` and restart Indico. The plugin
is then off in every event until its **Sponsors** feature switch is turned on
there; site-wide default tiers and templates are set at Administration →
Plugins → Event Sponsors.
