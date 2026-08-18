# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

from flask_wtf.file import FileAllowed, FileField
from wtforms import Form as PlainForm
from wtforms.fields import BooleanField, IntegerField, SelectField, StringField, TextAreaField, URLField
from wtforms.validators import DataRequired, NumberRange, Optional, ValidationError

from indico.web.forms.base import IndicoForm
from indico.web.forms.widgets import SwitchWidget

from indico_eventsponsors import _
from indico_eventsponsors.models.templates import LAYOUTS, TEMPLATE_FIELDS
from indico_eventsponsors.models.tiers import SponsorTier
from indico_eventsponsors.shortcodes import SLUG_RE


IMAGE_TYPES = ('png', 'jpg', 'jpeg', 'gif', 'svg', 'webp')


class SponsorForm(IndicoForm):
    name = StringField(_('Name'), [DataRequired()])
    is_active = BooleanField(_('Active'), widget=SwitchWidget(),
                             description=_('Inactive sponsors are kept but never shown on the site.'))
    tier_id = SelectField(_('Tier'), coerce=int,
                          description=_('A sponsor with no tier is never rendered: the tier is what decides how '
                                        'large its logo is drawn.'))
    tagline = StringField(_('One-line description'),
                          description=_('A single sentence, for places a paragraph will not fit.'))
    description = TextAreaField(_('Full description'), render_kw={'rows': 5})
    homepage_url = URLField(_('Homepage'), [Optional()])
    campaign_url = URLField(_('Campaign link'), [Optional()],
                            description=_('An address for a particular campaign or offer.'))
    use_campaign_url = BooleanField(_('Link to the campaign instead of the homepage'), widget=SwitchWidget(),
                                    description=_('The homepage is kept either way, so this can be turned off '
                                                  'again when the campaign ends.'))
    contribution_ids = StringField(
        _('Contributions'),
        description=_("Comma-separated contribution numbers — the ones shown in this event's contribution "
                      "list. The sponsor's logo appears on those talks in the phone app. Leave empty for a "
                      'sponsor of the event as a whole.'),
    )
    logo = FileField(_('Logo'), [FileAllowed(IMAGE_TYPES, _('That is not an image file.'))])
    delete_logo = BooleanField(_('Remove the current logo'))
    square_logo = FileField(_('Square logo'), [FileAllowed(IMAGE_TYPES, _('That is not an image file.'))],
                            description=_('Used where a block is laid out in squares. Templates asking for it fall '
                                          'back to the ordinary logo when there is none.'))
    delete_square_logo = BooleanField(_('Remove the current square logo'))

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.event = event
        #: Set by `validate_contribution_ids`, so the controller stores the ids
        #: the form already resolved instead of parsing the box a second time.
        self.resolved_contribution_ids = []
        tiers = SponsorTier.query.filter_by(event_id=event.id).order_by(SponsorTier.position, SponsorTier.id).all()
        self.tier_id.choices = [(0, _('No tier'))] + [(t.id, f'{t.name} ({t.size})') for t in tiers]

    def validate_contribution_ids(self, field):
        from indico_eventsponsors.util import parse_contribution_ids
        found, unknown = parse_contribution_ids(self.event, field.data)
        if unknown:
            # Naming them beats "invalid input": with twenty numbers in the box,
            # the useful information is which one is wrong.
            raise ValidationError(_('No contribution in this event matches: {numbers}')
                                  .format(numbers=', '.join(unknown)))
        self.resolved_contribution_ids = found

    def validate_use_campaign_url(self, field):
        if field.data and not self.campaign_url.data:
            raise ValidationError(_('There is no campaign link to use.'))


class TemplateForm(IndicoForm):
    """The template's own settings. The per-tier matrix is built separately --
    see `build_matrix_form`, which cannot be a static class because its fields
    depend on which tiers the event has.
    """

    slug = StringField(_('Shortcode'), [DataRequired()],
                       description=_('Typed into a page as {{slug}}. Must start with "sponsor" or "sponsors" '
                                     'followed by an underscore, and may contain lowercase letters, digits and '
                                     'underscores.'))
    title = StringField(_('Name'), [DataRequired()],
                        description=_('For your own reference; never shown on the site.'))
    layout = SelectField(_('Layout'), choices=[(value, _(label)) for value, label in LAYOUTS])
    max_logo_pct = IntegerField(_('Largest logo width (%)'), [NumberRange(min=2, max=100)], default=22,
                                description=_('What share of the available width the largest tier takes. Smaller '
                                              'tiers scale down from there in proportion to their size, and the '
                                              'whole block adapts to the space it is dropped into.'))
    for_app = BooleanField(_('Use this template in the phone app'), widget=SwitchWidget(),
                           description=_("Only one template can be the app's; choosing this one releases any "
                                         'other.'))
    app_above_schedule = BooleanField(_('Display this above the schedule in the app'), widget=SwitchWidget(),
                                      description=_("Otherwise it sits below the day's talks. The top of the "
                                                    'screen is the first thing an attendee sees and the space they '
                                                    'came for, so a block there wants to be a short one.'))

    def validate_slug(self, field):
        if not SLUG_RE.match(field.data or ''):
            raise ValidationError(_('That is not a usable shortcode name.'))


def build_matrix_form(tiers, existing):
    """A form class with a checkbox per tier and field.

    Built per request because the fields *are* the event's tiers. `existing`
    maps a tier id to its stored settings, or is empty for a new template, in
    which case a tier starts with a logo, a name and a link.
    """
    attrs = {}
    for tier in tiers:
        settings = existing.get(tier.id)
        for field, label in TEMPLATE_FIELDS:
            default = getattr(settings, field) if settings else field in ('show_logo', 'show_name', 'linked')
            attrs[f'tier_{tier.id}_{field}'] = BooleanField(_(label), default=default)
    # A plain WTForms form, not an `IndicoForm`: its fields are rendered inside
    # the template form's own `<form>` element, so it must not carry a second
    # CSRF token that nothing submits.
    return type('MatrixForm', (PlainForm,), attrs)
