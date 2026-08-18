# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

import re

from werkzeug.datastructures import FileStorage

from indico.core.db import db

from indico_eventsponsors.models.sponsors import Sponsor, SponsorContribution, SponsorLogo
from indico_eventsponsors.models.templates import TEMPLATE_FIELDS, SponsorTemplate, SponsorTemplateTier
from indico_eventsponsors.models.tiers import SponsorTier


def event_tiers(event):
    return (SponsorTier.query.filter_by(event_id=event.id)
            .order_by(SponsorTier.position, SponsorTier.id).all())


def event_templates(event):
    return (SponsorTemplate.query.filter_by(event_id=event.id)
            .order_by(SponsorTemplate.position, SponsorTemplate.id).all())


def event_sponsors(event):
    """Every sponsor of the event, tiers first and untiered last.

    Untiered sponsors are sorted to the end rather than hidden: they never
    render on the site, and the management list is where somebody needs to
    notice that.
    """
    sponsors = Sponsor.query.filter_by(event_id=event.id).all()
    return sorted(sponsors, key=lambda s: (s.tier is None, s.tier.position if s.tier else 0,
                                           s.position, s.name.lower()))


def store_logo(event, file_storage):
    """Save an uploaded image and return its `SponsorLogo`."""
    # `event_id` rather than `event`: `_build_storage_path` reads it while
    # building the path, which happens before the row is ever flushed.
    logo = SponsorLogo(event_id=event.id, event=event, filename=file_storage.filename,
                       content_type=file_storage.mimetype)
    logo.save(file_storage.stream)
    db.session.add(logo)
    db.session.flush()
    return logo


def delete_logo(logo):
    """Remove an image from storage and from the database."""
    from indico_eventsponsors.plugin import EventsponsorsPlugin
    if logo is None:
        return
    # Row first, file second. Storage is not transactional: removing the file
    # takes effect immediately while the row only goes on commit, so doing it the
    # other way round leaves a sponsor pointing at a file that is not there if
    # anything later in the request fails -- which is a broken image on a
    # conference programme. This ordering fails the other way instead, leaving a
    # file nothing points at, which nobody ever sees.
    #
    # The pointers have to go before the row does, or the flush trips the
    # foreign key from `sponsors` and takes the whole request with it.
    for sponsor in Sponsor.query.filter(db.or_(Sponsor.logo_id == logo.id,
                                               Sponsor.square_logo_id == logo.id)):
        if sponsor.logo_id == logo.id:
            sponsor.logo_id = None
        if sponsor.square_logo_id == logo.id:
            sponsor.square_logo_id = None
    db.session.flush()
    db.session.delete(logo)
    db.session.flush()
    try:
        logo.delete()
    except Exception:
        # An orphaned file is not worth failing a request over, but a storage
        # backend refusing deletes is worth knowing about.
        EventsponsorsPlugin.logger.exception('Could not delete sponsor logo %r from storage', logo)


def apply_logo_fields(event, sponsor, form):
    """Apply the two upload fields and their two delete boxes to `sponsor`."""
    for attribute, upload_field, delete_field in (('logo', form.logo, form.delete_logo),
                                                  ('square_logo', form.square_logo, form.delete_square_logo)):
        current = getattr(sponsor, attribute)
        uploaded = upload_field.data
        # An untouched file input leaves the field holding whatever `obj=` put
        # there -- the existing `SponsorLogo` -- because that is how flask_wtf
        # keeps an edit form from wiping a file nobody meant to replace. So an
        # upload is only an upload when it is genuinely a `FileStorage`.
        if isinstance(uploaded, FileStorage) and uploaded.filename:
            setattr(sponsor, attribute, store_logo(event, uploaded))
            delete_logo(current)
        elif delete_field.data:
            setattr(sponsor, attribute, None)
            delete_logo(current)


def parse_contribution_ids(event, text):
    """Turn the comma-separated box into contribution ids belonging to `event`.

    Managers see a contribution's *friendly* id -- the small number in the
    event's contribution list and on the contribution's own page -- so that is
    what the box asks for. A global id (the number in a contribution's URL) is
    accepted too, because somebody who pasted one from the address bar has done
    nothing unreasonable and should not be told they are wrong.

    Returns (contribution_ids, unknown) where `unknown` holds whatever matched
    nothing, so the form can say which number it could not place rather than
    rejecting the lot.
    """
    contributions = [c for c in event.contributions if not c.is_deleted]
    by_friendly = {c.friendly_id: c.id for c in contributions}
    known_ids = {c.id for c in contributions}

    found, unknown = [], []
    for token in re.split(r'[\s,;]+', text or ''):
        if not token:
            continue
        if not token.lstrip('#').isdigit():
            unknown.append(token)
            continue
        number = int(token.lstrip('#'))
        # Friendly first: it is what the box asks for, and within one event a
        # friendly id is the more likely reading of a small number.
        if number in by_friendly:
            found.append(by_friendly[number])
        elif number in known_ids:
            found.append(number)
        else:
            unknown.append(token)
    # Order preserved, duplicates dropped -- somebody listing a talk twice meant
    # it once.
    return list(dict.fromkeys(found)), unknown


def format_contribution_ids(event, contribution_ids):
    """The friendly ids for `contribution_ids`, for putting back in the box."""
    friendly = {c.id: c.friendly_id for c in event.contributions if not c.is_deleted}
    return ', '.join(str(friendly[cid]) for cid in contribution_ids if cid in friendly)


def sync_contributions(sponsor, contribution_ids):
    """Make the sponsor's associations exactly `contribution_ids`."""
    wanted = set(contribution_ids)
    for link in list(sponsor.contribution_links):
        if link.contribution_id in wanted:
            wanted.discard(link.contribution_id)
        else:
            sponsor.contribution_links.remove(link)
    for contribution_id in wanted:
        sponsor.contribution_links.append(SponsorContribution(contribution_id=contribution_id))
    db.session.flush()


def sync_template_tiers(template, tiers, matrix_form):
    """Write the per-tier matrix back, creating rows for tiers that lacked one."""
    existing = {ts.tier_id: ts for ts in template.tier_settings}
    for tier in tiers:
        settings = existing.get(tier.id)
        if settings is None:
            settings = SponsorTemplateTier(template_id=template.id, tier_id=tier.id)
            db.session.add(settings)
        for field, _label in TEMPLATE_FIELDS:
            setattr(settings, field, bool(matrix_form[f'tier_{tier.id}_{field}'].data))
    db.session.flush()
