'''Admin monitoring for the Ellu / chatbot stack (health + learning gaps).'''

from django.conf import settings
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView
from rest_framework import status

from helpers import handle_exceptions, response


class AdminAiOps(APIView):
    permission_classes = [IsAdminUser]

    @handle_exceptions
    def get(self, request):
        days = 7
        try:
            days = max(1, min(int(request.query_params.get('days', 7)), 90))
        except (TypeError, ValueError):
            days = 7

        health = {
            'status': 'ok',
            'llm_configured': bool(getattr(settings, 'OPENAI_API_KEY', None)),
            'use_mongo': bool(getattr(settings, 'USE_MONGO', False)),
        }

        knowledge = {}
        try:
            if getattr(settings, 'USE_MONGO', False):
                from chatbot.mongo_db import get_db

                db = get_db()
                knowledge = {
                    'source': 'mongodb',
                    'total': db.knowledge_base.count_documents({}),
                    'with_embeddings': db.knowledge_base.count_documents(
                        {'embedding': {'$exists': True, '$ne': None}}
                    ),
                }
            else:
                from chatbot.models import KnowledgeBase

                knowledge = {
                    'source': 'postgres',
                    'total': KnowledgeBase.objects.count(),
                    'with_embeddings': KnowledgeBase.objects.filter(
                        embedding_json__isnull=False
                    ).count(),
                }
        except Exception as exc:
            knowledge = {'error': str(exc)}

        gaps = {}
        try:
            from chatbot.agents.learning_agent import LearningAgent

            gaps = LearningAgent().get_gap_summary(days=days) or {}
        except Exception as exc:
            gaps = {'error': str(exc), 'total_gaps': 0}

        return response(
            status=status.HTTP_200_OK,
            message='AI ops snapshot',
            data={
                'health': health,
                'knowledge': knowledge,
                'learning_gaps': gaps,
                'days': days,
            },
        )
