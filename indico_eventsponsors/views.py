# This file is part of the Event Sponsors plugin for Indico.
# Copyright (C) 2026 Adam Jenkins
#
# The Event Sponsors plugin is free software; you can redistribute
# it and/or modify it under the terms of the MIT License;
# see the LICENSE file for more details.

from indico.core.plugins import WPJinjaMixinPlugin
from indico.modules.events.management.views import WPEventManagement


class WPManageSponsors(WPJinjaMixinPlugin, WPEventManagement):
    sidemenu_option = 'eventsponsors'
