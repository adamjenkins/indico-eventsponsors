# Changelog

All notable changes to the Event Sponsors plugin are documented here.

## [0.1.0] — 2026-08-19

### Added
- **Event cloning.** Two cloners rather than one, because their costs differ:
  *Sponsorship tiers and templates* (ticked by default) carries the
  configuration an annual event almost always wants, while *Sponsors* carries
  last year's sponsor list — logo files copied byte for byte, contribution
  links following the cloned contributions — which is a separate decision. A
  clone made with neither ticked is still seeded with the site defaults,
  because the feature switch travels with the event and an enabled feature
  with no templates would leave any copied `{{sponsors_…}}` shortcode raw on
  the public pages.
- **A live preview of each template** — in the template editor, and behind an
  eye button on the settings page. The block exactly as a visitor sees it,
  with the event's current sponsors and real logo widths, rendered in an
  iframe so its inlined stylesheet stays off the management page. A template
  that currently renders nothing says so instead of showing an empty frame.
- **Click-to-copy shortcodes.** The shortcode is the one string a manager has
  to carry to another page by hand, so clicking it copies it — with a
  fallback for plain-HTTP instances, where `navigator.clipboard` does not
  exist.
- **Move to top and move to bottom** beside the single steps: new sponsors
  arrive alphabetically at position 0, so "last alphabetically, wanted first"
  was one submit per row in between. Moving or saving a sponsor now lands
  back on its row, via an anchor, rather than at the top of the list.
- **"Save and add another"** on a new sponsor's form, carrying the tier and
  the active switch into the next blank form — sponsors arrive in batches
  grouped by tier.
- **A contributions column** in the sponsor list, and an "Attached to"
  callout on a sponsor's page resolving the saved links to the numbers and
  titles the manager knows the talks by.
- **Deleting a tier asks first**, naming the ticked tiers and their sponsor
  counts — a tier takes its row in every template with it and leaves its
  sponsors untiered, which is too much to lose to a stray checkbox whose only
  button says "Save tiers". The save then reports what it deleted.
- **A callout on the sponsors page when the event has no templates**, since
  its shortcodes are then showing up verbatim to visitors — and a note under
  the site-wide default tiers explaining the three templates that are seeded
  alongside them.
- **"Display inline"** in a template's per-tier matrix: that tier's sponsors sit
  side by side and wrap onto further rows, rather than one per row. Per tier
  rather than per template on purpose — the usual arrangement is a headline tier
  with a row to itself and lower tiers flowing together, and that is one
  template.
- First working version. Sponsor records per event — name, one-line
  description, full paragraph, homepage, campaign link with an override for
  links, active/inactive, tier, and two optional images.
- **Sponsorship tiers with a size**, where the size is meaningful only next to
  the other tiers of the same event. A Gold tier at 60 against a Silver tier at
  40 draws Silver logos two thirds the width of Gold ones. Nothing is expressed
  in pixels: the largest tier takes a share of whatever width the block is
  given, so one block works in a page column, a sidebar and a phone.
- **Editable shortcode templates.** A template is one shortcode and decides,
  per tier, which of the logo, square logo, name, one-liner and paragraph
  appear and whether they link. A tier the template shows nothing for does not
  appear in that block at all, which is how a block is limited to its top
  tiers.
- **Shortcode expansion on an event's public pages**, so `{{sponsors_full}}`
  typed into a custom page, the event description or an abstract is replaced by
  the block. Done by substituting into the finished HTML response, because
  Indico offers no hook for filtering author-written HTML.
- **A Features switch**, off by default, gating both the Customization menu
  entry and every URL the plugin owns.
- **Site-wide defaults** at Administration → Plugins: a tier list an admin
  writes once, copied into an event the first time the feature is switched on
  there, along with three starting templates.
- **A JSON endpoint for the phone app** carrying the app template's per-tier
  field choices already resolved onto each sponsor, so a client renders what the
  manager configured instead of reimplementing the matrix.
- **"Display this above the schedule in the app"**, beneath the switch that
  makes a template the app's. Off by default: the top of a phone screen is the
  space an attendee came for, so a sponsor block there has to be chosen rather
  than inherited.

### Fixed
- **Renaming tiers into a collision no longer loses the whole save.** The
  unique constraint on names only ever surfaced as a 500 that rolled back
  every rename, resize and delete on the page. What matters is the *final*
  set of names, so the handler settles them first — case-insensitively,
  because two tiers differing only in case is a trap rather than a feature.
  Swapping two names in one submit works, chains of renames work (detouring
  through a throwaway name where the flush order would trip the constraint),
  deleting a name and re-adding it works, and a real collision reverts that
  one row with a warning instead of failing the save.
- **A tier created after the event's templates now renders in them.** It gets
  a row in every existing template, holding the same defaults the template
  editor shows for a tier without one; before, it rendered nowhere while the
  editor showed it fully configured.
