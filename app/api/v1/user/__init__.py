from flask_smorest import Blueprint

from .ApiUserPreferences import blp as user_preference_api
from .ApiUserProfile import blp as user_profile_api
from .ApiUserCustomization import blp as user_customization_api
from .ApiAppPassword import blp as app_password_api
from .ApiAI import blp as ai_api
from .ApiApiTokens import blp as api_tokens_api
from .ApiLiveUpdates import blp as live_updates_api
from .ApiOAuthProvider import blp as oauth_provider_api
from .ApiOpenCloud import blp as opencloud_api
from .ApiSmartCalendar import blp as smart_calendar_api
from .ApiSpamFilter import blp as spam_filter_api
from .ApiTranscripts import blp as transcripts_api
from .ApiPGP import blp as pgp_api
from .ApiPushNotifications import blp as push_notifications_api

user_profile_apis : list[Blueprint] = [user_profile_api, user_preference_api, user_customization_api, app_password_api, push_notifications_api, pgp_api, api_tokens_api, live_updates_api, oauth_provider_api, opencloud_api, smart_calendar_api, spam_filter_api, transcripts_api, ai_api]
