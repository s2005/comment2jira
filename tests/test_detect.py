"""Tests for comment2jira deployment detection."""

from typing import Any

import pytest

from comment2jira.detect import (
    DEPLOYMENT_CLOUD,
    DEPLOYMENT_DC,
    clear_deployment_cache,
    deployment_from_server_info,
    detect_deployment,
)


class FakeServerInfoClient:
    """Minimal fake implementing the ServerInfoSource protocol."""

    def __init__(self, info: dict[str, Any]) -> None:
        self.info = info
        self.calls = 0

    async def get_server_info(self) -> dict[str, Any]:
        self.calls += 1
        return self.info


class TestDeploymentFromServerInfo:
    @pytest.mark.unit
    def test_cloud(self) -> None:
        assert deployment_from_server_info({"deploymentType": "Cloud"}) == DEPLOYMENT_CLOUD

    @pytest.mark.unit
    def test_server_maps_to_dc(self) -> None:
        assert deployment_from_server_info({"deploymentType": "Server"}) == DEPLOYMENT_DC

    @pytest.mark.unit
    def test_missing_maps_to_dc(self) -> None:
        assert deployment_from_server_info({}) == DEPLOYMENT_DC


class TestDetectDeployment:
    def setup_method(self) -> None:
        clear_deployment_cache()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_override_wins_without_call(self) -> None:
        client = FakeServerInfoClient({})
        result = await detect_deployment(client, override="dc")
        assert result == DEPLOYMENT_DC
        assert client.calls == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cloud_detection(self) -> None:
        client = FakeServerInfoClient({"deploymentType": "Cloud"})
        result = await detect_deployment(client)
        assert result == DEPLOYMENT_CLOUD

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_result_cached_per_host(self) -> None:
        client = FakeServerInfoClient({"deploymentType": "Cloud"})
        first = await detect_deployment(client, host="jira.example.com")
        second = await detect_deployment(client, host="jira.example.com")
        assert first == second == DEPLOYMENT_CLOUD
        assert client.calls == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cache_keyed_by_host(self) -> None:
        client = FakeServerInfoClient({"deploymentType": "Cloud"})
        await detect_deployment(client, host="one.example.com")
        await detect_deployment(client, host="two.example.com")
        assert client.calls == 2
