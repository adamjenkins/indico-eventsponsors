# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

from io import BytesIO

import pytest

from indico_eventsponsors.clone import SponsorsCloner, SponsorSettingsCloner
from indico_eventsponsors.defaults import DEFAULT_TEMPLATES, DEFAULT_TIERS, seed_event
from indico_eventsponsors.models.sponsors import Sponsor, SponsorLogo
from indico_eventsponsors.models.templates import SponsorTemplate
from indico_eventsponsors.models.tiers import SponsorTier


@pytest.fixture
def source_event(db, dummy_event):
    """An event whose sponsor setup differs from the site defaults."""
    seed_event(dummy_event, [('Gold', 60), ('Silver', 40)], DEFAULT_TEMPLATES)
    gold = SponsorTier.query.filter_by(event_id=dummy_event.id, name='Gold').one()
    # An edit the defaults would not produce, so a test can tell "copied from
    # the old event" apart from "seeded again".
    full = SponsorTemplate.query.filter_by(event_id=dummy_event.id, slug='sponsors_full').one()
    next(ts for ts in full.tier_settings if ts.tier_id == gold.id).show_tagline = True
    logo = SponsorLogo(event_id=dummy_event.id, event=dummy_event, filename='acme.png', content_type='image/png')
    logo.save(BytesIO(b'pretend this is a png'))
    db.session.add(logo)
    db.session.add_all([
        Sponsor(event_id=dummy_event.id, tier_id=gold.id, name='Acme', homepage_url='https://acme.example',
                logo=logo),
        Sponsor(event_id=dummy_event.id, tier_id=None, name='Nowhere'),
    ])
    db.session.flush()
    return dummy_event


def _clone_settings(old_event, new_event):
    """Run the settings cloner the way `run_cloners` would, returning its shared data."""
    return {'sponsor_tiers': SponsorSettingsCloner(old_event).run(new_event, {'sponsor_tiers'}, {})}


def test_the_cloners_are_registered(request_context):
    from indico.modules.events.cloning import get_event_cloners
    cloners = get_event_cloners()
    assert 'sponsor_tiers' in cloners
    assert 'sponsors' in cloners


def test_a_clone_is_seeded_even_without_the_cloners(db, dummy_event):
    from indico_eventsponsors.plugin import EventSponsorsFeature

    # The feature flag travels with a clone, so the seed must too -- an enabled
    # feature with no templates leaves copied shortcodes raw on public pages.
    EventSponsorsFeature.enabled(dummy_event, cloning=True)
    assert SponsorTier.query.filter_by(event_id=dummy_event.id).has_rows()
    assert SponsorTemplate.query.filter_by(event_id=dummy_event.id).has_rows()


def test_the_settings_cloner_replaces_the_seed_with_the_old_configuration(db, source_event, create_event):
    new_event = create_event(id_=2)
    # By the time cloners run the clone already carries the site defaults.
    seed_event(new_event, list(DEFAULT_TIERS), DEFAULT_TEMPLATES)
    _clone_settings(source_event, new_event)

    tiers = SponsorTier.query.filter_by(event_id=new_event.id).order_by(SponsorTier.position).all()
    assert [(t.name, t.size) for t in tiers] == [('Gold', 60), ('Silver', 40)]
    templates = SponsorTemplate.query.filter_by(event_id=new_event.id).order_by(SponsorTemplate.position).all()
    assert [t.slug for t in templates] == [slug for slug, *_rest in DEFAULT_TEMPLATES]
    assert sum(t.for_app for t in templates) == 1
    # The matrix came from the old event -- including the edit the defaults
    # would not have produced -- and every row points at this event's own rows.
    full = next(t for t in templates if t.slug == 'sponsors_full')
    gold = next(t for t in tiers if t.name == 'Gold')
    by_tier = {ts.tier_id: ts for ts in full.tier_settings}
    assert set(by_tier) == {t.id for t in tiers}
    assert by_tier[gold.id].show_tagline


def test_the_sponsors_cloner_copies_sponsors_tiers_and_logos(db, source_event, create_event):
    new_event = create_event(id_=2)
    shared_data = _clone_settings(source_event, new_event)
    SponsorsCloner(source_event).run(new_event, {'sponsor_tiers', 'sponsors'}, shared_data)

    sponsors = {s.name: s for s in Sponsor.query.filter_by(event_id=new_event.id)}
    assert set(sponsors) == {'Acme', 'Nowhere'}
    # Acme's tier is the *new* event's Gold, not a pointer back into the old one.
    assert sponsors['Acme'].tier.event_id == new_event.id
    assert sponsors['Acme'].tier.name == 'Gold'
    assert sponsors['Nowhere'].tier is None
    # The logo is a fresh row and a fresh file with the same bytes.
    old_logo = Sponsor.query.filter_by(event_id=source_event.id, name='Acme').one().logo
    new_logo = sponsors['Acme'].logo
    assert new_logo.id != old_logo.id
    assert new_logo.event_id == new_event.id
    with new_logo.open() as fd:
        assert fd.read() == b'pretend this is a png'


