# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

from indico.core.plugins import IndicoPluginBlueprint

from indico_eventsponsors.controllers import (RHManageSettings, RHManageSponsors, RHSponsorCreate, RHSponsorDelete,
                                              RHSponsorEdit, RHSponsorLogo, RHSponsorMove, RHSponsorsData,
                                              RHTemplateCreate, RHTemplateDelete, RHTemplateEdit, RHTemplatePreview)


# Every URL below 404s unless the event has the Sponsors feature switched on. The
# menu entry hides itself too; this is what stops a bookmarked URL working around
# that, and it is also what makes the shortcode inert on an event that has not
# opted in.
blueprint = IndicoPluginBlueprint('eventsponsors', __name__, event_feature='eventsponsors')

blueprint.add_url_rule('/event/<int:event_id>/manage/sponsors/', 'manage', RHManageSponsors)
blueprint.add_url_rule('/event/<int:event_id>/manage/sponsors/new', 'sponsor_create', RHSponsorCreate,
                       methods=('GET', 'POST'))
blueprint.add_url_rule('/event/<int:event_id>/manage/sponsors/<int:sponsor_id>', 'sponsor_edit', RHSponsorEdit,
                       methods=('GET', 'POST'))
blueprint.add_url_rule('/event/<int:event_id>/manage/sponsors/<int:sponsor_id>/delete', 'sponsor_delete',
                       RHSponsorDelete, methods=('POST',))
blueprint.add_url_rule('/event/<int:event_id>/manage/sponsors/<int:sponsor_id>/move/<any(up,down,top,bottom):direction>',
                       'sponsor_move', RHSponsorMove, methods=('POST',))

blueprint.add_url_rule('/event/<int:event_id>/manage/sponsors/settings', 'settings', RHManageSettings,
                       methods=('GET', 'POST'))
blueprint.add_url_rule('/event/<int:event_id>/manage/sponsors/templates/new', 'template_create', RHTemplateCreate,
                       methods=('GET', 'POST'))
blueprint.add_url_rule('/event/<int:event_id>/manage/sponsors/templates/<int:template_id>', 'template_edit',
                       RHTemplateEdit, methods=('GET', 'POST'))
blueprint.add_url_rule('/event/<int:event_id>/manage/sponsors/templates/<int:template_id>/delete',
                       'template_delete', RHTemplateDelete, methods=('POST',))
blueprint.add_url_rule('/event/<int:event_id>/manage/sponsors/templates/<int:template_id>/preview',
                       'template_preview', RHTemplatePreview)

blueprint.add_url_rule('/event/<int:event_id>/sponsors/logo/<int:logo_id>/<filename>', 'logo', RHSponsorLogo)
blueprint.add_url_rule('/event/<int:event_id>/sponsors/data', 'data', RHSponsorsData)
