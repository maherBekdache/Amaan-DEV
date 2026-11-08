# Future directions: models and tools

What exists today (updated 8 Nov 2026):

| Layer | Today | Kind |
|---|---|---|
| Message cues | weighted Arabic / Arabizi / English phrase rules | rules |
| Link checks | local rules (typo domains, hidden redirects, lookalikes) + URL.vet + OpenPhish/URLhaus lists + Safe Browsing + VirusTotal + urlscan.io | rules + reputation |
| Page capture | expansion worker (redirect chain, page text, form fields, download hashes; no browser) behind the egress proxy | evidence |
| AI | local LLM via Ollama (`qwen2.5:3b` default) summarizes the message and every tool's answer in plain words | generative AI, advisory |

The AI never replaces the evidence-based verdict: it is shown as a second
opinion. That keeps every verdict explainable (project rule 3).

## 1. Better AI reasoning
1. **Bigger local model with the GPU.** `AMAAN_AI_MODEL=qwen2.5:7b` (or 14b) in `.env`.
   Expect clearly better Arabic/Arabizi understanding. Measure it (see §7) before switching.
2. **Cloud LLM (e.g. Claude) for best quality.** The code already uses a provider
   interface (`backend/amaan/ai/provider.py`): add a `CloudProvider.generate_json`
   and select it with a setting. Needs a team decision (DECISIONS.md) because content
   would leave the machine. Privacy-friendly middle ground: send the **evidence
   summary only** (signals, sources, defanged link, expansion worker findings), not the raw
   message, unless the user explicitly asks for a deeper check.
3. **Multimodal QR reasoning.** Give the model the QR image and a screenshot from the browser sandbox (§8)
   (vision models): "this poster's QR sticker covers another QR", "page shows the
   BLOM logo but the domain isn't BLOM's".
4. **Prompt-injection hardening.** Scam text and pages are untrusted. Today they are
   fenced in `<untrusted>` tags, the output is a fixed JSON schema, and it is clipped.
   Next: an automated red-team test set (messages that try to talk the AI into
   "safe"), run in CI.

## 2. Our own scam-intent model (the ML part of the project)
- **Dataset:** collect and anonymize Lebanese scam and normal messages (Arabic, Arabizi,
  English): team phones, WhatsApp exports from volunteers, public reports. Label:
  scam type (code theft, prize, fake bank, parcel, investment, …).
- **Model:** fine-tune an Arabic BERT (e.g. MARBERT / CAMeLBERT, which handle dialect)
  for scam-intent classification; compare with the LLM and the current rules.
- **On the phone:** export to ONNX / TFLite so the mobile app classifies messages
  locally (fits the hybrid design: content never leaves the phone).
- Plug it into the existing `scam-intent` slot of the voice pipeline (Milestone 2) too.

## 3. Visual phishing detection
- **PhishIntention** (USENIX Security 2022; CC0 code) detects a known brand's logo on
  a login page whose domain isn't that brand's: fake login pages too new for any list.
- Run it on screenshots URL.vet already takes (or the browser sandbox, §8), in **static mode only**: its
  "CRP locator" step drives a real Chrome through the site, which would break hard
  rule 1 unless it runs in a container.
- Add Lebanese brands (OMT, Whish, BLOM, Bank Audi, touch, alfa, LibanPost…) to its
  logo list; it ships ~280 global brands.
- Heavy (PyTorch + Detectron2, slow on CPU): use the GPU machine.
- Weights are downloaded from Google Drive with no licence stated: ask the authors
  before any public release.

## 4. More sources and tools
- **File checks** for files people receive (PDF, APK): today the worker only hashes downloads; a hash lookup and a static APK check (permissions, signer) would come next. Pandora is one option.
- **Certificate-transparency watch** (e.g. CertStream) for new domains that look like
  Lebanese brands: flag `omt-lb-gift.com` the day it's registered, before it's reported.
- **DNS blocklists** (e.g. Spamhaus DBL) as one more source.
- **Sharing:** export confirmed scams as MISP events to Lebanon's CERT / partners.

## 5. Community reports (closing the loop)
- "Report this as a scam / as safe" button → our own list, shown with the
  *Reported by others* label once several independent users agree.
- Feeds back into the dataset (§2) and into the local blocklist.

## 6. WhatsApp directly on the phone
These need a **development build** of the app (`npx expo run:android` / `eas build`)
instead of Expo Go; iPhone builds also need an Apple developer account.
- **"Share to Amaan"**: long-press a message or photo in WhatsApp → Share → Amaan
  checks it immediately (Android share intent, iOS share extension). Easiest win.
- **Android only: watch notifications.** With the user's permission
  (NotificationListenerService), Amaan reads incoming WhatsApp notifications from
  unknown numbers and warns right away, with no linked device. Not possible on iPhone.
- **Background alerts** from the computer's watcher as phone notifications.

## 7. Measuring (needed before every change above)
- A labelled evaluation set (e.g. 500 messages + 300 links + 100 QR images).
- Report precision / recall / false-positive rate per layer and combined, and speed.
- The CI already guards the demo examples (`backend/tests/test_examples.py`); extend
  it with the evaluation set so no change silently makes Amaan worse.

## 8. Sandbox roadmap (budget: \$200 approved, all self-hosted)
Design and layers: LINK_SECURITY.md.
- **Now:** Docker containers (runc), read-only, no capabilities, internal network, egress proxy.
- **Option now:** gVisor (`AMAAN_SANDBOX_RUNTIME=runsc`), a user-space kernel; free.
- **Spring 2027:** Firecracker microVMs (one disposable VM per check, about 125 ms start) on a Linux
  host with KVM; OpenSandbox is a candidate manager. Not possible inside the phone app (Android AVF is
  closed to third-party apps; Apple's Virtualization framework is macOS only).
- **Layer L6, browser sandbox:** a disposable headless Chrome of our own, behind the same proxy, for
  pages that only show the scam after scripts run (screenshots for §1.3 and §3).
- **Trace view** for the demo: each layer's input and output, defanged, so the data flow is visible.
