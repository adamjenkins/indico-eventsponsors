# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

import pytest

from indico_eventsponsors.defaults import MARK_WIDTH_UNITS
from indico_eventsponsors.forms import ContributionMarkForm, SponsorForm
from indico_eventsponsors.models.sponsors import Sponsor


def _submit(app, event, **data):
    """Validate a sponsor form the way a POST of `data` would."""
    data.setdefault('name', 'Acme')
    data.setdefault('tier_id', '0')
    with app.test_request_context(method='POST', data=data):
        form = SponsorForm(event=event, meta={'csrf': False})
        valid = form.validate()
    return form, valid


def test_link_fields_require_a_real_url(app, db, dummy_event):
    # `URLField` only sets `type="url"` on the input; without a server-side
    # validator a crafted request stores anything, including `javascript:`.
    form, valid = _submit(app, dummy_event, homepage_url='javascript:alert(1)')
    assert not valid
    assert form.homepage_url.errors
    form, valid = _submit(app, dummy_event, campaign_url='javascript:alert(1)')
    assert not valid
    assert form.campaign_url.errors
    _form, valid = _submit(app, dummy_event, homepage_url='https://acme.example')
    assert valid


def test_unmatched_contributions_are_dropped_not_fatal(app, db, dummy_event):
    # The form is multipart and a failed submit costs any selected logo files,
    # so a typo in the contributions box must not reject the save.
    form, valid = _submit(app, dummy_event, contribution_ids='999')
    assert valid
    assert form.resolved_contribution_ids == []
    assert form.dropped_contribution_tokens == ['999']


@pytest.mark.parametrize(('homepage', 'expected'), (
    ('https://acme.example', 'https://acme.example'),
    ('http://acme.example', 'http://acme.example'),
    ('javascript:alert(1)', None),
    ('ftp://files.example', None),
    ('', None),
))
def test_link_url_only_returns_http_addresses(homepage, expected):
    sponsor = Sponsor(name='Acme', homepage_url=homepage, campaign_url='', use_campaign_url=False)
    assert sponsor.link_url == expected


def test_link_url_does_not_fall_back_around_a_bad_campaign_url():
    # A pre-validator row with a scriptable campaign address renders no link at
    # all rather than quietly linking the homepage the manager overrode.
    sponsor = Sponsor(name='Acme', homepage_url='https://acme.example',
                      campaign_url='javascript:alert(1)', use_campaign_url=True)
    assert sponsor.link_url is None


def _submit_marks(app, **data):
    """Validate the marks form the way a POST of `data` would."""
    data.setdefault('contrib_mark_width', '20')
    data.setdefault('contrib_mark_unit', '%')
    with app.test_request_context(method='POST', data=data):
        form = ContributionMarkForm(meta={'csrf': False})
        valid = form.validate()
    return form, valid


def test_the_unit_select_offers_exactly_the_allowed_units():
    # The select is built from the same constant the normaliser clamps against,
    # so the two cannot drift into offering a unit that would be rejected.
    assert [value for value, _label in ContributionMarkForm.contrib_mark_unit.kwargs['choices']] == \
        list(MARK_WIDTH_UNITS)


@pytest.mark.parametrize('unit', ('nope', 'PX', 'px; background: url(x)', ''))
def test_a_unit_outside_the_allow_list_is_refused(app, unit):
    form, valid = _submit_marks(app, contrib_mark_unit=unit)
    assert not valid
    assert form.contrib_mark_unit.errors
    # One complaint, not two: the width is judged against the limits of a unit,
    # and there are none for a unit that does not exist.
    assert not form.contrib_mark_width.errors


@pytest.mark.parametrize(('width', 'unit'), (
    ('200', '%'), ('0', '%'), ('-5', '%'),
    ('2000', 'px'), ('0.5', 'px'),
    ('0.05', 'em'), ('99', 'em'),
    ('0.05', 'rem'), ('99', 'rem'),
    ('101', 'vh'), ('101', 'vw'),
))
def test_a_width_outside_its_units_limits_is_refused_not_clamped(app, width, unit):
    # The stored value is clamped, but a manager who typed 200% is told so
    # rather than finding 100 in the box afterwards and wondering who changed
    # it.
    form, valid = _submit_marks(app, contrib_mark_width=width, contrib_mark_unit=unit)
    assert not valid
    assert form.contrib_mark_width.errors
    assert form.contrib_mark_width.data == pytest.approx(float(width))


@pytest.mark.parametrize(('width', 'unit'), (
    ('1', '%'), ('100', '%'), ('20', '%'), ('1000', 'px'),
    ('0.1', 'em'), ('2.5', 'rem'), ('50', 'rem'), ('100', 'vh'), ('100', 'vw'),
))
def test_a_width_inside_its_units_limits_is_accepted(app, width, unit):
    _form, valid = _submit_marks(app, contrib_mark_width=width, contrib_mark_unit=unit)
    assert valid


def test_a_missing_width_is_a_complaint_rather_than_a_silent_default(app):
    # `InputRequired` rather than a fallback: a submit with the box emptied is
    # a manager who meant to type something, not one who meant the default.
    with app.test_request_context(method='POST', data={'contrib_mark_unit': '%'}):
        form = ContributionMarkForm(meta={'csrf': False})
        assert not form.validate()
    assert form.contrib_mark_width.errors == ['This field is required.']


def test_a_width_that_is_not_a_number_is_reported_once(app):
    form, valid = _submit_marks(app, contrib_mark_width='wide')
    assert not valid
    # The field has already said it is not a number; a second error about a
    # range it was never in would only bury the first.
    assert len(form.contrib_mark_width.errors) == 1
