# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

from uuid import uuid4

from flask import flash, jsonify, make_response, redirect, request
from markupsafe import escape
from werkzeug.exceptions import NotFound

from indico.core.db import db
from indico.core.plugins import url_for_plugin
from indico.modules.events.controllers.base import RHDisplayEventBase
from indico.modules.events.management.controllers.base import RHManageEventBase

from indico_eventsponsors import _
from indico_eventsponsors.forms import SponsorForm, TemplateForm, build_matrix_form
from indico_eventsponsors.models.sponsors import Sponsor
from indico_eventsponsors.models.templates import TEMPLATE_FIELDS, SponsorTemplate
from indico_eventsponsors.models.tiers import SponsorTier
from indico_eventsponsors.rendering import build_groups, logo_url, render_block
from indico_eventsponsors.util import (apply_logo_fields, delete_logo, event_sponsors, event_templates, event_tiers,
                                       format_contribution_ids, next_position, seed_tier_into_templates,
                                       sync_contributions, sync_template_tiers)
from indico_eventsponsors.views import WPManageSponsors


class RHSponsorsManageBase(RHManageEventBase):
    pass


class RHManageSponsors(RHSponsorsManageBase):
    """The sponsor list -- the page the Customization menu points at."""

    def _process(self):
        return WPManageSponsors.render_template('manage_sponsors.html', self.event,
                                                sponsors=event_sponsors(self.event),
                                                tiers=event_tiers(self.event),
                                                templates=event_templates(self.event))


class RHSponsorCreate(RHSponsorsManageBase):
    def _process(self):
        # The query arguments are how "save and add another" carries a batch's
        # shared fields into the next blank form: sponsors usually arrive
        # grouped by tier, so the tier should not fall back to "No tier" on
        # every add. On a POST the submitted data wins over these regardless.
        form = SponsorForm(event=self.event, is_active=request.args.get('is_active', '1') != '0',
                           tier_id=request.args.get('tier_id', 0, type=int))
        if form.validate_on_submit():
            sponsor = Sponsor(event_id=self.event.id)
            # `apply_sponsor_form` adds and flushes it: the contribution
            # associations need a sponsor row to point at.
            self._apply(form, sponsor)
            flash(_('Sponsor added.'), 'success')
            if 'save_add_another' in request.form:
                return redirect(url_for_plugin('eventsponsors.sponsor_create', self.event,
                                               tier_id=sponsor.tier_id or 0,
                                               is_active='1' if sponsor.is_active else '0'))
            return redirect(url_for_plugin('eventsponsors.manage', self.event, _anchor=f'sponsor-{sponsor.id}'))
        return WPManageSponsors.render_template('edit_sponsor.html', self.event, form=form, sponsor=None)

    def _apply(self, form, sponsor):
        apply_sponsor_form(self.event, form, sponsor)


class RHSponsorEdit(RHSponsorsManageBase):
    normalize_url_spec = {'locators': {lambda self: self.sponsor}}

    def _process_args(self):
        RHSponsorsManageBase._process_args(self)
        self.sponsor = _get_sponsor(self.event, request.view_args['sponsor_id'])

    def _process(self):
        form = SponsorForm(event=self.event, obj=self.sponsor,
                           tier_id=self.sponsor.tier_id or 0,
                           contribution_ids=format_contribution_ids(self.event, self.sponsor.linked_contribution_ids))
        if form.validate_on_submit():
            apply_sponsor_form(self.event, form, self.sponsor)
            flash(_('Sponsor updated.'), 'success')
            return redirect(url_for_plugin('eventsponsors.manage', self.event, _anchor=f'sponsor-{self.sponsor.id}'))
        return WPManageSponsors.render_template('edit_sponsor.html', self.event, form=form, sponsor=self.sponsor)


