# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

"""Expanding {{sponsors_*}} in the pages Indico has already rendered.

Indico has no hook for filtering author-written HTML. A custom menu page renders
`page.html|sanitize_html` straight into the document and nothing sits in
between, so the only place a shortcode can be substituted is the finished
response. That is blunt, and the guards below exist to keep it from being
expensive: the ordinary request pays one `in` test against the response body and
nothing else.

Deliberate limits, all of them consequences of working at this level:

* Only HTML responses of event *display* URLs. Management pages are skipped, so
  a manager editing a page still sees the shortcode they typed.
* Only exact `{{slug}}` with no spaces inside the braces, and only slugs
  matching `sponsors?_…`. That keeps one cheap substring test as the gate, and
  keeps this away from any other doubled braces on the page.
* An unrecognised slug is left exactly as it was, so a typo shows itself instead
  of quietly rendering nothing.
* Nothing inside ``<head>`` is expanded into markup. Indico repeats an event's
  description into ``<meta property="og:description">``, and a block of logos
  cannot live in an attribute -- a shortcode there is *removed* rather than
  expanded, so social-media previews get clean text instead of either a raw
  ``{{sponsors_full}}`` or a stylesheet stuffed into an attribute.
* Nothing inside ``<script>``, ``<style>`` or ``<textarea>`` is touched either.
* PDFs, iCal, the API and email are not HTML responses and are not touched.
"""

import re

from flask import request

from indico_eventsponsors.rendering import load_sponsors_by_tier, render_block


#: The substring every shortcode must contain, tested before anything else.
MARKER = '{{sponsor'

_SHORTCODE_RE = re.compile(r'\{\{(sponsors?_[a-z0-9_]{1,40})\}\}')

#: Opens a region whose contents are not markup. The matching closer is found
#: with a plain search from the opener onwards rather than one `.*?</\1>`
#: regex, whose backtracking rescans to end-of-document for every unterminated
#: opener -- unbounded CPU in a filter running on public, unauthenticated
#: loads.
_OPAQUE_OPEN_RE = re.compile(r'<(script|style|textarea)\b', re.IGNORECASE)
_OPAQUE_CLOSE_RES = {tag: re.compile(rf'</{tag}\s*>', re.IGNORECASE)
                     for tag in ('script', 'style', 'textarea')}

_HEAD_END_RE = re.compile(r'</head\s*>', re.IGNORECASE)

#: Slugs a manager may give a template -- the same shape the expander looks for.
SLUG_RE = re.compile(r'^sponsors?_[a-z0-9_]{1,40}$')


def expand(html, event, *, with_styles=True):
    """Substitute every known shortcode in `html`. Unknown ones are left alone."""
    templates = {t.slug: t for t in event.sponsor_templates}
    if not templates:
        return html
    # `sponsors` is one load shared by every shortcode on the page, fetched
    # only once a known one actually appears in it.
    state = {'styled': not with_styles, 'sponsors': None}

    def replace(match):
        template = templates.get(match.group(1))
        if template is None:
            return match.group(0)
        if state['sponsors'] is None:
            state['sponsors'] = load_sponsors_by_tier(event)
        block = render_block(event, template, with_styles=not state['styled'],
                             sponsors_by_tier=state['sponsors'])
        if block:
            state['styled'] = True
        return block

    def drop(match):
        return '' if match.group(1) in templates else match.group(0)

    head_match = _HEAD_END_RE.search(html)
    if head_match is None:
        head, body = '', html
    else:
        head, body = html[:head_match.end()], html[head_match.end():]
    return _SHORTCODE_RE.sub(drop, head) + _substitute_outside_opaque(body, replace)


def _substitute_outside_opaque(html, replace):
    """Run `replace` everywhere except inside script, style and textarea elements.

    Not a parser, and does not need to be: it only has to avoid rewriting text
    that a browser will never read as markup. A `<script>` containing the string
    `</script>` inside a JavaScript string literal would end the region early,
    which at worst means a shortcode there is expanded -- the same thing that
    happened before this existed. An opener with no closer at all makes the
    whole remainder opaque, which is also how a browser reads it.
    """
    out = []
    cursor = 0
    while (opener := _OPAQUE_OPEN_RE.search(html, cursor)) is not None:
        out.append(_SHORTCODE_RE.sub(replace, html[cursor:opener.start()]))
        closer = _OPAQUE_CLOSE_RES[opener.group(1).lower()].search(html, opener.end())
        if closer is None:
            out.append(html[opener.start():])
            return ''.join(out)
        out.append(html[opener.start():closer.end()])
        cursor = closer.end()
    out.append(_SHORTCODE_RE.sub(replace, html[cursor:]))
    return ''.join(out)


def expand_response(response):
    """`after_request` hook. Returns `response` untouched unless it needs work."""
    from indico.modules.events import Event

    from indico_eventsponsors.plugin import FEATURE_NAME, EventsponsorsPlugin

    if (request.method != 'GET' or response.status_code != 200 or response.direct_passthrough
            or response.mimetype != 'text/html' or response.headers.get('Content-Encoding')):
        return response
    event_id = (request.view_args or {}).get('event_id')
    if event_id is None or '/manage/' in request.path:
        return response
    try:
        body = response.get_data(as_text=True)
    except (RuntimeError, UnicodeDecodeError):
        return response
    if MARKER not in body:
        return response
    try:
        event = Event.get(event_id, is_deleted=False)
        if event is None or not event.has_feature(FEATURE_NAME):
            return response
        expanded = expand(body, event)
        if expanded != body:
            response.set_data(expanded)
    except Exception:
        # Flask re-raises an error out of an `after_request` hook, replacing a
        # page that was already built with an error page. A failed expansion
        # must cost less than the page it failed on: the raw shortcode stays.
        EventsponsorsPlugin.logger.exception('Could not expand sponsor shortcodes on %s', request.path)
    return response
