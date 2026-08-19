# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

import pytest

from indico_eventsponsors.forms import SponsorForm
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
