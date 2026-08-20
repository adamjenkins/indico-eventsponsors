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
  side by side and wrap ("display inline") or take a row each. Inline logos are
  drawn into a box of one shape and fitted inside it, so a row of mixed artwork
  stands on a single line. So `{{sponsors_full}}` might give
  Gold sponsors a logo and a paragraph while Silver sponsors get a logo and a
  name, and `{{sponsors_logoonly}}` gives everyone just a logo.
- A tier the template shows nothing for does not appear in that block at all.
  That is how a template is limited to its top tiers.
- A sponsor can be **attached to particular contributions** by listing their
  numbers — the ones shown in the event's contribution list. The phone app then
  draws that sponsor's logo small in the corner of those talks.
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

**Cloning an event** carries the sponsor setup instead: the tiers, templates
and per-tier choices are ticked by default in the clone dialog, while the
sponsors themselves — logo files included — are a separate box, since last
year's sponsor list is a separate decision. A clone made with neither ticked
still gets the site defaults, so a shortcode copied along with a page never
shows up raw.

## Marking a sponsor's talks

A sponsor can be attached to contributions, and those talks then carry the
sponsor's logo. **Tiers and templates → Sponsor marks on contributions**
controls that: a width with a unit — `%`, `px`, `em`, `rem`, `vh` or `vw`,
defaulting to `20%` — and three switches for the three places a mark can
appear.

The width is one number for all three, because a mark is the same gesture
wherever it lands; the unit is there because "a fifth of the row" and "eight
rem" are both reasonable answers and which one is right depends on the theme.
A percentage is of the space the mark sits in — the talk row in the app, the
content column on a contribution page.

| Switch | Where |
|---|---|
| Talk rows in the app | The small corner mark in the schedule, agenda and search lists |
| Talk screens in the app | Under the abstract on a talk's own screen |
| Contribution pages on the site | Under the abstract on the Indico contribution page |

The last one needs no shortcode. It is inserted into the finished page the
same way `{{sponsors_…}}` is, since Indico has no template hook beside a
contribution's description — so it appears on a contribution page without any
page having to ask for it, and nowhere else.

Only an **active** sponsor **in a tier** marks a talk, matching the rule the
rendered blocks already use.

## For the phone app

`GET /event/<id>/sponsors/data` returns the tiers, the sponsors and the *app
template's* per-tier field choices already resolved onto each sponsor, so a
client renders what the manager configured instead of reimplementing the matrix
and drifting from it. It 404s when the feature is off.

It also carries `contribution_marks` — the mark width, its unit, and whether
the app should draw marks on talk rows and on talk screens. A client that does
not find the key is talking to a plugin older than it is, and should keep
whatever it did before rather than inventing a default.

## Installation

Requires Indico 3.3 or newer. There are no frontend assets to build.

1. Get the plugin. Every tagged release attaches a wheel, which is all there is
   to install:
   ```bash
   pip install https://github.com/adamjenkins/indico-eventsponsors/releases/download/v0.2.0/indico_plugin_eventsponsors-0.2.0-py3-none-any.whl
   ```
   To work on the plugin instead, clone this repository anywhere convenient.
2. Activate Indico's virtualenv and install the plugin — from a clone, in
   editable mode:
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