class RHSponsorDelete(RHSponsorsManageBase):
    def _process_args(self):
        RHSponsorsManageBase._process_args(self)
        self.sponsor = _get_sponsor(self.event, request.view_args['sponsor_id'])

    def _process_POST(self):
        delete_logo(self.sponsor.logo)
        delete_logo(self.sponsor.square_logo)
        db.session.delete(self.sponsor)
        db.session.flush()
        flash(_('Sponsor deleted.'), 'success')
        return redirect(url_for_plugin('eventsponsors.manage', self.event))


class RHSponsorMove(RHSponsorsManageBase):
    """Move a sponsor within its tier: one step, or straight to either end.

    The ends matter because new sponsors arrive alphabetically -- everyone
    starts at the column default position 0, name breaks the tie -- so "last
    alphabetically, wanted first" is the common case, and stepping there is
    one submit per row in between.
    """

    def _process_args(self):
        RHSponsorsManageBase._process_args(self)
        self.sponsor = _get_sponsor(self.event, request.view_args['sponsor_id'])

    def _process_POST(self):
        direction = request.view_args['direction']
        siblings = sorted((s for s in Sponsor.query.filter_by(event_id=self.event.id, tier_id=self.sponsor.tier_id)),
                          key=lambda s: (s.position, s.name.lower()))
        index = siblings.index(self.sponsor)
        if direction in ('up', 'down'):
            target = index + (-1 if direction == 'up' else 1)
            if 0 <= target < len(siblings):
                siblings[index], siblings[target] = siblings[target], siblings[index]
        else:
            siblings.insert(0 if direction == 'top' else len(siblings), siblings.pop(index))
        # Rewrite every position rather than swapping two: positions drift as
        # sponsors are added and deleted, and a swap between two equal values
        # does nothing at all.
        for position, sponsor in enumerate(siblings):
            sponsor.position = position
        db.session.flush()
        # The anchor lands the manager back on the row that moved instead of at
        # the top of the list, hunting for it after every step.
        return redirect(url_for_plugin('eventsponsors.manage', self.event, _anchor=f'sponsor-{self.sponsor.id}'))


class RHSponsorLogo(RHDisplayEventBase):
    """Serve a logo. Public, like any other image on an event's pages."""

    normalize_url_spec = {'locators': {lambda self: self.logo}}

    def _process_args(self):
        RHDisplayEventBase._process_args(self)
        from indico_eventsponsors.models.sponsors import SponsorLogo
        self.logo = SponsorLogo.query.filter_by(id=request.view_args['logo_id'],
                                                event_id=self.event.id).first()
        if self.logo is None:
            raise NotFound

    def _process(self):
        from indico.core.storage.backend import StorageError
        try:
            response = self.logo.send()
        except StorageError:
            # The row outliving its file is possible -- storage is not
            # transactional -- and when it happens the honest answer is that
            # this image is not here. A 404 renders as a broken image; letting
            # the StorageError through renders as a broken page.
            raise NotFound
        # A logo row is immutable -- replacing an image stores a new row with a
        # new id and swaps the sponsor's pointer -- so the content behind this
        # URL can never change, and `send_file`'s default `no-cache` would cost
        # one conditional request per logo per page view.
        response.cache_control.no_cache = False
        response.cache_control.max_age = 86400
        return response


