# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

"""What a brand-new event starts with.

An admin sets the tier list at Administration -> Plugins; the templates below
are fixed starting points rather than settings, because a template is mostly a
per-tier matrix and there are no tier *ids* to key one against until an event
exists. Both are copied into an event the first time the feature is switched on
there, and are the event's own from that moment on.

The sponsor-mark constants live here too. They are the same kind of thing -- a
starting position, plus the bounds it may be moved within -- and keeping them
beside the rest means the form, the app payload and the website mark all read
one definition instead of three that can drift apart.
"""

from math import isfinite

from indico.core.db import db

from indico_eventsponsors.models.sponsors import Sponsor  # noqa: F401  (imported so the mapper is configured)
from indico_eventsponsors.models.templates import TEMPLATE_FIELDS, SponsorTemplate, SponsorTemplateTier
from indico_eventsponsors.models.tiers import SponsorTier


DEFAULT_TIERS = (
    ('Platinum', 100),
    ('Gold', 70),
    ('Silver', 45),
    ('Bronze', 30),
)

#: Each template is (slug, title, layout, max_logo_pct, fields), where `fields`
#: maps a *rank* -- 0 for the largest tier, 1 for the next, and so on -- to the
#: field names that tier shows. A rank with no entry falls back to the last one
#: listed, so a site with six tiers still gets something sensible.
DEFAULT_TEMPLATES = (
    ('sponsors_full', 'Full', 'list', 30, {
        0: ('show_logo', 'show_name', 'show_description', 'linked'),
        1: ('show_logo', 'show_name', 'show_tagline', 'linked'),
        2: ('show_logo', 'show_name', 'linked'),
    }),
    ('sponsors_logoonly', 'Logos only', 'grid', 22, {
        0: ('show_logo', 'linked'),
    }),
    ('sponsors_app', 'Phone app', 'grid', 40, {
        0: ('show_logo', 'show_name', 'show_tagline', 'linked'),
        1: ('show_logo', 'show_name', 'linked'),
    }),
)

#: The slug whose default template is marked as the app's.
APP_TEMPLATE_SLUG = 'sponsors_app'

#: The units a sponsor mark's width may be given in. The width and its unit end
#: up concatenated into a `style` attribute in three places, two of them
#: server-rendered, so the unit is only ever one of these: a free-text CSS
#: length must never reach an attribute.
MARK_WIDTH_UNITS = ('%', 'px', 'em', 'rem', 'vh', 'vw')

#: (smallest, largest) per unit -- wide enough not to argue with anybody's
#: layout, narrow enough that a typo, or a crafted request, cannot blow the
#: mark up over the page it is meant to sit quietly on.
MARK_WIDTH_LIMITS = {'%': (1, 100), 'px': (1, 1000), 'em': (0.1, 50),
                     'rem': (0.1, 50), 'vh': (1, 100), 'vw': (1, 100)}

#: What an event starts with, and what anything unusable falls back to.
DEFAULT_MARK_WIDTH = 20
DEFAULT_MARK_UNIT = '%'


def normalize_mark_width(width, unit):
    """Settle a stored or submitted (width, unit) pair into a usable one.

    The one place the pair is coerced and clamped, so the settings form, the
    app payload and the website mark cannot disagree about what a width means
    -- or about what to do with one that means nothing. Anything unusable
    falls back to the default rather than rendering: a mark at the wrong size
    is a nuisance, a `style` attribute carrying somebody else's CSS is not.

    Returns (width, unit), the width as an `int` whenever it has no fractional
    part, so that `%` and `px` -- which is very nearly every mark -- stay whole
    numbers both in the JSON and in the attribute.
    """
    if unit not in MARK_WIDTH_UNITS:
        # An unrecognised unit takes the width down with it. The two only mean
        # anything together: a width of 20 was chosen for the unit it was
        # stored beside, and keeping it against a fallback unit invents a size
        # nobody asked for.
        return DEFAULT_MARK_WIDTH, DEFAULT_MARK_UNIT
    try:
        value = float(width)
    except (TypeError, ValueError):
        value = float(DEFAULT_MARK_WIDTH)
    if not isfinite(value):
        # `min`/`max` pass a NaN straight through instead of clamping it, so
        # this cannot be left to the bounds below.
        value = float(DEFAULT_MARK_WIDTH)
    low, high = MARK_WIDTH_LIMITS[unit]
    # Two decimals is as fine as a mark width ever needs to be, and rounding
    # keeps float arithmetic from writing 0.30000000000000004 into a style.
    value = round(min(max(value, low), high), 2)
    return (int(value) if value == int(value) else value), unit


def parse_tier_lines(text):
    """Parse the admin setting's "Name = size" lines into (name, size) pairs.

    Raises `ValueError` with a message meant for the admin editing the box.
    """
    tiers = []
    seen = set()
    for number, raw in enumerate((text or '').splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, size = line.partition('=')
        name, size = name.strip(), size.strip()
        if not separator or not name:
            raise ValueError(f'Line {number}: expected "Name = size", got {line!r}')
        if not size.isdigit() or int(size) <= 0:
            raise ValueError(f'Line {number}: {size!r} is not a size (a whole number above zero)')
        if name.lower() in seen:
            raise ValueError(f'Line {number}: {name!r} appears twice')
        seen.add(name.lower())
        tiers.append((name, int(size)))
    return tiers


def seed_event(event, tiers, templates):
    """Give `event` its own copy of the default tiers and templates.

    Does nothing if the event already has tiers *or templates* -- switching the
    feature off and on again must not resurrect deleted tiers or duplicate
    edited ones. Templates are checked too because an event can legitimately
    hold zero tiers, and re-seeding one would collide with its surviving
    templates on the slug constraint.
    """
    if (SponsorTier.query.filter_by(event_id=event.id).has_rows()
            or SponsorTemplate.query.filter_by(event_id=event.id).has_rows()):
        return

    created = []
    # Largest first, so a template's rank 0 is the top tier whatever the admin
    # called it.
    for position, (name, size) in enumerate(sorted(tiers, key=lambda t: -t[1])):
        tier = SponsorTier(event_id=event.id, name=name, size=size, position=position)
        db.session.add(tier)
        created.append(tier)
    db.session.flush()

    for position, (slug, title, layout, max_logo_pct, fields) in enumerate(templates):
        template = SponsorTemplate(event_id=event.id, slug=slug, title=title, layout=layout,
                                   max_logo_pct=max_logo_pct, position=position,
                                   for_app=(slug == APP_TEMPLATE_SLUG))
        db.session.add(template)
        db.session.flush()
        highest_rank = max(fields) if fields else 0
        for rank, tier in enumerate(created):
            shown = fields.get(min(rank, highest_rank), ())
            settings = SponsorTemplateTier(template_id=template.id, tier_id=tier.id)
            for field, _label in TEMPLATE_FIELDS:
                setattr(settings, field, field in shown)
            db.session.add(settings)
    db.session.flush()
