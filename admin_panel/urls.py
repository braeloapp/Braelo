from django.urls import path
from users.api.login import LoginWithEmail

from admin_panel.api.users import AllUsers,AllFeedback,AllNotifications,ReportedUsers,SendAdminNotification
from users.api.business import FetchBusinesses
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
   # Report an issue to admin
   path('support', AllFeedback.as_view(), name='support'),
   # Action taken by admin
   path('report/action', ReportedUsers.as_view(), name='support'),
   # Account creation by admin
   path('signup', SignUpWithEmail.as_view(), name='admin-signup'),
    #Admin Login
   path('login', LoginWithEmail.as_view(), name='admin-panel-login' ),
   # Fetch all business
   path('business', FetchBusinesses.as_view(), name='fetch-all-business'),
   # Read notifications
   path('notificatons', AllNotifications.as_view(), name='read-notifications'),
   # Delete Listings
   path('delete', DeleteListing.as_view(), name='delete-listings'),
   # Send Admin notification
   path('notification/send',SendAdminNotification.as_view(), name='send-notification'),

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
