# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

import re
from io import BytesIO
from uuid import uuid4

import pytest

from indico.core import signals
from indico.modules.events.features.util import set_feature_enabled

from indico_eventsponsors.controllers import RHManageSettings
from indico_eventsponsors.defaults import DEFAULT_TEMPLATES, seed_event
from indico_eventsponsors.models.sponsors import Sponsor, SponsorLogo
from indico_eventsponsors.models.templates import SponsorTemplate, SponsorTemplateTier
from indico_eventsponsors.models.tiers import SponsorTier
from indico_eventsponsors.util import (delete_logo, delete_queued_files, event_sponsors, event_templates, event_tiers,
                                       next_position)


@pytest.fixture
def tiers(db, dummy_event):
    seed_event(dummy_event, [('Gold', 60), ('Silver', 40)], DEFAULT_TEMPLATES)
    db.session.flush()
    return event_tiers(dummy_event)


def _save_tiers(app, db, event, data):
    """Run the tier-save handler the way a POST of `data` would reach it."""
    with app.test_request_context(method='POST', data=data):
        rh = RHManageSettings()
        rh.event = event
        rh._save_tiers(event_tiers(event))
    db.session.flush()


def _form_data(tiers):
    """The form fields a submit of the page as it stands would carry."""
    data = {}
    for tier in tiers:
        data[f'name_{tier.id}'] = tier.name
        data[f'size_{tier.id}'] = str(tier.size)
    return data


def test_renaming_onto_a_kept_name_leaves_the_row_alone(app, db, dummy_event, tiers):
    # The name check must be case-insensitive even though the database
    # constraint is not: two tiers differing only in case is a trap, not a
    # feature.
    gold, silver = tiers
    data = _form_data(tiers)
    data[f'name_{silver.id}'] = 'gold'
    data[f'size_{silver.id}'] = '55'
    _save_tiers(app, db, dummy_event, data)
    assert (silver.name, silver.size) == ('Silver', 40)
    assert (gold.name, gold.size) == ('Gold', 60)


def test_a_collision_does_not_lose_the_rest_of_the_save(app, db, dummy_event, tiers):
    gold, silver = tiers
    data = _form_data(tiers)
    data[f'name_{silver.id}'] = 'Gold'
    data[f'size_{gold.id}'] = '80'
    _save_tiers(app, db, dummy_event, data)
    assert silver.name == 'Silver'
    assert gold.size == 80


def test_swapping_two_names_is_a_valid_end_state(app, db, dummy_event, tiers):
    gold, silver = tiers
    data = _form_data(tiers)
    data[f'name_{gold.id}'] = 'Silver'
    data[f'name_{silver.id}'] = 'Gold'
    _save_tiers(app, db, dummy_event, data)
    assert (gold.name, silver.name) == ('Silver', 'Gold')


def test_a_chain_of_renames_where_the_claimer_updates_first(app, db, dummy_event, tiers):
    # Gold has the lower id, and the final flush batches its UPDATEs in
    # primary-key order: without a detour, Gold would claim 'Silver' before
    # Silver's own rename vacates it.
    gold, silver = tiers
    data = _form_data(tiers)
    data[f'name_{gold.id}'] = 'Silver'
    data[f'name_{silver.id}'] = 'Bronze'
    _save_tiers(app, db, dummy_event, data)
    assert (gold.name, silver.name) == ('Silver', 'Bronze')


def test_a_chain_of_renames_where_the_vacater_updates_first(app, db, dummy_event, tiers):
    gold, silver = tiers
    data = _form_data(tiers)
    data[f'name_{gold.id}'] = 'Platinum'
    data[f'name_{silver.id}'] = 'Gold'
    _save_tiers(app, db, dummy_event, data)
    assert (gold.name, silver.name) == ('Platinum', 'Gold')


