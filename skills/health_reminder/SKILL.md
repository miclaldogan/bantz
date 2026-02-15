---
name: health-reminder
version: 0.1.0
author: Bantz Team
description: "💊 Health Reminder — medication, water, ergonomics, and activity reminders."
icon: 💊
status: planned
tags:
  - future
  - health
  - scheduler-dependent

dependencies:
  - epic: "EPIC 6 — Scheduler"
    status: pending

triggers:
  - pattern: "(?i)(medication|vitamin|pill).*(remind|add|when|did I take)"
    intent: health.medication
    examples:
      - "remind me to take my medication"
      - "did I forget to take my vitamin"
      - "add my morning pill"
    priority: 80

  - pattern: "(?i)(drink water|take a break|rest|ergonomics|sitting time)"
    intent: health.wellness
    examples:
      - "set up water drinking reminders"
      - "how long have I been sitting"
      - "is it time for a break"
    priority: 70

tools:
  - name: health.add_medication
    description: "Add medication/vitamin reminder"
    handler: system
    parameters:
      - name: name
        type: string
        description: "Medication/vitamin name"
      - name: schedule
        type: string
        description: "Schedule: morning, noon, evening, or cron"
      - name: dose
        type: string
        description: "Dose information"

  - name: health.water_reminder
    description: "Water drinking reminder (Pomodoro-style interval)"
    handler: system
    parameters:
      - name: interval_minutes
        type: integer
        description: "Reminder interval (minutes, default: 45)"
      - name: daily_goal_ml
        type: integer
        description: "Daily goal (ml, default: 2500)"

  - name: health.ergonomics
    description: "Ergonomics reminder — sitting time tracking"
    handler: system
    parameters:
      - name: max_sitting_minutes
        type: integer
        description: "Max sitting time (default: 90 minutes)"

  - name: health.daily_log
    description: "Daily health log (medication taken, water drunk, etc.)"
    handler: system
    parameters:
      - name: action
        type: string
        description: "Action taken"
        enum: ["medication_taken", "water_drunk", "break_taken", "exercise"]

notes: |
  Phase G+ feature. Low complexity — depends on Scheduler EPIC.
  Cron-based reminders + D-Bus notification.
  Medication tracking: SQLite medication_log table.
  Ergonomics: X11/Wayland idle time API for sitting time calculation.
