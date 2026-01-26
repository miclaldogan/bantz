# Voice Autocorrect + Risk Gate — Spec (v0.6)

## Goal
Make voice feel “Jarvis-like”:
- No “Şunu mu demek istedin?” questions.
- System silently auto-corrects to the nearest supported command when confidence is high enough.
- If confidence is low: ask user to repeat (re-record), not debate.
- Risky actions still require confirmation (handled by daemon Policy).

## Architecture
**Voice loop (client)**
1) ASR → `(text, meta)`
2) Autocorrect decision → `normalized_text` or `re_record`
3) Send to daemon → router/policy/skills
4) If daemon returns `unknown` (voice UX): re-record prompt

**Daemon (single brain)**
- NLU → intent
- Policy → allow/confirm/deny
- Skills execute

## Inputs from codebase (ground truth)
Derived from [src/bantz/router/nlu.py](../src/bantz/router/nlu.py).

### Core / Scheduling
- `reminder_add`: “hatırlat: yarın 9:00 toplantı”, “5 dakika sonra hatırlat: çay”
- `reminder_list`: “hatırlatmalar”, “hatırlatmaları göster”
- `reminder_delete`: “hatırlatma #3 sil”
- `reminder_snooze`: “hatırlatma #3 10 dakika ertele”

- `checkin_add`: “her gün 21:00 yokla: su içtin mi?”
- `checkin_list`: “check-in’leri göster”
- `checkin_delete`: “check-in #3 sil”
- `checkin_pause/resume`: “check-in #3 durdur / başlat”

### PC / App Control
- `app_open`: “discord aç”, “vscode başlat”
- `app_close`: “discord kapat”
- `app_focus`: “discord’a geç”, “firefox öne al”
- `app_list`: “uygulamalar / pencereler”
- `app_type`: “yaz: merhaba”
- `app_submit`: “gönder”, “enter bas”, “submit”
- `app_session_exit`: “uygulamadan çık”, “normal moda dön”

### Browser Agent
- `browser_open`: “instagram aç”, “github aç”, “aç: https://…”
- `browser_scan`: “sayfayı tara”, “linkleri göster”, “bu sayfada ne var”
- `browser_click`: “12’ye tıkla”, “'Log in' yazana tıkla”, “giriş yap butonuna tıkla”
- `browser_type`: “[3] alanına yaz: …”, “şunu yaz: …”
- `browser_scroll_down/up`: “aşağı kaydır / yukarı kaydır”
- `browser_back`: “geri dön”
- `browser_info`: “neredeyim”, “bu sayfa ne”
- `browser_detail`: “detay 5”, “5 hakkında bilgi”
- `browser_wait`: “bekle 3 saniye”

## Canonical command dictionary (15 starter)
Each entry has a **canonical** phrase (what autocorrect normalizes to) and its **aliases** (ASR variations).

This list mirrors `COMMAND_CANONICAL` in [src/bantz/voice/loop.py](../src/bantz/voice/loop.py#L158).

| # | Canonical | Aliases (partial) |
|---|-----------|-------------------|
| 1 | `evet` | yes, tamam, ok |
| 2 | `hayır` | hayir, no |
| 3 | `iptal` | vazgeç, cancel |
| 4 | `uygulamalar` | pencereler, açık pencereler, windows, show windows |
| 5 | `discord aç` | discord, dis kord, open discord |
| 6 | `firefox aç` | firefox, open firefox |
| 7 | `kapat` | close |
| 8 | `gönder` | gonder, enter bas, yolla, send, submit |
| 9 | `uygulamadan çık` | normal moda dön |
| 10 | `yaz:` (prefix) | yaz, type:, type |
| 11 | `hatırlat:` (prefix) | hatırlatma:, reminder:, remind |
| 12 | `son olaylar` | events, eventler |
| 13 | `instagram aç` | instagram, instegram, insta, open instagram |
| 14 | `youtube aç` | youtube, you tube, yutup, open youtube |
| 15 | `sayfayı tara` | yeniden tara, linkleri göster, scan page |
| – | `geri dön` | geri don, back |
| – | `aşağı kaydır` | scroll down |
| – | `yukarı kaydır` | scroll up |
| – | `1'e tıkla` | click 1 (example template — dynamic for N) |
| – | `bekle 3 saniye` | wait 3 (example template) |

## Decision model (Auto-correct + Risk Gate)
### Signals
**ASR confidence (from meta)**
- `no_speech_prob > 0.6` → LOW
- `avg_logprob > -0.6` → HIGH
- `avg_logprob < -1.0` → LOW
- otherwise → MED

**Command match (rapidfuzz score 0–100)**
- `>= 93` → HIGH match
- `90–92` → MED match
- `< 90` → weak

### Modes
1) **HIGH** (bucket != LOW and match >= 93)
- normalize to canonical and run

2) **MED** (bucket in {HIGH, MED} and match >= 90)
- normalize to canonical and run
- risky intent will still trigger daemon confirmation

3) **LOW**
- do not send to daemon
- prompt: “Anlayamadım. Tekrar söyler misin?”

### Risk Gate
Risk is enforced by daemon policy (confirm/deny rules). Suggested risky intents to treat as confirm/deny via policy:
- `app_submit` (send/enter)
- `app_close` / session-exit style actions
- destructive scheduler ops: `reminder_delete`, `checkin_delete`, `checkin_pause`
- `browser_click` when click target text exists (already gated)

## Voice UX rules
- No “did you mean?” dialog.
- Unknown intent from daemon in voice mode → re-record prompt.
- Always allow global exit words in Enter-PTT: `çık/exit/quit/stop`.

## Implementation notes
- Autocorrect happens only in voice client; daemon stays authoritative.
- Keep dictionary small initially; grow via observed ASR mistakes (add aliases).
- If LLM is enabled later, use it only for **text cleanup**, then run the same command matching and policy.

## Code pointers
- Command dict: [src/bantz/voice/loop.py L158](../src/bantz/voice/loop.py#L158) (`COMMAND_CANONICAL`)
- Bucket logic: `_asr_bucket()` — same file
- Decision: `_autocorrect()` — same file
- NLU ground truth: [src/bantz/router/nlu.py](../src/bantz/router/nlu.py)
