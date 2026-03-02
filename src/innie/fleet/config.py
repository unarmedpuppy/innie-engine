"""Fleet gateway configuration — loads agent registry from YAML."""

import logging
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from innie.fleet.models import AgentConfig

logger = logging.getLogger(__name__)


class HealthCheckConfig(BaseModel):
    interval_seconds: int = 30
    timeout_seconds: int = 10
    failure_threshold: int = 3


class FleetConfig(BaseModel):
    health_check: HealthCheckConfig = Field(default_factory=HealthCheckConfig)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)


def load_fleet_config(config_path: str | None = None) -> FleetConfig:
    """Load fleet config from YAML file."""
    path = config_path or os.environ.get("INNIE_FLEET_CONFIG")

    if not path:
        # Check default locations
        for candidate in [
            Path.cwd() / "fleet.yaml",
            Path.home() / ".innie" / "fleet.yaml",
        ]:
            if candidate.exists():
                path = str(candidate)
                break

    if not path or not Path(path).exists():
        logger.warning("No fleet config found, starting with empty registry")
        return FleetConfig()

    logger.info(f"Loading fleet config from {path}")
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    health_cfg = HealthCheckConfig(**raw.get("health_check", {}))

    agents = {}
    for agent_id, agent_data in raw.get("agents", {}).items():
        try:
            agents[agent_id] = AgentConfig(**agent_data)
        except Exception as e:
            logger.warning(f"Invalid agent config for '{agent_id}': {e}")

    return FleetConfig(health_check=health_cfg, agents=agents)
