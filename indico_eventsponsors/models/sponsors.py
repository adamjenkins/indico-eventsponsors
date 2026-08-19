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


class SponsorContribution(db.Model):
    """A sponsor attached to one contribution.

    A real table rather than a list of ids on the sponsor, so a contribution
    that is deleted takes its associations with it instead of leaving a number
    pointing at nothing. Many-to-many in both directions: a talk can have more
    than one sponsor, and a sponsor usually has more than one talk.
    """

    __tablename__ = 'sponsor_contributions'
    __table_args__ = (db.UniqueConstraint('sponsor_id', 'contribution_id'),
                      {'schema': 'plugin_eventsponsors'})

    id = db.Column(db.Integer, primary_key=True)
    sponsor_id = db.Column(db.Integer, db.ForeignKey('plugin_eventsponsors.sponsors.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    contribution_id = db.Column(db.Integer, db.ForeignKey('events.contributions.id', ondelete='CASCADE'),
                                nullable=False, index=True)

    contribution = db.relationship('Contribution', lazy=True)

    def __repr__(self):
        return format_repr(self, 'id', 'sponsor_id', 'contribution_id')


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
    contribution_links = db.relationship('SponsorContribution', lazy=True, cascade='all, delete-orphan',
                                         backref=db.backref('sponsor', lazy=True))

    @property
    def linked_contribution_ids(self):
        """The contributions this sponsor is attached to, as global ids.

        Deliberately not named `contribution_ids`: the sponsor form has a field
        by that name holding the manager's comma-separated text, and WTForms
        fills a field from the object it was given in preference to anything
        passed alongside it. With both called the same thing the box came back
        showing a Python list of global ids instead of the numbers that were
        typed into it.
        """
        return sorted(link.contribution_id for link in self.contribution_links)

    @property
    def locator(self):
        return dict(self.event.locator, sponsor_id=self.id)

    @property
    def link_url(self):
        """The address a link on this sponsor should point at, or None for no link.

        Only http(s) addresses count. The form validates new input, but rows
        written before it did -- or through anything that bypasses it -- go
        straight into an anchor's href on public pages, where any other scheme
        is at best broken and at worst `javascript:`.
        """
        url = self.campaign_url if self.use_campaign_url and self.campaign_url else self.homepage_url
        if url and url.startswith(('http://', 'https://')):
            return url
        return None

    def __repr__(self):
        return format_repr(self, 'id', 'event_id', 'tier_id', is_active=True, _text=self.name)
