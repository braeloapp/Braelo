"""
Knowledge-style answers (KB hybrid search, exact KB, RAG, optional directory appendix)
are implemented in ``chatbot.chat_flow.process_message`` (Tier 1c and Tier 2).

Routing that skips directory-first for guidance-style turns lives in
``chatbot.agents.intent_classifier.should_preempt_directory_for_knowledge``.
This module is a stable import point for future extraction without duplicating gpt_service APIs.
"""

from __future__ import annotations