def test_deleting_and_readding_a_name_in_one_submit(app, db, dummy_event, tiers):
    gold, _silver = tiers
    data = _form_data(tiers)
    data[f'delete_{gold.id}'] = 'on'
    data['new_name'] = 'Gold'
    data['new_size'] = '90'
    _save_tiers(app, db, dummy_event, data)
    remaining = event_tiers(dummy_event)
    assert [(t.name, t.size) for t in remaining] == [('Silver', 40), ('Gold', 90)]
    new_gold = remaining[-1]
    assert new_gold.id != gold.id
    # The re-created tier must render somewhere: a row in every template, like
    # any other tier created after seeding.
    assert (SponsorTemplateTier.query.filter_by(tier_id=new_gold.id).count()
            == len(DEFAULT_TEMPLATES))


def test_renaming_onto_a_name_deleted_in_the_same_submit(app, db, dummy_event, tiers):
    gold, silver = tiers
    data = _form_data(tiers)
    data[f'delete_{gold.id}'] = 'on'
    data[f'name_{silver.id}'] = 'Gold'
    _save_tiers(app, db, dummy_event, data)
    assert [t.name for t in event_tiers(dummy_event)] == ['Gold']


def test_a_new_tier_with_a_taken_name_is_not_added(app, db, dummy_event, tiers):
    data = _form_data(tiers)
    data['new_name'] = 'GOLD'
    data['new_size'] = '90'
    _save_tiers(app, db, dummy_event, data)
    assert SponsorTier.query.filter_by(event_id=dummy_event.id).count() == 2


def test_new_positions_follow_their_own_table(db, dummy_event, tiers):
    # The fixture seeds two tiers and three templates. A new row of either kind
    # continues its *own* table's order -- counting the other one (the old
    # `len(tiers)` shape) sat a new template inside the seeded order.
    assert next_position(SponsorTier, dummy_event) == 2
    assert next_position(SponsorTemplate, dummy_event) == 3


def test_a_new_tier_sorts_after_the_survivors_of_deletions(app, db, dummy_event, tiers):
    gold, _silver = tiers
    data = _form_data(tiers)
    data[f'delete_{gold.id}'] = 'on'
    _save_tiers(app, db, dummy_event, data)
    remaining = event_tiers(dummy_event)
    data = _form_data(remaining)
    data['new_name'] = 'Bronze'
    data['new_size'] = '20'
    _save_tiers(app, db, dummy_event, data)
    tiers_now = event_tiers(dummy_event)
    assert [t.name for t in tiers_now] == ['Silver', 'Bronze']
    # Strictly after, not a tie broken by id: positions survive deletions, so a
    # row count could land on a position a surviving tier still holds.
    assert tiers_now[-1].position > tiers_now[0].position


def _stored_logo(db, event):
    logo = SponsorLogo(event_id=event.id, event=event, filename='acme.png', content_type='image/png')
    logo.save(BytesIO(b'pretend this is a png'))
    db.session.add(logo)
    db.session.flush()
    return logo


def test_a_deleted_logos_file_stays_until_the_commit(db, dummy_event):
    logo = _stored_logo(db, dummy_event)
    storage, file_id = logo.storage, logo.storage_file_id
    delete_logo(logo)
    # The row is gone, the bytes are not: anything failing later in the request
    # rolls the row back, and a restored row must still have its file.
    assert SponsorLogo.query.filter_by(event_id=dummy_event.id).count() == 0
    with storage.open(file_id) as fd:
        assert fd.read() == b'pretend this is a png'
    delete_queued_files()
    # KeyError because the test storage backend is a plain dict.
    with pytest.raises(KeyError):
        storage.open(file_id)


def test_the_after_commit_signal_sweeps_the_file_queue(db, dummy_event):
    logo = _stored_logo(db, dummy_event)
    storage, file_id = logo.storage, logo.storage_file_id
    delete_logo(logo)
    # The plugin's receiver stays connected across requests; the queue in `g`
    # is what scopes the sweep to this one.
    signals.core.after_commit.send()
    with pytest.raises(KeyError):
        storage.open(file_id)


def test_the_data_endpoint_is_briefly_cacheable(db, test_client, dummy_event):
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    db.session.flush()
    response = test_client.get(f'/event/{dummy_event.id}/sponsors/data')
    assert response.status_code == 200
    # Public, and hit by every attendee's device on every sync -- the one
    # endpoint whose load multiplies with attendance.
    assert response.cache_control.max_age == 60


