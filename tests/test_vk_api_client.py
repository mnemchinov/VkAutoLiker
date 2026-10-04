from unittest.mock import MagicMock, patch

import pytest
import requests

from vk_api import CaptchaError, VKApiClient, VKApiError


class TestVKApiClient:
    def test_call_success(self, mock_config, mock_logger):
        client = VKApiClient(mock_config, mock_logger)

        mock_response = MagicMock()
        mock_response.json.return_value = {"response": {"items": [1, 2, 3]}}
        with patch("vk_api.vk_api_client.requests.get", return_value=mock_response):
            result = client.call("newsfeed.search", {"q": "test"})

        assert result == {"items": [1, 2, 3]}

    def test_call_error_code_6_retries_then_success(self, mock_config, mock_logger):
        """Error 6 — ретрай в цикле, успех на 2-й попытке."""
        client = VKApiClient(mock_config, mock_logger)

        error_response = MagicMock()
        error_response.json.return_value = {
            "error": {"error_code": 6, "error_msg": "Too many requests"}
        }
        success_response = MagicMock()
        success_response.json.return_value = {"response": {"ok": True}}

        with patch(
            "vk_api.vk_api_client.requests.get", side_effect=[error_response, success_response]
        ):
            with patch("vk_api.vk_api_client.time.sleep"):
                result = client.call("newsfeed.search", {"q": "test"})

        assert result == {"ok": True}

    def test_call_error_code_6_exhausts_retries(self, mock_config, mock_logger):
        """Error 6 — исчерпаны все 3 попытки, выбрасывает VKApiError."""
        client = VKApiClient(mock_config, mock_logger)

        error_response = MagicMock()
        error_response.json.return_value = {
            "error": {"error_code": 6, "error_msg": "Too many requests"}
        }

        with patch("vk_api.vk_api_client.requests.get", return_value=error_response) as mock_get:
            with patch("vk_api.vk_api_client.time.sleep"):
                with pytest.raises(VKApiError) as exc_info:
                    client.call("newsfeed.search", {"q": "test"})

        assert exc_info.value.code == 6
        assert mock_get.call_count == 3

    def test_call_error_code_14_raises_captcha(self, mock_config, mock_logger):
        client = VKApiClient(mock_config, mock_logger)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "error": {"error_code": 14, "error_msg": "Captcha needed"}
        }

        with patch("vk_api.vk_api_client.requests.get", return_value=mock_response):
            with pytest.raises(CaptchaError):
                client.call("newsfeed.search", {"q": "test"})

    def test_call_other_error_raises_vkapierror(self, mock_config, mock_logger):
        client = VKApiClient(mock_config, mock_logger)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "error": {"error_code": 15, "error_msg": "Access denied"}
        }

        with patch("vk_api.vk_api_client.requests.get", return_value=mock_response):
            with pytest.raises(VKApiError) as exc_info:
                client.call("newsfeed.search", {"q": "test"})

        assert exc_info.value.code == 15

    def test_call_network_error_retries_then_success(self, mock_config, mock_logger):
        """Сетевая ошибка (ConnectionError) — ретрай, успех на 2-й попытке."""
        client = VKApiClient(mock_config, mock_logger)

        success_response = MagicMock()
        success_response.json.return_value = {"response": {"ok": True}}

        with patch(
            "vk_api.vk_api_client.requests.get",
            side_effect=[
                requests.exceptions.ConnectionError("No connection"),
                success_response,
            ],
        ):
            with patch("vk_api.vk_api_client.time.sleep"):
                result = client.call("newsfeed.search", {"q": "test"})

        assert result == {"ok": True}

    def test_call_network_error_exhausts_retries(self, mock_config, mock_logger):
        """Сетевая ошибка — исчерпаны все 3 попытки, выбрасывает VKApiError."""
        client = VKApiClient(mock_config, mock_logger)

        with patch(
            "vk_api.vk_api_client.requests.get",
            side_effect=requests.exceptions.ConnectionError("No connection"),
        ):
            with patch("vk_api.vk_api_client.time.sleep"):
                with pytest.raises(VKApiError) as exc_info:
                    client.call("newsfeed.search", {"q": "test"})

        assert exc_info.value.code == 0

    def test_json_decode_error_retries_then_success(self, mock_config, mock_logger):
        """Не-JSON ответ (502/Cloudflare HTML) — ретрай, успех на 2-й попытке."""
        client = VKApiClient(mock_config, mock_logger)

        success_response = MagicMock()
        success_response.json.return_value = {"response": {"ok": True}}

        bad_response = MagicMock()
        bad_response.json.side_effect = requests.exceptions.JSONDecodeError(
            "Expecting value", "", 0
        )

        with patch(
            "vk_api.vk_api_client.requests.get", side_effect=[bad_response, success_response]
        ):
            with patch("vk_api.vk_api_client.time.sleep"):
                result = client.call("newsfeed.search", {"q": "test"})

        assert result == {"ok": True}

    def test_json_decode_error_exhausts_retries(self, mock_config, mock_logger):
        """Не-JSON ответ — исчерпаны все 3 попытки, выбрасывает VKApiError."""
        client = VKApiClient(mock_config, mock_logger)

        bad_response = MagicMock()
        bad_response.json.side_effect = requests.exceptions.JSONDecodeError(
            "Expecting value", "", 0
        )

        with patch("vk_api.vk_api_client.requests.get", return_value=bad_response) as mock_get:
            with patch("vk_api.vk_api_client.time.sleep"):
                with pytest.raises(VKApiError) as exc_info:
                    client.call("newsfeed.search", {"q": "test"})

        assert exc_info.value.code == 0
        assert mock_get.call_count == 3

    def test_rate_limit_applied(self, mock_config, mock_logger):
        client = VKApiClient(mock_config, mock_logger)

        mock_response = MagicMock()
        mock_response.json.return_value = {"response": {}}

        with patch("vk_api.vk_api_client.requests.get", return_value=mock_response) as mock_get:
            with patch("vk_api.vk_api_client.time.sleep") as mock_sleep:
                client.call("test.method")
                client.call("test.method")

        assert mock_get.call_count == 2
        assert mock_sleep.call_count >= 1
