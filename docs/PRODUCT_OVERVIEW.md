# Spotflow — Product Overview

*A plain-language guide to what this platform is, who it serves, and how the pieces fit together.*

---

## 1. What is this?

Spotflow is a **smart parking platform** for cities and campuses where parking is scarce, disputed, and often informal. It combines three ideas that usually live in separate apps:

1. **Monitoring** — Small cameras at individual parking bays watch whether the right vehicle is in the right place.
2. **Accountability** — When someone parks where they should not, the system records what happened and gives the legitimate driver a fair way to respond.
3. **Marketplace** — People who control a bay can rent it out by the hour or by reservation; people who need parking can find, pay, and park immediately.

The product is built for a **Romanian context** (license plates, lei, local documents for vehicle proof), but the model works anywhere people share or rent parking informally.

The product is branded **Spotflow** everywhere users interact with the system (web app, emails, notifications). Internal services and deployment may still use legacy **ParkWatch** names for databases and environment variables.

---

## 2. The problem it tries to solve

Parking in dense areas creates the same frustrations again and again:

- You pay for a spot, return, and find **someone else in your bay**.
- You rent a private driveway or garage spot from a neighbour, but there is **no easy way to pay, schedule, or enforce** who may park when.
- Building managers and small operators have **no cheap tools** to know which bays are empty, occupied, or violated without walking the lot.
- When something goes wrong, disputes are **he-said-she-said** — with no photo, timestamp, or shared record.

Spotflow does not replace municipal enforcement or police. It gives **property owners, tenants, and communities** a shared record, light automation, and a simple economy (Spots) so parking can be monitored, rented, and paid for in one place.

---

## 3. Who is it for?

### Drivers and commuters

People who park regularly in the same city or building. They register their license plates, see alerts when their assigned spot is misused, appeal incorrect flags, and **book or rent** other people’s bays when they need somewhere to park.

### Spot owners

Anyone who **controls** a monitored bay: a tenant with an assigned plate, a landlord with a spare space, a small garage operator. They can **claim** a bay linked to their plate, list it for rent, choose automatic or manual approval for bookings, and optionally use **smart pricing** that adjusts rates based on demand.

### Operators and administrators

Staff who manage devices (cameras at each bay), review disputed cases, verify new plates against official documents, and watch fleet-wide maps and analytics. They see occupancy, violations, and user activity across all locations.

---

## 4. How monitoring works (without technical jargon)

Each parking bay can have a **small edge device** (for example a Raspberry Pi with a camera) that:

- Knows which **license plate** is allowed in that bay (the “assigned” plate).
- Periodically checks what it sees and reports whether the bay looks **empty**, **correct**, or **wrong**.
- Can take a **photo** when asked, especially when a mismatch persists.

That information flows to a central server. Drivers linked to the assigned plate get **notifications** when an unauthorized vehicle appears to be using their spot. The system also keeps a **history** of incidents so patterns are visible over time.

When someone has an **active rental or reservation**, the allowed plate temporarily becomes the **renter’s plate** for that window. The camera treats the renter as authorized until the booking ends. Owners and renters do not need to reconfigure hardware by hand for each booking.

---

## 5. Fairness: plates, proof, and appeals

Trust matters. Spotflow does not let anyone type a plate and immediately gain full trust.

**Adding a plate** requires uploading an official document (for example registration or city paperwork) that is checked against the plate number and the account holder’s name. Plates can be pending, approved, or rejected.

If a **violation or “fine” record** is created for your plate, you can:

- Request **photo evidence** from the camera.
- **Appeal** with a written explanation; in many cases an automated review looks at the image first, and unclear cases go to a human administrator.
- Download a simple **resolution receipt** once a case is closed.

The goal is transparency: you see **when**, **where**, and **what vehicle** triggered the event, not just a penalty with no context.

---

## 6. Renting and booking parking

### Listing a spot

After you **claim** a bay that matches your verified plate, you can turn it into a **listing**:

- Set whether bookings need **your approval** or happen **automatically** after payment.
- Set prices in **Spots** (see below) for instant hourly rent, scheduled rent, and a small deposit for future reservations.
- Add a short description (covered, EV-friendly, etc.).

### Finding parking

