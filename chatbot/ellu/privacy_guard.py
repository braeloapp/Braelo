"""
Privacy Guard
Checks every incoming message for privacy violations.
If user sends sensitive data, Éllu acknowledges and ignores it.
If Éllu's response contains forbidden data requests, blocks it.
"""

import re
import logging
from chatbot.ellu.persona import (
    FORBIDDEN_DATA_REQUESTS,
    SENSITIVE_TOPIC_KEYWORDS,
    get_phrase,
)

logger = logging.getLogger(__name__)


class PrivacyGuard:

    def check_incoming_message(
        self, message: str, detected_language: str
    ) -> tuple[str, str]:
        """
        Checks if user sent sensitive data we should not store.
        Returns a tuple: (action, response_message)
        Action is either "BLOCK" or "PASS".
        """
        msg_lower = message.lower()

        # SSN pattern: XXX-XX-XXXX
        if re.search(r'\b\d{3}-\d{2}-\d{4}\b', message):
            logger.warning("[PrivacyGuard] SSN pattern detected — ignoring")
            return "BLOCK", get_phrase("no_ssn", detected_language)

        # Credit card pattern
        if re.search(r'\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b', message):
            logger.warning("[PrivacyGuard] Credit card pattern detected")
            return "BLOCK", get_phrase("no_ssn", detected_language)

        # Forbidden keywords
        for keyword in FORBIDDEN_DATA_REQUESTS:
            if keyword in msg_lower:
                logger.info(f"[PrivacyGuard] Forbidden keyword: {keyword}")
                return "BLOCK", get_phrase("no_ssn", detected_language)

        return "PASS", ""

    def is_sensitive_topic(
        self, message: str
    ) -> bool:
        """
        Returns True if message is asking for health/legal/
        financial ADVICE (not just finding professionals).
        """
        msg_lower = message.lower()
        return any(
            kw in msg_lower
            for kw in SENSITIVE_TOPIC_KEYWORDS
        )

    def check_outgoing_response(
        self, response: str
    ) -> bool:
        """
        Returns True if response is safe to send.
        Blocks if response accidentally contains forbidden data.
        Short tokens (itin, pin, …) use word-boundary matching so words like "waiting"
        do not false-positive on substring "itin".
        """
        resp_lower = response.lower()
        short_whole_word = frozenset(
            {"itin", "ein", "ssn", "pin", "cvv"}
        )
        for keyword in FORBIDDEN_DATA_REQUESTS:
            kw = (keyword or "").strip().lower()
            if not kw:
                continue
            if kw in short_whole_word:
                if re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", resp_lower):
                    logger.error(
                        "[PrivacyGuard] BLOCKED outgoing: contains whole-word '%s'",
                        kw,
                    )
                    return False
            elif kw in resp_lower:
                logger.error(
                    "[PrivacyGuard] BLOCKED outgoing: contains '%s'",
                    kw,
                )
                return False
        return True
