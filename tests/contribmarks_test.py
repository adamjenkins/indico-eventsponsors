# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

from io import BytesIO

import pytest
from flask import Response

from indico.modules.events.features.util import set_feature_enabled

from indico_eventsponsors.contribmarks import find_description_end, find_sponsor, insert_mark, mark_response
from indico_eventsponsors.models.sponsors import Sponsor, SponsorContribution, SponsorLogo
from indico_eventsponsors.util import event_tiers


#: A contribution page reduced to the part this module reads: the anchor core
#: renders, an abstract with a nested `<div>` of the kind author-written HTML is
#: full of, and something after it to prove the mark lands between the two.
PAGE = ('<html><body><h1>A talk</h1>'
        '<div class="description js-mathjax"><p>An abstract</p><div class="box">aside</div></div>'
        '<div class="contribution-details">the rest of the page</div>'
        '</body></html>')


def _marked(html, mark='<MARK>'):
    """`insert_mark` with a placeholder, so a test reads as a placement rule."""
    return insert_mark(html, mark)


def test_the_mark_goes_after_the_whole_description():
    out = _marked(PAGE)
    # After the description's *own* closing tag -- not after the nested one,
    # which is the mistake a non-counting search would make.
    assert '<div class="box">aside</div></div><MARK><div class="contribution-details">' in out
    assert out.replace('<MARK>', '') == PAGE


def test_a_spaced_closing_tag_is_still_the_end_of_the_block():
    # `</div >` is valid markup and appears in pasted abstracts; skipping to the
    # `>` rather than counting six characters is what keeps the mark from
    # landing inside the tag it follows.
    html = '<div class="description js-mathjax">text</div ><p>after</p>'
    assert _marked(html) == '<div class="description js-mathjax">text</div ><MARK><p>after</p>'


def test_a_commented_out_closing_tag_does_not_end_the_block():
    # An abstract with a commented-out `</div>` in it is the case that puts a
    # logo in the middle of somebody's text rather than under it.
    html = ('<div class="description js-mathjax">before<!-- </div> -->after</div>'
            '<p>the rest</p>')
    assert _marked(html).endswith('after</div><MARK><p>the rest</p>')


def test_nothing_is_inserted_when_the_page_has_no_description():
    # "Underneath the abstract" has no meaning on a page with no abstract, so
    # the mark is not placed at some other plausible spot instead.
    assert _marked('<html><body><h1>A talk</h1><p>No abstract here.</p></body></html>') is None


@pytest.mark.parametrize(('html', 'why'), (
    ('<div class="description js-mathjax"><div>never closed</div>', 'the block never closes'),
    ('<div class="description js-mathjax">a<!-- unterminated', 'the comment runs to the end'),
    ('<div class="description js-mathjax">one</div><div class="description js-mathjax">two</div>',
     'two anchors, no way to tell which'),
))
def test_nothing_is_inserted_when_the_scan_does_not_resolve(html, why):
    # A mark in the wrong place is worse than no mark: an absent one gets
    # asked about, a misplaced one just reads as a broken page.
    assert find_description_end(html) is None, why
    assert _marked(html) is None, why


def test_a_runaway_page_is_given_up_on_rather_than_scanned_forever():
    # This runs on public, unauthenticated page loads, so the amount of work
    # one of them can ask for has to have a ceiling -- and reaching the ceiling
    # is a scan that did not resolve, not a guess.
    html = '<div class="description js-mathjax">' + '<div>' * 20000
    assert find_description_end(html) is None


@pytest.fixture
def sponsored_contribution(db, dummy_event, dummy_contribution):
    """An event whose dummy contribution is linked to a sponsor with a logo."""
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    logo = SponsorLogo(event_id=dummy_event.id, event=dummy_event, filename='acme.png', content_type='image/png')
    logo.save(BytesIO(b'pretend this is a png'))
    db.session.add(logo)
    sponsor = Sponsor(event_id=dummy_event.id, tier_id=event_tiers(dummy_event)[0].id, name='Acme', logo=logo)
    sponsor.contribution_links.append(SponsorContribution(contribution_id=dummy_contribution.id))
    db.session.add(sponsor)
    db.session.flush()
    return dummy_event, dummy_contribution, sponsor


