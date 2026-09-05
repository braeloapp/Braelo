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

from admin_panel.api.admin import (
    AllUsers,
    ActiveUsers,
    AdminMe,
    AllAppFeedback,
    AllFeedback,
    AllNotifications,
    ReportedUsers,
    SendAdminNotification,
    DeleteAdminNotification,
    AdminBanner,
)
from admin_panel.api.collections import AdminMongoCollections
from users.api import (
    FetchBusinesses,
    DeactivateBusiness,
    UpdateBusiness,
    SignUpWithEmail,
    DeactivateUser,
    LoginWithEmail,
    UpdateProfile,
    FetchListings,
    BusinessBanner,
)

from listings.api import (
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
    SavedListing,
    UserListing,
    DeleteListing,
    FlipListingStatus,
)

urlpatterns = [
    # MongoDB collection names (admin tools); with/without trailing slash
    path('collections/', AdminMongoCollections.as_view()),
    path('collections', AdminMongoCollections.as_view()),
    # Active users only (some admin UIs call this path)
    path('users/active/', ActiveUsers.as_view()),
    path('users/active', ActiveUsers.as_view()),
    # Update api's
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
    path('me', AdminMe.as_view()),
    path('feedback', AllAppFeedback.as_view()),
    # All users fetch to admin
    path('users', AllUsers.as_view()),
    # admin adding banner
    path('banner', AdminBanner.as_view()),
    # Report an issue to admin
    path('support', AllFeedback.as_view()),
    # Get user all listings for Admin
    path('user/all', UserListing.as_view()),
    # Admin Login
    path('login', LoginWithEmail.as_view()),
    # Delete Listings
    path('delete', DeleteListing.as_view()),
    # Flip listing active/inactive (staff/superuser; any owner's listing)
    path('listing/flip/status', FlipListingStatus.as_view()),
    # Get saved listings for Admin
    path('get-save', SavedListing.as_view()),
    # Account creation by admin
    path('signup', SignUpWithEmail.as_view()),
    # Fetch all business
    path('business', FetchBusinesses.as_view()),
    # Update User
    path('user/update', UpdateProfile.as_view()),
    # Action taken by admin, and get method for getting all reports
    path('report/action', ReportedUsers.as_view()),
    # Read notifications
    path('notificatons', AllNotifications.as_view()),
    # Update a business
    path('business/update', UpdateBusiness.as_view()),
    # Deactivate a user
    path('user/deactivate', DeactivateUser.as_view()),
    # Deleting business banner
    path('business/banner/delete', BusinessBanner.as_view()),
    # Update banner
    path('business/banner/update', BusinessBanner.as_view()),
    # Fetch Business Listings for admin
    path('business/fetch/listings', FetchListings.as_view()),
    # Delete a business
    path('business/deactivate', DeactivateBusiness.as_view()),
    # Send Admin notification
    path('notification/send', SendAdminNotification.as_view()),
    # Delete notification by id
    path('notification/delete', DeleteAdminNotification.as_view()),
]
