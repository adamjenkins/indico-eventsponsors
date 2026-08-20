# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

import re

from flask import g, has_app_context
from werkzeug.datastructures import FileStorage

from indico.core.db import db
from indico.core.storage.backend import get_storage

from indico_eventsponsors.defaults import normalize_mark_width
from indico_eventsponsors.models.sponsors import Sponsor, SponsorContribution, SponsorLogo
from indico_eventsponsors.models.templates import NEW_TIER_FIELDS, TEMPLATE_FIELDS, SponsorTemplate, SponsorTemplateTier
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


def contribution_mark_settings(event):
    """The event's sponsor-mark settings, with the width already settled.

    One reader for the settings form, the app payload and the website mark, so
    that none of them has to remember that a stored width means nothing apart
    from its unit, or that either of the two can be nonsense -- an event
    restored from a backup of an older version, a setting written by hand.
    """
    from indico_eventsponsors.plugin import EventsponsorsPlugin
    settings = EventsponsorsPlugin.event_settings.get_all(event)
    width, unit = normalize_mark_width(settings['contrib_mark_width'], settings['contrib_mark_unit'])
    return {
        'width': width,
        'unit': unit,
        'on_rows': bool(settings['contrib_mark_on_rows']),
        'on_app_detail': bool(settings['contrib_mark_on_app_detail']),
        'on_web_detail': bool(settings['contrib_mark_on_web_detail']),
    }


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


#: `g` key holding the storage files whose rows were deleted in this request,
#: as (backend, file_id) pairs. Swept by `delete_queued_files` after commit.
_PENDING_FILES_KEY = 'eventsponsors_pending_file_deletes'


def delete_logo(logo):
    """Remove an image from the database, and from storage once that commits.

    Storage is not transactional: a file delete takes effect immediately, while
    the row delete below only happens on commit and is undone if anything later
    in the request fails -- which would leave a sponsor pointing at a file that
    is no longer there, a broken image on a conference programme. So the file
    is only queued here, and deleted by `delete_queued_files` once the commit
    has made the row's removal final. The one failure mode left is a file
    nothing points at, which nobody ever sees.

    The pointers have to go before the row does, or the flush trips the
    foreign key from `sponsors` and takes the whole request with it.
    """
    if logo is None:
        return
    for sponsor in Sponsor.query.filter(db.or_(Sponsor.logo_id == logo.id,
                                               Sponsor.square_logo_id == logo.id)):
        if sponsor.logo_id == logo.id:
            sponsor.logo_id = None
        if sponsor.square_logo_id == logo.id:
            sponsor.square_logo_id = None
    db.session.flush()
    db.session.delete(logo)
    db.session.flush()
    if logo.storage_file_id is not None:
        g.setdefault(_PENDING_FILES_KEY, []).append((logo.storage_backend, logo.storage_file_id))


def delete_queued_files(sender=None, **kwargs):
    """Delete the files whose rows went in this request. Runs after commit.

    Connected to `signals.core.after_commit` for the process's whole life (see
    the plugin) rather than connected and disconnected around each request:
    the queue lives in `g`, so a commit only ever sweeps its own request's
    files, and there is no receiver registration for another thread to race.
    """
    from indico_eventsponsors.plugin import EventsponsorsPlugin
    if not has_app_context():
        return
    for backend, file_id in g.pop(_PENDING_FILES_KEY, []):
        try:
            get_storage(backend).delete(file_id)
        except Exception:
            # The transaction is committed, so there is nothing left to fail:
            # an orphaned file is the accepted cost. A storage backend refusing
            # deletes is still worth knowing about.
            EventsponsorsPlugin.logger.exception('Could not delete file %s from storage %s', file_id, backend)


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


def next_position(model, event):
    """The position after every existing `model` row of `event`.

    `max + 1` rather than a row count: positions survive deletions, so a count
    can land on a position a surviving row still holds -- and the new row then
    sorts by the id tiebreak instead of unambiguously last.
    """
    last = db.session.query(db.func.max(model.position)).filter(model.event_id == event.id).scalar()
    return last + 1 if last is not None else 0


def seed_tier_into_templates(event, tier):
    """Give a brand-new tier a row in every template the event already has.

    Without this a tier created after the templates renders in none of them:
    `build_groups` reads a missing row as "deliberately excluded", while the
    template editor shows the tier with `NEW_TIER_FIELDS` ticked -- a default
    that would exist only on screen until every template was opened and
    re-saved. Storing that same set makes the form and the database agree.
    """
    for template in SponsorTemplate.query.filter_by(event_id=event.id):
        settings = SponsorTemplateTier(template=template, tier=tier)
        for field, _label in TEMPLATE_FIELDS:
            setattr(settings, field, field in NEW_TIER_FIELDS)
        db.session.add(settings)
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
