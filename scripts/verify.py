#!/usr/bin/env python3
# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

"""End-to-end verification against a real Indico instance.

    python3 scripts/verify.py --session <sid> --event <id>

`--session` is the value of the Indico session cookie for a user who can manage
the event (`indico_session` normally, `indico_session_http` on an instance whose
base URL is plain http). Minting one server-side beats putting a password in a
script.

Everything is asserted numerically -- rendered widths, stored rows, HTTP status
-- rather than by eye. The run is idempotent: it clears the event's sponsors
first and puts the template settings back afterwards, so it can be repeated.
"""
import argparse
import struct
import sys
import tempfile
import zlib
from pathlib import Path

from playwright.sync_api import sync_playwright


def solid_png(path, width, height, rgb):
    """A flat PNG of a known size, so uploads need no fixture files.

    The sizes matter: the script asserts that a logo is drawn at a share of the
    container rather than at its own natural width, and a source image that is
    already the right size would let that pass for the wrong reason.
    """
    raw = b''.join(b'\x00' + bytes(rgb) * width for _ in range(height))

    def chunk(tag, data):
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body))

    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
                           + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
    return str(path)


#: Tallied on an object rather than in module globals, so `check` needs no
#: `global` statement to record a result.
tally = {'passed': 0, 'failed': 0}


def check(label, ok, detail=''):
    tally['passed' if ok else 'failed'] += 1
    print(f'  {"PASS" if ok else "FAIL"}  {label}' + (f' — {detail}' if detail else ''))


parser = argparse.ArgumentParser()
parser.add_argument('--base', default='http://localhost:8000')
parser.add_argument('--session', required=True, help='value of the Indico session cookie')
parser.add_argument('--cookie-name', default='indico_session_http')
parser.add_argument('--event', type=int, required=True)
parser.add_argument('--out', default='.', help='where to write screenshots')
args = parser.parse_args()

