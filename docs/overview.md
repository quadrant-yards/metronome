# Project Overview

## What is Metronome?

Metronome powers a weekly client meeting called **Metrics** — a structured, recurring review designed to be reliable and boring. The meeting exists across all of Sam's client engagements and follows a strict, standardized format.

The goal is a durable artifact: Google Sheets files that live in the client's Drive, are populated automatically, and outlast Sam's engagement.

---

## The Meeting Format

- Held weekly, typically **Tuesdays**
- Each attendee screen-shares their component's Google Sheets file
- Each file covers one component (e.g. Engineering, Product, Ops) and contains **3–20 tabs**, one per metric
- Every tab shows:
  - Trailing **5 weeks** of data
  - Trailing **12 months** of data
  - Both as **graphs and raw data points**
- The format follows a strict template, applied religiously across all clients

---

## Metric Categories

Metrics are organized into components. Common ones include:

- **Engineering** — DataDog, AWS, GCP, and similar tools
- **Product**
- **Operations**
- **Financial**
- **Revenue**

A typical client has ~50 metrics across 3–5 components. The mix depends on the client's maturity.

---

## Current (Manual) Workflow

1. Each metric owner has their own Google Sheet
2. Every **Monday**, owners manually pull their numbers from their respective tools and enter them into the sheet
3. Every **Tuesday**, the team meets and takes turns screen-sharing their sheets

This process is cumbersome and relies on each owner knowing how to pull their own data.

---

## What Metronome Does (Vision)

Metronome is the automation layer that keeps the meeting artifacts fresh. There are four conceptual phases:

| Phase | Description | Status |
|---|---|---|
| **1. Metric Selection** | Deciding what to measure for a client. The hardest part — big initial effort, evolves over time. | Future scope |
| **2. Configuration** | Defining which metrics a client tracks, where data lives, and how to transform it. Client-specific transformation logic, standardized output format. | Core |
| **3. Collection** | Pulling data from sources (APIs, databases, spreadsheets, etc.) on a Monday schedule. | Core |
| **4. Output** | Populating standardized Google Sheets in the client's Drive, ready for Tuesday. | Core |

---

## Key Design Constraints

- **Output lives in the client's Google Drive** — not Sam's infrastructure
- **The artifact must outlast the engagement** — clients should be able to keep using the sheets after Sam is gone
- **Transformation logic is client-specific** — the path to the data varies, but the output schema is standardized
- **Metric selection is a lifecycle, not a one-time event** — big setup at engagement start, refined over time

---

## Open Questions

- Where does Metronome itself live — web app, script, something the client can run?
- What is the right starting point for building — configuration, collection, or output?
- How does metric selection eventually get represented in the tool?
