# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

import posixpath

from indico.core.config import config
from indico.core.db import db
from indico.core.storage import StoredFileMixin
from indico.util.fs import secure_filename
from indico.util.string import format_repr, strict_str


class SponsorLogo(StoredFileMixin, db.Model):
    """One uploaded image belonging to a sponsor.

    Both images a sponsor can have -- the ordinary logo and the square one --
    are rows here rather than two sets of columns on `Sponsor`, so there is one
    storage path scheme, one delete path and one download endpoint instead of
    two of each.
    """

    __tablename__ = 'sponsor_logos'
    __table_args__ = {'schema': 'plugin_eventsponsors'}

    #: Logos are replaced outright rather than revised, so no version chain.
    version_of = None

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.events.id'), nullable=False, index=True)

    event = db.relationship('Event', lazy=True)

    @property
    def locator(self):
        return dict(self.event.locator, logo_id=self.id, filename=self.filename)

    def _build_storage_path(self):
        self.assign_id()
        filename = '{}-{}'.format(self.id, secure_filename(self.filename, 'logo'))
        path = posixpath.join('event', strict_str(self.event_id), 'sponsors', filename)
        return config.ATTACHMENT_STORAGE, path

    def __repr__(self):
        return format_repr(self, 'id', 'event_id', _text=self.filename)


class Sponsor(db.Model):
    """One sponsor of one event."""

    __tablename__ = 'sponsors'
    __table_args__ = {'schema': 'plugin_eventsponsors'}

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.events.id'), nullable=False, index=True)
    tier_id = db.Column(db.Integer, db.ForeignKey('plugin_eventsponsors.sponsor_tiers.id'), nullable=True,
                        index=True)

    #: Inactive sponsors are kept but never rendered -- a sponsorship that has
    #: lapsed is worth keeping for next year, and deleting it is not the same
    #: thing as taking it off the site.
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    name = db.Column(db.String, nullable=False)
    #: One sentence. Shown where a paragraph would not fit.
    tagline = db.Column(db.String, nullable=False, default='')
    #: The full paragraph.
    description = db.Column(db.Text, nullable=False, default='')

    homepage_url = db.Column(db.String, nullable=False, default='')
    campaign_url = db.Column(db.String, nullable=False, default='')
    #: When set, links point at the campaign URL instead of the homepage. The
    #: homepage is kept either way, so the override can be lifted after the
    #: campaign ends without anyone having to find the address again.
    use_campaign_url = db.Column(db.Boolean, nullable=False, default=False)

    position = db.Column(db.Integer, nullable=False, default=0)

    logo_id = db.Column(db.Integer, db.ForeignKey('plugin_eventsponsors.sponsor_logos.id'), nullable=True)
    square_logo_id = db.Column(db.Integer, db.ForeignKey('plugin_eventsponsors.sponsor_logos.id'), nullable=True)

    event = db.relationship('Event', lazy=True, backref=db.backref('sponsors', lazy='dynamic'))
    tier = db.relationship('SponsorTier', lazy=False, backref=db.backref('sponsors', lazy='dynamic'))
    logo = db.relationship('SponsorLogo', lazy=False, foreign_keys=logo_id)
    square_logo = db.relationship('SponsorLogo', lazy=False, foreign_keys=square_logo_id)

    @property
    def locator(self):
        return dict(self.event.locator, sponsor_id=self.id)

    @property
    def link_url(self):
        """The address a link on this sponsor should point at, or None for no link."""
        if self.use_campaign_url and self.campaign_url:
            return self.campaign_url
        return self.homepage_url or None

    def __repr__(self):
        return format_repr(self, 'id', 'event_id', 'tier_id', is_active=True, _text=self.name)
