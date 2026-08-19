# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

from indico.core.db import db
from indico.modules.events.cloning import EventCloner, get_attrs_to_clone
from indico.modules.events.features.util import is_feature_enabled

from indico_eventsponsors import _
from indico_eventsponsors.models.sponsors import Sponsor, SponsorContribution, SponsorLogo
from indico_eventsponsors.models.templates import TEMPLATE_FIELDS, SponsorTemplate, SponsorTemplateTier
from indico_eventsponsors.models.tiers import SponsorTier


class SponsorSettingsCloner(EventCloner):
    """Copy the tiers, the templates and the per-tier matrix.

    Two cloners rather than one because their costs differ: this one carries
    configuration, which an annual event almost always wants, while
    `SponsorsCloner` carries last year's sponsor list and its logo files,
    which is a separate decision.
    """

    name = 'sponsor_tiers'
    friendly_name = _('Sponsorship tiers and templates')
    is_default = True

    @property
    def is_visible(self):
        from indico_eventsponsors.plugin import FEATURE_NAME
        return is_feature_enabled(self.old_event, FEATURE_NAME)

    @property
    def is_available(self):
        return (SponsorTier.query.filter_by(event_id=self.old_event.id).has_rows()
                or SponsorTemplate.query.filter_by(event_id=self.old_event.id).has_rows())

    def run(self, new_event, cloners, shared_data, event_exists=False):
        # The feature flag travels with the event, so by the time cloners run
        # `EventSponsorsFeature.enabled` has already seeded the clone with the
        # *site* defaults. That seed only exists as a fallback for when this
        # cloner is not selected; here it gives way to the old event's own
        # configuration.
        for template in SponsorTemplate.query.filter_by(event_id=new_event.id):
            db.session.delete(template)
        for tier in SponsorTier.query.filter_by(event_id=new_event.id):
            db.session.delete(tier)
        db.session.flush()

        tier_map = {}
        tier_attrs = get_attrs_to_clone(SponsorTier)
        for old_tier in SponsorTier.query.filter_by(event_id=self.old_event.id):
            tier = SponsorTier(event_id=new_event.id, **{attr: getattr(old_tier, attr) for attr in tier_attrs})
            db.session.add(tier)
            tier_map[old_tier.id] = tier
        db.session.flush()

        template_attrs = get_attrs_to_clone(SponsorTemplate)
        for old_template in SponsorTemplate.query.filter_by(event_id=self.old_event.id):
            template = SponsorTemplate(event_id=new_event.id,
                                       **{attr: getattr(old_template, attr) for attr in template_attrs})
            db.session.add(template)
            for old_settings in old_template.tier_settings:
                settings = SponsorTemplateTier(template=template, tier=tier_map[old_settings.tier_id])
                for field, _label in TEMPLATE_FIELDS:
                    setattr(settings, field, getattr(old_settings, field))
                db.session.add(settings)
        db.session.flush()
        return {'tier_map': tier_map}


class SponsorsCloner(EventCloner):
    """Copy the sponsors themselves, logo files included."""

    name = 'sponsors'
    friendly_name = _('Sponsors')
    #: A sponsor without its tier is never rendered, so the configuration has
    #: to come along.
    requires = frozenset({'sponsor_tiers'})
    #: Contribution links can only survive if the contributions were cloned
    #: too; without them the links are dropped rather than left pointing into
    #: the old event.
    uses = frozenset({'contributions'})

    @property
    def is_visible(self):
        from indico_eventsponsors.plugin import FEATURE_NAME
        return is_feature_enabled(self.old_event, FEATURE_NAME)

    @property
    def is_available(self):
        return Sponsor.query.filter_by(event_id=self.old_event.id).has_rows()

    def run(self, new_event, cloners, shared_data, event_exists=False):
        tier_map = shared_data['sponsor_tiers']['tier_map']
        contrib_map = shared_data['contributions']['contrib_map'] if 'contributions' in cloners else {}
        contribution_by_old_id = {old.id: new for old, new in contrib_map.items()}
        attrs = get_attrs_to_clone(Sponsor)
        for old_sponsor in Sponsor.query.filter_by(event_id=self.old_event.id):
            sponsor = Sponsor(event_id=new_event.id, **{attr: getattr(old_sponsor, attr) for attr in attrs})
            # An untiered sponsor stays untiered -- `get` rather than indexing.
            sponsor.tier = tier_map.get(old_sponsor.tier_id)
            db.session.add(sponsor)
            for attribute in ('logo', 'square_logo'):
                old_logo = getattr(old_sponsor, attribute)
                if old_logo is not None:
                    setattr(sponsor, attribute, self._copy_logo(new_event, old_logo))
            for link in old_sponsor.contribution_links:
                contribution = contribution_by_old_id.get(link.contribution_id)
                if contribution is not None:
                    sponsor.contribution_links.append(SponsorContribution(contribution=contribution))
        db.session.flush()

    def _copy_logo(self, new_event, old_logo):
        # `event_id` alongside `event` for the same reason as `store_logo`:
        # `_build_storage_path` reads it before the row is flushed.
        logo = SponsorLogo(event_id=new_event.id, event=new_event, filename=old_logo.filename,
                           content_type=old_logo.content_type)
        with old_logo.open() as fd:
            logo.save(fd)
        db.session.add(logo)
        db.session.flush()
        return logo
