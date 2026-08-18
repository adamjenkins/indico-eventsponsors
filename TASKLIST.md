# TASKLIST — Event Sponsors, round 1

A new Indico plugin: sponsor records per event, rendered into the site through
shortcodes, and published to the phone app.

Decisions taken with the user before building:

- Shortcodes are expanded **in the finished HTML response** of an event's public
  pages. Indico has no filter hook for author-written HTML, so this is the only
  mechanism that makes `{{sponsors_full}}` work wherever someone can type it.
- Tiers and templates are **per event, seeded from site-wide defaults** the
  first time an event turns the feature on. Nobody retypes Gold/Silver/Bronze
  per conference; editing one event never disturbs another.
- Sponsor records are **per event**. No shared library, no cross-event
  permission model.
- Added mid-build: the sponsors must also reach the **phone app**, through a
  template marked as the app's.

## Phase 1 — The plugin exists and can be switched on

- [x] `indico-eventsponsors/`, package `indico_eventsponsors`, distribution
      `indico-plugin-eventsponsors`, entry point `eventsponsors`, DB schema
      `plugin_eventsponsors`. Scaffolded from the shape of the blockschedule
      repo, which is this workspace's known-good plugin layout.
- [x] `EventSponsorsFeature`, off by default, on the event Features page.
- [x] The blueprint carries `event_feature`, so every URL 404s when it is off.
- [x] The Customization side-menu entry appears only with the feature on.

## Phase 2 — Data

- [x] `SponsorTier` — name, size, position, per event.
- [x] `Sponsor` — active, tier, name, tagline, description, homepage URL,
      campaign URL, "use the campaign URL for links", position.
- [x] `SponsorLogo` (`StoredFileMixin`) — one row per image, `kind` of `wide` or
      `square`, so both logos share one storage path scheme.
- [x] `SponsorTemplate` — slug (the shortcode), title, layout, the widest tier's
      share of the container, and a flag marking the one template the phone app
      uses.
- [x] `SponsorTemplateTier` — per template *and* tier: which of logo, square
      logo, name, tagline, description to show, and whether to link.
- [x] One migration creating the schema and all five tables.

## Phase 3 — Managing sponsors (Customization → Sponsors)

- [x] A list, grouped by tier, showing at a glance what is active.
- [x] Add/edit/delete a sponsor, with both logo uploads and a delete checkbox
      per image. Plain multipart form, not the dropzone widget — this is a
      handful of fields on an ordinary page, not an upload area.
- [x] Reordering within a tier.

## Phase 4 — Settings (tiers and templates)

- [x] Tier editor: every tier's name and size on one form, plus a blank row to
      add one and a delete box to remove one. One page, one save.
- [x] Template list; add/edit/delete a template.
- [x] The template editor's per-tier matrix: a row per tier, a checkbox per
      field, plus "link it". A tier added later shows up with sensible defaults
      rather than vanishing from existing templates.
- [x] Exactly one template can be the app's; choosing a new one clears the old.
- [x] Added 2026-08-18: a second switch beneath it puts that template above the
      day's talks instead of below them. Off by default.

## Phase 5 — Shortcodes on the site

- [x] `{{<slug>}}` expanded in `text/html` responses for event display pages.
      Slugs must match `sponsors?_[a-z0-9_]+`, which keeps the scan cheap and
      keeps the plugin away from any other `{{…}}` on the page.
- [x] Guards, in order of cost: GET only, HTML only, not a `/manage/` URL, the
      event has the feature, and the body actually contains `{{sponsor`. Only
      then does a regex run.
- [x] Unknown slugs are left alone, so a typo shows itself instead of silently
      rendering nothing.
- [x] Rendering: tier size drives logo width as a percentage of the container,
      relative to the largest tier — Gold 60 against Silver 40 gives Silver
      logos two thirds the width — so the block adapts to whatever space it is
      dropped into. A floor stops the smallest tier disappearing on a phone.

## Phase 6 — Site-wide defaults

- [x] Plugin settings at Administration → Plugins: default tiers and default
      templates.
- [x] Copied into an event the first time the feature is switched on there.
      Copied, not shared: the point is a starting position, not a constraint.

## Phase 7 — The phone app

- [x] A public JSON endpoint carrying the tiers, the sponsors and the *app
      template's* per-tier field choices — so the app renders what the manager
      configured instead of reimplementing the matrix.
- [x] `indico-schedule-app`: fetch on sync, store in IndexedDB, cache logos as
      blobs so they survive a cold offline start, and render a sponsors block.

## Verification

Against the live 3.3.12 instance: **26 browser checks** (`scripts/verify.py`)
and **21 unit tests**, plus **62 checks** in the phone app's own suite, six of
them new.

- [x] Feature off: no menu entry, URLs 404, shortcode left as typed.
- [x] Feature on: shortcode expands on a custom page and in the event
      description; an unknown slug is untouched.
- [x] Logo widths are in the ratio the tier sizes imply, measured in a browser
      rather than eyeballed.
- [x] Links honour the campaign-URL override.
- [x] Inactive sponsors never render.
- [x] The app shows the sponsors offline, from stored blobs.
