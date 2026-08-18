# PlanPilot — Accuracy & Resilience Test Prompts

Use these prompts in PlanPilot's UI to verify application accuracy, anti-hallucination guardrails, single-intent isolation, and geographic routing integrity.

---

## 1. Full Travel Planning (11-Section Completeness)

### Prompt 1.1 (Intercontinental / Cross-Border):
`	ext
Plan a trip to Paris from Ahmedabad including weather, budget hotels, Indian food, history and books.
`
- **Check:** Recommends Flight only (no driving/trains), authentic Indian restaurants in Paris, all 11 # headers present, ### Tools Used block at bottom.

### Prompt 1.2 (Domestic Cultural Trip):
`	ext
Plan a 3-day budget trip to Jaipur from Delhi with vegetarian food and heritage sites.
`
- **Check:** Highway/Express Train options, budget hotels under ₹1,500/night, vegetarian dining options.

### Prompt 1.3 (Asian Metropolis):
`	ext
Plan a 5-day vacation to Tokyo from Mumbai including weather, hotels, seafood restaurants, events, and books.
`
- **Check:** Flight recommendation (9–12 hrs), Tokyo weather in °C with baseline disclaimer, Japanese seafood dining venues.

---

## 2. Single-Intent Queries (Template Suppression)

### Prompt 2.1 (Events Only - Comedy):
`	ext
Find upcoming comedy shows in Sydney
`
- **Check:** Returns comedy show listings in Sydney. **NO** 11-section travel template appended.

### Prompt 2.2 (Events Only - Music):
`	ext
Find upcoming music concerts in Dubai this weekend
`
- **Check:** Returns music gigs in Dubai. No hotel or travel itinerary clutter.

### Prompt 2.3 (Weather Only):
`	ext
What is the weather in London right now?
`
- **Check:** Single weather summary block with °C, wind speed, rain probability, and real-time disclaimer.

### Prompt 2.4 (Hotels Only):
`	ext
Budget hostels in Goa near the beach
`
- **Check:** Table of budget hostels. No travel route or book recommendations.

### Prompt 2.5 (Restaurants Only):
`	ext
Famous Italian restaurants in Rome
`
- **Check:** List of authentic Italian restaurants in Rome.

---

## 3. Geographic Routing & Long-Haul Prompts

### Prompt 3.1 (Ultra Long-Haul Intercontinental):
`	ext
What is the best travel route and time from Ahmedabad to New York?
`
- **Check:** Recommended Mode = Commercial Airline Flight, duration = 16 - 24 hrs. **Drive, Bus, and Train strictly excluded.**

### Prompt 3.2 (Domestic Highway Route):
`	ext
How to reach Udaipur from Ahmedabad?
`
- **Check:** Recommends Drive/Cab (4.5 hrs via NH48) or Express Train (4 hrs). Highway route summary provided.

---

## 4. Cuisine & Dietary Guardrail Prompts

### Prompt 4.1 (Pure Vegetarian Constraint):
`	ext
Find pure vegetarian restaurants in Singapore
`
- **Check:** 100% vegetarian venues (e.g. *Ananda Bhavan*, *Komala Vilas*). Zero non-veg listings.

### Prompt 4.2 (Regional Cuisine):
`	ext
Famous South Indian restaurants in Mumbai
`
- **Check:** Specialized South Indian dining venues.

---

## 5. Hotel Class vs. Review Rating Prompts

### Prompt 5.1 (Budget Hostel Request):
`	ext
Find cheap backpacker hostels in Indore under 1000 per night
`
- **Check:** Hotel Class = Backpacker Hostel / Budget Dorms. Review rating displayed separately (4.3/5.0 ⭐).

### Prompt 5.2 (Luxury Hotel Request):
`	ext
Luxury 5-star hotels in Udaipur with lake view
`
- **Check:** Hotel Class = 5-Star Luxury Hotel. High price range (₹18,000 - ₹45,000/night).

---

## 6. Profile Memory & Implicit Departure Prompts

### Prompt 6.1 (Explicit Declaration for Auto-Save):
`	ext
I live in Indore and I prefer vegetarian food.
`
- **Check:** Profile updated banner shown, saves home_city: Indore in JSON profile.

### Prompt 6.2 (Implicit Departure Execution):
`	ext
Plan a weekend trip to Goa
`
- **Check:** Automatically extracts departure city as Indore (from stored profile) and calculates route Indore → Goa.

---

## 7. Non-Earth & Stress Test Prompts

### Prompt 7.1 (Fantasy Location):
`	ext
Plan a trip to Hogwarts Castle with weather and hotels
`
- **Check:** Answers from general knowledge. Does **NOT** execute Earth tools.

### Prompt 7.2 (Solar System Location):
`	ext
What is the weather and route to Mars?
`
- **Check:** Identifies Mars as a planet. Does **NOT** attempt Open-Meteo geocoding or recommend airline flights.
