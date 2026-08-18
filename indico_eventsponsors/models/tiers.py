# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

from indico.core.db import db
from indico.util.string import format_repr


class SponsorTier(db.Model):
    """A named level of sponsorship, and how large its logos are drawn.

    `size` is a bare number with no unit, and that is deliberate: it only ever
    means something relative to the other tiers of the same event. Gold at 60
    against Silver at 40 means Silver logos are drawn two thirds the width of
    Gold ones, whatever width the page happens to give the block.
    """

    __tablename__ = 'sponsor_tiers'
    __table_args__ = (db.UniqueConstraint('event_id', 'name'),
                      db.CheckConstraint('size > 0', 'positive_size'),
                      {'schema': 'plugin_eventsponsors'})

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.events.id'), nullable=False, index=True)
    name = db.Column(db.String, nullable=False)
    size = db.Column(db.Integer, nullable=False, default=50)
    position = db.Column(db.Integer, nullable=False, default=0)

    event = db.relationship('Event', lazy=True, backref=db.backref('sponsor_tiers', lazy='dynamic'))

    def __repr__(self):
        return format_repr(self, 'id', 'event_id', 'size', _text=self.name)
