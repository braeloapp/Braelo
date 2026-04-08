"""
Ranking Agent — orders directory results.

Currently relies on get_top_businesses / discovery ordering; this layer is a
stable hook for future relevance, distance, or sponsored weight tuning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

AGENT_LOG = "[BraeloAgent:Ranking]"


@dataclass
class RankingOutput:
    businesses: list
    strategy: str
    meta: dict = field(default_factory=dict)


class RankingAgent:
    def run(
        self,
        businesses: list | None,
        *,
        message: str = "",
        user_lat=None,
        user_lon=None,
    ) -> RankingOutput:
        items = list(businesses or [])
        strategy = "pipeline_default"
        if getattr(django_settings, "BRAELO_AGENT_DEBUG", True):
            logger.info(
                "%s strategy=%s n_in=%s n_out=%s (hook for future distance/sponsor scoring)",
                AGENT_LOG,
                strategy,
                len(items),
                len(items),
            )
        return RankingOutput(businesses=items, strategy=strategy, meta={})
