# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

"""Turning an event's sponsors into a block of HTML.

The sizing rule lives here and nowhere else: a tier's `size` is meaningless on
its own and only ever compared with the other tiers of the same event. The
largest tier is drawn at the template's `max_logo_pct` of the block's width and
everything else in proportion, so the block is sized by the space it is dropped
into rather than by any fixed number of pixels.
"""

import re
from functools import cache
from pathlib import Path

from flask_pluginengine import render_plugin_template
from markupsafe import Markup
from sqlalchemy.orm import selectinload

from indico.core.plugins import url_for_plugin

from indico_eventsponsors.models.sponsors import Sponsor


#: Never smaller than this, whatever the arithmetic says: on a phone the block
#: is a few hundred pixels wide, and a quarter of that is not a logo any more.
MIN_LOGO_PX = 80

_STYLESHEET = Path(__file__).parent / 'templates' / 'sponsors.css'
_CSS_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)
_BLANK_LINES_RE = re.compile(r'\n{2,}')


@cache
def stylesheet():
    """The block's CSS, with its comments removed.

    Cached for the life of the process: this is a packaged asset that cannot
    change under a running server, and caching also means a missing file fails
    once rather than on every request.

    This file is inlined into somebody's page rather than served as an asset, so
    everything in it is downloaded by every visitor. The comments are written
    for whoever maintains the rules -- including the licence header, which the
    header linter requires and which has no business on a conference programme --
    and they are worth keeping in the repository and not worth shipping.

    Stripped with a regular expression, which is safe precisely because this is
    not arbitrary CSS: it is one file in this repository with no comment-like
    text inside a string.
    """
    css = _CSS_COMMENT_RE.sub('', _STYLESHEET.read_text())
    return _BLANK_LINES_RE.sub('\n', css).strip()


def logo_url(logo):
    return url_for_plugin('eventsponsors.logo', logo.event, logo_id=logo.id, filename=logo.filename)


def sponsor_image(sponsor, fields):
    """The image this template wants for this sponsor, or None.

    A template asking for the square logo falls back to the ordinary one rather
    than rendering a gap: "square" is a preference about shape, not a promise
    that somebody uploaded two files.
    """
    if fields.show_square_logo and sponsor.square_logo:
        return sponsor.square_logo
    if fields.show_logo or fields.show_square_logo:
        return sponsor.logo or (sponsor.square_logo if fields.show_logo else None)
    return None


def load_sponsors_by_tier(event):
    """The event's renderable sponsors in one round trip, grouped by tier id.

    `tier.sponsors` is a dynamic backref -- one query per tier -- and each
    sponsor's contribution links would otherwise lazy-load one at a time while
    being serialised. On the public JSON endpoint that query count multiplies
    by every attendee's every sync, so the whole set is fetched up front.
    """
    sponsors = (Sponsor.query
                .filter(Sponsor.event_id == event.id, Sponsor.is_active, Sponsor.tier_id.isnot(None))
                .options(selectinload(Sponsor.contribution_links))
                .all())
    by_tier = {}
    for sponsor in sponsors:
        by_tier.setdefault(sponsor.tier_id, []).append(sponsor)
    return by_tier


def build_groups(event, template, sponsors_by_tier=None):
    """One entry per tier this template renders, largest tier first.

    A tier the template has no settings for, or whose settings show nothing, is
    left out entirely -- that absence is how "Bronze does not appear in this
    block" is expressed. Sponsors with no tier at all are never rendered: with
    no tier there is no size, and no answer to how large to draw them.

    `sponsors_by_tier` takes the map `load_sponsors_by_tier` builds, so one
    page holding several shortcodes shares a single load.
    """
    settings_by_tier = {ts.tier_id: ts for ts in template.tier_settings}
    tiers = [t for t in sorted(event.sponsor_tiers, key=lambda t: (t.position, t.id))
             if t.id in settings_by_tier and settings_by_tier[t.id].shows_anything]
    if not tiers:
        return []
    if sponsors_by_tier is None:
        sponsors_by_tier = load_sponsors_by_tier(event)

    groups = []
    for tier in tiers:
        sponsors = sorted(sponsors_by_tier.get(tier.id, ()), key=lambda s: (s.position, s.name.lower()))
        if not sponsors:
            continue
        groups.append({'tier': tier, 'fields': settings_by_tier[tier.id], 'sponsors': sponsors})
    if not groups:
        return []
    # The largest tier that actually renders, not the largest configured: an
    # empty top tier -- the usual state early on, while the headline slot is
    # still being sold -- must not shrink every logo below it.
    largest = max(group['tier'].size for group in groups)
    for group in groups:
        group['width_pct'] = round(group['tier'].size / largest * template.max_logo_pct, 3)
    return groups


def render_block(event, template, *, with_styles=True, sponsors_by_tier=None):
    """The HTML for one shortcode.

    `with_styles` carries the stylesheet inline. The block can land on any page
    of the site, including ones this plugin never sees rendered, so it cannot
    assume a stylesheet was loaded -- it brings its own, once per response.
    """
    groups = build_groups(event, template, sponsors_by_tier)
    if not groups:
        return ''
    # The template is named with its plugin prefix rather than bare: this renders
    # from an `after_request` hook, which runs outside any plugin context, and a
    # bare name would need one.
    # `Markup`: this is the plugin's own stylesheet read off disk, not anything a
    # user supplied, and escaping it would put `&gt;` in the middle of a selector.
    styles = Markup(stylesheet()) if with_styles else None
    return render_plugin_template('eventsponsors:sponsors_block.html', template=template, groups=groups,
                                  styles=styles, logo_url=logo_url, sponsor_image=sponsor_image,
                                  min_logo_px=MIN_LOGO_PX)
