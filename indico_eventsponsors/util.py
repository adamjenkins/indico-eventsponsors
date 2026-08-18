# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

from werkzeug.datastructures import FileStorage

from indico.core.db import db

from indico_eventsponsors.models.sponsors import Sponsor, SponsorLogo
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
    try:
        logo.delete()
    except Exception:
        # A file already gone from storage must not block deleting the row that
        # points at it -- otherwise a half-cleaned upload wedges the form for
        # good, and the row is what actually renders a broken image. Logged
        # rather than swallowed, because a storage backend failing this way is
        # worth knowing about even though it is not the user's problem.
        EventsponsorsPlugin.logger.exception('Could not delete sponsor logo %r from storage', logo)
    db.session.delete(logo)


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