Other users open **Find parking**, see available listings on a **map**, and can:

- **Book instantly** — pay for a number of hours and, if approved (or auto-approved), park right away with their plate authorized on the camera.
- **Schedule** — pick a start and end time, pay a deposit upfront, and complete payment when the booking is confirmed.

Only **verified plates** on the renter’s account can be used for a booking. You cannot rent your own listing to yourself.

### While a booking is active

For the booked period, the system treats the renter as the legitimate user of that bay. Owners can see pending requests, approve or reject them, and view recent bookings on their spots.

---

## 7. Spots — the in-app currency

**Spots** are the platform’s internal credits. The rule is simple:

| Concept | Meaning |
|--------|---------|
| **1 Spot = 1 Romanian leu (RON)** | Easy mental math for local users |
| **No platform commission on top** | What you pay in lei becomes Spots in your wallet (in the demo checkout, no real card processing yet) |
| **No tax line added by the app** | Spots are a balance inside the product, not a tax invoice |

### Wallet

Every driver account has a **wallet balance** in Spots. You spend Spots on parking bookings and subscriptions; you receive Spots when someone rents your space (after approvals and payments complete).

### Hardware kits (operators)

B2B pricing for Raspberry Pi + camera edge kits per bay is documented in [HARDWARE_PRICING.md](HARDWARE_PRICING.md) (recommended list price roughly **1,650–1,950 RON** per bay installed in Romania, depending on volume).

### Topping up

You add Spots through a **buy Spots** flow (currently a **demo card form** — no real payment processor connected yet). The amount you enter in lei is the number of Spots credited.

### Monthly subscription

Users can subscribe for **50 lei per month**, which grants **50 Spots** at the start of each billing cycle. Subscription can be paid from the wallet balance or through the same demo checkout. This is positioned as a membership that keeps your account active with a monthly allowance of Spots.

---

## 8. Smart pricing

Owners who want help setting rates can use **smart pricing**, which looks at signals such as:

- **Interest in the spot** — views on the listing, booking attempts, and completed rentals (logged automatically in an activity history).
- **Time** — hour of day, weekday vs weekend, public holidays in Romania.
- **Location** — how central the bay is relative to the city core.
- **Weather** (light influence) — optional adjustment from public weather data.
- **Occupancy** — whether the bay often appears occupied or empty.

Three modes exist:

| Mode | What happens |
|------|----------------|
| **Manual** | You set prices yourself; smart pricing only advises if you ask. |
| **Suggest** | The system proposes new hourly rates (including **fractional** Spots, e.g. 10.5 per hour); you **accept** or ignore. |
| **Auto** | Prices update within your **minimum and maximum** bounds as demand changes. |

Owners always set **floor and ceiling** prices so automation cannot run away. Suggested changes come with a **short explanation** (for example busier Friday evening, more views this week).

---

## 9. Maps and the live picture

Maps are central to how people understand the system:

- **Administrators** see all monitored bays, colour-coded by status (empty, occupied, correct plate, violation).
- **Drivers** see bays related to their fines and activity.
- **Renters** see listed spots available to book.

Maps were designed to be **tall and readable** on desktop and phone so users can orient themselves quickly. Status can update in near real time when devices report in.

---

## 10. Notifications and staying informed

Drivers can enable **browser push notifications** (where supported) to learn when their spot may be misused. Email can be used for evidence and operational messages depending on server configuration.

The activity log behind the scenes records page visits, listing views, booking attempts, payments, and pricing updates. That log is not shown as a consumer feature today, but it powers **demand-aware pricing** and gives operators an audit trail if they need to investigate disputes or abuse.

---

## 11. Demo mode and rollout

The product supports a **demo mode** for presentations: sample devices, fines, and read-only settings so visitors can click through without changing real data.

For a real deployment you would:

- Install edge devices at each bay and register them with the server.
- Assign plates to bays and onboard drivers with document verification.
- Turn on listings and wallet flows when payment integration is ready.

Technical setup, APIs, and security notes live in the other documents under `docs/` (architecture, API, deployment). This overview intentionally avoids implementation detail.

---

## 12. Values and boundaries

**What Spotflow is good at**

