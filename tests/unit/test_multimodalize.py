import asyncio
import base64
from unittest.mock import MagicMock

import pytest

from craftsman.router.sessions import SessionsRouter


@pytest.fixture
def router(mocker):
    mocker.patch("craftsman.router.sessions.CraftsmanLogger")
    return SessionsRouter(MagicMock(), MagicMock(), set())


def arun(coro):
    return asyncio.run(coro)


# --- passthrough cases ---


def test_non_string_content_passthrough(router):
    message = {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    result = arun(router.multimodalize_message(message))
    assert result is message


def test_no_media_tokens_passthrough(router):
    message = {"role": "user", "content": "Hello world, no tokens here"}
    result = arun(router.multimodalize_message(message))
    assert result is message


# --- image ---


def test_image_token_produces_image_url_block(router, tmp_path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"fake-image-data")
    router.librarian.structure_db.get_artifact.return_value = {
        "mime_type": "image/jpeg",
        "filepath": str(img),
    }
    msg = {"role": "user", "content": "@image:abc123"}
    result = arun(router.multimodalize_message(msg))
    assert result["role"] == "user"
    assert len(result["content"]) == 1
    block = result["content"][0]
    assert block["type"] == "image_url"
    expected = base64.b64encode(b"fake-image-data").decode()
    assert block["image_url"]["url"] == f"data:image/jpeg;base64,{expected}"


# --- audio format mapping ---


def test_audio_mpeg_maps_to_mp3(router, tmp_path):
    af = tmp_path / "sound.mp3"
    af.write_bytes(b"audio-data")
    router.librarian.structure_db.get_artifact.return_value = {
        "mime_type": "audio/mpeg",
        "filepath": str(af),
    }
    result = arun(
        router.multimodalize_message(
            {"role": "user", "content": "@audio:abc123"}
        )
    )
    assert result["content"][0]["input_audio"]["format"] == "mp3"


def test_audio_xwav_maps_to_wav(router, tmp_path):
    af = tmp_path / "sound.wav"
    af.write_bytes(b"audio-data")
    router.librarian.structure_db.get_artifact.return_value = {
        "mime_type": "audio/x-wav",
        "filepath": str(af),
    }
    result = arun(
        router.multimodalize_message(
            {"role": "user", "content": "@audio:abc123"}
        )
    )
    assert result["content"][0]["input_audio"]["format"] == "wav"


def test_audio_wave_maps_to_wav(router, tmp_path):
    af = tmp_path / "sound.wav"
    af.write_bytes(b"audio-data")
    router.librarian.structure_db.get_artifact.return_value = {
        "mime_type": "audio/wave",
        "filepath": str(af),
    }
    result = arun(
        router.multimodalize_message(
            {"role": "user", "content": "@audio:abc123"}
        )
    )
    assert result["content"][0]["input_audio"]["format"] == "wav"


# --- text surrounding tokens ---


def test_text_before_and_after_image_token(router, tmp_path):
    img = tmp_path / "photo.png"
    img.write_bytes(b"data")
    router.librarian.structure_db.get_artifact.return_value = {
        "mime_type": "image/png",
        "filepath": str(img),
    }
    msg = {"role": "user", "content": "Look: @image:abc123 done"}
    result = arun(router.multimodalize_message(msg))
    types = [p["type"] for p in result["content"]]
    assert types == ["text", "image_url", "text"]
    assert result["content"][0]["text"] == "Look: "
    assert result["content"][2]["text"] == " done"


# --- missing artifact ---


def test_missing_artifact_token_only_returns_original(router):
    router.librarian.structure_db.get_artifact.return_value = None
    msg = {"role": "user", "content": "@image:aaaabbbbccdd0011"}
    result = arun(router.multimodalize_message(msg))
    assert result is msg


def test_text_preserved_when_artifact_missing(router):
    router.librarian.structure_db.get_artifact.return_value = None
    msg = {"role": "user", "content": "prefix @image:aaaabbbbccdd0011"}
    result = arun(router.multimodalize_message(msg))
    assert result["content"] == [{"type": "text", "text": "prefix "}]
