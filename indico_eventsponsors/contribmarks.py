# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

"""A sponsor's logo under the abstract on Indico's own contribution page.

Nothing of the sort exists in core, and there is no hook beside the description
to hang it on: the contribution display template renders the abstract inline,
with no `template_hook` and no plugin-visible seam anywhere near it. So this
works the same way `shortcodes.py` does -- on the finished response -- and for
the same reason. Patching core would be cleaner and cannot ship inside a
plugin; a customization-directory template override would work and is
per-deployment configuration rather than plugin code, which is how staging and
production drift apart.

Working at this level is blunt, so the rules it follows are narrow ones:

* One endpoint only. The gates below are ordered so that an ordinary request --
  any request that is not a contribution display page -- pays a single
  comparison against `request.endpoint` and nothing else. No body is read, no
  query is made, no regular expression is run.
* The anchor is the single `<div class="description js-mathjax">` core renders,
  and the mark goes immediately after that element's own closing tag. Finding
  that tag means counting `<div>`s forward from the anchor, because a
  description is author-written HTML and may contain any number of nested ones.
* **If the scan does not resolve cleanly, nothing is inserted.** A logo landing
  in the middle of somebody's abstract, or after the wrong element, is worse
  than no logo at all -- the manager can see an absent mark and ask why; a
  misplaced one just looks like the page is broken. Same answer when the page
  carries no description block: "underneath the abstract" means nothing without
  an abstract.
* The mark is plain markup with an inline `style` and no script. This page
  never loads the plugin's assets, and a `<script>` injected into a finished
  response would need the request's CSP nonce, which this is in no position to
  know.

The regular expressions here scan forward from a fixed position and can never
backtrack across the document. This runs on public, unauthenticated page loads;
a pattern like `<div.*?</div>` would rescan to end-of-document for every
unterminated opener, which is unbounded CPU handed to anybody with a URL.
"""

import re

from flask import request
from markupsafe import escape

from indico_eventsponsors import _
from indico_eventsponsors.models.sponsors import Sponsor, SponsorContribution
from indico_eventsponsors.models.tiers import SponsorTier
from indico_eventsponsors.rendering import logo_url
from indico_eventsponsors.util import contribution_mark_settings


#: The substring the anchor must contain, tested before any pattern is run.
MARKER = 'class="description js-mathjax"'

#: Core's own markup, matched as it is written: `<div class="description
#: js-mathjax">`. Deliberately not tolerant of a different class list or a
#: different attribute order -- if core rewrites that block, this stops
#: recognising it and stops inserting, which is the correct failure. A tolerant
#: pattern would instead go looking for the nearest thing that resembles it.
_ANCHOR_RE = re.compile(r'<div\s+class="description js-mathjax"\s*>', re.IGNORECASE)

#: The tokens the depth scan cares about: a `div` opener, a `div` closer, or the
#: start of a comment. `\b` keeps `<divider>` out of it. Comments are tracked
#: because a description is author-written and a commented-out `</div>` in it
#: would close the block early -- and "early" here means a logo dropped into the
#: middle of the abstract. Anything else between the tags is text as far as this
#: is concerned; `<script>` and `<style>` cannot appear inside a description,
#: which core renders through `sanitize_html`.
_SCAN_RE = re.compile(r'<!--|<(/?)div\b', re.IGNORECASE)

#: How many tokens -- `<div>` tags and comments -- the scan will look at before
#: giving up. Generous --
#: a pasted abstract can be full of markup nobody wrote by hand -- but finite,
#: which is the point: this runs on public page loads, and the amount of work
#: one of them can ask for has to have a ceiling. Reaching it is treated as a
#: scan that did not resolve, so nothing is inserted.
_MAX_SCAN_TOKENS = 10000

#: A tall logo drawn at a wide setting would otherwise push the rest of the page
#: down the screen. The cap is in pixels rather than relative units because it
#: guards against artwork proportions, which have nothing to do with the width
#: the manager chose. Same number the phone app uses for the same logo.
_MAX_MARK_HEIGHT_PX = 140


def find_description_end(html):
    """Where the description element's closing `</div>` ends, or None.

    None means "do not insert": no description block, more than one of them, a
    stray closing tag, an unterminated comment, or an opener that never closes
    within the cap. Every one of those is a page this cannot read confidently,
    and the answer to a page this cannot read is to leave it exactly as it is.

    More than one match is a refusal rather than a choice of the first: core
    renders exactly one description block, so a second one came from somewhere
    else -- most likely author-written HTML inside the abstract itself -- and
    there is then no honest way to tell which is the one to sit under.
    """
    match = _ANCHOR_RE.search(html)
    if match is None or _ANCHOR_RE.search(html, match.end()) is not None:
        return None
    depth = 1
    cursor = match.end()
    for _token_number in range(_MAX_SCAN_TOKENS):
        token = _SCAN_RE.search(html, cursor)
        if token is None:
            return None
        if token.group(1) is None:
            # A comment. Skip the whole of it in one step rather than reading
            # what is inside: an unterminated one makes the rest of the
            # document a comment, so there is no matching close to be found.
            end = html.find('-->', token.end())
            if end == -1:
                return None
            cursor = end + 3
            continue
        if token.group(1):
            depth -= 1
            if depth == 0:
                # The closing tag may be written `</div >`, so the mark goes
                # after the whole of it rather than after a fixed number of
                # characters.
                close = html.find('>', token.end())
                return close + 1 if close != -1 else None
        else:
            depth += 1
        cursor = token.end()
    return None


