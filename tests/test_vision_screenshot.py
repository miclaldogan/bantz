import pytest

from bantz.router.nlu import parse_intent
from bantz.router.policy import Policy
from bantz.skills.vision import take_screenshot


class TestNLUVisionScreenshot:
    @pytest.mark.parametrize(
        "text,expected_slots",
        [
            ("ekran görüntüsü al", {}),
            ("screenshot al", {}),
            ("ekranı çek", {}),
            ("screenshot al: 10 20 300 400", {"x": 10, "y": 20, "w": 300, "h": 400}),
            ("ekran görüntüsü al: 1 2 3 4", {"x": 1, "y": 2, "w": 3, "h": 4}),
        ],
    )
    def test_parses_intent_and_slots(self, text, expected_slots):
        parsed = parse_intent(text)
        assert parsed.intent == "vision_screenshot"
        for k, v in expected_slots.items():
            assert parsed.slots.get(k) == v


class TestPolicyVisionScreenshot:
    @pytest.fixture
    def policy(self):
        return Policy.from_json_file("config/policy.json")

    def test_policy_requires_confirmation(self, policy):
        decision, _ = policy.decide(text="ekran görüntüsü al", intent="vision_screenshot", confirmed=False)
        assert decision == "confirm"


class TestVisionScreenshotSkill:
    def test_region_validation(self):
        ok, msg, res = take_screenshot(x=10, y=20, w=None, h=40)
        assert ok is False
        assert isinstance(msg, str)
        assert res is None

    def test_take_screenshot_graceful(self, tmp_path):
        out = tmp_path / "shot.png"
        ok, msg, res = take_screenshot(out_path=str(out))
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

        # If deps/display are available, verify it actually wrote the file.
        if ok:
            assert res is not None
            assert out.exists()
            assert str(out) == res.path
        else:
            # If deps missing or capture fails, ensure it fails cleanly.
            assert res is None
            assert "❌" in msg
