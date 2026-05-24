# Spotflow — Demo tehnic (2 minute)

**Public:** ingineri, integratori, operatori IT  
**Durată:** ~120 s  
**Focus:** pipeline edge → server → UI; sincronizare număr la rezervare; ledger Credits; routing și reputație  
**Notă:** Nu acoperă hardware Pi, OCR on-device sau deploy — doar ce se vede în aplicație. Detaliile de arhitectură stau în documentația separată.

---

## Pregătire (off-camera)

| Item | Detaliu |
|------|---------|
| Server | `python app.py` în `server/` (port configurat în env, de ob. **2026**) |
| Viewport | **Desktop ≥1200px** — hărțile Leaflet și acțiunile din listă nu se bat cu bara mobilă |
| Intrare | `/login?demo=1` → rol **Șofer** → autentificare → cod **456789** pe pagina 2FA |
| Sesiune | Cont demo cu date sintetice București / Cluj / Craiova; sold Credits preîncărcat |
| După login | Aterizezi pe **`/portal`** (acasă șofer). Repetiție: [http://127.0.0.1:2026/portal](http://127.0.0.1:2026/portal) |
| Evită | Concierge AI (instabil în unele sesiuni) — folosește search clasic |

**Credențiale demo**

| Câmp | Valoare |
|------|---------|
| Utilizator | `demo` |
| Parolă | `demo123!` |
| Cod 2FA | `456789` |
| Rol | **Șofer** (implicit) |

**Login rapid:** `/login?demo=1` (prefill utilizator și parolă)

---

## Beat sheet tehnic

| Timp | Strat | Mesaj cheie |
|------|-------|-------------|
| 0:00–0:12 | Stack | Edge OCR + Flask + portal — un singur model de date pentru monitorizare și marketplace |
| 0:12–0:32 | **`/portal` acasă șofer** | Hartă alerte, card Mismatch, dovadă foto și contestație |
| 0:32–0:52 | Discovery | Geocoding + enrichment disponibilitate + routing direct vs „walk-in” |
| 0:52–1:12 | Tranzacție | Rezervare → debit wallet (hundredths) → propagare număr autorizat către device |
| 1:12–1:32 | Policy | Trust passport, praguri min_trust, smart pricing cu floor/ceiling |
| 1:32–2:00 | Close | Un flux, trei roluri (driver / owner / admin); stack extensibil prin API REST |

---

## Script — pas cu pas

> Vorbește peste click-uri. Pauze scurte doar la 2FA și după confirmarea plății.

### 0:00 — Autentificare și context sesiune (12 s)

**Ecran:** `/login?demo=1` → verificare 2FA → **`/portal`**

**Acțiuni:** Autentificare șofer; introdu **`456789`**; Continuă.

→ aterizare pe **`/portal`** (acasă șofer). Dacă nu ești acolo, deschide [http://127.0.0.1:2026/portal](http://127.0.0.1:2026/portal).

**Spune:**
> „Spotflow e un strat central Flask peste SQLite: device-uri edge raportează starea locului, iar același backend servește portalul șofer, marketplace-ul și dashboard-ul operator. Intru într-o sesiune demo — date sintetice, dar fluxurile reale.”

**Ecran:** **`/portal`** — badge Demo, salut „Hi, Demo User”, număr verificat, sold Credits, harta *Where alerts happened* dedesubt

**Arată:** badge-ul numărului verificat, soldul Credits, sumarul alertelor (need action / in review / open / resolved).

---

### 0:12 — Portal: alerte și hartă (20 s)

**Ecran:** Rămâi pe **`/portal`** — hartă + listă alerte

**Acțiuni:** Derulează la harta *Where alerts happened*; deschide o alertă **Mismatch**; arată câmpurile Detected / Expected; nu apăsa Request photo dacă ești pe viewport îngust (bară fixă jos).

**Spune:**
> „Fiecare incident e legat de un `Device` cu coordonate. Clientul edge trimite heartbeat și, la nepotrivire, un `Fine` cu timestamp și scor OCR. În UI vezi starea: nepotrivire, review uman, sau rezolvat. Request photo pune device-ul în coadă de captură — worker-ul serverului livrează dovada; contestația poate trece prin review automat, apoi escaladare admin.”

**Tehnic (o frază):** SSE pe `/stream` actualizează dashboard-ul fără refresh complet.

---

### 0:32 — Discovery: hartă, filtre, routing (20 s)

**Ecran:** `/portal/find-parking`

**Acțiuni:** Nav **Find parking**. Pagina poate veni deja cu centrul pe București — ok. În câmpul *Where do you need parking?* tastează **Piata Universitatii**, alege sugestia, apasă search. Arată legenda culorilor pe hartă. Derulează la o listare cu badge verde *Available now*.

**Spune:**
> „Căutarea geocodează destinația, apoi `enrich_listing_items` calculează disponibilitatea la `target_at`. Sortarea combină relevanță, distanță și preț. Routing-ul separă locuri la destinație de variante walk-in — două strategii în același set de rezultate, nu doar sortare pe distanță Euclidiană.”

**Nu folosi:** panoul Quick parking search / concierge — nu e necesar pentru demo-ul live.

---

### 0:52 — Rezervare și ledger (20 s)

**Acțiuni:** **Pay & park** pe prima listare disponibilă. Lasă intervalul implicit din modal. Confirmă plata.

**Spune:**
> „Prețul e în Credits, stocat intern în hundredths — un Credit echivalează un leu, fără comision platformă în demo. La submit, serverul debitează wallet-ul și creează booking-ul. Dacă listing-ul e pe manual approval, plata e rezervată până acceptă proprietarul; dacă e auto-approve, numărul chiriașului devine imediat `assigned_plate` temporar pe device — fără SSH pe Pi.”

**Ecran așteptat:** modal *Payment received — pending approval* **sau** confirmare instant — ambele sunt valide; explică modul listing-ului, nu promite automatizare camera dacă vezi pending.

**Acțiuni:** **Done**.

---

### 1:12 — Policy layer: trust și owner (20 s)

**Ecran:** `/portal/settings` → card **My spots**

**Acțiuni:** Deschide **My spots**. Arată un loc listat cu rată dinamică; opțional badge pending pe cerere de booking.

**Spune:**
> „Trust passport agregă plecări la timp, no-show și istoric contestații — `min_trust_score` pe listing filtrează cine poate rezerva instant. Proprietarul setează manual/auto approval, floor și ceiling pentru smart pricing, și primește Credits la finalizarea plății. Activity log-ul din spate alimentează semnalele de cerere — nu e feature consumer, dar explică de ce tariful se mișcă.”

---

### 1:32 — Închidere (28 s)

**Spune:**
> „Rezumat: edge raportează, serverul persistă și notifică, portalul leagă monitorizarea de marketplace și wallet. Operatorul vede flota pe `/admin` — device health, cozi verificare, export CSV — același model de date. API-urile REST pentru register, heartbeat, config și fines permit integrare fără UI. Întrebări pe fluxul de date sau pe extensii?”

**Opțional (10 s, doar dacă se cere):** logout → login Admin → `/admin` → hartă flotă + chart 7 zile + chip appeals.

---

## Teleprompter (bloc continuu)

> Spotflow e un strat central Flask peste SQLite: device-uri edge raportează starea locului, iar același backend servește portalul șofer, marketplace-ul și dashboard-ul operator. Intru într-o sesiune demo — date sintetice, dar fluxurile reale. Fiecare cont trece prin verificare simulată — codul **456789**, fără email trimis.
>
> Pe **`/portal`**, fiecare incident e legat de un device cu coordonate. Clientul edge trimite heartbeat și, la nepotrivire, un fine cu timestamp și scor OCR. În UI vezi nepotrivire, review uman sau rezolvat. Request photo pune device-ul în coadă de captură; contestația poate trece prin review automat, apoi escaladare admin. SSE actualizează dashboard-ul fără refresh complet.
>
> La Find parking, geocoding-ul ancorează harta, enrichment-ul calculează disponibilitatea la ora țintă, iar routing-ul separă locuri la destinație de variante walk-in. Prețul e în Credits, hundredths în ledger. La rezervare, wallet-ul se debitează și booking-ul propagă numărul autorizat către device când approval mode permite — altfel plata rămâne pending până acceptă owner-ul.
>
> Trust passport și min_trust_score controlează cine rezervă instant. Owner setează smart pricing cu floor/ceiling și approval manual sau automat. Operatorul vede aceeași flotă pe admin, cu export și cozi de verificare. API REST pentru device și fines — integrare fără UI. Întrebări?

---

## Checklist live

```
[ ] Desktop width, server pornit
[ ] /login?demo=1 → 2FA (456789) → /portal
[ ] /portal — hartă alerte + card Mismatch (Detected vs Expected)
[ ] Find parking → Piata Universitatii → hartă + legendă
[ ] Pay & park → explică pending vs auto-approve → Done
[ ] Account → My spots → trust / smart pricing / pending
[ ] Închidere stack + API
```

---

## Recuperare rapidă

| Simptom | Acțiune |
|---------|---------|
| Hartă goală | Refresh; re-search *Bucharest city center* |
| Fără Pay & park | Secțiunea *All nearby spots* → *Book anyway* |
| Butoane acoperite (mobil) | Treci pe lățime desktop sau derulează deasupra barei fixe |
| Concierge error | Ignoră — folosește search clasic |
| Modal pending approval | Spune explicit: manual approval; camera sync după Accept |
| Nu ești pe portal după 2FA | Deschide direct /portal |

---

## Ce nu repetăm (acoperit în alt material)

- Pitch comercial „patru aplicații în una”, persona Maria, FAQ consumatori  
- Preț kit hardware Pi, pași deploy DietPi, tuning Tesseract  
- Detaliu complet appeal/Ollama, schema DB câmp cu câmp  

---

## Rute utile

| Ecran | Cale |
|-------|------|
| Login demo | `/login?demo=1` |
| **Portal șofer (acasă)** | **`/portal`** |
| Marketplace | `/portal/find-parking` |
| Cont / trust | `/portal/settings` |
| Owner | `/portal/my-spots` |
| Wallet | `/portal/wallet` |
| Admin | `/admin` |

---

*Demo: `demo` / `demo123!`, 2FA `456789`. Verificat live: login, **/portal** + hartă, find parking manual, booking wallet, account/my spots.*
