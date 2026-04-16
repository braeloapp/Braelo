"""
Éllu Response Formatter
Formats ALL outgoing responses in Éllu's voice and style.
Adds badges, labels, rankings, and soft CTAs.
Every response the user sees passes through here.
"""

import logging
from chatbot.ellu.persona import get_phrase, PHRASES

logger = logging.getLogger(__name__)

# Directory rows from Mongo/SQL do not include a source field; tag here so curated vs external works.
BRAELO_DIRECTORY_SOURCE = "braelo_directory"


def tag_businesses_as_braelo_directory(businesses: list | None) -> list:
    """Ensure Mongo/SQL listing dicts are marked for Éllu curated formatting (does not touch business_matching)."""
    if not businesses:
        return []
    out = []
    for b in businesses:
        if isinstance(b, dict):
            nb = dict(b)
            if not nb.get("source"):
                nb["source"] = BRAELO_DIRECTORY_SOURCE
            out.append(nb)
        else:
            out.append(b)
    return out


class ElluResponseFormatter:
    """
    Takes raw data (businesses, KB answers, LLM text) and 
    formats it as Éllu's response following all playbook rules:
    - Braelo Curated badge on internal results
    - External label on Google Places results
    - Max 5 internal / max 3 external
    - Ranking: sponsored → proximity → clicks → contacts → rating
    - Soft CTA at end
    - User's name if known
    - Correct language
    """

    def format_business_results(
        self,
        businesses: list,
        source: str,
        detected_language: str,
        user_name: str = "",
        location_context: str = "",
        show_cta: bool = True,
        *,
        include_curated_lead: bool = True,
    ) -> str:
        """
        Formats business search results in Éllu's style.
        source: "braelo_directory" | "google_places" | "mixed"
        """
        lang = detected_language
        phrases = PHRASES.get(lang, PHRASES["en"])

        if not businesses:
            return self.format_no_results(
                detected_language, location_context
            )

        # ── Rank businesses per playbook order ───────────────────
        ranked = self._rank_businesses(businesses, source)

        # ── Split internal vs external ────────────────────────────
        internal = [
            b for b in ranked
            if b.get("source") == "braelo_directory"
        ][:5]   # max 5 internal
        external = [
            b for b in ranked
            if b.get("source") != "braelo_directory"
        ][:3]   # max 3 external

        lines = []

        # ── Internal results with Braelo Curated badge ────────────
        if internal:
            badge = phrases["braelo_curated_badge"]
            if include_curated_lead:
                lines.append(
                    get_phrase("found_curated", lang)
                )
                lines.append("")
            for i, biz in enumerate(internal, 1):
                lines.extend(
                    self._format_single_business(
                        biz, i, badge, lang, is_sponsored=(
                            biz.get("is_sponsored", False)
                        )
                    )
                )

        # ── External results with External label ──────────────────
        if external:
            lines.append("")
            lines.append(
                get_phrase("external_label", lang)
            )
            lines.append("")
            ext_badge = phrases["external_badge"]
            for i, biz in enumerate(external, 1):
                lines.extend(
                    self._format_single_business(
                        biz, i, ext_badge, lang,
                        is_external=True
                    )
                )

        # ── Soft CTA ─────────────────────────────────────────────
        if show_cta:
            lines.append("")
            lines.append(get_phrase("ask_next", lang))

        return "\n".join(lines)

    def format_no_results(
        self,
        detected_language: str,
        location_context: str = "",
        log_demand: bool = True,
    ) -> str:
        """
        Formats the "no results" response per playbook.
        Always offers external options, never dead-ends.
        """
        lang = detected_language
        lines = [get_phrase("no_curated", lang)]
        if log_demand:
            lines.append("")
            lines.append(get_phrase("demand_logged", lang))
        lines.append("")
        lines.append(get_phrase("ask_adjust", lang))
        return "\n".join(lines)

    def format_knowledge_response(
        self,
        kb_text: str,
        detected_language: str,
        appended_businesses: list = None,
        user_name: str = "",
    ) -> str:
        """
        Formats a knowledge/guidance response in Éllu's voice.
        Optionally appends relevant business suggestions.
        """
        lang = detected_language
        lines = [kb_text]

        if appended_businesses:
            lines.append("")
            badge = PHRASES.get(
                lang, PHRASES["en"]
            )["braelo_curated_badge"]
            lines.append(
                get_phrase("found_curated", lang)
            )
            for i, biz in enumerate(appended_businesses[:3], 1):
                lines.extend(
                    self._format_single_business(
                        biz, i, badge, lang
                    )
                )

        lines.append("")
        lines.append(get_phrase("ask_next", lang))
        return "\n".join(lines)

    def format_clarification(
        self,
        question: str,
        detected_language: str,
    ) -> str:
        """Formats a clarification question in Éllu's voice."""
        return question

    def format_sensitive_topic(
        self, detected_language: str
    ) -> str:
        """
        Formats the sensitive topic redirect per playbook.
        Used for health/legal/financial advice requests.
        """
        return get_phrase("sensitive_topic", detected_language)

    def format_welcome(
        self,
        detected_language: str,
        user_name: str = "",
        is_returning: bool = False,
    ) -> str:
        """Formats welcome message."""
        lang = detected_language
        if is_returning and user_name:
            return get_phrase(
                "welcome_returning", lang,
                name_part=f", {user_name}"
            )
        elif is_returning:
            return get_phrase(
                "welcome_returning", lang, name_part=""
            )
        return get_phrase("welcome_new", lang)

    def _rank_businesses(
        self, businesses: list, source: str
    ) -> list:
        """
        Ranks businesses per playbook order:
        1. Sponsored (is_sponsored=True)
        2. Proximity (has lat/lng)
        3. Click rate (impressions_used)
        4. Contact rate (contact_count)
        5. Rating
        """
        def rank_key(b):
            sponsored = 0 if b.get("is_sponsored") else 1
            has_location = 0 if (
                b.get("latitude") and b.get("longitude")
            ) else 1
            clicks = -(b.get("impressions_used", 0))
            contacts = -(b.get("contact_count", 0))
            rating = -(b.get("rating") or 0)
            return (sponsored, has_location, clicks,
                    contacts, rating)

        return sorted(businesses, key=rank_key)

    def _format_single_business(
        self,
        biz: dict,
        index: int,
        badge: str,
        lang: str,
        is_sponsored: bool = False,
        is_external: bool = False,
    ) -> list:
        """Formats one business entry in Éllu's style."""
        phrases = PHRASES.get(lang, PHRASES["en"])
        lines = []

        name = biz.get("name", "")
        city = biz.get("city", "")
        state = biz.get("state", "")
        phone = biz.get("phone", "")
        whatsapp = biz.get("whatsapp_url", "")
        email = biz.get("email", "")
        social = biz.get("social_url", "")
        maps_url = biz.get("maps_url", "")
        subcategory = biz.get("subcategory", "")
        rating = biz.get("rating")
        open_now = biz.get("open_now")

        location_parts = [p for p in [city, state] if p]
        location_str = ", ".join(location_parts)

        # Sponsored label
        sponsored_label = ""
        if is_sponsored:
            sponsored_label = (
                f" [{phrases['sponsored_badge']}]"
            )

        # Main line
        lines.append(
            f"{index}. {name}{sponsored_label} "
            f"[{badge}]"
        )

        if subcategory:
            lines.append(f"   🏷️ {subcategory}")
        if location_str:
            lines.append(f"   📍 {location_str}")
        if rating:
            lines.append(f"   ⭐ {rating}/5")
        if open_now is True:
            open_label = {
                "en": "Open now",
                "pt": "Aberto agora",
                "es": "Abierto ahora"
            }.get(lang, "Open now")
            lines.append(f"   ✅ {open_label}")
        elif open_now is False:
            closed_label = {
                "en": "Closed now",
                "pt": "Fechado agora",
                "es": "Cerrado ahora"
            }.get(lang, "Closed now")
            lines.append(f"   🔴 {closed_label}")
        if phone:
            lines.append(f"   📞 {phone}")
        if whatsapp:
            lines.append(f"   💬 WhatsApp: {whatsapp}")
        if email:
            lines.append(f"   ✉️ {email}")
        if social and not is_external:
            lines.append(f"   🌐 {social}")
        if maps_url:
            lines.append(f"   🗺️ {maps_url}")
        lines.append("")

        return lines