def _login(test_client, user):
    """Log `user` in and arm the session with a known CSRF token."""
    token = str(uuid4())
    with test_client.session_transaction() as sess:
        sess.set_session_user(user)
        sess['_csrf_token'] = token
    return token


def test_the_template_preview_shows_the_saved_block(db, test_client, dummy_user, dummy_event):
    dummy_user.is_admin = True
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    tier = event_tiers(dummy_event)[0]
    db.session.add(Sponsor(event_id=dummy_event.id, tier_id=tier.id, name='Acme'))
    db.session.flush()
    template = event_templates(dummy_event)[0]
    _login(test_client, dummy_user)
    response = test_client.get(f'/event/{dummy_event.id}/manage/sponsors/templates/{template.id}/preview')
    assert response.status_code == 200
    # The block itself, stylesheet included -- what a visitor would see, not a
    # description of it.
    assert b'Acme' in response.data
    assert b'<style>' in response.data


def test_a_template_showing_nothing_previews_as_an_explanation(db, test_client, dummy_user, dummy_event):
    dummy_user.is_admin = True
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    template = event_templates(dummy_event)[0]
    _login(test_client, dummy_user)
    # No sponsors yet: on a public page that is deliberate silence, in a
    # preview it would read as breakage.
    response = test_client.get(f'/event/{dummy_event.id}/manage/sponsors/templates/{template.id}/preview')
    assert response.status_code == 200
    assert b'renders nothing' in response.data


@pytest.fixture
def ordered_sponsors(db, dummy_event, tiers):
    gold = tiers[0]
    sponsors = [Sponsor(event_id=dummy_event.id, tier_id=gold.id, name=name, position=position)
                for position, name in enumerate(('Alpha', 'Beta', 'Wanted'))]
    db.session.add_all(sponsors)
    db.session.flush()
    return sponsors


def test_moving_a_sponsor_to_the_top_is_one_submit(db, test_client, dummy_user, dummy_event, ordered_sponsors):
    dummy_user.is_admin = True
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    wanted = ordered_sponsors[-1]
    token = _login(test_client, dummy_user)
    response = test_client.post(f'/event/{dummy_event.id}/manage/sponsors/{wanted.id}/move/top',
                                data={'csrf_token': token})
    assert response.status_code == 302
    # The anchor puts the manager back at the row that moved, not at the top of
    # the list hunting for it.
    assert response.location.endswith(f'#sponsor-{wanted.id}')
    assert [s.name for s in event_sponsors(dummy_event)] == ['Wanted', 'Alpha', 'Beta']


def test_moving_a_sponsor_to_the_bottom(db, test_client, dummy_user, dummy_event, ordered_sponsors):
    dummy_user.is_admin = True
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    first = ordered_sponsors[0]
    token = _login(test_client, dummy_user)
    response = test_client.post(f'/event/{dummy_event.id}/manage/sponsors/{first.id}/move/bottom',
                                data={'csrf_token': token})
    assert response.status_code == 302
    assert [s.name for s in event_sponsors(dummy_event)] == ['Beta', 'Wanted', 'Alpha']


def test_save_and_add_another_carries_the_shared_fields(db, test_client, dummy_user, dummy_event, tiers):
    dummy_user.is_admin = True
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    gold = tiers[0]
    token = _login(test_client, dummy_user)
    response = test_client.post(f'/event/{dummy_event.id}/manage/sponsors/new',
                                data={'csrf_token': token, 'name': 'Acme', 'tier_id': str(gold.id),
                                      'is_active': 'y', 'save_add_another': '1'})
    assert response.status_code == 302
    assert f'tier_id={gold.id}' in response.location
    assert 'is_active=1' in response.location
    assert Sponsor.query.filter_by(event_id=dummy_event.id, name='Acme').count() == 1
    # The next blank form starts on the same tier instead of falling back to
    # "No tier" -- sponsors normally arrive in batches grouped by tier.
    follow = test_client.get(response.location)
    assert follow.status_code == 200
    assert re.search(rf'<option selected(?:="[^"]*")? value="{gold.id}">', follow.get_data(as_text=True))


