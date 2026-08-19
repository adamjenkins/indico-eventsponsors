# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

from flask import session
from wtforms.fields import TextAreaField
from wtforms.validators import ValidationError

from indico.core import signals
from indico.core.plugins import IndicoPlugin, url_for_plugin
from indico.modules.events.features.base import EventFeature
from indico.web.forms.base import IndicoForm
from indico.web.menu import SideMenuItem

from indico_eventsponsors import _
from indico_eventsponsors.blueprint import blueprint
from indico_eventsponsors.defaults import DEFAULT_TEMPLATES, DEFAULT_TIERS, parse_tier_lines, seed_event


#: The event feature this plugin is gated behind. Also used by `blueprint.py`.
FEATURE_NAME = 'eventsponsors'


class SettingsForm(IndicoForm):
    default_tiers = TextAreaField(
        _('Default tiers'),
        description=_('One tier per line, as "Name = size". The size is relative: a tier at 60 draws its logos '
                      'half again as wide as a tier at 40. Copied into an event the first time the feature is '
                      'switched on there, and editable per event afterwards. Along with these tiers, the event '
                      'also gets three built-in templates -- {{sponsors_full}}, {{sponsors_logoonly}}, and a '
                      '"Phone app" one that feeds the schedule app instead of any page -- likewise its own '
                      'copies, editable and deletable there.'),
        render_kw={'rows': 6},
    )

    def validate_default_tiers(self, field):
        try:
            parse_tier_lines(field.data)
        except ValueError as exc:
            raise ValidationError(str(exc))


class EventsponsorsPlugin(IndicoPlugin):
    """Event Sponsors

    Keeps sponsor records for an event -- logo, description, tier and links --
    and renders them into the site wherever a shortcode such as
    {{sponsors_full}} appears.
    """

    configurable = True
    settings_form = SettingsForm

    default_settings = {
        'default_tiers': '\n'.join(f'{name} = {size}' for name, size in DEFAULT_TIERS),
    }

    def init(self):
        super().init()
        self.connect(signals.event.get_feature_definitions, self._get_feature_definitions)
        self.connect(signals.event_management.get_cloners, self._get_cloners)
        self.connect(signals.menu.items, self._add_management_sidemenu_item, sender='event-management-sidemenu')
        self.connect(signals.core.app_created, self._extend_app)
        self.connect(signals.core.after_commit, self._sweep_deleted_files)

    def _get_feature_definitions(self, sender, **kwargs):
        return EventSponsorsFeature

    def _get_cloners(self, sender, **kwargs):
        from indico_eventsponsors.clone import SponsorsCloner, SponsorSettingsCloner
        yield SponsorSettingsCloner
        yield SponsorsCloner

    def _sweep_deleted_files(self, sender, **kwargs):
        # Fires on every commit, and does nothing unless this request queued a
        # logo file for deletion -- see `util.delete_logo`, which must not
        # touch storage until the commit has made the row's removal final.
        from indico_eventsponsors.util import delete_queued_files
        delete_queued_files()

    def _add_management_sidemenu_item(self, sender, event, **kwargs):
        if not event.can_manage(session.user) or not event.has_feature(FEATURE_NAME):
            return
        return SideMenuItem('eventsponsors', _('Sponsors'), url_for_plugin('eventsponsors.manage', event),
                            section='customization', weight=40, icon='star')

    def _extend_app(self, app, **kwargs):
        # Shortcode expansion is a response filter because Indico offers no hook
        # for filtering author-written HTML: a custom page renders
        # `page.html|sanitize_html` straight into the document, and nothing in
        # between is extensible. See `shortcodes.expand_response` for the guards
        # that keep this off every request that cannot possibly need it.
        from indico_eventsponsors.shortcodes import expand_response
        app.after_request(expand_response)

    def get_blueprints(self):
        return blueprint


class EventSponsorsFeature(EventFeature):
    name = FEATURE_NAME
    friendly_name = _('Sponsors')
    description = _('Keep sponsor records for this event and render them into pages with shortcodes such as '
                    '{{sponsors_full}}.')

    @classmethod
    def is_default_for_event(cls, event):
        return False

    @classmethod
    def enabled(cls, event, cloning):
        # The first time an event turns this on it gets its own copy of the
        # site's default tiers and templates. Copied rather than shared: the
        # point of a default is a starting position, not a constraint, and an
        # event that edits its tiers must not change anyone else's.
        #
        # A clone is seeded too. The flag travels with the event whether or
        # not the sponsor cloners were ticked, and an enabled feature with no
        # templates leaves any copied {{sponsors_*}} shortcode raw on the
        # public pages. When `SponsorSettingsCloner` runs it replaces this
        # seed with the old event's own configuration.
        seed_event(event, parse_tier_lines(EventsponsorsPlugin.settings.get('default_tiers')), DEFAULT_TEMPLATES)