- **The delete confirmations actually confirm.** They were inline `onsubmit`
  handlers, which Indico's CSP silently never runs — the nonce applies to
  script blocks, never to handler attributes — so deleting a sponsor or a
  template was one unguarded click. They now go through core's declarative
  `data-confirm`.
- **Link addresses are checked twice.** The form now carries a real `URL()`
  validator — `URLField` alone only sets `type="url"` on the input, which any
  crafted request skips — and `link_url` returns nothing unless the address
  is http(s), so a `javascript:` URL stored before the validator existed
  never reaches an anchor's href on a public page.
- **A typo in the contributions box no longer rejects the save.** The form is
  multipart and no browser repopulates a file input, so a failed submit cost
  whatever logos were selected. The unmatched numbers are dropped and named
  in a warning after saving instead.
- **A failed shortcode expansion leaves the page alone.** Flask re-raises an
  error out of an `after_request` hook, replacing a page that was already
  built with an error page; the raw shortcode stays, and the failure is
  logged.
- **An unterminated `<script>`, `<style>` or `<textarea>` no longer costs a
  rescan of the page.** The opaque-region matcher was one backtracking
  `.*?</tag>` regex, whose unterminated openers rescan to end-of-document —
  unbounded CPU in a filter running on public, unauthenticated loads. It is
  now a linear scan, and an opener with no closer makes the whole remainder
  opaque, which is also how a browser reads it.
- **A deleted logo's file leaves storage only after the commit.** Storage is
  not transactional: the old order removed the file immediately while the
  row's delete could still be rolled back by a later failure, leaving a
  sponsor pointing at a file that is not there. The file is now queued and
  swept once the commit has made the row's removal final; the one failure
  mode left is a file nothing points at, which nobody ever sees.
- **The sponsor queries no longer grow with the sponsor count.** The
  renderable sponsors are fetched in one round trip, contribution links
  included, and shared by every shortcode on the page — on the JSON endpoint
  the old per-tier, per-sponsor queries multiplied by every attendee's every
  sync. That endpoint is now cacheable for a minute, logo responses for a day
  (a logo URL's content can never change — replacing an image is a new row
  with a new id), and the stylesheet is read and stripped once per process.
- **An empty larger tier no longer shrinks everyone else.** The block's scale
  comes from the largest tier that actually renders, not the largest
  configured: an event that has not sold its headline slot yet — the usual
  starting state — must not draw every other logo smaller than asked for.
- **New tiers and templates sort after their own kind.** Both took their
  position from a count of the *tiers*, so a new template could land inside
  the seeded order — and positions survive deletions, so even a same-table
  count could collide with a surviving row. The next position is now the
  maximum of the row's own table plus one.
- **Switching the feature off and on again no longer re-seeds an event that
  deleted all its tiers.** An event can legitimately hold zero tiers; seeding
  is now skipped if either tiers or templates survive, where before the
  re-seed collided with the surviving templates on the slug constraint.
- **The inlined stylesheet no longer carries its own comments.** The block's CSS
  is injected into somebody's page rather than served as an asset, so everything
  in it is downloaded by every visitor — including the licence header the header
  linter requires. The comments stay in the repository and are stripped on the
  way out, which halved what gets inlined.
- **Inline logos now share a line.** Every logo in an inline tier is drawn into
  a box of the same shape, with the artwork fitted inside it standing on the
  floor — so a row of mixed proportions reads as a row. Anchoring the cards to
  the bottom was not enough: the text under each logo wraps to a different
  number of lines and left the logos wherever that text put them. The artwork is
  fitted, never cropped or stretched; the cost is that a tall logo is drawn
  smaller than a wide one of the same tier, which is the price of them sharing a
  line at all.
- **Sponsors could overlap each other on the page.** In the list layout a row
  was allowed to shrink below the height of the logo inside it, so a tall logo
  was drawn over the next sponsor and over whatever followed the block. Two
  causes, both inherited from rules the grid layout needs: `flex-wrap: wrap`
  turned the column into a multi-line flex container, which shrinks its items
  rather than growing, and `flex-shrink: 1` let it. Only showed up once real
  logos with real aspect ratios were uploaded.

### Notes on the shortcode mechanism
- Shortcodes are expanded in the **body** of an event's display pages only.
  Nothing in `<head>` is expanded into markup: Indico repeats the event
  description into `<meta property="og:description">`, and a block of logos
  cannot live in an attribute — a shortcode there is removed instead, so social
  previews get clean text.
- `<script>`, `<style>` and `<textarea>` contents are never touched, and
  management pages are skipped so an editor still shows the shortcode as typed.
- An unrecognised slug is left exactly as written, so a typo shows itself
  rather than silently rendering nothing.