- Making private and semi-private parking **visible, rentable, and auditable**.
- Giving assigned drivers **evidence** when someone else uses their bay.
- Aligning **payment, authorization, and camera logic** for short-term rentals.

**What it is not**

- A replacement for city parking police or national vehicle registries.
- A guaranteed legal contract between landlord and tenant (terms remain between parties; the app is the instrument).
- A fully licensed payment institution until real card processing and compliance are added.

---

## 13. Why “Spotflow”

The name reflects how the product is meant to feel in daily use:

- **Spot** — one parking bay, and the in-app **Spots** currency.
- **Flow** — drivers moving between bays, owners listing empty time, and payments moving through the wallet without friction.

It reads naturally in English, works in marketing, and does not sound like a government enforcement tool.

---

## 14. A day in the life (three stories)

### Maria — assigned tenant

Maria has a leased parking space at her block. Her plate is verified with a PDF from registration. One evening she gets a push alert: another plate has been in her bay for twenty minutes. She opens the app, sees the location on the map, requests a camera photo, and submits a short appeal because she lent the car to her partner. The system checks the image; if the plate still does not match, the case can go to the building administrator. Maria never had to confront a stranger in the garage.

### Andrei — spot owner

Andrei claims a monitored bay tied to his plate and lists it on weekdays while he uses public transport. He sets smart pricing to **suggest** mode with a floor of 8 Spots and a ceiling of 18 Spots per hour. Friday afternoon the app recommends 14.5 Spots; he taps accept. Two bookings arrive — one instant, one scheduled — and Spots land in his wallet when renters pay. He approves one manual request from a neighbour he does not recognize.

### The administrator — small operator

Elena manages forty bays across two streets. Her dashboard map shows greens and reds at a glance. She adds a new device when a camera is installed, assigns plates for new tenants, and reviews appeals that automation could not resolve. She exports fine history when the property manager asks for a monthly report. Rental activity is visible through bookings linked to listings, not a separate spreadsheet.

---

## 15. Glossary

| Term | Meaning |
|------|---------|
| **Bay / spot** | One physical parking place, usually monitored by one device. |
| **Assigned plate** | The plate allowed to park in that bay by default (often the tenant or owner). |
| **Listing** | An owner’s offer to rent a bay, with prices and approval rules. |
| **Instant book** | Pay and park for a chosen number of hours starting now (or when approved). |
| **Schedule** | Reserve a future time window with a deposit, then complete payment. |
| **Spot** | In-app credit; 1 Spot ≈ 1 leu for pricing and wallet balance. |
| **Violation / fine record** | A logged mismatch event; not necessarily a government fine. |
| **Appeal** | Driver challenge to a record, with optional photo review. |
| **Smart pricing** | Automated or suggested rate changes based on demand and context. |
| **Activity log** | Internal record of views, bookings, and actions used for demand signals. |

---

## 16. Frequently asked questions

**Do I need the app if I only rent out my spot?**  
You need an account to claim the bay, set listing prices, and receive Spots. Renters use the same app to find and pay.

**Can prices be 10.5 Spots per hour?**  
Yes. Smart pricing and manual entry support fractional Spots; charges round up to whole Spots when debiting a wallet.

**What if the camera is wrong?**  
Appeals and human review exist precisely for OCR or edge-case errors. The product is designed around evidence, not blind penalties.

**Is real card payment live?**  
As of this documentation, checkout is a **demo** form. Production would connect a payment provider later; Spots logic is already in place.

**Does the owner need a camera?**  
For monitoring and enforcement, a device at the bay is required. For marketplace-only use in theory, you could list a space, but authorization during rentals works best when the bay is monitored.

---

## 17. Summary

Spotflow is a **community-scale parking operating system**: cameras and plates at the edge, a fair account layer in the middle, and a **Spots** economy that lets owners monetize empty time while drivers book with confidence. Smart pricing and activity logging make the marketplace respond to real interest instead of static signs on a wall.

For operators, it is a live map of the lot. For owners, it is a way to list and price a bay. For drivers, it is proof, access, and payment in one place — built for the friction of everyday parking in a busy city.

---

*Document version: product overview for stakeholders, partners, and non-technical readers. Last aligned with features including peer-to-peer rental, Spots wallet, smart pricing, and activity-based demand logging.*
