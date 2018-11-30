
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def default_icon_theme():
    # Our tests need to run on a system with no default display, so all
    # our display-specific get_default() stuff will break.

    from gi.repository import Gtk
    with mock.patch(
            'gi.repository.Gtk.IconTheme.get_default',
            mock.Mock(spec=Gtk.IconTheme.get_default)):
        yield
