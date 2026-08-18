# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

import pytest

from indico_eventsponsors.models.sponsors import Sponsor
from indico_eventsponsors.models.templates import SponsorTemplate, SponsorTemplateTier
from indico_eventsponsors.models.tiers import SponsorTier
from indico_eventsponsors.rendering import build_groups
from indico_eventsponsors.shortcodes import expand


@pytest.fixture
def sponsored_event(db, dummy_event):
    """An event with two tiers, one sponsor each, and a template showing both."""
    gold = SponsorTier(event_id=dummy_event.id, name='Gold', size=60, position=0)
    silver = SponsorTier(event_id=dummy_event.id, name='Silver', size=40, position=1)
    db.session.add_all([gold, silver])
    db.session.flush()
    db.session.add_all([
        Sponsor(event_id=dummy_event.id, tier_id=gold.id, name='Acme', homepage_url='https://acme.example'),
        Sponsor(event_id=dummy_event.id, tier_id=silver.id, name='Globex', homepage_url='https://globex.example'),
    ])
    template = SponsorTemplate(event_id=dummy_event.id, slug='sponsors_full', title='Full', layout='grid',
                               max_logo_pct=30)
    db.session.add(template)
    db.session.flush()
    for tier in (gold, silver):
        db.session.add(SponsorTemplateTier(template_id=template.id, tier_id=tier.id, show_logo=False,
                                           show_square_logo=False, show_name=True, show_tagline=False,
                                           show_description=False, linked=True))
    db.session.flush()
    return dummy_event, template, gold, silver


def test_widths_are_in_proportion_to_tier_size(sponsored_event):
    event, template, _gold, _silver = sponsored_event
    groups = build_groups(event, template)
    # The largest tier takes the template's share; everything else is scaled
    # from it, so 40 against 60 is two thirds of 30%.
    assert [g['width_pct'] for g in groups] == [30, 20]


def test_a_tier_showing_nothing_is_left_out(db, sponsored_event):
    event, template, _gold, silver = sponsored_event
    settings = next(ts for ts in template.tier_settings if ts.tier_id == silver.id)
    settings.show_name = False
    db.session.flush()
    groups = build_groups(event, template)
    assert [g['tier'].name for g in groups] == ['Gold']
    # The remaining tier is now the largest, so it takes the full share.
    assert groups[0]['width_pct'] == 30


def test_inactive_sponsors_are_never_rendered(db, sponsored_event):
    event, template, gold, _silver = sponsored_event
    Sponsor.query.filter_by(event_id=event.id, tier_id=gold.id).one().is_active = False
    db.session.flush()
    assert [g['tier'].name for g in build_groups(event, template)] == ['Silver']


def test_a_sponsor_with_no_tier_is_never_rendered(db, sponsored_event):
    event, _template, _gold, _silver = sponsored_event
    db.session.add(Sponsor(event_id=event.id, tier_id=None, name='Nowhere'))
    db.session.flush()
    html = expand('{{sponsors_full}}', event)
    assert 'Nowhere' not in html
    assert 'Acme' in html


def test_the_campaign_url_overrides_the_homepage(db, sponsored_event):
    event, _template, gold, _silver = sponsored_event
    sponsor = Sponsor.query.filter_by(event_id=event.id, tier_id=gold.id).one()
    sponsor.campaign_url = 'https://acme.example/offer'
    assert sponsor.link_url == 'https://acme.example'
    sponsor.use_campaign_url = True
    assert sponsor.link_url == 'https://acme.example/offer'


def test_expand_replaces_a_known_shortcode(sponsored_event):
    event, _template, _gold, _silver = sponsored_event
    html = expand('<p>before</p>{{sponsors_full}}<p>after</p>', event)
    assert '<p>before</p>' in html
    assert '<p>after</p>' in html
    assert '{{sponsors_full}}' not in html
    assert 'Acme' in html and 'Globex' in html


