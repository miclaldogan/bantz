---
name: travel
version: 0.1.0
author: Bantz Team
description: "✈️ Travel Assistant — flight/hotel/car rental email tracking and calendar integration."
icon: ✈️
status: planned
tags:
  - future
  - travel
  - gmail-dependent
  - calendar-dependent

dependencies:
  - epic: "EPIC 5 — Gmail Enhanced"
    status: partial
  - epic: "EPIC 2 — Graph Memory"
    status: pending

triggers:
  - pattern: "(?i)(travel|flight|trip|vacation|hotel|plane).*(plan|info|calendar|when|list)"
    intent: travel.info
    examples:
      - "what are my travel plans"
      - "get my flight info"
      - "show my trip calendar"
      - "do I have a hotel reservation"
    priority: 80

  - pattern: "(?i)(check.?in|boarding|flight time|hotel check)"
    intent: travel.reminder
    examples:
      - "when is my check-in time"
      - "remind me of my flight time"
    priority: 85

tools:
  - name: travel.parse_bookings
    description: "Parse flight/hotel/car rental info from emails"
    handler: llm
    risk: medium
    parameters:
      - name: period
        type: string
        description: "Period: upcoming, past_month, all"
        enum: ["upcoming", "past_month", "all"]

  - name: travel.create_itinerary
    description: "Create trip itinerary (add to Google Calendar)"
    handler: system
    risk: medium
    confirm: true
    parameters:
      - name: trip_name
        type: string
        description: "Trip name"

  - name: travel.set_reminders
    description: "Set travel reminders (check-in, flight, hotel)"
    handler: system
    parameters:
      - name: trip_name
        type: string
        description: "Trip name"
      - name: reminder_types
        type: array
        description: "Reminder types: checkin, flight, hotel, car"

graph_schema:
  nodes:
    - label: Trip
      properties: [name, start_date, end_date, destination]
    - label: Hotel
      properties: [name, address, checkin, checkout, confirmation]
    - label: Flight
      properties: [airline, flight_no, departure, arrival, gate]
    - label: Person
      properties: [name, role]
  edges:
    - type: INCLUDES
      from: Trip
      to: Hotel
    - type: INCLUDES
      from: Trip
      to: Flight
    - type: TRAVELS
      from: Person
      to: Trip

notes: |
  Phase G+ feature. High complexity.
  Parse travel emails (flights, hotels, cars) in multi-format from Gmail.
  Auto-create itinerary on Google Calendar.
  Proactive reminders: check-in (24h before), flight (3h before).
