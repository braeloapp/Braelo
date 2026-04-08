"""
Validation Agent — lightweight checks before returning directory intro + payloads.
Does not mutate legal/compliance text; logs issues for ops.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

AGENT_LOG = "[BraeloAgent:Validation]"


@dataclass
class ValidationOutput:
    is_valid: bool
    issues: list
    passed_checks: list
    source_verified: bool
    meta: dict = field(default_factory=dict)


class ValidationAgent:
    KNOWN_SOURCES = frozenset(
        {
            "braelo_directory",
            "braelo_directory_mongo",
            "braelo_directory_sql",
            "google_places",
            "knowledge_base",
            "llm",
            "casual",
            "llm_fallback",
        }
    )

    def run(
        self,
        *,
        response_text: str,
        source: str,
        detected_language: str,
        original_message: str,
        businesses_count: int,
    ) -> ValidationOutput:
        issues = []
        passed = []

        if not (response_text or "").strip():
            issues.append("empty_response_text")
        else:
            passed.append("non_empty_text")

        if len(response_text or "") < 5 and businesses_count > 0:
            issues.append("intro_suspiciously_short_with_results")
        elif businesses_count > 0:
            passed.append("intro_length_ok_with_results")

        source_verified = source in {
            "braelo_directory",
            "braelo_directory_mongo",
            "braelo_directory_sql",
            "knowledge_base",
        }
        if source not in self.KNOWN_SOURCES:
            issues.append(f"unknown_source:{source}")
        else:
            passed.append("source_known")

        if detected_language not in ("en", "es", "pt"):
            issues.append("unexpected_language_code")
        else:
            passed.append("language_code_ok")

        valid = len(issues) == 0
        out = ValidationOutput(
            is_valid=valid,
            issues=issues,
            passed_checks=passed,
            source_verified=source_verified,
        )
        if getattr(django_settings, "BRAELO_AGENT_DEBUG", True):
            logger.info(
                "%s valid=%s source=%s businesses=%s issues=%s passed=%s",
                AGENT_LOG,
                valid,
                source,
                businesses_count,
                issues,
                passed,
            )
        return out
