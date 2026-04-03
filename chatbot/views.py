"""
Django views for Braelo chatbot API (uses config.settings).
"""
import logging
import os
import json

from django.http import JsonResponse, HttpResponse

logger = logging.getLogger(__name__)
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings as django_settings

_legacy_model = None
_legacy_intents = None
_legacy_words = None
_legacy_classes = None


def _load_legacy():
    global _legacy_model, _legacy_intents, _legacy_words, _legacy_classes
    if _legacy_model is not None:
        return True
    try:
        import pickle
        from keras.models import load_model
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_path = os.path.join(base, "chatbot_model.h5")
        intents_path = os.path.join(base, "intents.json")
        words_path = os.path.join(base, "words.pkl")
        classes_path = os.path.join(base, "classes.pkl")
        if all(os.path.isfile(f) for f in [model_path, intents_path, words_path, classes_path]):
            _legacy_model = load_model(model_path)
            _legacy_intents = json.load(open(intents_path, encoding="utf-8"))
            _legacy_words = pickle.load(open(words_path, "rb"))
            _legacy_classes = pickle.load(open(classes_path, "rb"))
            return True
    except Exception:
        pass
    return False


def home(request):
    try:
        return render(request, "chatbot/index.html")
    except Exception:
        return HttpResponse("<p>Braelo Chatbot API. Use POST /chatbot/api/chat or /chatbot/get</p>")


def _parse_user_location(data: dict) -> dict:
    loc = {}
    if data.get("city"):
        loc["city"] = str(data["city"]).strip()[:128]
    if data.get("state"):
        loc["state"] = str(data["state"]).strip()
    if data.get("county"):
        loc["county"] = str(data["county"]).strip()
    if data.get("zip_code"):
        loc["zip_code"] = str(data["zip_code"]).strip()
    if "location_enabled" in data:
        loc["location_enabled"] = bool(data["location_enabled"])
    if data.get("latitude") is not None:
        try:
            loc["latitude"] = float(data["latitude"])
        except (TypeError, ValueError):
            pass
    if data.get("longitude") is not None:
        try:
            loc["longitude"] = float(data["longitude"])
        except (TypeError, ValueError):
            pass
    loc["explicit_address_in_request"] = bool(
        str(data.get("city") or "").strip()
        or str(data.get("state") or "").strip()
        or str(data.get("county") or "").strip()
        or str(data.get("zip_code") or "").strip()
    )
    loc["explicit_profile_location"] = bool(
        loc.get("city") or loc.get("state") or loc.get("zip_code") or loc.get("county")
    )
    return loc