class RHManageSettings(RHSponsorsManageBase):
    """Tiers and templates: the second page."""

    def _process(self):
        tiers = event_tiers(self.event)
        if request.method == 'POST':
            self._save_tiers(tiers)
            return redirect(url_for_plugin('eventsponsors.settings', self.event))
        return WPManageSponsors.render_template('manage_settings.html', self.event, tiers=tiers,
                                                templates=event_templates(self.event))

    def _save_tiers(self, tiers):
        kept, deleted_names = [], []
        for tier in tiers:
            if request.form.get(f'delete_{tier.id}'):
                deleted_names.append(tier.name)
                db.session.delete(tier)
            else:
                kept.append(tier)
        # Deletions reach the database before anything else: the unique
        # constraint on names is checked per statement, so a name freed by a
        # delete is only reusable -- by a rename, or by the new-tier row --
        # once the delete has been flushed.
        db.session.flush()

        desired = {}
        for tier in kept:
            name = (request.form.get(f'name_{tier.id}') or '').strip()
            size = request.form.get(f'size_{tier.id}')
            if not name or not (size or '').isdigit() or int(size) <= 0:
                flash(_('A tier needs a name and a size above zero; {name} was left as it was.')
                      .format(name=tier.name), 'warning')
                desired[tier.id] = (tier.name, tier.size)
            else:
                desired[tier.id] = (name, int(size))
        _resolve_tier_names(kept, desired)
        _apply_tier_changes(kept, desired)

        new_name = (request.form.get('new_name') or '').strip()
        new_size = request.form.get('new_size')
        if new_name:
            if not (new_size or '').isdigit() or int(new_size) <= 0:
                flash(_('The new tier needs a size above zero.'), 'warning')
            elif any(tier.name.lower() == new_name.lower() for tier in kept):
                flash(_('There is already a tier called {name}; the new tier was not added.')
                      .format(name=new_name), 'warning')
            else:
                tier = SponsorTier(event_id=self.event.id, name=new_name, size=int(new_size),
                                   position=next_position(SponsorTier, self.event))
                db.session.add(tier)
                db.session.flush()
                # The templates already exist, so the new tier needs its row in
                # each of them now -- nothing else ever writes one, and a tier
                # without rows renders nowhere while looking configured.
                seed_tier_into_templates(self.event, tier)
        db.session.flush()
        if deleted_names:
            flash(_('Tiers saved; deleted {names}.').format(names=', '.join(deleted_names)), 'success')
        else:
            flash(_('Tiers saved.'), 'success')


def _resolve_tier_names(kept, desired):
    """Settle every tier's final name before anything is written.

    Only the database enforces the unique constraint on names, and it does so
    as a 500 that rolls back the whole save -- every rename, resize and delete
    on the page. What matters is the *final* set of names, compared
    case-insensitively (the constraint is not): swapping two tiers' names in
    one submit is a valid end state, while renaming a tier onto one that keeps
    its name is a collision, and a collision reverts that one row instead of
    losing the save.
    """
    claimed = {}

    def revert(tier):
        flash(_('There is already a tier called {name}; it was left as it was.')
              .format(name=desired[tier.id][0]), 'warning')
        lowered = desired[tier.id][0].lower()
        if claimed.get(lowered) is tier:
            del claimed[lowered]
        desired[tier.id] = (tier.name, tier.size)
        # The stored name a reverted tier falls back to may itself have been
        # claimed by an earlier rename; that tier then reverts too. Each tier
        # reverts at most once, so the chain ends.
        other = claimed.get(tier.name.lower())
        if other is not None and other is not tier:
            revert(other)
        claimed[tier.name.lower()] = tier

    for tier in kept:
        name = desired[tier.id][0]
        if name == tier.name:
            # An unchanged name never produces an UPDATE, so it can never trip
            # the constraint -- whatever else claims it must step aside.
            claimed.setdefault(name.lower(), tier)
            continue
        lowered = name.lower()
        other = claimed.get(lowered)
        # A rename is blocked by an earlier tier that settled on the name, and
        # equally by a later tier that holds it and is not renaming away.
        blocked = (other is not None and other is not tier) or (
            lowered != tier.name.lower()
            and any(t is not tier and t.name.lower() == lowered and desired[t.id][0].lower() == lowered
                    for t in kept))
        if blocked:
            revert(tier)
        else:
            claimed[lowered] = tier