def test_expand_leaves_an_unknown_shortcode_alone(sponsored_event):
    event, _template, _gold, _silver = sponsored_event
    # A typo has to be visible. Rendering nothing would look like "there are no
    # sponsors", which is a different and wrong statement.
    assert expand('{{sponsors_typo}}', event) == '{{sponsors_typo}}'


def test_expand_ignores_other_doubled_braces(sponsored_event):
    event, _template, _gold, _silver = sponsored_event
    text = '{{ sponsors_full }} {{something_else}} {{ }}'
    assert expand(text, event) == text


def test_the_stylesheet_travels_once(sponsored_event):
    event, _template, _gold, _silver = sponsored_event
    html = expand('{{sponsors_full}} {{sponsors_full}}', event)
    assert html.count('<style>') == 1


def test_a_shortcode_in_the_head_is_removed_not_expanded(sponsored_event):
    event, _template, _gold, _silver = sponsored_event
    # Indico repeats the event description into <meta property="og:description">.
    # A block of logos cannot live in an attribute, and leaving the raw
    # shortcode there publishes it to every social-media preview.
    html = ('<html><head><meta property="og:description" content="Hello {{sponsors_full}}">'
            '</head><body>{{sponsors_full}}</body></html>')
    out = expand(html, event)
    head, body = out.split('</head>')
    assert '{{sponsors_full}}' not in head
    assert 'evsp' not in head
    assert 'content="Hello "' in head
    assert 'Acme' in body


def test_an_unknown_shortcode_in_the_head_is_still_left_alone(sponsored_event):
    event, _template, _gold, _silver = sponsored_event
    html = '<html><head><title>{{sponsors_typo}}</title></head><body></body></html>'
    assert expand(html, event) == html


def test_scripts_and_textareas_are_not_touched(sponsored_event):
    event, _template, _gold, _silver = sponsored_event
    html = ('<body><script>var t = "{{sponsors_full}}";</script>'
            '<textarea>{{sponsors_full}}</textarea>{{sponsors_full}}</body>')
    out = expand(html, event)
    assert out.count('{{sponsors_full}}') == 2
    assert 'Acme' in out


def test_the_app_placement_defaults_to_below_the_schedule(db, dummy_event):
    from indico_eventsponsors.models.templates import SponsorTemplate

    template = SponsorTemplate(event_id=dummy_event.id, slug='sponsors_app', title='App')
    db.session.add(template)
    db.session.flush()
    # The top of a phone screen is the space the attendee came for. Putting a
    # sponsor block there has to be a decision, not something inherited.
    assert template.app_above_schedule is False


def test_a_tier_with_only_presentation_fields_shows_nothing(db, sponsored_event):
    event, template, gold, _silver = sponsored_event
    settings = next(ts for ts in template.tier_settings if ts.tier_id == gold.id)
    settings.show_name = False
    settings.linked = True
    settings.inline = True
    db.session.flush()
    # "Link it" and "display inline" say how to show a sponsor, not whether to.
    # A tier with only those ticked has nothing to draw.
    assert not settings.shows_anything
    assert [g['tier'].name for g in build_groups(event, template)] == ['Silver']


def test_inline_marks_the_tier_in_the_rendered_block(db, sponsored_event):
    event, template, gold, _silver = sponsored_event
    next(ts for ts in template.tier_settings if ts.tier_id == gold.id).inline = True
    db.session.flush()
    html = expand('{{sponsors_full}}', event)
    assert 'evsp-tier evsp-inline" data-tier="Gold"' in html
    assert 'evsp-tier" data-tier="Silver"' in html


def test_the_inlined_stylesheet_carries_no_comments(sponsored_event):
    event, _template, _gold, _silver = sponsored_event
    from indico_eventsponsors.rendering import stylesheet

    css = stylesheet()
    # Everything in this file is downloaded by every visitor of a page carrying
    # a shortcode, including the licence header the linter requires. The rules
    # ship; the prose does not.
    assert '/*' not in css and '*/' not in css
    assert 'This file is part of' not in css
    assert '.evsp-tier' in css and 'flex' in css
    assert '/*' not in expand('{{sponsors_full}}', event)
