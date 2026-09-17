'''Admin audit log list API.'''

from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView
from rest_framework import status

from helpers import handle_exceptions, response
from admin_panel.models import AdminAuditLog


class AdminAuditLogList(APIView):
    permission_classes = [IsAdminUser]

    @handle_exceptions
    def get(self, request):
        qs = AdminAuditLog.objects.all()
        target_type = (request.query_params.get('target_type') or '').strip()
        target_id = (request.query_params.get('target_id') or '').strip()
        action = (request.query_params.get('action') or '').strip()
        if target_type:
            qs = qs.filter(target_type=target_type)
        if target_id:
            qs = qs.filter(target_id=target_id)
        if action:
            qs = qs.filter(action=action)

        try:
            page = max(int(request.query_params.get('page', 1)), 1)
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = min(max(int(request.query_params.get('page_size', 25)), 1), 100)
        except (TypeError, ValueError):
            page_size = 25

        total = qs.count()
        start = (page - 1) * page_size
        rows = qs[start : start + page_size]
        results = [
            {
                'id': row.id,
                'actor_id': row.actor_id,
                'actor_email': row.actor_email,
                'action': row.action,
                'target_type': row.target_type,
                'target_id': row.target_id,
                'summary': row.summary,
                'reason': row.reason,
                'previous_state': row.previous_state,
                'new_state': row.new_state,
                'metadata': row.metadata,
                'created_at': row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
        return response(
            status=status.HTTP_200_OK,
            message='Audit logs fetched',
            data={
                'count': total,
                'page': page,
                'page_size': page_size,
                'results': results,
            },
        )