def _apply_tier_changes(kept, desired):
    """Write the settled names and sizes back, in a constraint-safe order.

    The unique constraint is checked per statement, not at commit, so a rename
    onto a name another tier is still holding -- a swap, or a chain of renames
    -- detours through a throwaway name first. The tier that detours is the
    one *vacating* a wanted name, not the one claiming it: the final flush
    batches its UPDATEs in primary-key order, so a claim can reach the
    database before the vacate it depends on, and only freeing the name
    beforehand is safe in both directions.
    """
    wanted = {desired[tier.id][0].lower(): tier for tier in kept}
    detoured = False
    for tier in kept:
        claimer = wanted.get(tier.name.lower())
        if claimer is not None and claimer is not tier:
            tier.name = uuid4().hex
            detoured = True
    if detoured:
        db.session.flush()
    for tier in kept:
        tier.name, tier.size = desired[tier.id]
    db.session.flush()


class RHTemplateCreate(RHSponsorsManageBase):
    def _process(self):
        return _edit_template(self, None)


class RHTemplateEdit(RHSponsorsManageBase):
    def _process_args(self):
        RHSponsorsManageBase._process_args(self)
        self.template = _get_template(self.event, request.view_args['template_id'])

    def _process(self):
        return _edit_template(self, self.template)


class RHTemplateDelete(RHSponsorsManageBase):
    def _process_args(self):
        RHSponsorsManageBase._process_args(self)
        self.template = _get_template(self.event, request.view_args['template_id'])

    def _process_POST(self):
        db.session.delete(self.template)
        db.session.flush()
        flash(_('Template deleted.'), 'success')
        return redirect(url_for_plugin('eventsponsors.settings', self.event))


class RHTemplatePreview(RHSponsorsManageBase):
    """One template rendered exactly as a visitor would see it.

    Served bare, for an iframe on the management pages: the iframe keeps the
    block's inlined `<style>` away from the management page's own rules, and
    gives the manager the real thing -- current sponsors, current matrix, real
    logo widths -- without saving and hunting down a public page carrying the
    shortcode.
    """

    # The management base sends `X-Frame-Options: DENY`, which would block the
    # one thing this endpoint exists for. Same-origin framing must stay open
    # for the settings page's iframe; anything cross-origin stays refused.
    DENY_FRAMES = False

    def _process_args(self):
        RHSponsorsManageBase._process_args(self)
        self.template = _get_template(self.event, request.view_args['template_id'])

    def _process(self):
        html = render_block(self.event, self.template, with_styles=True)
        if not html:
            # An empty block on a public page is deliberate silence; in a
            # preview it reads as breakage, so say why there is nothing.
            html = ('<p style="font-family: sans-serif; color: #777;">{}</p>'
                    .format(escape(_('This template currently renders nothing: it needs at least one active '
                                     'sponsor in a tier the template shows.'))))
        response = make_response(html)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        return response


class RHSponsorsData(RHDisplayEventBase):
    """The sponsors as JSON, for the phone app.

    Carries the *app template's* per-tier field choices resolved onto each
    sponsor, so the app renders what the manager configured rather than
    reimplementing the matrix and drifting from it.
    """

    def _process(self):
        from indico_eventsponsors.plugin import FEATURE_NAME
        if not self.event.has_feature(FEATURE_NAME):
            raise NotFound
        templates = event_templates(self.event)
        template = next((t for t in templates if t.for_app), None) or (templates[0] if templates else None)
        if template is None:
            response = jsonify(event_id=self.event.id, template=None, tiers=[], sponsors=[])
        else:
            groups = build_groups(self.event, template)
            response = jsonify(
                event_id=self.event.id,
                event_title=self.event.title,
                template={'slug': template.slug, 'title': template.title, 'layout': template.layout,
                          'max_logo_pct': template.max_logo_pct,
                          'above_schedule': template.app_above_schedule},
                tiers=[{'id': g['tier'].id, 'name': g['tier'].name, 'size': g['tier'].size,
                        'width_pct': g['width_pct'], 'inline': bool(g['fields'].inline)} for g in groups],
                sponsors=[_serialize_sponsor(s, g) for g in groups for s in g['sponsors']],
            )
        # Public data, and by the app's sync design the one endpoint every
        # attendee's device hits on every sync. A minute of caching removes
        # most of the repeat load, and the app keeps its own copy anyway.
        response.cache_control.max_age = 60
        return response