def insert_mark(html, mark):
    """`html` with `mark` placed after the description block, or None.

    Split out from the response hook so that the placement rule can be read --
    and tested -- without a request, a response or a database behind it.
    """
    position = find_description_end(html)
    if position is None:
        return None
    return html[:position] + mark + html[position:]


def build_mark(sponsor, logo, width, unit):
    """The markup for one mark: a logo at the configured width, and nothing else.

    Not a link, matching the phone app's talk screen: this is a credit on a page
    about somebody's talk, not an invitation to leave it. The sponsors block a
    manager puts on the event's own pages is where links belong.

    Every style is inline because it has to be. This page loads none of the
    plugin's assets, and a `<style>` block dropped into a finished response
    would be styling a document this plugin has never seen. The width and unit
    are the only values that vary, and they are the pair `normalize_mark_width`
    has already clamped and restricted to `MARK_WIDTH_UNITS`, so no free text
    reaches the attribute. The sponsor's own data is escaped.

    A percentage resolves against the block the description was set in, so "20%"
    is a fifth of the width of the text it sits under -- which is what a manager
    picking that number is looking at.
    """
    alt = _('Sponsored by {name}').format(name=sponsor.name)
    # The class is for a site that wants to restyle or hide the mark from its
    # own stylesheet; nothing here depends on it.
    return (f'<div class="evsp-contrib-mark" style="width: {width}{unit}; max-width: 100%; '
            f'margin-top: 1.2em; opacity: 0.9;">'
            f'<img src="{escape(logo_url(logo))}" alt="{escape(alt)}" loading="lazy" '
            f'style="display: block; width: 100%; height: auto; max-height: {_MAX_MARK_HEIGHT_PX}px; '
            f'object-fit: contain; object-position: left center;">'
            f'</div>')


def find_sponsor(event, contribution_id):
    """The sponsor whose logo marks this talk, as (sponsor, logo), or None.

    One sponsor, not all of them, and the same one the phone app picks: the
    first in the order the sponsors are rendered in everywhere else -- largest
    tier first, then the manager's own ordering within it. A talk with several
    sponsors gets the senior one; the sponsors block is where the full list
    belongs, and a stack of logos under an abstract is not a credit any more.

    Untiered sponsors are excluded by the join, as they are everywhere else: a
    sponsor with no tier has no size, is never rendered on the site, and the
    management list is where its absence is meant to be noticed. Inactive ones
    are excluded too -- a lapsed sponsorship is kept, not shown.

    Either image will do, the ordinary logo first, matching the app's
    `logo_url ?? square_logo_url`: "square" is a preference about shape and not
    a promise that anybody uploaded two files.
    """
    sponsors = (Sponsor.query
                .join(SponsorContribution, SponsorContribution.sponsor_id == Sponsor.id)
                .join(SponsorTier, SponsorTier.id == Sponsor.tier_id)
                .filter(Sponsor.event_id == event.id, Sponsor.is_active,
                        SponsorContribution.contribution_id == contribution_id)
                .order_by(SponsorTier.position, SponsorTier.id, Sponsor.position, Sponsor.id)
                .all())
    for sponsor in sponsors:
        logo = sponsor.logo or sponsor.square_logo
        if logo is not None:
            return sponsor, logo
    return None


def mark_response(response):
    """`after_request` hook. Returns `response` untouched unless it needs work.

    The gates are in cost order, and the order is the point: everything before
    the database work is a comparison or two, so a request for anything other
    than a contribution's display page leaves this having done one dictionary
    lookup. `direct_passthrough` and `Content-Encoding` are both "the bytes are
    not ours to rewrite" -- a streamed file and an already-compressed body.
    """
    from indico.modules.events import Event

    from indico_eventsponsors.plugin import FEATURE_NAME, EventsponsorsPlugin

    if request.endpoint != 'contributions.display_contribution':
        return response
    if (request.method != 'GET' or response.status_code != 200 or response.direct_passthrough
            or response.mimetype != 'text/html' or response.headers.get('Content-Encoding')):
        return response
    view_args = request.view_args or {}
    event_id, contribution_id = view_args.get('event_id'), view_args.get('contrib_id')
    if event_id is None or contribution_id is None:
        return response
    try:
        event = Event.get(event_id, is_deleted=False)
        if event is None or not event.has_feature(FEATURE_NAME):
            return response
        marks = contribution_mark_settings(event)
        if not marks['on_web_detail']:
            return response
        found = find_sponsor(event, contribution_id)
        if found is None:
            return response
        sponsor, logo = found
        try:
            body = response.get_data(as_text=True)
        except (RuntimeError, UnicodeDecodeError):
            return response
        if MARKER not in body:
            return response
        marked = insert_mark(body, build_mark(sponsor, logo, marks['width'], marks['unit']))
        if marked is not None:
            response.set_data(marked)
    except Exception:
        # Flask re-raises an error out of an `after_request` hook, which would
        # throw away a page that was already built and hand the visitor an error
        # page instead. A sponsor's logo is not worth a contribution page: the
        # failure is logged and the page goes out unmarked.
        EventsponsorsPlugin.logger.exception('Could not add the sponsor mark on %s', request.path)
    return response
