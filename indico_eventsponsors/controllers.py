# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

from flask import flash, jsonify, redirect, request
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
from indico_eventsponsors.rendering import build_groups, logo_url
from indico_eventsponsors.util import (apply_logo_fields, delete_logo, event_sponsors, event_templates, event_tiers,
                                       sync_template_tiers)
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
        form = SponsorForm(event=self.event, is_active=True)
        if form.validate_on_submit():
            sponsor = Sponsor(event_id=self.event.id)
            self._apply(form, sponsor)
            db.session.add(sponsor)
            db.session.flush()
            flash(_('Sponsor added.'), 'success')
            return redirect(url_for_plugin('eventsponsors.manage', self.event))
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
                           tier_id=self.sponsor.tier_id or 0)
        if form.validate_on_submit():
            apply_sponsor_form(self.event, form, self.sponsor)
            flash(_('Sponsor updated.'), 'success')
            return redirect(url_for_plugin('eventsponsors.manage', self.event))
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
    """Move a sponsor up or down within its tier."""

    def _process_args(self):
        RHSponsorsManageBase._process_args(self)
        self.sponsor = _get_sponsor(self.event, request.view_args['sponsor_id'])

    def _process_POST(self):
        direction = -1 if request.view_args['direction'] == 'up' else 1
        siblings = sorted((s for s in Sponsor.query.filter_by(event_id=self.event.id, tier_id=self.sponsor.tier_id)),
                          key=lambda s: (s.position, s.name.lower()))
        index = siblings.index(self.sponsor)
        target = index + direction
        if 0 <= target < len(siblings):
            siblings[index], siblings[target] = siblings[target], siblings[index]
        # Rewrite every position rather than swapping two: positions drift as
        # sponsors are added and deleted, and a swap between two equal values
        # does nothing at all.
        for position, sponsor in enumerate(siblings):
            sponsor.position = position
        db.session.flush()
        return redirect(url_for_plugin('eventsponsors.manage', self.event))


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
        return self.logo.send()


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
        for tier in tiers:
            if request.form.get(f'delete_{tier.id}'):
                db.session.delete(tier)
                continue
            name = (request.form.get(f'name_{tier.id}') or '').strip()
            size = request.form.get(f'size_{tier.id}')
            if not name or not (size or '').isdigit() or int(size) <= 0:
                flash(_('A tier needs a name and a size above zero; {name} was left as it was.')
                      .format(name=tier.name), 'warning')
                continue
            tier.name = name
            tier.size = int(size)
        new_name = (request.form.get('new_name') or '').strip()
        new_size = request.form.get('new_size')
        if new_name:
            if not (new_size or '').isdigit() or int(new_size) <= 0:
                flash(_('The new tier needs a size above zero.'), 'warning')
            else:
                db.session.add(SponsorTier(event_id=self.event.id, name=new_name, size=int(new_size),
                                           position=len(tiers)))
        db.session.flush()
        flash(_('Tiers saved.'), 'success')


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
            return jsonify(event_id=self.event.id, template=None, tiers=[], sponsors=[])
        groups = build_groups(self.event, template)
        return jsonify(
            event_id=self.event.id,
            event_title=self.event.title,
            template={'slug': template.slug, 'title': template.title, 'layout': template.layout,
                      'max_logo_pct': template.max_logo_pct,
                      'above_schedule': template.app_above_schedule},
            tiers=[{'id': g['tier'].id, 'name': g['tier'].name, 'size': g['tier'].size,
                    'width_pct': g['width_pct']} for g in groups],
            sponsors=[_serialize_sponsor(s, g) for g in groups for s in g['sponsors']],
        )


def _serialize_sponsor(sponsor, group):
    fields = group['fields']
    return {
        'id': sponsor.id,
        'tier_id': group['tier'].id,
        'name': sponsor.name,
        'tagline': sponsor.tagline,
        'description': sponsor.description,
        'url': sponsor.link_url if fields.linked else None,
        'logo_url': logo_url(sponsor.logo) if sponsor.logo else None,
        'square_logo_url': logo_url(sponsor.square_logo) if sponsor.square_logo else None,
        'show': {field: bool(getattr(fields, field)) for field, _label in TEMPLATE_FIELDS},
    }


def apply_sponsor_form(event, form, sponsor):
    form.populate_obj(sponsor, skip={'logo', 'square_logo', 'delete_logo', 'delete_square_logo', 'tier_id'})
    sponsor.tier_id = form.tier_id.data or None
    apply_logo_fields(event, sponsor, form)


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
                template = SponsorTemplate(event_id=rh.event.id, position=len(tiers))
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
