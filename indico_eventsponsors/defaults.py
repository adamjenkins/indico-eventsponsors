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
"""

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

    Does nothing if the event already has tiers -- switching the feature off and
    on again must not resurrect deleted tiers or duplicate edited ones.
    """
    if SponsorTier.query.filter_by(event_id=event.id).has_rows():
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
