'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
End points registry file.
---------------------------------------------------
'''

from . import views
from django.urls import path

from .api.devices import SaveDeviceToken
from .api.user_interest import InterestListCreateView
from .api import (
    LoginWithEmail,
    VerifyOTP,
    SignUpWithEmail,
    LoginAuth,
    TokenRefresh,
    ForgotPassword,
    ChangePassword,
    Logout,
    CreatePassword,
    UpdateProfile,
    UserProfile,
    AboutUser,
    DeactivateUser,
    PublicProfile,
    FlipUserStatus,
    BusinessDashboard,
    BussinessListing,
    FetchBusinesses,
    ScanBusinessQR,
    DeactivateBusiness,
    FetchListings,
    UpdateBusiness,
    Activate_Business,
    FetchSingleBusiness,
    ExploreBusiness,
    BusinessBanner,
)

# todo import from separate files.

urlpatterns = [
    # Testing
    path('', views.sign_in, name='sign_in'),
    # Login end points
    path('login/email', LoginWithEmail.as_view()),
    # Verify otp
    path('verifyotp', VerifyOTP.as_view()),
    # Sign up endpoints
    path('signup/email', SignUpWithEmail.as_view()),
    # Sign_up/Login [Google, Apple, Phone]
    path('login', LoginAuth.as_view()),
    # Refresh token
    path('token/refresh', TokenRefresh.as_view()),
    # Forgot password
    path('forgot/password', ForgotPassword.as_view()),
    # Change password
    path('change/password', ChangePassword.as_view()),
    # Create new password
    path('new/password', CreatePassword.as_view()),
    # Logout
    path('api/logout', Logout.as_view()),
    path('interests', InterestListCreateView.as_view()),
    # Update Profile
    path('update/profile', UpdateProfile.as_view()),
    path('user/profile', UserProfile.as_view()),
    # about user
    path('user/about', AboutUser.as_view()),
    # Delete
    path('user/delete', DeactivateUser.as_view()),
    # Public Profile
    path('public-profile', PublicProfile.as_view()),
    # Flip User Status
    path('user/flip-status', FlipUserStatus.as_view()),
    # Add device Token
    path('device/token', SaveDeviceToken.as_view()),
    # Business Dashboard
    path('business/dashboard', BusinessDashboard.as_view()),
    # Business Lisitng (with and without trailing slash so POST is not redirected and Authorization is preserved)
    path('business/', BussinessListing.as_view()),
    path('business', BussinessListing.as_view()),
    # fetch all Business
    path('business/fetch', FetchBusinesses.as_view()),
    # Deactive Business
    path('business/deactivate', DeactivateBusiness.as_view()),
    # Fetch Listings of Business
    path('business/listings', FetchListings.as_view()),
    # Activate business
    path('business/activate', Activate_Business.as_view()),
    # Update business
    path('business/update', UpdateBusiness.as_view()),
    # Fetch Single business
    path('business/fetch-single', FetchSingleBusiness.as_view()),
    # Explore Business
    path('business/explore', ExploreBusiness.as_view()),
    # Business Banners
    path('business/banner', BusinessBanner.as_view()),
    # Fetch Business
    path('business/<str:pk>', ScanBusinessQR.as_view()),
]
