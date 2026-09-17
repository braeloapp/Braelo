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
    AdminUserDetail,
    AdminBusinessDetail,
    AllAppFeedback,
    AllFeedback,
    SupportReply,
    AllNotifications,
    ReportedUsers,
    SendAdminNotification,
    DeleteAdminNotification,
    ReadAdminNotification,
    AdminBanner,
)
from admin_panel.api.collections import AdminMongoCollections
from admin_panel.api.statistics import AdminStatistics
from admin_panel.api.taxonomy import AdminTaxonomy
from admin_panel.api.audit import AdminAuditLogList
from admin_panel.api.platform_settings import (
    PlatformSettingsAdmin,
    PlatformSettingsPublic,
)
from admin_panel.api.blocks import AdminBlockedUsers
from admin_panel.api.analytics import AdminAnalyticsOverview
from admin_panel.api.search import AdminGlobalSearch
from admin_panel.api.cms import LegalDocumentAdmin, LegalDocumentPublic
from admin_panel.api.ai_ops import AdminAiOps
from users.api import (
    FetchBusinesses,
    DeactivateBusiness,
    UpdateBusiness,
    SignUpWithEmail,
    DeactivateUser,
    ReactivateUser,
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
    path('statistics/', AdminStatistics.as_view()),
    path('statistics', AdminStatistics.as_view()),
    path('analytics/overview/', AdminAnalyticsOverview.as_view()),
    path('analytics/overview', AdminAnalyticsOverview.as_view()),
    path('search/', AdminGlobalSearch.as_view()),
    path('search', AdminGlobalSearch.as_view()),
    path('ai-ops/', AdminAiOps.as_view()),
    path('ai-ops', AdminAiOps.as_view()),
    path('cms/<str:doc_type>/', LegalDocumentAdmin.as_view()),
    path('cms/<str:doc_type>', LegalDocumentAdmin.as_view()),
    path('legal/<str:doc_type>/', LegalDocumentPublic.as_view()),
    path('legal/<str:doc_type>', LegalDocumentPublic.as_view()),
    path('audit-logs/', AdminAuditLogList.as_view()),
    path('audit-logs', AdminAuditLogList.as_view()),
    path('platform-settings/', PlatformSettingsAdmin.as_view()),
    path('platform-settings', PlatformSettingsAdmin.as_view()),
    path('platform-config/', PlatformSettingsPublic.as_view()),
    path('platform-config', PlatformSettingsPublic.as_view()),
    path('blocks/', AdminBlockedUsers.as_view()),
    path('blocks', AdminBlockedUsers.as_view()),
    # Active users only (some admin UIs call this path)
    path('users/active/', ActiveUsers.as_view()),
    path('users/active', ActiveUsers.as_view()),
    path('users/<int:pk>', AdminUserDetail.as_view()),
    path('users/<int:pk>/', AdminUserDetail.as_view()),
    path('taxonomy/', AdminTaxonomy.as_view()),
    path('taxonomy', AdminTaxonomy.as_view()),
    path('support/search/', AllFeedback.as_view()),
    path('support/search', AllFeedback.as_view()),
    path('support/reply/', SupportReply.as_view()),
    path('support/reply', SupportReply.as_view()),
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
    # Read notifications (typo alias kept for older admin builds)
    path('notifications', AllNotifications.as_view()),
    path('notificatons', AllNotifications.as_view()),
    # Update a business
    path('business/update', UpdateBusiness.as_view()),
    # Deactivate a user
    path('user/deactivate', DeactivateUser.as_view()),
    path('user/reactivate', ReactivateUser.as_view()),
    # Deleting business banner
    path('business/banner/delete', BusinessBanner.as_view()),
    # Update banner
    path('business/banner/update', BusinessBanner.as_view()),
    # Fetch Business Listings for admin
    path('business/fetch/listings', FetchListings.as_view()),
    # Delete a business
    path('business/deactivate', DeactivateBusiness.as_view()),
    path('business/<str:pk>', AdminBusinessDetail.as_view()),
    path('business/<str:pk>/', AdminBusinessDetail.as_view()),
    # Send Admin notification
    path('notification/send', SendAdminNotification.as_view()),
    path('notification/send/', SendAdminNotification.as_view()),
    # Delete notification by id
    path('notification/delete', DeleteAdminNotification.as_view()),
    path('notification/delete/', DeleteAdminNotification.as_view()),
    # Mark notification read/unread (admin panel)
    path('notification/read', ReadAdminNotification.as_view()),
    path('notification/read/', ReadAdminNotification.as_view()),
]
