import os

from bantz.security.env_loader import load_env, load_env_file
from bantz.security.secrets import mask_path, mask_secrets, sanitize

# Use os.path.join so tests work on any OS/machine
_FAKE_CONFIG = os.path.join("home", "user", ".config", "bantz", "google")


def test_mask_path_basename_only() -> None:
    assert mask_path(os.path.join(_FAKE_CONFIG, "client_secret.json")) == "…/client_secret.json"
    assert mask_path("client_secret.json") == "…/client_secret.json"


def test_mask_secrets_common_patterns() -> None:
    google_key = "AIza" + ("A" * 30)
    ya29 = "ya29." + ("B" * 40)
    jwt = "eyJ" + ("A" * 12) + "." + ("B" * 12) + "." + ("C" * 12)
    bearer = "Bearer abcDEF0123-._~+/=="

    fake_token_path = os.path.join(_FAKE_CONFIG, "token.json")
    text = (
        f"key={google_key} oauth={ya29} jwt={jwt} auth={bearer} "
        f"path={fake_token_path}"
    )

    masked = mask_secrets(text)
    assert "AIza" not in masked
    assert "ya29." not in masked
    assert "eyJ" not in masked
    assert "Bearer ***REDACTED***" in masked
    assert "…/token.json" in masked


def test_mask_secrets_env_assignment_and_json_fields() -> None:
    google_key = "AIza" + ("A" * 30)

    masked_env = mask_secrets(f"GEMINI_API_KEY={google_key}")
    assert masked_env == "GEMINI_API_KEY=***REDACTED***"

    masked_json = mask_secrets('{"access_token": "ya29.ABCDEF"}')
    assert "ya29." not in masked_json
    assert "***REDACTED***" in masked_json


def test_mask_secrets_private_key_block() -> None:
    private_key = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
    masked = mask_secrets(private_key)
    assert masked == "***REDACTED***"


def test_sanitize_recursive() -> None:
    fake_sa_path = os.path.join(_FAKE_CONFIG, "service_account.json")
    data = {
        "auth": "Bearer abcDEF0123-._~+/==",
        "nested": {"path": fake_sa_path},
        "list": ["ya29.ABCDEF", "ok"],
    }

    out = sanitize(data)
    assert out["auth"] == "Bearer ***REDACTED***"
    assert out["nested"]["path"] == "…/service_account.json"
    assert out["list"][0] == "***REDACTED***"


def test_env_loader_load_env_file_and_override(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    p = tmp_path / "test.env"
    p.write_text("GEMINI_API_KEY=AIza" + ("A" * 30) + "\n#comment\nFOO=bar\n", encoding="utf-8")

    loaded = load_env_file(str(p))
    assert set(loaded) == {"GEMINI_API_KEY", "FOO"}
    assert os.environ.get("FOO") == "bar"

    # Should not override by default
    monkeypatch.setenv("FOO", "existing")
    loaded2 = load_env_file(str(p), override=False)
    assert "FOO" not in loaded2
    assert os.environ.get("FOO") == "existing"

    # But should override when asked
    loaded3 = load_env_file(str(p), override=True)
    assert "FOO" in loaded3
    assert os.environ.get("FOO") == "bar"


def test_env_loader_load_env_uses_env_var(monkeypatch, tmp_path) -> None:
    p = tmp_path / "bantz.env"
    p.write_text("FOO=baz\n", encoding="utf-8")
    monkeypatch.setenv("BANTZ_ENV_FILE", str(p))

    monkeypatch.delenv("FOO", raising=False)
    loaded = load_env()
    assert loaded == ["FOO"]
    assert os.environ.get("FOO") == "baz"