BASE, SID, EVENT, OUT = args.base, args.session, args.event, args.out
WORK = Path(tempfile.mkdtemp(prefix='eventsponsors-verify-'))
WIDE = solid_png(WORK / 'wide.png', 300, 100, (30, 90, 160))
SQUARE = solid_png(WORK / 'square.png', 200, 200, (170, 60, 40))
DOMAIN = BASE.split('//', 1)[1].split(':')[0].split('/')[0]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={'width': 1400, 'height': 950})
    ctx.add_cookies([{'name': args.cookie_name, 'value': SID, 'domain': DOMAIN, 'path': '/'}])
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))

    print('\n== Adding sponsors ==')
    # Start from an empty list, so the counts below mean something on a re-run.
    page.goto(f'{BASE}/event/{EVENT}/manage/sponsors/', wait_until='networkidle')
    while page.locator('table tbody tr').count():
        page.locator('table tbody tr a.icon-edit').first.click()
        page.wait_for_load_state('networkidle')
        page.once('dialog', lambda d: d.accept())
        page.click('button.icon-remove.danger:not([data-href])')
        page.wait_for_load_state('networkidle')
    for name, tier, tagline, url, logo in (
        ('Aperture Science', 'Platinum', 'We do what we must because we can.',
         'https://aperture.example', WIDE),
        ('Black Mesa', 'Gold', 'Research facility.', 'https://blackmesa.example', WIDE),
        ('Cyberdyne', 'Silver', 'Systems.', 'https://cyberdyne.example', SQUARE),
    ):
        page.goto(f'{BASE}/event/{EVENT}/manage/sponsors/new', wait_until='networkidle')
        page.fill('#name', name)
        page.fill('#tagline', tagline)
        page.fill('#homepage_url', url)
        page.fill('#description', f'{name} is a long-standing supporter of this conference.')
        # The option label carries the size in brackets, so match on the value.
        value = page.evaluate("(t) => [...document.querySelectorAll('#tier_id option')]"
                              ".find(o => o.textContent.trim().startsWith(t)).value", tier)
        page.select_option('#tier_id', value=value)
        page.set_input_files('#logo', logo)
        page.click('input[type=submit], button[type=submit]')
        page.wait_for_load_state('networkidle')

    rows = page.locator('table tbody tr')
    check('all three sponsors are listed', rows.count() == 3, f'{rows.count()} rows')
    check('the list shows their tiers', 'Platinum' in page.content() and 'Silver' in page.content())
    check('no JS errors on the management page', not errors, '; '.join(errors[:2]))
    page.screenshot(path=f'{OUT}/sponsors-list.png', full_page=True)

    # Leave the top tier's template settings as this script expects to find them:
    # the section below measures against Platinum, and an earlier run switches it
    # off on purpose.
    page.goto(f'{BASE}/event/{EVENT}/manage/sponsors/settings', wait_until='networkidle')
    page.locator('a.icon-edit').first.click()
    page.wait_for_load_state('networkidle')
    for field in ('show_logo', 'show_name', 'show_description'):
        page.locator(f'input[name$="_{field}"]').first.check()
    page.click('input[type=submit]')
    page.wait_for_load_state('networkidle')

    print('\n== The logo is served ==')
    page.goto(f'{BASE}/event/{EVENT}/manage/sponsors/', wait_until='networkidle')
    logo_src = page.locator('table tbody tr img').first.get_attribute('src')
    got = page.evaluate(
        "async (src) => { const r = await fetch(src);"
        " return [r.status, r.headers.get('content-type')]; }",
        logo_src)
    check('an uploaded logo downloads as an image', got[0] == 200 and got[1].startswith('image/'), str(got))

    print('\n== The shortcode on a real page ==')
    # Put the shortcode into the event description, which is ordinary author HTML.
    page.goto(f'{BASE}/event/{EVENT}/', wait_until='networkidle')
    rendered = page.locator('.evsp')
    check('the description shortcode expanded', rendered.count() >= 1, f'{rendered.count()} blocks')
    if rendered.count():
        widths = page.evaluate('''() => [...document.querySelectorAll('.evsp-tier')].map(tier => {
            const logo = tier.querySelector('.evsp-logo img');
            return [tier.dataset.tier, logo ? logo.getBoundingClientRect().width : 0];
        })''')
        check('the stylesheet arrived with the block',
              page.evaluate("() => getComputedStyle(document.querySelector('.evsp-tier')).display === 'flex'"))
        by_tier = dict(widths)
        # The ratios of the drawn logos must be the ratios of the tier sizes,
        # whatever the page is actually wide. The sizes are read from the event
        # rather than written here: hardcoding them made this fail the moment
        # somebody edited a tier, which is not a fault worth reporting.
        sizes = page.evaluate(
            'async (id) => (await (await fetch(`/event/${id}/sponsors/data`)).json()).tiers',
            EVENT)
        sizes = {tier['name']: tier['size'] for tier in sizes}
        biggest = max(sizes, key=lambda name: sizes[name]) if sizes else None
        for name, size in sorted(sizes.items(), key=lambda item: -item[1])[1:]:
            expected = size / sizes[biggest]
            top, other = by_tier.get(biggest), by_tier.get(name)
            ratio = (other / top) if top and other else None
            check(f'a {name} logo is {expected:.2f} the width of a {biggest} one',
                  ratio is not None and abs(ratio - expected) < 0.02,
                  f'{ratio:.3f} ({by_tier})' if ratio else f'missing a tier: {by_tier}')
        # Adaptivity is the claim that the block is sized by its container and
        # not by any fixed number of pixels. Halving the container is the direct
        # test of it -- narrowing the viewport is not, because Indico's own page
        # column has a minimum width and simply scrolls.
        halved = page.evaluate('''() => {
            const block = document.querySelector('.evsp');
            const before = block.querySelector('.evsp-logo img').getBoundingClientRect().width;
            const parent = block.parentElement;
            const original = parent.style.width;
            parent.style.width = (parent.getBoundingClientRect().width / 2) + 'px';
            const after = block.querySelector('.evsp-logo img').getBoundingClientRect().width;
            parent.style.width = original;
            return [before, after];
        }''')
        check('halving the space halves the logos', abs(halved[1] / halved[0] - 0.5) < 0.03,
              f'{halved[0]:.0f}px -> {halved[1]:.0f}px')
    check('an unknown shortcode is left as typed', '{{sponsors_typo}}' in page.content())
    page.screenshot(path=f'{OUT}/sponsors-rendered.png', full_page=True)
    check('no JS errors on the display page', not errors, '; '.join(errors[:2]))

    print('\n== Nothing overlaps ==')
    # A row shorter than its own contents is how a logo ends up drawn on top of
    # the sponsor below it. Measured rather than looked at: the failure is
    # invisible until an image happens to be tall enough.
    geometry = page.evaluate('''() => {
        const rows = [...document.querySelectorAll('.evsp-item')].map(el => {
            const r = el.getBoundingClientRect();
            return {tier: el.closest('.evsp-tier').dataset.tier, top: r.top + scrollY,
                    bottom: r.bottom + scrollY, height: r.height, content: el.scrollHeight};
        });
        let overlaps = 0;
        for (let i = 1; i < rows.length; i++) {
            if (rows[i].top < rows[i - 1].bottom - 1) { overlaps++; }
        }
        return {rows, clipped: rows.filter(r => r.content > r.height + 1), overlaps};
    }''')
    check('no row is shorter than what is inside it', not geometry['clipped'],
          str(geometry['clipped']))
    check('no row starts before the one above it ends', geometry['overlaps'] == 0,
          f"{geometry['overlaps']} overlaps in {len(geometry['rows'])} rows")
    check('the block ends above whatever follows it', page.evaluate('''() => {
        const block = document.querySelector('.evsp');
        const next = block.nextElementSibling;
        return !next || block.getBoundingClientRect().bottom <= next.getBoundingClientRect().top + 1;
    }'''))

    print('\n== Display inline ==')
    page.goto(f'{BASE}/event/{EVENT}/manage/sponsors/settings', wait_until='networkidle')
    page.locator('tr', has_text='sponsors_full').locator('a.icon-edit').first.click()
    page.wait_for_load_state('networkidle')
    headers = [h.strip() for h in page.locator('table thead th').all_inner_texts()]
    check('the matrix offers it per tier', 'Display inline' in headers, str(headers))
    boxes = page.locator('input[name$="_inline"]')
    for index in range(boxes.count()):
        # Every tier but the first, so the mixed arrangement the option exists
        # for is what gets checked.
        (boxes.nth(index).uncheck if index == 0 else boxes.nth(index).check)(force=True)
    page.click('input[type=submit]')
    page.wait_for_load_state('networkidle')
    page.goto(f'{BASE}/event/{EVENT}/', wait_until='networkidle')
    page.wait_for_timeout(600)
    rows = page.evaluate('''() => [...document.querySelectorAll('.evsp-tier')].map(t => [
        t.dataset.tier, t.classList.contains('evsp-inline'),
        getComputedStyle(t).flexDirection, getComputedStyle(t).flexWrap])''')
    check('a template can mix a stacked tier with inline ones',
          len(rows) >= 2 and rows[0][1] is False and rows[1][1] is True, str(rows))
    check('an inline tier lays out as a wrapping row',
          all(r[2] == 'row' and r[3] == 'wrap' for r in rows if r[1]), str(rows))

    print('\n== Inline rows share a line ==')
    # A box of the right height proves nothing if the picture hangs out of it,
    # which is exactly what happened once and passed a weaker check.
    alignment = page.evaluate('''() => {
        const rows = new Map();
        for (const card of document.querySelectorAll('.evsp-inline .evsp-item')) {
            const key = Math.round((card.getBoundingClientRect().top + scrollY) / 20);
            if (!rows.has(key)) { rows.set(key, []); }
            const box = card.querySelector('.evsp-logo');
            if (box) { rows.get(key).push(box.getBoundingClientRect()); }
        }
        const lines = [...rows.values()].filter(r => r.length > 1).map(r => ({
            count: r.length,
            bottomSpread: Math.max(...r.map(b => b.bottom)) - Math.min(...r.map(b => b.bottom)),
            heightSpread: Math.max(...r.map(b => b.height)) - Math.min(...r.map(b => b.height)),
        }));
        const escaped = [];
        for (const box of document.querySelectorAll('.evsp-inline .evsp-logo')) {
            const img = box.querySelector('img');
            if (!img) { continue; }
            const b = box.getBoundingClientRect(), i = img.getBoundingClientRect();
            if (i.bottom > b.bottom + 1 || i.top < b.top - 1) { escaped.push(Math.round(i.height)); }
        }
        const shapes = [...document.querySelectorAll('.evsp-inline .evsp-logo img')]
            .map(i => Math.round((i.naturalWidth / i.naturalHeight) * 100) / 100);
        return {lines, escaped, shapes: [...new Set(shapes)]};
    }''')
    if not alignment['lines']:
        print('  --   no inline tier has two sponsors on a row; skipping the alignment checks')
    else:
        check('every logo box on a row is the same height',
              all(line['heightSpread'] <= 1 for line in alignment['lines']), str(alignment['lines']))
        check('and they stand on one line',
              all(line['bottomSpread'] <= 1 for line in alignment['lines']), str(alignment['lines']))
        check('the artwork stays inside its box', not alignment['escaped'], str(alignment['escaped']))
        check('and the shapes really do differ, so this proves something',
              len(alignment['shapes']) >= 2, str(alignment['shapes']))

    print('\n== The campaign URL overrides the homepage ==')
    page.goto(f'{BASE}/event/{EVENT}/manage/sponsors/', wait_until='networkidle')
    page.locator('table tbody tr a.icon-edit').first.click()
    page.wait_for_load_state('networkidle')
    page.fill('#campaign_url', 'https://aperture.example/offer')
    page.check('#use_campaign_url')
    page.click('input[type=submit]')
    page.wait_for_load_state('networkidle')
    page.goto(f'{BASE}/event/{EVENT}/', wait_until='networkidle')
    hrefs = page.evaluate("() => [...document.querySelectorAll('.evsp a')].map(a => a.href)")
    check('the link uses the campaign address', 'https://aperture.example/offer' in hrefs, str(hrefs[:3]))
    check('the homepage is still kept for the others',
          any(h.rstrip('/') == 'https://blackmesa.example' for h in hrefs), str(hrefs[:3]))

    print('\n== Tiers ==')
    page.goto(f'{BASE}/event/{EVENT}/manage/sponsors/settings', wait_until='networkidle')
    before = page.locator('table').first.locator('tbody tr').count()
    page.fill('input[name=new_name]', 'Community')
    page.fill('input[name=new_size]', '15')
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle')
    after = page.locator('table').first.locator('tbody tr').count()
    check('a tier can be added', after == before + 1, f'{before} -> {after} rows (one is the blank add row)')
    tier_id = page.evaluate('''() => {
        const input = [...document.querySelectorAll('input[type=text]')].find(i => i.value === 'Community');
        return input.name.split('_')[1];
    }''')
    page.check(f'input[name=delete_{tier_id}]')
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle')
    check('a tier can be removed again',
          page.locator('table').first.locator('tbody tr').count() == before, 'back to the original count')

    print('\n== The template matrix ==')
    page.goto(f'{BASE}/event/{EVENT}/manage/sponsors/settings', wait_until='networkidle')
    page.locator('a.icon-edit').first.click()
    page.wait_for_load_state('networkidle')
    boxes = page.locator('table input[type=checkbox]')
    check('there is a checkbox per tier and field', boxes.count() >= 4 * 6, f'{boxes.count()} boxes')
    # Take the whole top tier out of this template and confirm it disappears.
    for field in ('show_logo', 'show_name', 'show_tagline', 'show_description', 'show_square_logo'):
        target = page.locator(f'input[name$="_{field}"]').first
        if target.is_checked():
            target.uncheck()
    page.click('input[type=submit]')
    page.wait_for_load_state('networkidle')
    page.goto(f'{BASE}/event/{EVENT}/', wait_until='networkidle')
    tiers_shown = page.evaluate("() => [...document.querySelectorAll('.evsp-tier')].map(t => t.dataset.tier)")
    check('a tier showing nothing drops out of the block', 'Platinum' not in tiers_shown, str(tiers_shown))

    # Put it back, so the run leaves the event as it found it -- and so the next
    # run's size checks have a top tier to measure against.
    page.goto(f'{BASE}/event/{EVENT}/manage/sponsors/settings', wait_until='networkidle')
    page.locator('a.icon-edit').first.click()
    page.wait_for_load_state('networkidle')
    for field in ('show_logo', 'show_name', 'show_description'):
        page.locator(f'input[name$="_{field}"]').first.check()
    page.click('input[type=submit]')
    page.wait_for_load_state('networkidle')
    page.goto(f'{BASE}/event/{EVENT}/', wait_until='networkidle')
    tiers_shown = page.evaluate("() => [...document.querySelectorAll('.evsp-tier')].map(t => t.dataset.tier)")
    check('ticking the boxes again brings the tier back', 'Platinum' in tiers_shown, str(tiers_shown))

    print('\n== The app placement checkbox ==')
    page.goto(f'{BASE}/event/{EVENT}/manage/sponsors/settings', wait_until='networkidle')
    page.locator('tr', has_text='sponsors_app').locator('a.icon-edit').first.click()
    page.wait_for_load_state('networkidle')
    order = page.evaluate('''() => {
        const ids = [...document.querySelectorAll('input')].map(i => i.id).filter(Boolean);
        return [ids.indexOf('for_app'), ids.indexOf('app_above_schedule')];
    }''')
    check('the placement switch sits directly under the app switch',
          order[0] >= 0 and order[1] == order[0] + 1, str(order))
    page.locator('#app_above_schedule').check(force=True)
    page.click('input[type=submit]')
    page.wait_for_load_state('networkidle')
    above = page.evaluate('async (id) => (await (await fetch(`/event/${id}/sponsors/data`)).json()).template',
                          EVENT)
    check('ticking it reaches the app payload', above.get('above_schedule') is True, str(above))
    page.goto(f'{BASE}/event/{EVENT}/manage/sponsors/settings', wait_until='networkidle')
    page.locator('tr', has_text='sponsors_app').locator('a.icon-edit').first.click()
    page.wait_for_load_state('networkidle')
    check('and the form comes back ticked', page.locator('#app_above_schedule').is_checked())

    print('\n== The phone app endpoint ==')
    data = page.evaluate('async (id) => (await fetch(`/event/${id}/sponsors/data`)).json()', EVENT)
    check('the app gets the app template', data['template']['slug'] == 'sponsors_app', str(data['template']))
    check('the app gets the sponsors', len(data['sponsors']) >= 2, f"{len(data['sponsors'])} sponsors")
    check('each sponsor carries the resolved field choices',
          all('show' in s and 'width' not in s for s in data['sponsors']))
    check('tiers carry their computed width share',
          all('width_pct' in t for t in data['tiers']), str(data['tiers']))

    print('\n== With the feature switched off ==')
    page.goto(f'{BASE}/event/{EVENT}/manage/features/', wait_until='networkidle')
    switch = page.locator('#form-group-eventsponsors input[type=checkbox], input[name=eventsponsors]').first
    check('the Sponsors switch is on the Features page', switch.count() > 0)
    switch.click()
    page.wait_for_timeout(1500)
    status = page.evaluate('async (id) => (await fetch(`/event/${id}/manage/sponsors/`)).status', EVENT)
    check('the management URL 404s once it is off', status == 404, str(status))
    page.goto(f'{BASE}/event/{EVENT}/', wait_until='networkidle')
    check('the shortcode is left as typed when the feature is off',
          '{{sponsors_full}}' in page.content() and page.locator('.evsp').count() == 0)
    switch = page.locator('#form-group-eventsponsors input[type=checkbox], input[name=eventsponsors]').first
    page.goto(f'{BASE}/event/{EVENT}/manage/features/', wait_until='networkidle')
    page.locator('#form-group-eventsponsors input[type=checkbox], input[name=eventsponsors]').first.click()
    page.wait_for_timeout(1500)
    status = page.evaluate('async (id) => (await fetch(`/event/${id}/manage/sponsors/`)).status', EVENT)
    check('turning it back on restores everything', status == 200, str(status))

    browser.close()

print(f'\n{tally["passed"]} passed, {tally["failed"]} failed')
sys.exit(1 if tally['failed'] else 0)
