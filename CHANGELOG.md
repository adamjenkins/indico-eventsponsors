# Changelog

All notable changes to the Event Sponsors plugin are documented here.

## [Unreleased]

### Added
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
