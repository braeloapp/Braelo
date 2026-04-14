"""
KB + RAG orchestration lives in ``chatbot.chat_flow.process_message`` (Tier 1c / Tier 2).
Routing uses ``chatbot.agents.intent_classifier.should_preempt_directory_for_knowledge``.
LLM calls use Éllu base prompts from ``chatbot.ellu.persona.get_system_prompt``.
"""

from __future__ import annotations

from chatbot.ellu.persona import get_system_prompt

__all__ = ["get_system_prompt"]
