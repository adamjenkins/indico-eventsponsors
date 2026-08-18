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
from pathlib import Path

from flask_pluginengine import render_plugin_template
from markupsafe import Markup

from indico.core.plugins import url_for_plugin


#: Never smaller than this, whatever the arithmetic says: on a phone the block
#: is a few hundred pixels wide, and a quarter of that is not a logo any more.
MIN_LOGO_PX = 80

_STYLESHEET = Path(__file__).parent / 'templates' / 'sponsors.css'
_CSS_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)
_BLANK_LINES_RE = re.compile(r'\n{2,}')


def stylesheet():
    """The block's CSS, with its comments removed.

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


def build_groups(event, template):
    """One entry per tier this template renders, largest tier first.

    A tier the template has no settings for, or whose settings show nothing, is
    left out entirely -- that absence is how "Bronze does not appear in this
    block" is expressed. Sponsors with no tier at all are never rendered: with
    no tier there is no size, and no answer to how large to draw them.
    """
    settings_by_tier = {ts.tier_id: ts for ts in template.tier_settings}
    tiers = [t for t in sorted(event.sponsor_tiers, key=lambda t: (t.position, t.id))
             if t.id in settings_by_tier and settings_by_tier[t.id].shows_anything]
    if not tiers:
        return []

    largest = max(t.size for t in tiers)
    groups = []
    for tier in tiers:
        fields = settings_by_tier[tier.id]
        sponsors = sorted((s for s in tier.sponsors if s.is_active), key=lambda s: (s.position, s.name.lower()))
        if not sponsors:
            continue
        groups.append({
            'tier': tier,
            'fields': fields,
            'sponsors': sponsors,
            'width_pct': round(tier.size / largest * template.max_logo_pct, 3),
        })
    return groups


def render_block(event, template, *, with_styles=True):
    """The HTML for one shortcode.

    `with_styles` carries the stylesheet inline. The block can land on any page
    of the site, including ones this plugin never sees rendered, so it cannot
    assume a stylesheet was loaded -- it brings its own, once per response.
    """
    groups = build_groups(event, template)
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
