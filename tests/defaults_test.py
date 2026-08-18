# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

import pytest

from indico_eventsponsors.defaults import DEFAULT_TEMPLATES, parse_tier_lines, seed_event
from indico_eventsponsors.models.templates import SponsorTemplate, SponsorTemplateTier
from indico_eventsponsors.models.tiers import SponsorTier


def test_parse_tier_lines_reads_name_and_size():
    assert parse_tier_lines('Gold = 60\nSilver=40\n\n# a comment\n') == [('Gold', 60), ('Silver', 40)]


@pytest.mark.parametrize(('text', 'fragment'), (
    ('Gold', 'expected'),
    ('Gold = nine', 'not a size'),
    ('Gold = 0', 'not a size'),
    ('Gold = 60\ngold = 40', 'twice'),
))
def test_parse_tier_lines_rejects_nonsense(text, fragment):
    with pytest.raises(ValueError, match=fragment):
        parse_tier_lines(text)


def test_seed_event_creates_tiers_largest_first(db, dummy_event):
    seed_event(dummy_event, [('Silver', 40), ('Gold', 60)], DEFAULT_TEMPLATES)
    db.session.flush()
    tiers = SponsorTier.query.filter_by(event_id=dummy_event.id).order_by(SponsorTier.position).all()
    assert [(t.name, t.size) for t in tiers] == [('Gold', 60), ('Silver', 40)]


def test_seed_event_marks_exactly_one_app_template(db, dummy_event):
    seed_event(dummy_event, [('Gold', 60)], DEFAULT_TEMPLATES)
    db.session.flush()
    templates = SponsorTemplate.query.filter_by(event_id=dummy_event.id).all()
    assert len(templates) == len(DEFAULT_TEMPLATES)
    assert sum(t.for_app for t in templates) == 1


def test_seed_event_is_not_repeated(db, dummy_event):
    # Switching the feature off and on again must not resurrect deleted tiers
    # or duplicate edited ones.
    seed_event(dummy_event, [('Gold', 60)], DEFAULT_TEMPLATES)
    db.session.flush()
    seed_event(dummy_event, [('Platinum', 90)], DEFAULT_TEMPLATES)
    db.session.flush()
    assert SponsorTier.query.filter_by(event_id=dummy_event.id).count() == 1


def test_seed_event_gives_lower_tiers_fewer_fields(db, dummy_event):
    seed_event(dummy_event, [('Gold', 60), ('Silver', 40), ('Bronze', 20)], DEFAULT_TEMPLATES)
    db.session.flush()
    full = SponsorTemplate.query.filter_by(event_id=dummy_event.id, slug='sponsors_full').one()
    by_tier = {ts.tier.name: ts for ts in full.tier_settings}
    assert by_tier['Gold'].show_description
    assert not by_tier['Silver'].show_description
    assert by_tier['Silver'].show_tagline
    assert not by_tier['Bronze'].show_tagline
    assert SponsorTemplateTier.query.filter_by(template_id=full.id).count() == 3
