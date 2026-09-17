'''Safety records: user blocks (NOT a chat UI).'''

from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView
from rest_framework import status

from helpers import handle_exceptions, response
from chats.models import BlockedUser


class AdminBlockedUsers(APIView):
    permission_classes = [IsAdminUser]

    @handle_exceptions
    def get(self, request):
        try:
            page = max(int(request.query_params.get('page', 1)), 1)
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = min(max(int(request.query_params.get('page_size', 25)), 1), 100)
        except (TypeError, ValueError):
            page_size = 25

        qs = BlockedUser.objects.all().order_by('-created_at')
        blocker = (request.query_params.get('blocker_id') or '').strip()
        blocked = (request.query_params.get('blocked_id') or '').strip()
        if blocker:
            qs = qs.filter(blocker_id=blocker)
        if blocked:
            qs = qs.filter(blocked_id=blocked)

        total = qs.count()
        start = (page - 1) * page_size
        rows = list(qs.skip(start).limit(page_size))
        results = [
            {
                'id': str(row.id),
                'blocker_id': row.blocker_id,
                'blocked_id': row.blocked_id,
                'created_at': row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
        return response(
            status=status.HTTP_200_OK,
            message='Blocked user records fetched',
            data={
                'count': total,
                'page': page,
                'page_size': page_size,
                'results': results,
            },
        )
