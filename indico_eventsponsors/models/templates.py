# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

from indico.core.db import db
from indico.util.string import format_repr


#: Every field of a sponsor a template can choose to show, and the label the
#: settings page puts next to its checkbox.
TEMPLATE_FIELDS = (
    ('show_logo', 'Logo'),
    ('show_square_logo', 'Square logo'),
    ('show_name', 'Name'),
    ('show_tagline', 'One-line description'),
    ('show_description', 'Full description'),
    ('linked', 'Link to the sponsor'),
)

LAYOUTS = (
    ('grid', 'Grid -- logos side by side, wrapping'),
    ('list', 'List -- one sponsor per row, logo beside the text'),
)


class SponsorTemplate(db.Model):
    """One shortcode, and what it renders.

    `slug` is the shortcode: a template with the slug `sponsors_full` is what
    `{{sponsors_full}}` on a page expands to. Which *fields* appear is decided
    per tier, in `SponsorTemplateTier` -- so one template can give Gold
    sponsors a logo and a name while Silver sponsors get only a name.
    """

    __tablename__ = 'sponsor_templates'
    __table_args__ = (db.UniqueConstraint('event_id', 'slug'),
                      {'schema': 'plugin_eventsponsors'})

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.events.id'), nullable=False, index=True)
    slug = db.Column(db.String, nullable=False)
    title = db.Column(db.String, nullable=False, default='')
    layout = db.Column(db.String, nullable=False, default='grid')

    #: What share of the block's width the *largest* tier's logo takes, as a
    #: percentage. Everything else is scaled down from there in proportion to
    #: its tier size, so the whole block is relative to the space it is given
    #: rather than to any fixed pixel width.
    max_logo_pct = db.Column(db.Integer, nullable=False, default=22)

    #: The one template the phone app renders. At most one per event; setting it
    #: on another clears this one (see `controllers.RHTemplateEdit`).
    for_app = db.Column(db.Boolean, nullable=False, default=False)

    #: Where the app puts it. Above the day's talks is the most valuable space
    #: on the screen and the most intrusive place to spend it, so the default is
    #: below -- a sponsor block at the top has to be chosen, not inherited.
    #: Meaningless unless `for_app` is set.
    app_above_schedule = db.Column(db.Boolean, nullable=False, default=False)

    position = db.Column(db.Integer, nullable=False, default=0)

    event = db.relationship('Event', lazy=True, backref=db.backref('sponsor_templates', lazy='dynamic'))

    @property
    def locator(self):
        return dict(self.event.locator, template_id=self.id)

    @property
    def shortcode(self):
        return '{{' + self.slug + '}}'

    def __repr__(self):
        return format_repr(self, 'id', 'event_id', for_app=False, _text=self.slug)


class SponsorTemplateTier(db.Model):
    """What one template shows for sponsors of one tier.

    A tier with no row here is not rendered by that template at all. That is the
    mechanism behind "Gold gets a logo, Silver gets a name, Bronze is not in
    this block" -- absence is a real answer, not a missing record.
    """

    __tablename__ = 'sponsor_template_tiers'
    __table_args__ = (db.UniqueConstraint('template_id', 'tier_id'),
                      {'schema': 'plugin_eventsponsors'})

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('plugin_eventsponsors.sponsor_templates.id'),
                            nullable=False, index=True)
    tier_id = db.Column(db.Integer, db.ForeignKey('plugin_eventsponsors.sponsor_tiers.id'),
                        nullable=False, index=True)

    show_logo = db.Column(db.Boolean, nullable=False, default=True)
    show_square_logo = db.Column(db.Boolean, nullable=False, default=False)
    show_name = db.Column(db.Boolean, nullable=False, default=True)
    show_tagline = db.Column(db.Boolean, nullable=False, default=False)
    show_description = db.Column(db.Boolean, nullable=False, default=False)
    linked = db.Column(db.Boolean, nullable=False, default=True)

    template = db.relationship('SponsorTemplate', lazy=False,
                               backref=db.backref('tier_settings', lazy=False, cascade='all, delete-orphan'))
    tier = db.relationship('SponsorTier', lazy=False,
                           backref=db.backref('template_settings', lazy=True, cascade='all, delete-orphan'))

    @property
    def shows_anything(self):
        return any(getattr(self, field) for field, _label in TEMPLATE_FIELDS if field != 'linked')

    def __repr__(self):
        return format_repr(self, 'id', 'template_id', 'tier_id')
