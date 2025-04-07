'''
---------------------------------------------------
Project:        Braelo
Date:           March 20, 2025
Author:         Faizan
---------------------------------------------------

Description:
admin_panel endpoints.
---------------------------------------------------
'''

from django.urls import path
from users.api import DeactivateUser, LoginWithEmail, UpdateProfile


from admin_panel.api.admin import (
    AllUsers,
    AllFeedback,
    AllNotifications,
    ReportedUsers,
    SendAdminNotification,
    AdminBanner,
)
from users.api.business import (
    FetchBusinesses,
    DeactivateBusiness,
    UpdateBusiness,
)
from users.api.signup import SignUpWithEmail
from listings.api.update_listing import (
    RealEstateUpdateAPI,
    VehicleUpdateAPI,
    ElectronicsUpdateAPI,
    EventsUpdateAPI,
    FashionUpdateAPI,
    JobsUpdateAPI,
    ServicesUpdateAPI,
    SportsHobbyUpdateAPI,
    KidsUpdateAPI,
    FurnitureUpdateAPI,
)

from listings.api.saved_listing import DeleteListing


urlpatterns = [
    # All users fetch to admin
    path('users', AllUsers.as_view(), name='all-users'),
    # Deactivate a user
    path('user/deactivate', DeactivateUser.as_view(), name='deactivate-user'),
    # Update User
    path('user/update', UpdateProfile.as_view(), name='update-user'),
    # Report an issue to admin
    path('support', AllFeedback.as_view(), name='support'),
    # Action taken by admin, and get method for getting all reports
    path('report/action', ReportedUsers.as_view(), name='action'),
    # Account creation by admin
    path('signup', SignUpWithEmail.as_view(), name='admin-signup'),
    # Admin Login
    path('login', LoginWithEmail.as_view(), name='admin-panel-login'),
    # Fetch all business
    path('business', FetchBusinesses.as_view(), name='fetch-all-business'),
    # Read notifications
    path('notificatons', AllNotifications.as_view(), name='read-notifications'),
    # Delete Listings
    path('delete', DeleteListing.as_view(), name='delete-listings'),
    # admin adding banner
    path('banner', AdminBanner.as_view(), name='admin-adding-banner'),
    # Delete a business
    path(
        'business/deactivate',
        DeactivateBusiness.as_view(),
        name='business-deactivate',
    ),
    # Update a business
    path('business/update', UpdateBusiness.as_view(), name='update-business'),
    # Send Admin notification
    path(
        'notification/send',
        SendAdminNotification.as_view(),
        name='send-notification',
    ),
    # Update api
    path('jobs/<str:pk>', JobsUpdateAPI.as_view()),
    path('kids/<str:pk>', KidsUpdateAPI.as_view()),
    path('events/<str:pk>', EventsUpdateAPI.as_view()),
    path('fashion/<str:pk>', FashionUpdateAPI.as_view()),
    path('vehicles/<str:pk>', VehicleUpdateAPI.as_view()),
    path('services/<str:pk>', ServicesUpdateAPI.as_view()),
    path('furniture/<str:pk>', FurnitureUpdateAPI.as_view()),
    path('realestate/<str:pk>', RealEstateUpdateAPI.as_view()),
    path('electronics/<str:pk>', ElectronicsUpdateAPI.as_view()),
    path('sportshobby/<str:pk>', SportsHobbyUpdateAPI.as_view()),
]
