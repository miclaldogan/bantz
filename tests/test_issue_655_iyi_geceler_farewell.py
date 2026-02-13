# SPDX-License-Identifier: MIT
"""Issue #655: 'iyi geceler' must be farewell, not greeting."""

from bantz.routing.preroute import IntentCategory, PreRouter


def test_iyi_geceler_routes_to_farewell():
    router = PreRouter()
    result = router.route("iyi geceler")
    assert result.matched is True
    assert result.intent == IntentCategory.FAREWELL
    assert result.rule_name == "farewell"