def _serialize_sponsor(sponsor, group):
    fields = group['fields']
    return {
        'id': sponsor.id,
        'tier_id': group['tier'].id,
        'name': sponsor.name,
        'tagline': sponsor.tagline,
        'description': sponsor.description,
        'url': sponsor.link_url if fields.linked else None,
        # Global contribution ids, not the friendly ones the manager typed: this
        # is what a client matches against in the schedule payload.
        'contribution_ids': sponsor.linked_contribution_ids,
        'logo_url': logo_url(sponsor.logo) if sponsor.logo else None,
        'square_logo_url': logo_url(sponsor.square_logo) if sponsor.square_logo else None,
        'show': {field: bool(getattr(fields, field)) for field, _label in TEMPLATE_FIELDS},
    }


def apply_sponsor_form(event, form, sponsor):
    form.populate_obj(sponsor, skip={'logo', 'square_logo', 'delete_logo', 'delete_square_logo', 'tier_id',
                                     'contribution_ids'})
    sponsor.tier_id = form.tier_id.data or None
    apply_logo_fields(event, sponsor, form)
    if sponsor.id is None:
        # The associations need a sponsor row to point at.
        db.session.add(sponsor)
        db.session.flush()
    sync_contributions(sponsor, form.resolved_contribution_ids)
    if form.dropped_contribution_tokens:
        flash(_('No contribution in this event matches: {numbers}. The sponsor was saved without them.')
              .format(numbers=', '.join(form.dropped_contribution_tokens)), 'warning')


def _edit_template(rh, template):
    tiers = event_tiers(rh.event)
    existing = {ts.tier_id: ts for ts in template.tier_settings} if template else {}
    form = TemplateForm(obj=template)
    matrix_class = build_matrix_form(tiers, existing)
    matrix = matrix_class(request.form if request.method == 'POST' else None, prefix='matrix')
    if form.validate_on_submit():
        if _slug_taken(rh.event, form.slug.data, template):
            form.slug.errors.append(_('Another template already uses that shortcode.'))
        else:
            if template is None:
                template = SponsorTemplate(event_id=rh.event.id,
                                           position=next_position(SponsorTemplate, rh.event))
                db.session.add(template)
            form.populate_obj(template)
            db.session.flush()
            if template.for_app:
                _release_other_app_templates(rh.event, template)
            sync_template_tiers(template, tiers, matrix)
            flash(_('Template saved.'), 'success')
            return redirect(url_for_plugin('eventsponsors.settings', rh.event))
    return WPManageSponsors.render_template('edit_template.html', rh.event, form=form, matrix=matrix,
                                            template=template, tiers=tiers, fields=TEMPLATE_FIELDS)


def _release_other_app_templates(event, template):
    (SponsorTemplate.query
     .filter(SponsorTemplate.event_id == event.id, SponsorTemplate.id != template.id,
             SponsorTemplate.for_app.is_(True))
     .update({'for_app': False}, synchronize_session='fetch'))


def _slug_taken(event, slug, template):
    query = SponsorTemplate.query.filter_by(event_id=event.id, slug=slug)
    if template is not None:
        query = query.filter(SponsorTemplate.id != template.id)
    return query.has_rows()


def _get_sponsor(event, sponsor_id):
    sponsor = Sponsor.query.filter_by(id=sponsor_id, event_id=event.id).first()
    if sponsor is None:
        raise NotFound
    return sponsor


def _get_template(event, template_id):
    template = SponsorTemplate.query.filter_by(id=template_id, event_id=event.id).first()
    if template is None:
        raise NotFound
    return template