def test_the_management_pages_render_with_contribution_links(db, test_client, dummy_user, dummy_event,
                                                             dummy_contribution, ordered_sponsors):
    from indico_eventsponsors.models.sponsors import SponsorContribution

    dummy_user.is_admin = True
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    sponsor = ordered_sponsors[0]
    sponsor.contribution_links.append(SponsorContribution(contribution_id=dummy_contribution.id))
    db.session.flush()
    _login(test_client, dummy_user)
    template = event_templates(dummy_event)[0]
    # A render of each management page: the sponsor list's contribution count,
    # the edit page's "Attached to" callout, and both preview iframes.
    for url in (f'/event/{dummy_event.id}/manage/sponsors/',
                f'/event/{dummy_event.id}/manage/sponsors/new',
                f'/event/{dummy_event.id}/manage/sponsors/{sponsor.id}',
                f'/event/{dummy_event.id}/manage/sponsors/settings',
                f'/event/{dummy_event.id}/manage/sponsors/templates/{template.id}'):
        response = test_client.get(url)
        assert response.status_code == 200, url
    edit_page = test_client.get(f'/event/{dummy_event.id}/manage/sponsors/{sponsor.id}').get_data(as_text=True)
    assert f'#{dummy_contribution.friendly_id} {dummy_contribution.title}' in edit_page


def test_logo_responses_are_cacheable_for_a_day(db, test_client, dummy_event, monkeypatch):
    from indico.web.flask.util import send_file

    set_feature_enabled(dummy_event, 'eventsponsors', True)
    logo = _stored_logo(db, dummy_event)
    # The in-memory test backend cannot send files; core's `send_file` is what
    # every real backend goes through, `no-cache` default included.
    monkeypatch.setattr(SponsorLogo, 'send',
                        lambda self, inline=True: send_file(self.filename, BytesIO(b'png'), self.content_type))
    response = test_client.get(f'/event/{dummy_event.id}/sponsors/logo/{logo.id}/{logo.filename}')
    assert response.status_code == 200
    # A logo URL's content can never change -- a replacement is a new row with
    # a new id -- so `send_file`'s default `no-cache` buys nothing.
    assert response.cache_control.private
    assert not response.cache_control.no_cache
    assert response.cache_control.max_age == 86400


def test_the_data_endpoint_carries_the_contribution_marks(db, test_client, dummy_event):
    from indico_eventsponsors.plugin import EventsponsorsPlugin

    set_feature_enabled(dummy_event, 'eventsponsors', True)
    EventsponsorsPlugin.event_settings.set_multi(dummy_event, {
        'contrib_mark_width': 2.5, 'contrib_mark_unit': 'rem', 'contrib_mark_on_rows': False,
        'contrib_mark_on_app_detail': True, 'contrib_mark_on_web_detail': False,
    })
    db.session.flush()
    marks = test_client.get(f'/event/{dummy_event.id}/sponsors/data').json['contribution_marks']
    # `on_web_detail` is deliberately absent: it governs a page the app neither
    # draws nor can do anything about, and a switch a client cannot honour is
    # one it will eventually honour wrongly.
    assert marks == {'width': 2.5, 'unit': 'rem', 'on_rows': False, 'on_detail': True}


def test_the_marks_are_sent_even_when_the_event_has_no_template(db, test_client, dummy_event):
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    for template in SponsorTemplate.query.filter_by(event_id=dummy_event.id):
        db.session.delete(template)
    db.session.flush()
    payload = test_client.get(f'/event/{dummy_event.id}/sponsors/data').json
    # The degenerate branch answers a different shape of payload, and an app
    # reading the marks out of it must not have to special-case their absence.
    assert payload['template'] is None
    assert payload['contribution_marks'] == {'width': 20, 'unit': '%', 'on_rows': True, 'on_detail': True}


def test_stored_nonsense_never_reaches_the_payload(db, test_client, dummy_event):
    from indico_eventsponsors.plugin import EventsponsorsPlugin

    set_feature_enabled(dummy_event, 'eventsponsors', True)
    # A backup restored from an older version, or a setting written by hand:
    # the reader settles the pair rather than trusting what is in the table.
    EventsponsorsPlugin.event_settings.set_multi(dummy_event, {'contrib_mark_width': 500,
                                                               'contrib_mark_unit': 'px'})
    db.session.flush()
    marks = test_client.get(f'/event/{dummy_event.id}/sponsors/data').json['contribution_marks']
    assert (marks['width'], marks['unit']) == (500, 'px')
    EventsponsorsPlugin.event_settings.set(dummy_event, 'contrib_mark_unit', 'nonsense')
    db.session.flush()
    marks = test_client.get(f'/event/{dummy_event.id}/sponsors/data').json['contribution_marks']
    assert (marks['width'], marks['unit']) == (20, '%')


