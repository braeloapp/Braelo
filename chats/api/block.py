'''User-level block / unblock API.'''

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from chats.services import assert_user_can_chat, block_user, unblock_user
from helpers import handle_exceptions, response


def _parse_block_flag(raw):
    if raw is None:
        raise ValidationError({'block': 'Must provide block status.'})
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().lower()
    if value in ('true', '1', 'yes'):
        return True
    if value in ('false', '0', 'no'):
        return False
    raise ValidationError(
        {'block': 'Invalid block status, must be true or false.'}
    )


class BlockUserApi(APIView):
    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def post(self, request):
        assert_user_can_chat(request.user)
        target_id = request.data.get('user_id')
        if target_id is None:
            raise ValidationError({'user_id': 'user_id is required.'})
        should_block = _parse_block_flag(request.data.get('block'))
        if should_block:
            block_user(request.user.id, target_id)
            return response(
                status=status.HTTP_200_OK,
                message='User blocked',
                data={},
            )
        unblock_user(request.user.id, target_id)
        return response(
            status=status.HTTP_200_OK,
            message='User unblocked',
            data={},
        )
