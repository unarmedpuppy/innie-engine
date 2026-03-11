"""Fleet health monitor — background polling of server agents."""

import asyncio
import logging
import time
from datetime import datetime

import httpx

from innie.fleet.models import (
    Agent,
    AgentStatus,
    AgentType,
    ChannelHealth,
    FleetStats,
    HeartbeatHealth,
    ProviderHealth,
)

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Periodically checks /health on all SERVER agents and stores rich health data."""

    def __init__(
        self,
        agents: dict[str, Agent],
        interval: int = 30,
        timeout: int = 10,
        failure_threshold: int = 3,
    ):
        self.agents = agents
        self.interval = interval
        self.timeout = timeout
        self.failure_threshold = failure_threshold
        self._task: asyncio.Task | None = None

    async def start(self):
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        await self._check_all()
        while True:
            await asyncio.sleep(self.interval)
            await self._check_all()

    async def _check_all(self):
        tasks = [
            self._check_agent(agent_id)
            for agent_id, agent in self.agents.items()
            if agent.agent_type == AgentType.SERVER
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_agent(self, agent_id: str):
        agent = self.agents.get(agent_id)
        if not agent:
            return

        health = agent.health
        health.last_check = datetime.utcnow().isoformat()

        try:
            start = time.monotonic()
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{agent.endpoint}/health",
                    timeout=self.timeout,
                )
            elapsed_ms = (time.monotonic() - start) * 1000

            if resp.status_code == 200:
                health.status = AgentStatus.ONLINE
                health.consecutive_failures = 0
                health.last_success = health.last_check
                health.response_time_ms = elapsed_ms
                health.error = None
                self._parse_health_data(health, resp.json())
            else:
                self._record_failure(health, f"HTTP {resp.status_code}")

        except httpx.TimeoutException:
            self._record_failure(health, "Timeout")
        except httpx.ConnectError:
            self._record_failure(health, "Connection failed")
        except Exception as e:
            self._record_failure(health, str(e))

    def _parse_health_data(self, health, data: dict) -> None:
        """Extract rich fields from the agent's /health response."""
        health.version = data.get("version")
        health.host = data.get("host")
        health.uptime_seconds = data.get("uptime_seconds")

        # Channels
        raw_channels = data.get("channels", [])
        health.channels = [
            ChannelHealth(
                name=ch.get("name", "unknown"),
                enabled=ch.get("enabled", False),
                connected=ch.get("connected", False),
                base_url=ch.get("base_url"),
                error=ch.get("error"),
            )
            for ch in raw_channels
        ]

        # Heartbeat
        hb = data.get("heartbeat", {})
        health.heartbeat = HeartbeatHealth(
            last_run=hb.get("last_run"),
            status=hb.get("status"),
        )

        # Model provider
        mp = data.get("model_provider", {})
        health.model_provider = ProviderHealth(
            provider=mp.get("provider"),
            reachable=mp.get("reachable", False),
            latency_ms=mp.get("latency_ms"),
            error=mp.get("error"),
        )

    def _record_failure(self, health, error: str):
        health.consecutive_failures += 1
        health.error = error
        if health.consecutive_failures >= self.failure_threshold:
            health.status = AgentStatus.OFFLINE
        else:
            health.status = AgentStatus.DEGRADED

    async def check_now(self, agent_id: str):
        """Force immediate health check on a specific agent."""
        await self._check_agent(agent_id)

    def get_stats(self) -> FleetStats:
        stats = FleetStats()
        response_times = []

        for agent in self.agents.values():
            if agent.agent_type != AgentType.SERVER:
                continue

            stats.total_agents += 1
            s = agent.health.status

            if s == AgentStatus.ONLINE:
                stats.online_count += 1
                if agent.health.response_time_ms is not None:
                    response_times.append(agent.health.response_time_ms)
            elif s == AgentStatus.OFFLINE:
                stats.offline_count += 1
            elif s == AgentStatus.DEGRADED:
                stats.degraded_count += 1
            else:
                stats.unknown_count += 1

            if agent.expected_online:
                stats.expected_online_count += 1
                if s in (AgentStatus.OFFLINE, AgentStatus.UNKNOWN):
                    stats.unexpected_offline_count += 1

        if response_times:
            stats.avg_response_time_ms = sum(response_times) / len(response_times)

        stats.last_updated = datetime.utcnow().isoformat()
        return stats
