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


def test_an_empty_larger_tier_does_not_shrink_the_rest(db, sponsored_event):
    event, template, gold, _silver = sponsored_event
    Sponsor.query.filter_by(event_id=event.id, tier_id=gold.id).delete()
    db.session.flush()
    groups = build_groups(event, template)
    assert [g['tier'].name for g in groups] == ['Silver']
    # The scale is set by the largest tier that renders, not the largest
    # configured: an event that has not sold its headline slot yet -- the usual
    # starting state -- must not draw every other logo smaller than asked for.
    assert groups[0]['width_pct'] == 30


def test_build_groups_accepts_a_preloaded_sponsor_map(sponsored_event):
    from indico_eventsponsors.rendering import load_sponsors_by_tier

    event, template, _gold, _silver = sponsored_event
    groups = build_groups(event, template, load_sponsors_by_tier(event))
    assert [s.name for g in groups for s in g['sponsors']] == ['Acme', 'Globex']


def test_the_sponsor_queries_do_not_grow_with_the_sponsor_count(db, sponsored_event, count_queries):
    event, template, gold, silver = sponsored_event

    def serialise():
        for group in build_groups(event, template):
            for sponsor in group['sponsors']:
                sponsor.linked_contribution_ids  # noqa: B018

    serialise()  # warm the identity map, so both counted runs start equal
    with count_queries() as count:
        serialise()
    baseline = count()
    for i in range(10):
        db.session.add(Sponsor(event_id=event.id, tier_id=(gold if i % 2 else silver).id, name=f'Sponsor {i}'))
    db.session.flush()
    with count_queries() as count:
        serialise()
    # Five times the sponsors, the same round trips: the JSON endpoint serves
    # every attendee's every sync, so per-sponsor queries multiply twice over.
    assert count() == baseline


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


def test_an_unterminated_script_makes_the_remainder_opaque(sponsored_event):
    event, _template, _gold, _silver = sponsored_event
    # A browser reads an unclosed <script> as running to the end of the
    # document, so nothing after it is markup to expand -- and finding that out
    # must not cost a backtracking rescan of the whole page.
    html = '{{sponsors_full}}<p>text</p><script>var t = "{{sponsors_full}}";'
    out = expand(html, event)
    assert 'Acme' in out
    assert out.endswith('<script>var t = "{{sponsors_full}}";')


def test_a_failed_expansion_leaves_the_response_alone(app, db, dummy_event, monkeypatch):
    from flask import Response

    from indico.modules.events.features.util import set_feature_enabled

    from indico_eventsponsors import shortcodes

    set_feature_enabled(dummy_event, 'eventsponsors', True)
    db.session.flush()
    monkeypatch.setattr(shortcodes, 'expand', lambda *args, **kwargs: 1 / 0)
    body = '<p>{{sponsors_full}}</p>'
    with app.test_request_context(f'/event/{dummy_event.id}/sponsors/data'):
        out = shortcodes.expand_response(Response(body, mimetype='text/html'))
    # Flask re-raises an error from an `after_request` hook, turning a finished
    # 200 into an error page; a raw shortcode on the page beats that.
    assert out.status_code == 200
    assert out.get_data(as_text=True) == body


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


def test_the_stylesheet_is_read_once_per_process(sponsored_event):
    from indico_eventsponsors.rendering import stylesheet

    # A packaged asset cannot change under a running server, so re-reading and
    # re-stripping it per response buys nothing.
    assert stylesheet() is stylesheet()


def test_a_tier_added_later_renders_in_existing_templates(db, sponsored_event):
    from indico_eventsponsors.util import seed_tier_into_templates

    event, template, _gold, _silver = sponsored_event
    tier = SponsorTier(event_id=event.id, name='Community', size=20, position=2)
    db.session.add(tier)
    db.session.flush()
    seed_tier_into_templates(event, tier)
    db.session.add(Sponsor(event_id=event.id, tier_id=tier.id, name='Initech'))
    db.session.flush()
    # Without a `SponsorTemplateTier` row the tier would vanish from every
    # template that predates it, while the editor showed it as configured.
    assert 'Community' in [g['tier'].name for g in build_groups(event, template)]
    assert 'Initech' in expand('{{sponsors_full}}', event)


def test_a_late_tiers_stored_default_matches_the_forms(db, sponsored_event):
    from indico_eventsponsors.models.templates import NEW_TIER_FIELDS, TEMPLATE_FIELDS
    from indico_eventsponsors.util import seed_tier_into_templates

    event, template, _gold, _silver = sponsored_event
    tier = SponsorTier(event_id=event.id, name='Community', size=20, position=2)
    db.session.add(tier)
    db.session.flush()
    seed_tier_into_templates(event, tier)
    settings = SponsorTemplateTier.query.filter_by(template_id=template.id, tier_id=tier.id).one()
    # The row must hold exactly what `build_matrix_form` presents for a tier
    # without one, or the template editor would show a default that exists only
    # on screen.
    assert {field for field, _label in TEMPLATE_FIELDS if getattr(settings, field)} == set(NEW_TIER_FIELDS)


def test_contribution_ids_are_read_as_friendly_ids(db, dummy_event, dummy_contribution):
    from indico_eventsponsors.util import parse_contribution_ids

    db.session.flush()
    # The number a manager can see is the friendly one, so that is what the box
    # reads first -- and it is a different number from the global id.
    found, unknown = parse_contribution_ids(dummy_event, str(dummy_contribution.friendly_id))
    assert found == [dummy_contribution.id]
    assert not unknown


def test_a_global_id_is_accepted_too(db, dummy_event, dummy_contribution):
    from indico_eventsponsors.util import parse_contribution_ids

    db.session.flush()
    # Somebody who pasted the number out of a contribution's URL has done
    # nothing unreasonable and should not be told they are wrong.
    found, unknown = parse_contribution_ids(dummy_event, str(dummy_contribution.id))
    assert found == [dummy_contribution.id]
    assert not unknown


def test_unknown_numbers_are_named_not_swallowed(db, dummy_event, dummy_contribution):
    from indico_eventsponsors.util import parse_contribution_ids

    db.session.flush()
    found, unknown = parse_contribution_ids(dummy_event, f'{dummy_contribution.friendly_id}, 999999, banana')
    # The good one is still resolved, and the form is told exactly which two it
    # could not place -- "invalid input" is useless with twenty numbers in a box.
    assert found == [dummy_contribution.id]
    assert unknown == ['999999', 'banana']


def test_separators_and_duplicates_are_forgiven(db, dummy_event, dummy_contribution):
    from indico_eventsponsors.util import parse_contribution_ids

    db.session.flush()
    friendly = dummy_contribution.friendly_id
    found, unknown = parse_contribution_ids(dummy_event, f' #{friendly} ,,{friendly};\n{friendly} ')
    assert found == [dummy_contribution.id]
    assert not unknown


def test_a_sponsor_publishes_its_contributions(db, sponsored_event, dummy_contribution):
    from indico_eventsponsors.models.sponsors import Sponsor
    from indico_eventsponsors.util import sync_contributions

    event, _template, gold, _silver = sponsored_event
    sponsor = Sponsor.query.filter_by(event_id=event.id, tier_id=gold.id).one()
    sync_contributions(sponsor, [dummy_contribution.id])
    assert sponsor.linked_contribution_ids == [dummy_contribution.id]
    # Named `linked_contribution_ids`, not `contribution_ids`: the form has a
    # field by the latter name and WTForms would fill it from the object.
    assert not hasattr(sponsor, 'contribution_ids')
