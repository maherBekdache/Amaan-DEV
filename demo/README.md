# Demo samples

Safe, ready-made inputs for testing and for the demo video. Every link uses
`example.com` (reserved by IANA, never a real scam) or a real official site.
`backend/tests/test_demo_samples.py` checks that each one still triggers the
expected signals, so if someone breaks a rule, CI goes red before the demo
does.

Regenerate the images after editing `samples.json`:
`backend\.venv\Scripts\python demo\make_qr_samples.py`

## QR images (`demo/qr/`): drag them in, or show them to the webcam

| File | What it shows | Expected |
|---|---|---|
| `01-official-omt.png` | the real omt.com.lb | **Low**, *Verified* official domain |
| `02-at-sign-trick.png` | `omt.com.lb@…example.com`: looks like OMT, opens another site | **High** |
| `03-open-wifi.png` | "Free_Beirut_Airport", no password | **Medium** |
| `04-premium-sms.png` | ready-made SMS "SUBSCRIBE GOLD" to 1199 | **Medium** |
| `05-crypto-payment.png` | bitcoin payment request | **High** |
| `06-phone-call.png` | international phone number | **Low**, with a note |
| `07-three-codes.png` | 3 codes in one image (AUB site, Wi-Fi, router IP) | **Medium**, 3 items |
| `08-photo-of-poster.jpg` | small, tilted, blurry QR in a "photo" | decoded; brand warning |

For the **camera**: open a PNG full-screen on your phone and hold it in front
of the laptop webcam.

## Messages: copy and paste (Ctrl+V anywhere on the page)

Arabic, scam: prize + code request (**High**)
```
مبروك! ربحت جائزة من OMT بقيمة 500$. ادخل على omt-gift.example.com/claim وابعتلي رمز التحقق يلي رح يوصلك
```

Arabizi, scam (**High**)
```
Mabrouk! rbe7t jeyze men Whish 🎁 ekbos hon whish-money.example.com w ab3atli el code yalli wasalak
```

English, bank threat (**High**)
```
URGENT: Your BLOM Bank account will be suspended within 24 hours. Verify now: http://blom-secure.example.com/login
```

Parcel / customs fee (**High**)
```
LibanPost: your parcel is held at customs. Pay the 2$ customs fee here: libanpost-delivery.example.com/pay
```

Lookalike with a digit, paypa**1** (**High**)
```
Log in to confirm your payment: https://paypa1.com/signin
```

Normal chat (**Low** with URL.vet running)
```
kifak? check the AUB calendar on https://www.aub.edu.lb w mnetla2a bokra
```

The hidden-character sample (zero-width + right-to-left override) is in
`samples.json` (`hidden-characters`). Invisible characters don't survive
copy-paste from a web page, so use the automated test, or paste it from the
JSON file opened in VS Code.

## Showing a "Community report" (a link others reported)
This needs a link that is *currently* on a phishing list, which changes daily.
On the day of recording, take one from PhishTank's recent submissions
(https://phishtank.org: look only, never click a link there), copy the
**text** of the URL and paste it into Amaan. With the real URL.vet running,
the result shows the purple *Community report* label. Don't put that link in
the repo or the video description.
