import pytest


@pytest.mark.live
class TestE2E:
    def test_full_cycle(self, mock_config):
        pytest.skip(
            "Live E2E test requires manual login + real VK post. Run manually with --vk-post=URL"
        )

    def test_login_and_search(self, mock_config):
        pytest.skip(
            "Requires manual browser login. Run: python src/main.py login && python src/main.py test"
        )
