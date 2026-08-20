# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

import pytest

from indico_eventsponsors.defaults import (DEFAULT_TEMPLATES, MARK_WIDTH_UNITS, normalize_mark_width, parse_tier_lines,
                                           seed_event)
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


def test_seed_event_is_not_repeated_when_only_templates_remain(db, dummy_event):
    # An event can legitimately hold zero tiers -- every one deleted by hand,
    # or an empty default list. Re-toggling the feature must not re-seed
    # against its surviving templates and trip the slug constraint.
    seed_event(dummy_event, [('Gold', 60)], DEFAULT_TEMPLATES)
    db.session.flush()
    for tier in SponsorTier.query.filter_by(event_id=dummy_event.id):
        db.session.delete(tier)
    db.session.flush()
    seed_event(dummy_event, [('Gold', 60)], DEFAULT_TEMPLATES)
    db.session.flush()
    assert not SponsorTier.query.filter_by(event_id=dummy_event.id).has_rows()
    assert SponsorTemplate.query.filter_by(event_id=dummy_event.id).count() == len(DEFAULT_TEMPLATES)


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


@pytest.mark.parametrize('unit', MARK_WIDTH_UNITS)
def test_every_offered_unit_is_kept(unit):
    assert normalize_mark_width(10, unit) == (10, unit)


@pytest.mark.parametrize('unit', ('nope', 'PX', 'px;', '', None, 'expression(alert(1))'))
def test_a_unit_outside_the_allow_list_falls_back_to_the_default(unit):
    # The pair ends up concatenated into a `style` attribute, so the allow-list
    # is the whole of the defence -- and the width goes down with the unit,
    # because 20 was chosen for the unit it was stored beside.
    assert normalize_mark_width(45, unit) == (20, '%')


@pytest.mark.parametrize(('width', 'unit', 'expected'), (
    # Clamped to the bounds of the unit submitted, which differ per unit.
    (500, '%', (100, '%')),
    (0, '%', (1, '%')),
    (5000, 'px', (1000, 'px')),
    (0, 'px', (1, 'px')),
    (200, 'vh', (100, 'vh')),
    (200, 'vw', (100, 'vw')),
    # em and rem are the two whose floor is fractional: a mark can legitimately
    # be a tenth of a line tall, and clamping those to 1 would be clamping them
    # to ten times what was asked for.
    (0.05, 'em', (0.1, 'em')),
    (0.05, 'rem', (0.1, 'rem')),
    (2.5, 'rem', (2.5, 'rem')),
    (99, 'em', (50, 'em')),
    # Two decimals is as fine as a mark width ever needs to be, and rounding is
    # what keeps float arithmetic out of the attribute.
    (12.3456, 'em', (12.35, 'em')),
))
def test_a_width_is_clamped_to_the_limits_of_its_unit(width, unit, expected):
    assert normalize_mark_width(width, unit) == expected


@pytest.mark.parametrize('width', ('20', 20, 20.0, 20.004))
def test_a_whole_width_stays_a_whole_number(width):
    # `%` and `px` are very nearly every mark, and "20.0%" in a style attribute
    # or "20.0" in the app's JSON is a value nobody typed.
    value, _unit = normalize_mark_width(width, '%')
    assert value == 20
    assert isinstance(value, int)


@pytest.mark.parametrize('width', (None, '', 'wide', 'javascript:alert(1)', object(),
                                   float('nan'), float('inf'), float('-inf')))
def test_an_unusable_width_falls_back_rather_than_rendering(width):
    # A NaN needs saying separately: `min`/`max` pass one straight through
    # instead of clamping it, so the bounds alone would not catch it.
    assert normalize_mark_width(width, 'px') == (20, 'px')
