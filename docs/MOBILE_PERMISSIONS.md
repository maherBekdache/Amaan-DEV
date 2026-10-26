# What a phone app may see: Android vs iOS

Checked October 2026 against Android, Google Play and Apple developer documentation (sources at the end).
Short answer: **no app on either platform can read inside WhatsApp or listen to a WhatsApp call.**
Android lets an app read *notifications* (so the text of incoming messages, when previews are on);
iOS does not. Both let the user *share* a message, picture or voice note into Amaan.

## What each route gives Amaan

| Route | Android | iOS | Needs | What Amaan gets |
|---|---|---|---|---|
| Paste / scan / pick a screenshot (today) | ✔ | ✔ | nothing (Expo Go) | what the user gives it |
| WhatsApp chat export (today) | ✔ | ✔ | nothing (Expo Go) | a whole chat, photos, voice-note files |
| WhatsApp linked device on the computer (today) | ✔ | ✔ | the computer runs `start-whatsapp.bat` | new messages, photos, voice notes, **call start/end only** (no audio), for chosen chats |
| "Share to Amaan" from WhatsApp, SMS, Telegram | ✔ share intent | ✔ share extension | development build + `expo-share-intent@8` (SDK 57) | one message, link, picture or voice note, when the user shares it |
| Read incoming notifications | ✔ `NotificationListenerService` | ✘ no API | development build + native module; user enables it in Settings | sender name and message text from WhatsApp, SMS, Telegram, Viber (if previews are on); "🎤 Voice message" placeholder only |
| Screen ordinary phone calls | ✔ `CallScreeningService` (call screening role) | ◐ Call Directory / Live Caller ID Lookup | development build | caller number for **cellular** (`tel:`) calls, not for WhatsApp calls |
| Filter SMS from unknown senders | ◐ only as the default SMS app | ✔ Message Filter extension | development build; iOS: extension can only ask *its own* server, through Apple | SMS text from unknown numbers (not iMessage, not WhatsApp) |
| Accessibility service (read the screen) | ◐ technically possible, Play policy restricts it to accessibility tools; anti-scam use is not listed | ✘ | Play declaration + video; sideloaded apps hit "restricted settings" | anything on screen: too much access for our privacy rules |
| Call audio (cellular or WhatsApp) | ✘ Play forbids remote call-audio recording; WhatsApp audio is end-to-end encrypted | ✘ | | nothing |

✔ available · ◐ limited · ✘ not possible

Extra Android rule: since Android 13, **sideloaded** apps (installed from an APK file, not a store)
cannot get the notification listener or accessibility until the user opens the app's info page and
allows "restricted settings". A demo APK must show that step.

## What this means for Amaan

1. **WhatsApp calls stay a computer feature.** A linked device sees when a call rings, is answered or
   ends, never the audio. That is enough for: unknown caller alerts, foreign-number warnings and the
   one-ring ("Wangiri") warning, now built (`whatsapp-bridge/src/wa.js`, `backend/amaan/api/whatsapp.py`).
2. **Voice notes:** the computer receives them through the linked device and, when a local
   speech-to-text server is set (`AMAAN_STT_URL`, for example the team's Lebanese Whisper model), checks
   what they say. Without it, the alert says the voice note was not checked.
3. **Android can do more, iOS stays manual.** Next, in a development build:
   - both: "Share to Amaan" (`npx expo install expo-share-intent@8`, one config plugin);
   - Android: a small native module with `NotificationListenerService` that passes WhatsApp/SMS
     notification text to the same on-device rules (`packages/core`) and posts a warning notification;
   - Android: `CallScreeningService` for cellular calls from unknown numbers (number reputation, one-ring);
   - iOS: SMS Message Filter extension (unknown senders) and a Call Directory list of reported numbers.
4. **Leaving Expo Go is the decision to take first.** Every item in point 3 needs a development build
   (`eas build`). Android APKs are free to build; iPhone builds need the $99/year Apple developer account.
   Expo Go keeps working for everything built today.

## Sources
- Android 15 restricted settings for sideloaded apps: https://androidauthority.com/android-15-restricted-settings-sideloading-3481098
- Google Play policy on the AccessibilityService API: https://support.google.com/googleplay/android-developer/answer/16585319
- Android `CallScreeningService` (screens `tel` calls; needs the call screening role): https://git.aicp-rom.com/frameworks_base.git/plain/telecomm/java/android/telecom/CallScreeningService.java
- Apple SMS and MMS message filtering (unknown senders only; network only through Apple): https://developer.apple.com/documentation/identitylookup/sms-and-mms-message-filtering
- Live Caller ID Lookup on iOS 18 (used by Truecaller): https://techcabal.com/2025/01/22/apple-update-delivers-truecallers-real-time-caller-id-and-advanced-spam-blocking-to-iphone/
- Baileys call events (`offer`, `accept`, `timeout`, `reject`, `terminate`; no media): `whatsapp-bridge/node_modules/baileys/lib/Types/Call.d.ts`
