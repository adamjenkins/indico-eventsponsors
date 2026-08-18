# indico-plugin-eventsponsors

Sponsor records for Indico events, rendered into the site wherever a shortcode
such as `{{sponsors_full}}` appears.

- Each event keeps its own sponsors: name, a one-line description, a full
  paragraph, a homepage address, a campaign address that can override it for
  links, an active/inactive switch, a tier, and up to two images — an ordinary
  logo and a square one.
- **Tiers carry a size**, and the size only means anything next to the other
  tiers of the same event. A Gold tier at 60 against a Silver tier at 40 draws
  Silver logos two thirds the width of Gold ones. Nothing is expressed in
  pixels: the largest tier takes a set share of whatever width the block is
  given, so the same block works in a page column, a sidebar or a phone.
- **Shortcodes are templates you edit.** A template is one shortcode, and
  decides — per tier — which of the logo, square logo, name, one-liner and
  paragraph appear, whether they link, and whether that tier's sponsors sit
  side by side and wrap ("display inline") or take a row each. So `{{sponsors_full}}` might give
  Gold sponsors a logo and a paragraph while Silver sponsors get a logo and a
  name, and `{{sponsors_logoonly}}` gives everyone just a logo.
- A tier the template shows nothing for does not appear in that block at all.
  That is how a template is limited to its top tiers.
- One template can be marked as the **phone app's**, and is what the app
  renders — either above the day's talks or below them, as a second switch
  decides. Below by default: the top of a phone screen is the space an attendee
  came for.

The feature is **off by default**. It is switched on per event from the event's
**Features** page, after which a **Sponsors** entry appears under
**Customization**.

## Where shortcodes work

Anywhere on an event's public pages: a custom menu page, the event description,
a contribution abstract, minutes. Type `{{sponsors_full}}` and it is replaced by
the block.

This is done by substituting into the finished HTML response, because Indico
offers no hook for filtering author-written HTML — a custom page renders its
stored HTML straight into the document with nothing extensible in between. The
consequences are worth stating plainly:

- It applies to **HTML pages of an event's display URLs only**. Management pages
  are skipped, so a manager editing a page still sees the shortcode they typed.
  PDFs, iCal, the API and email are not HTML and are never touched.
- The shortcode must be written **exactly** as `{{slug}}`, with no spaces inside
  the braces, and the slug must look like `sponsors_…` or `sponsor_…`. That is
  what lets an ordinary request be dismissed by a single substring test rather
  than a regular expression, and keeps the plugin away from any other doubled
  braces on the page.
- An **unrecognised slug is left exactly as typed**, so a mistyped shortcode
  shows itself rather than silently rendering nothing.
- The block carries its own stylesheet inline, once per page. It has to: it can
  land on pages belonging to themes this plugin never sees, and cannot assume a
  stylesheet was loaded. There is no asset build step for this plugin at all.

## Site-wide defaults

An administrator sets the default tier list at **Administration → Plugins →
Event Sponsors**, one tier per line as `Name = size`. Those tiers, and a
starting set of templates, are copied into an event the first time the feature
is switched on there. Copied, not shared — the point of a default is a starting
position, and an event editing its tiers must not change anyone else's.

## For the phone app

`GET /event/<id>/sponsors/data` returns the tiers, the sponsors and the *app
template's* per-tier field choices already resolved onto each sponsor, so a
client renders what the manager configured instead of reimplementing the matrix
and drifting from it. It 404s when the feature is off.

## Installation

Requires Indico 3.3 or newer. There are no frontend assets to build.

1. Clone this repository anywhere convenient.
2. Activate Indico's virtualenv and install the plugin:
   ```bash
   pip install -e .
   # (or, on a venv managed with uv: uv pip install --no-deps -e .)
   ```
3. Add `eventsponsors` to `PLUGINS` in `indico.conf`, keeping any already there:
   ```python
   PLUGINS = {'eventsponsors'}
   ```
4. Apply the database migration:
   ```bash
   indico db --plugin eventsponsors upgrade
   ```
5. Restart Indico.

Uploaded logos go to whatever `ATTACHMENT_STORAGE` is configured for; no
separate storage backend is needed.

## Development

```bash
pip install -e .
ruff check . && isort --check-only . && unbehead --check
pytest tests
```