def _parse_user_profile(data: dict) -> dict:
    """Extract name, email, phone for profile (no email/phone required upfront)."""
    profile = {}
    if data.get("name"):
        profile["name"] = str(data["name"]).strip()[:128]
    if data.get("display_name"):
        profile["display_name"] = str(data["display_name"]).strip()[:128]
    if not profile.get("display_name") and profile.get("name"):
        profile["display_name"] = profile["name"]
    if data.get("email"):
        profile["email"] = str(data["email"]).strip()[:254]
    if data.get("phone"):
        profile["phone"] = str(data["phone"]).strip()[:32]
    return profile


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def api_chat(request):
    if request.method == "OPTIONS":
        return HttpResponse("", status=200)
    try:
        data = json.loads(request.body) if request.body else {}
        message = (data.get("message") or data.get("msg") or "").strip()
        business_load_more = bool(data.get("business_load_more"))
        business_snapshot = data.get("business_snapshot")
        if len(message) > 4000:
            return JsonResponse({"error": "Invalid or missing message", "response": ""}, status=400)
        if not business_load_more:
            if not message:
                return JsonResponse({"error": "Invalid or missing message", "response": ""}, status=400)
        elif not isinstance(business_snapshot, dict):
            return JsonResponse({"error": "business_snapshot required", "response": ""}, status=400)
        # user_id is the STABLE identity for location/profile persistence (IP or explicit user_id).
        # session_id resets on every page-load so language detection re-locks per conversation.
        user_id = data.get("user_id") or _get_client_ip(request)
        session_id = data.get("session_id") or user_id
        user_location = _parse_user_location(data)
        try:
            from chatbot.services.reverse_geocode import merge_gps_into_location

            user_location = merge_gps_into_location(user_location)
        except Exception:
            logger.exception("chatbot.api_chat.reverse_geocode_merge_failed")
        user_profile = _parse_user_profile(data)
        logger.info(
            "chatbot.api_chat.request user_id=%s session_id=%s message_len=%s has_location=%s has_profile=%s geo=%s",
            user_id,
            session_id,
            len(message),
            bool(user_location),
            bool(user_profile),
            (user_location.get("latitude") is not None and user_location.get("longitude") is not None),
        )
    except Exception:
        logger.exception("chatbot.api_chat.bad_request")
        return JsonResponse({"error": "Bad request", "response": ""}, status=400)
    try:
        from chatbot.chat_flow import process_message
        out = process_message(
            message,
            user_id=user_id,
            session_id=session_id,
            user_location=user_location,
            user_profile=user_profile,
            business_load_more=business_load_more,
            business_snapshot=business_snapshot if isinstance(business_snapshot, dict) else None,
            business_offset=int(data.get("business_offset") or 0),
            business_page_size=data.get("business_page_size"),
        )
        payload = {
            "response": out["response"],
            "detected_language": out.get("detected_language", "en"),
            "businesses": out.get("businesses", []),
            "intent": out.get("intent", ""),
            "see_more": out.get("see_more", False),
            "location_note": out.get("location_note"),
            "question_analysis": out.get("question_analysis"),
            "business_pagination": out.get("business_pagination"),
        }
        if out.get("user_name") is not None:
            payload["user_name"] = out["user_name"]
        if out.get("require_contact_details"):
            payload["require_contact_details"] = True
            payload["contact_details_message"] = out.get("contact_details_message", "")
        loc_ctx = {}
        for _k in ("city", "state", "zip_code", "county"):
            _v = (user_location or {}).get(_k)
            if _v:
                loc_ctx[_k] = _v
        if loc_ctx:
            loc_ctx["from_device_gps"] = bool(
                data.get("latitude") is not None and data.get("longitude") is not None
            )
            payload["location_context"] = loc_ctx
        logger.info(
            "chatbot.api_chat.response user_id=%s intent=%s lang=%s response_len=%s businesses=%s",
            user_id,
            payload.get("intent"),
            payload.get("detected_language"),
            len(payload.get("response") or ""),
            len(payload.get("businesses") or []),
        )
        return JsonResponse(payload)
    except Exception as e:
        logger.exception("chatbot api_chat error")
        hint = ""
        try:
            from django.db.utils import OperationalError, ProgrammingError
            if isinstance(e, (OperationalError, ProgrammingError)):
                hint = " Run: python manage.py migrate"
        except Exception:
            pass
        return JsonResponse({
            "error": str(e) + hint,
            "response": "Sorry, something went wrong. Please try again.",
            "detected_language": "en",
            "businesses": [],
        }, status=500)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def legacy_get(request):
    if request.method == "OPTIONS":
        return HttpResponse("", status=200)
    msg = request.POST.get("msg") or ""
    if not msg:
        try:
            data = json.loads(request.body) if request.body else {}
            msg = data.get("msg") or ""
        except Exception:
            logger.exception("chatbot.legacy_get.body_parse_failed")
            msg = ""
    msg = msg.strip()
    if not msg:
        return HttpResponse("Please send a message.", status=400)
    logger.info("chatbot.legacy_get.request ip=%s message_len=%s", _get_client_ip(request), len(msg))
    if django_settings.OPENAI_API_KEY:
        try:
            from chatbot.chat_flow import process_message
            client_id = _get_client_ip(request)
            loc = {}
            if request.POST.get("state"):
                loc["state"] = request.POST.get("state")
            if request.POST.get("county"):
                loc["county"] = request.POST.get("county")
            if request.POST.get("zip_code"):
                loc["zip_code"] = request.POST.get("zip_code")
            try:
                body = json.loads(request.body) if request.body else {}
                loc.update(_parse_user_location(body))
            except Exception:
                pass
            out = process_message(msg, user_id=client_id, session_id=client_id, user_location=loc or None)
            logger.info(
                "chatbot.legacy_get.response user_id=%s response_len=%s",
                client_id,
                len(out.get("response") or ""),
            )
            return HttpResponse(out["response"])
        except Exception:
            logger.exception("chatbot.legacy_get.process_message_failed")
            return HttpResponse("Sorry, something went wrong. Please try again.")
    if _load_legacy():
        import random
        import numpy as np
        import nltk
        from nltk.stem import WordNetLemmatizer
        lemmatizer = WordNetLemmatizer()
        def clean_up_sentence(sentence):
            sentence_words = nltk.word_tokenize(sentence)
            return [lemmatizer.lemmatize(w.lower()) for w in sentence_words]
        def bow(sentence):
            sentence_words = clean_up_sentence(sentence)
            bag = [0] * len(_legacy_words)
            for s in sentence_words:
                for i, w in enumerate(_legacy_words):
                    if w == s:
                        bag[i] = 1
            return np.array(bag)
        def predict_class(sentence):
            p = bow(sentence)
            res = _legacy_model.predict(np.array([p]))[0]
            thresh = 0.25
            results = [[i, r] for i, r in enumerate(res) if r > thresh]
            results.sort(key=lambda x: x[1], reverse=True)
            return [{"intent": _legacy_classes[r[0]], "probability": str(r[1])} for r in results]
        def get_response(ints):
            tag = ints[0]["intent"]
            for i in _legacy_intents["intents"]:
                if i["tag"] == tag:
                    return random.choice(i["responses"])
            return "Sorry, I didn't understand that."
        if msg.startswith("my name is"):
            name = msg[11:]
            ints = predict_class(msg)
            res = get_response(ints).replace("{n}", name)
        elif msg.startswith("hi my name is"):
            name = msg[14:]
            ints = predict_class(msg)
            res = get_response(ints).replace("{n}", name)
        else:
            ints = predict_class(msg)
            res = get_response(ints) if ints else "Sorry, I didn't understand that."
        return HttpResponse(res)
    return HttpResponse("Chat is not configured. Set OPENAI_API_KEY or add chatbot_model.h5 and intents.json.")


