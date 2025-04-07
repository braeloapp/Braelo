'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------
Description:
Serializer file for users based endpoints
---------------------------------------------------
'''

from users.serializers.login import (
    PhoneLogin,
    TokenBlacklistSerializer,
    EmailLogin,
)
from users.serializers.signup import EmailSignup

from users.serializers.password import (
    ChangePasswordSerializer,
    CreatePasswordSerializer,
    VerifyOtpSerializer,
    ForgotPasswordSerializer,
)
from users.serializers.profile import (
    InterestSerializer,
    UpdateProfileSerializer,
    UserProfileSerializer,
)
