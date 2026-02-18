"""Legacy GTK overlay UI — moved to _legacy/ui/.

The desktop HUD is now handled by the Electron overlay (bantz-overlay/).
This package stub is kept so existing TYPE_CHECKING imports and tests
that reference bantz.ui.* don't cause ModuleNotFoundError at import time.
"""