def test_contribution_links_follow_the_contribution_map(db, source_event, create_event, dummy_contribution):
    from indico_eventsponsors.util import sync_contributions
    acme = Sponsor.query.filter_by(event_id=source_event.id, name='Acme').one()
    sync_contributions(acme, [dummy_contribution.id])

    new_event = create_event(id_=2)
    shared_data = _clone_settings(source_event, new_event)
    # Whatever the contributions cloner produced is keyed by the old objects.
    shared_data['contributions'] = {'contrib_map': {dummy_contribution: dummy_contribution}}
    SponsorsCloner(source_event).run(new_event, {'sponsor_tiers', 'sponsors', 'contributions'}, shared_data)
    cloned = Sponsor.query.filter_by(event_id=new_event.id, name='Acme').one()
    assert cloned.linked_contribution_ids == [dummy_contribution.id]


def test_contribution_links_are_dropped_when_contributions_were_not_cloned(db, source_event, create_event,
                                                                           dummy_contribution):
    from indico_eventsponsors.util import sync_contributions
    acme = Sponsor.query.filter_by(event_id=source_event.id, name='Acme').one()
    sync_contributions(acme, [dummy_contribution.id])

    new_event = create_event(id_=2)
    shared_data = _clone_settings(source_event, new_event)
    SponsorsCloner(source_event).run(new_event, {'sponsor_tiers', 'sponsors'}, shared_data)
    cloned = Sponsor.query.filter_by(event_id=new_event.id, name='Acme').one()
    # Dropped, not left pointing at the old event's contribution.
    assert cloned.linked_contribution_ids == []


def test_the_settings_cloner_copies_the_sponsor_marks(db, source_event, create_event):
    from indico_eventsponsors.plugin import EventsponsorsPlugin

    EventsponsorsPlugin.event_settings.set_multi(source_event, {
        'contrib_mark_width': 2.5, 'contrib_mark_unit': 'rem', 'contrib_mark_on_rows': False,
        'contrib_mark_on_app_detail': False, 'contrib_mark_on_web_detail': True,
    })
    new_event = create_event(id_=2)
    seed_event(new_event, list(DEFAULT_TIERS), DEFAULT_TEMPLATES)
    _clone_settings(source_event, new_event)
    settings = EventsponsorsPlugin.event_settings.get_all(new_event)
    # The marks are configuration, and configuration is what this cloner is
    # for: an annual event that settled on a mark size does not want to settle
    # on it again next year.
    assert settings['contrib_mark_width'] == pytest.approx(2.5)
    assert settings['contrib_mark_unit'] == 'rem'
    assert not settings['contrib_mark_on_rows']
    assert not settings['contrib_mark_on_app_detail']
    assert settings['contrib_mark_on_web_detail']


def test_a_setting_the_old_event_never_touched_is_not_frozen_into_the_clone(db, source_event, create_event,
                                                                            monkeypatch):
    from indico_eventsponsors.plugin import EventsponsorsPlugin

    EventsponsorsPlugin.event_settings.set(source_event, 'contrib_mark_unit', 'px')
    new_event = create_event(id_=2)
    _clone_settings(source_event, new_event)
    # Only the one key was ever stored, so the clone keeps reading the current
    # default for the width rather than freezing the old event's copy of it.
    assert set(EventsponsorsPlugin.event_settings.get_all(new_event, no_defaults=True)) == {'contrib_mark_unit'}
    monkeypatch.setitem(EventsponsorsPlugin.default_event_settings, 'contrib_mark_width', 35)
    assert EventsponsorsPlugin.event_settings.get(new_event, 'contrib_mark_width') == 35


def test_the_cloner_is_offered_for_an_event_that_has_only_mark_settings(db, create_event):
    from indico_eventsponsors.plugin import EventsponsorsPlugin

    event = create_event(id_=2)
    # No tiers, no templates: every one deleted by hand, or an empty default
    # list. Offering nothing to copy when there is something to copy is worse
    # than the reverse.
    assert not SponsorSettingsCloner(event).is_available
    EventsponsorsPlugin.event_settings.set(event, 'contrib_mark_width', 40)
    assert SponsorSettingsCloner(event).is_available


def test_importing_into_an_event_replaces_its_own_mark_settings(db, source_event, create_event):
    from indico_eventsponsors.plugin import EventsponsorsPlugin

    # This cloner has no `new_event_only`, so it also runs in the "import from
    # another event" flow, where the target already exists and may be
    # configured. The tiers and templates beside these settings are replaced
    # outright there; a merge left the target holding the source's unit against
    # its own width -- a size neither event had ever chosen.
    EventsponsorsPlugin.event_settings.set(source_event, 'contrib_mark_unit', 'px')
    target = create_event(id_=2)
    seed_event(target, list(DEFAULT_TIERS), DEFAULT_TEMPLATES)
    EventsponsorsPlugin.event_settings.set_multi(target, {
        'contrib_mark_width': 60, 'contrib_mark_on_web_detail': False,
    })
    _clone_settings(source_event, target)
    stored = EventsponsorsPlugin.event_settings.get_all(target, no_defaults=True)
    assert set(stored) == {'contrib_mark_unit'}
    settings = EventsponsorsPlugin.event_settings.get_all(target)
    assert settings['contrib_mark_unit'] == 'px'
    # Back to the defaults rather than the target's own leftovers.
    assert settings['contrib_mark_width'] == EventsponsorsPlugin.default_event_settings['contrib_mark_width']
    assert settings['contrib_mark_on_web_detail']
