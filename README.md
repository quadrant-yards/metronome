# Metronome

## Overview 
Metronome powers a weekly meeting called **Metrics** — a structured, recurring review aimed at building a culture of ownership + learning. 

The meeting follows a strict, [standardized format in Sheets](https://docs.google.com/spreadsheets/d/1txVXAT4Ms6pyvFn3COomt98aahXycbfttwWb-wIbgpM/edit). Metric owners pull their metrics, review them, and present them to the team; the team asks questions.

**Metronome** is a set of tools and skills to make extracting, transforming and (up)loading the metrics less painful.

## Usage

Metronome is cloned locally and used via two independent delivery channels:

- **Claude skills** — a plugin, installed once at the user/machine level via a local marketplace, so they're available as `/metronome-skills:<skill-name>` in other repos.
- **Python modules** — the `metronome` package, added to other repos as an editable install (`uv add --editable`), so `import metronome` picks up source edits live.

Both channels point at the local on-disk checkout rather than a git remote — there's nothing to publish, and edits are immediately live everywhere. 

# Metrics Meeting

## Context & Goal

Goal of the meeting: a culture of ownership + learning

- Ownership: autonomy + accountability  
- Learning: curiosity + evidence

## The Meeting

Platonic ideal of the meeting

- All owners prepare their own metrics ahead of time 
- Each owner presents their metrics  
  - There is a rigid format which allows the team to zip through a million metrics quickly
  - If an owner will miss the meeting, they need to find someone to cover  
- Everyone asks questions
- Improve week over week - add/edit/delete metrics  
  - Avoid: big metrics projects just for this meeting

Cadence
- Every Monday and every 1st day of the month, owners pull their data
  - Owners should review the data and investigate any anomalies
- Every Tuesday, the team meets and takes turns screen-sharing their sheets
  - Owners should be prepared to answer questions about anomalies live
  - Never moved or canceled; should be a “Metronome”   

The meeting is designed to be reliable and boring. 

## Meeting Setup (One-Time)

Setting the meeting up (one-off prework)

- Sketch mental model of components  
- Assign a single owner for each component of the mental model  
- Ask those owners to prepare to choose the metrics they can pull today

Metrics are organized into components. A typical startup winds up with ~50 metrics across 3–5 components but starts with only a few. The mix depends on the company's maturity. 

## Meeting Evaluation

Lagging indicators of success of the meeting

- Everyone can easily articulate the numbers that drive the business  
- Everyone asks questions of each other  
- The meeting can run on its own