def test_saving_the_marks_returns_to_the_section_that_was_edited(db, test_client, dummy_user, dummy_event):
    from indico_eventsponsors.plugin import EventsponsorsPlugin

    dummy_user.is_admin = True
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    db.session.flush()
    token = _login(test_client, dummy_user)
    response = test_client.post(f'/event/{dummy_event.id}/manage/sponsors/marks',
                                data={'csrf_token': token, 'contrib_mark_width': '30',
                                      'contrib_mark_unit': 'vw', 'contrib_mark_on_rows': 'y',
                                      'contrib_mark_on_web_detail': 'y'})
    assert response.status_code == 302
    # The section sits at the foot of a long page; the anchor lands the manager
    # back on it rather than at the top of the tier table.
    assert response.location.endswith('#sponsor-marks')
    settings = EventsponsorsPlugin.event_settings.get_all(dummy_event)
    assert (settings['contrib_mark_width'], settings['contrib_mark_unit']) == (30, 'vw')
    assert settings['contrib_mark_on_rows']
    assert settings['contrib_mark_on_web_detail']
    # A switch left off arrives as an absent field, not as a false one.
    assert not settings['contrib_mark_on_app_detail']


def test_an_invalid_marks_submit_keeps_the_manager_on_the_page(db, test_client, dummy_user, dummy_event):
    from indico_eventsponsors.plugin import EventsponsorsPlugin

    dummy_user.is_admin = True
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    db.session.flush()
    token = _login(test_client, dummy_user)
    response = test_client.post(f'/event/{dummy_event.id}/manage/sponsors/marks',
                                data={'csrf_token': token, 'contrib_mark_width': '500',
                                      'contrib_mark_unit': '%'})
    # The page comes back with the error beside the value typed, rather than a
    # redirect to a form that has quietly forgotten both.
    assert response.status_code == 200
    assert b'has to be between 1 and 100' in response.data
    assert EventsponsorsPlugin.event_settings.get(dummy_event, 'contrib_mark_width') == 20


def test_the_settings_page_shows_the_stored_marks(db, test_client, dummy_user, dummy_event):
    from indico_eventsponsors.plugin import EventsponsorsPlugin

    dummy_user.is_admin = True
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    EventsponsorsPlugin.event_settings.set_multi(dummy_event, {'contrib_mark_width': 12.5,
                                                               'contrib_mark_unit': 'rem'})
    db.session.flush()
    _login(test_client, dummy_user)
    page = test_client.get(f'/event/{dummy_event.id}/manage/sponsors/settings').get_data(as_text=True)
    assert 'value="12.5"' in page
    assert re.search(r'<option selected(?:="[^"]*")? value="rem">', page)


def test_the_tiers_form_names_its_own_endpoint(db, test_client, dummy_user, dummy_event):
    """The tiers form must not post to whatever URL the page happens to be at.

    An invalid marks submit re-renders this page *under the marks endpoint*, so
    a tiers form with no `action` would then send its rows to the marks handler:
    the rename is dropped, the manager is shown a mark-width error they did not
    cause, and nothing says the edit was lost.
    """
    dummy_user.is_admin = True
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    db.session.flush()
    token = _login(test_client, dummy_user)
    settings_url = f'/event/{dummy_event.id}/manage/sponsors/settings'

    for response in (test_client.get(settings_url),
                     test_client.post(f'/event/{dummy_event.id}/manage/sponsors/marks',
                                      data={'csrf_token': token, 'contrib_mark_width': '500',
                                            'contrib_mark_unit': '%'})):
        assert response.status_code == 200
        html = response.data.decode()
        start = html.index('id="tier-form"')
        opening = html[html.rindex('<form', 0, start):html.index('>', start) + 1]
        assert f'action="{settings_url}"' in opening
