# Google Vision (OCR + Labels)

This repo already has local vision options (Tesseract OCR + optional vision LLM). If you want **high-quality OCR / labels** with Google Cloud Vision, you can enable the service-account integration.

## 1) Create a service account

- In Google Cloud Console, enable **Cloud Vision API**.
- Create a **service account** and download the JSON key file.

## 2) Configure credentials

Set one of these env vars to point to the JSON file:

- `BANTZ_GOOGLE_SERVICE_ACCOUNT=/path/to/service_account.json`
- OR the standard `GOOGLE_APPLICATION_CREDENTIALS=/path/to/service_account.json`

If you do nothing, Bantz looks for:

- `~/.config/bantz/google/service_account.json`

## 3) Install vision deps

- `pip install -e '.[vision]'`

## 4) Use

Python helpers:

- `bantz.vision.google_vision.vision_ocr(path)`
- `bantz.vision.google_vision.vision_describe(path)`

Agent tools (if registered):

- `vision_ocr` (returns extracted text)
- `vision_describe` (returns labels + scores; also logo/face detections)

## Quota safety

A small persisted quota limiter prevents accidentally exceeding the free tier.

- Default: `1000` requests/month
- Override: `BANTZ_VISION_MONTHLY_QUOTA=2000`
- Quota state path: `BANTZ_VISION_QUOTA_PATH=/path/to/quota.json`