def _display(app, event, contribution, html=PAGE):
    """Run the hook on `html` the way a request for the talk's page would."""
    with app.test_request_context(f'/event/{event.id}/contributions/{contribution.id}/'):
        return mark_response(Response(html, mimetype='text/html')).get_data(as_text=True)


def test_the_hook_marks_a_sponsored_contribution(app, db, sponsored_contribution):
    event, contribution, _sponsor = sponsored_contribution
    out = _display(app, event, contribution)
    mark = out[out.index('<div class="evsp-contrib-mark"'):]
    # The default width, and the sponsor's name on the image for anybody
    # reading the page with a screen reader.
    assert 'width: 20%;' in mark
    assert 'alt="Sponsored by Acme"' in mark
    # Under the abstract, not inside it, and nothing else about the page moved.
    assert out.index('<div class="evsp-contrib-mark"') > out.index('<div class="box">aside</div>')
    assert out.index('<div class="evsp-contrib-mark"') < out.index('contribution-details')


def test_the_configured_width_and_unit_reach_the_style(app, db, sponsored_contribution):
    from indico_eventsponsors.plugin import EventsponsorsPlugin

    event, contribution, _sponsor = sponsored_contribution
    EventsponsorsPlugin.event_settings.set_multi(event, {'contrib_mark_width': 12.5, 'contrib_mark_unit': 'rem'})
    assert 'width: 12.5rem;' in _display(app, event, contribution)


def test_the_website_switch_turns_the_mark_off_by_itself(app, db, sponsored_contribution):
    from indico_eventsponsors.plugin import EventsponsorsPlugin

    event, contribution, _sponsor = sponsored_contribution
    # The app's own two switches stay on: the three surfaces are independent,
    # and this is the one the website reads.
    EventsponsorsPlugin.event_settings.set(event, 'contrib_mark_on_web_detail', False)
    assert _display(app, event, contribution) == PAGE


def test_an_unmarked_contribution_is_left_alone(app, db, dummy_event, dummy_contribution):
    set_feature_enabled(dummy_event, 'eventsponsors', True)
    db.session.flush()
    assert _display(app, dummy_event, dummy_contribution) == PAGE


def test_a_page_with_no_description_is_left_alone(app, db, sponsored_contribution):
    event, contribution, _sponsor = sponsored_contribution
    bare = '<html><body><h1>A talk</h1></body></html>'
    assert _display(app, event, contribution, bare) == bare


def test_a_failure_leaves_the_finished_page_alone(app, db, sponsored_contribution, monkeypatch):
    from indico_eventsponsors import contribmarks

    event, contribution, _sponsor = sponsored_contribution
    monkeypatch.setattr(contribmarks, 'find_sponsor', lambda *args: 1 / 0)
    # Flask re-raises out of an `after_request` hook, which would throw away a
    # page that was already built. A logo is not worth a contribution page.
    with app.test_request_context(f'/event/{event.id}/contributions/{contribution.id}/'):
        response = contribmarks.mark_response(Response(PAGE, mimetype='text/html'))
    assert response.status_code == 200
    assert response.get_data(as_text=True) == PAGE


def test_an_untiered_or_inactive_sponsor_never_marks_a_talk(db, sponsored_contribution):
    event, contribution, sponsor = sponsored_contribution
    assert find_sponsor(event, contribution.id)[0] is sponsor
    # The same rule as `build_groups`: a sponsor with no tier has no size and
    # is never rendered anywhere, and a lapsed one is kept, not shown.
    sponsor.tier_id = None
    db.session.flush()
    assert find_sponsor(event, contribution.id) is None
    sponsor.tier_id = event_tiers(event)[0].id
    sponsor.is_active = False
    db.session.flush()
    assert find_sponsor(event, contribution.id) is None