@require_http_methods(["GET"])
def health(request):
    logger.info("chatbot.health.check llm=%s", bool(getattr(django_settings, "OPENAI_API_KEY", None)))
    return JsonResponse({"status": "ok", "llm": bool(getattr(django_settings, "OPENAI_API_KEY", None))})


@require_http_methods(["GET"])
def debug_knowledge(request):
    logger.info("chatbot.debug_knowledge.request use_mongo=%s", bool(getattr(django_settings, "USE_MONGO", False)))
    if getattr(django_settings, "USE_MONGO", False):
        try:
            from chatbot.mongo_db import get_db
            db = get_db()
            total = db.knowledge_base.count_documents({})
            with_emb = db.knowledge_base.count_documents({"embedding": {"$exists": True, "$ne": None}})
            sample = list(db.knowledge_base.find({}).limit(5))
            return JsonResponse({
                "knowledge_base_total": total,
                "knowledge_base_with_embeddings": with_emb,
                "source": "mongodb",
                "sample_questions": [
                    {"q": (r.get("question") or "")[:80] + ("..." if len(r.get("question") or "") > 80 else ""), "state": r.get("state")}
                    for r in sample
                ],
                "openai_key_set": bool(getattr(django_settings, "OPENAI_API_KEY", None)),
            })
        except Exception as e:
            logger.exception("chatbot.debug_knowledge.error")
            return JsonResponse({"error": str(e), "knowledge_base_total": 0, "source": "mongodb"}, status=500)
    from chatbot.models import KnowledgeBase
    total = KnowledgeBase.objects.count()
    with_emb = KnowledgeBase.objects.filter(embedding_json__isnull=False).count()
    sample = KnowledgeBase.objects.all()[:5]
    return JsonResponse({
        "knowledge_base_total": total,
        "knowledge_base_with_embeddings": with_emb,
        "sample_questions": [
            {"q": r.question[:80] + ("..." if len(r.question or "") > 80 else ""), "state": r.state}
            for r in sample
        ],
        "openai_key_set": bool(getattr(django_settings, "OPENAI_API_KEY", None)),
    })


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def track_contact(request):
    if request.method == "OPTIONS":
        return HttpResponse("", status=200)
    try:
        data = json.loads(request.body) if request.body else {}
        business_id = data.get("business_id")
        contact_type = (data.get("contact_type") or "whatsapp").lower()
        if contact_type not in ("whatsapp", "phone", "email"):
            contact_type = "whatsapp"
        if not business_id:
            return JsonResponse({"error": "business_id required"}, status=400)
        user_id = data.get("user_id") or request.META.get("REMOTE_ADDR")
        logger.info(
            "chatbot.track_contact.request user_id=%s business_id=%s contact_type=%s use_mongo=%s",
            user_id,
            business_id,
            contact_type,
            bool(getattr(django_settings, "USE_MONGO", False)),
        )
        if getattr(django_settings, "USE_MONGO", False):
            try:
                from chatbot.mongo_db import get_db
                from datetime import datetime
                get_db().contact_tracking.insert_one({
                    "business_id": str(business_id),
                    "external_id": str(user_id),
                    "contact_type": contact_type,
                    "created_at": datetime.utcnow(),
                })
                return JsonResponse({"status": "ok"})
            except Exception as e:
                logger.exception("chatbot.track_contact.mongo_error")
                return JsonResponse({"error": str(e)}, status=500)
        from chatbot.models import Business, ContactTracking
        from django.shortcuts import get_object_or_404
        business = get_object_or_404(Business, pk=business_id)
        ContactTracking.objects.create(
            business=business,
            external_id=str(user_id),
            contact_type=contact_type,
        )
        return JsonResponse({"status": "ok"})
    except Exception as e:
        logger.exception("chatbot.track_contact.error")
        return JsonResponse({"error": str(e)}, status=500)


def _get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")
