# Project Beacon — Business Brief for Finals Pitch

**Pitch date:** 2026-04-24
**Track:** Agentic AI — Decentralized Swarm Intelligence
**SDGs:** SDG 9 (9.1, 9.5), SDG 3 (3.d)

---

## 1. THE ONE-LINER

> **Beacon is the first natural-language commander for disaster-response drone swarms — turning any first responder into a swarm operator when cell towers are down.**

---

## 2. MARKET POTENTIAL & DEMAND (Judging Criterion 1)

### TAM / SAM / SOM — slide-ready numbers

| Market layer | 2025 Size | Forecast | CAGR | Source |
|---|---|---|---|---|
| **Global UAV Ground Control Station (GCS)** — TAM | **USD 9.6 B** | USD 60.1 B by 2034 | **22.6%** | Fortune Business Insights |
| **Public Safety Drones** — SAM (our wedge) | USD 2.3 B (2023) | USD 9.9 B by 2033 | **15.7%** | Allied Market Research |
| **Search & Rescue Drones** — narrow SAM | USD 1.2 B (2025) | — | **18.5%** | Market Research Future |
| **Safety & Security Drones** | USD 2.76 B (2025) | USD 7.33 B by 2032 | **15.0%** | ReAnIn |
| **Malaysia drone market** — primary SOM anchor | **USD 129.4 M (2024)** | USD 315.5 M by 2033 | **10.4%** | IMARC Group |
| **Indonesia drone market** — secondary SOM anchor | USD 9.5 M (2025) | USD 12.8 M by 2030 | 6.3% | Knowledge Sourcing |

> **Slide take:** A $60B GCS market by 2034, growing 22.6% CAGR. Public safety is the fastest-adopting vertical. We play in the AI-agent layer that every other vendor is now scrambling to add.

### Demand drivers — the "why now"

- **ASEAN disaster economics:** UN ESCAP estimates Asia-Pacific loses **USD 86.5 B/year** on average to natural disasters. Asia-Pacific recorded **USD 65 B in 2023 losses** alone (Aon). Flooding alone exceeds **USD 30 B/year since 2010**.
- **Malaysia-specific demand signal:** Malaysia's drone market grew to **USD 129.4 M in 2024** on **10.4% CAGR**, underpinned by the government-backed **Malaysia Drone Technology Action Plan (MDTAP)** — an official ecosystem mandate for drone commercialization and safety (IMARC). A more expansive Knowledge Sourcing estimate even puts Malaysia at **USD 4.93 B in 2025 → USD 12.99 B by 2030 (21.4% CAGR)** when consumer + commercial + defense segments are bundled.
- **Golden 72 hours:** Survival rate drops from ~90% (first 24h) to **22% by day 3** and <10% after 72h. Every minute saved = lives saved.
- **Drone SAR proven:** Drone teams locate victims **191 seconds faster** than ground teams with **>90% detection** for stationary targets and **80% identification** in collapsed-building scenarios (IEEE, MDPI).
- **Starlink is already the de-facto disaster backhaul:** Deployed in Tonga (2022), Turkey (2023), Philippines Typhoon Odette/Masbate (multi-year), Ukraine. Philippines DICT now hands Gen-3 Starlink units directly to impacted provinces.
- **Regulatory tailwind:** FAA Part 108 BVLOS final rule expected **Spring 2026**; Philippines passed **RA 12287 (Declaration of State of Imminent Disaster Act, Sep 2025)** — pre-event funding release for disaster tech procurement.

### Adoption path (0 → 1 → many)

1. **Hackathon + Malaysia-first pilot:** Beachhead with **NADMA** + **APM (Angkatan Pertahanan Awam)** + the **PTK2Dron** program (MOSTI-sponsored, stood up after 2021 Sri Muda / Hulu Langat floods) — a ready-made procurement channel that already trains drone operators for flood zones.
2. **Expand to ASEAN peers:** PH NDRRMC, Indonesia BNPB, AHA Centre regional coordination.
3. **Sim-first sales motion:** Agencies can run Beacon on their own laptop against our Docker swarm before buying a single physical drone.
4. **Protobuf-first contract:** Swap sim for real MAVLink/PX4 hardware with no UI changes.
5. **Land-and-expand:** 1 operator per agency → multi-state deployments → regional AHA Centre standard.

---

## 3. BLUE OCEAN vs RED OCEAN

### Verdict: **Blue ocean in a red-ocean-looking space.**

**Red ocean** = defense drone swarm (Shield AI, Anduril, AeroVironment). Billions in funding, military-only, classified. Not us.

**Blue ocean** = the intersection we own:
- **Civilian disaster response** (not military combat)
- **Natural language command** (not joystick/waypoint UIs)
- **Comms-denied ASEAN context** (not Pentagon-funded CONUS ops)
- **BYOC / low-cost** (not $10M+ enterprise licenses)
- **Explainable agent reasoning** (not black-box autonomy)

### Blue Ocean 4-Actions Framework

| Action | What |
|---|---|
| **ELIMINATE** | Pilot training complexity · Proprietary hardware lock-in · Per-drone operator ratio |
| **REDUCE** | Enterprise licensing cost · Cloud dependency · Setup time in the field |
| **RAISE** | Agent decision transparency · Comms resilience (Starlink) · Multi-drone coordination |
| **CREATE** | Natural-language mission intent · Auditable LLM decision trails · Sim-first procurement |

### Competitive landscape (who we're NOT)

| Incumbent | Their strength | Their gap vs Beacon |
|---|---|---|
| **Shield AI (Hivemind, $5.6B val)** | Military autonomy pilot, V-BAT swarms over 30k sq mi | Combat-only, classified, no NL command layer |
| **Anduril (Lattice OS, $14B val)** | Real-time sensor-to-platform fusion | DoD-first, no civilian SAR UX, no ASEAN motion |
| **Skydio ($740M raised)** | 200+ US public safety agencies, strong US state DOT footprint | Single-drone pilot-centric, no swarm NL command, US-focused |
| **DJI FlightHub / Dock** | Consumer-to-enterprise drone fleet mgmt | No agentic reasoning, China export-control risk in ASEAN gov procurement |
| **Auterion / QGroundControl (open source)** | MAVLink standard, cheap | Pilot-UI, no swarm AI, zero natural language |
| **Hackathon rivals (FIRSTLIGHT, METRO MANILA RESCUE, Gazebo team)** | Photorealistic visuals (CesiumJS, Google 3D Tiles, Gazebo) | Visualization wrappers — no genuine multi-agent intelligence |

> **Differentiator headline:** Others show you *where* drones are. Beacon decides *what* they should do next — and lets you ask in plain English.

---

## 4. UNIQUE SELLING POINTS (slide-ready one-liners)

1. **"Command a swarm in plain English."** — Say *"scan the south-east quadrant for thermal signatures"*, the Commander Agent routes it to Navigation + Thermal sub-agents, the drones move. No pilot training.
2. **"Works when the cell tower doesn't."** — Starlink-backed satellite uplink keeps command-and-control alive when terrestrial infrastructure is gone.
3. **"One operator, whole swarm."** — Multi-agent architecture (Google ADK) coordinates 3–5+ drones from a single dashboard. Traditional SAR = 1 pilot per drone.
4. **"Every decision is auditable."** — Agent reasoning traces are persisted to SQLite. Judges, commanders, and insurers can replay *why* a drone moved.
5. **"Bring Your Own Compute."** — Runs on a responder's laptop + Starlink kit. No cloud subscription, no vendor lock-in, no classified clearance.
6. **"Protobuf-first, hardware-agnostic."** — Swap the Docker sim for real PX4/MAVLink drones without touching the UI.
7. **"ASEAN-first."** — Built around Pacific Ring of Fire threat models, local NGO procurement realities, and the 72-hour comms-blackout scenario.

---

## 4B. UNFAIR ADVANTAGE — what competitors *cannot* copy

USPs are what we do better today. **Unfair advantage is what stops anyone with money and engineers from catching up tomorrow.** Five moats:

### 1. Regulatory asymmetry — defense vendors are *locked out*

Shield AI, Anduril, AeroVironment all sit under **US ITAR / EAR export controls**. They cannot cleanly sell autonomy software to ASEAN civilian agencies (NADMA, NDRRMC, BNPB) without State Department friction per deal. Beacon, built civilian-first and open-contract, ships without that burden. *This is a structural gap they cannot close — their own government prevents it.*

### 2. Business-model incompatibility — incumbents can't afford to sell to us

Defense-tech margins depend on **USD 10M+ licenses and multi-year DoD contracts**. A provincial DRRMO or a Red Cross chapter has **~USD 5k–50k budgets**. Shield AI / Anduril cannot pivot downmarket without collapsing their own financial model. We're built for that price point from day one. *They can't follow without cannibalizing themselves.*

### 3. Explainability as an architectural bet, not a feature

Military autonomy is **classified-by-design**: Hivemind, Lattice, and similar systems are black boxes because the customer requires it. Beacon persists every agent decision trace to an auditable log — a product choice that aligns with civilian accountability norms (disaster command, insurance, journalism). **Retrofitting explainability onto a classified product is architecturally impossible.** They'd have to start over.

### 4. ASEAN context + procurement-channel access

Disaster response in ASEAN is **relationship-driven**: NADMA, PTK2Dron, AHA Centre, local DRRMOs. A Silicon Valley defense startup can buy the tech talent but not the **standing in-region**. Our team's local embedding, language coverage, and understanding of Pacific Ring of Fire threat models compounds every deployment. *Geography is an unfair advantage when the buyer is local.*

### 5. Mission-log data flywheel

Every real deployment adds **typhoon-, flood-, and earthquake-specific mission traces** to training signal for our planning agents. Defense incumbents accumulate *combat* data; consumer drone vendors accumulate *hobbyist* data. **Nobody else is accumulating ASEAN civilian-SAR reasoning traces.** The longer we run, the further ahead we get on the only dataset that matters for our market.

### The asymmetry, on one line

> *"Defense giants have the money but not the permission. DJI has the hardware but not the autonomy. Consumer GCS tools have the UX but not the intelligence. **The ASEAN civilian SAR swarm slot is ours to take — and structurally hard to take back.**"*

---

## 5. SUSTAINABILITY (Judging Criterion 2)

### Revenue model (multi-stream)

- **Public-sector SaaS** — Annual seat + mission-volume license to NDRRMC, BNPB, NADMA, AHA Centre.
- **NGO tier** — Discounted/free seats for Red Cross, MSF, UN OCHA in exchange for mission telemetry (anonymized).
- **Training & services** — "Beacon Operator" certification program — creates a regional skill pool.
- **Hardware partner margin** — Revenue share with Starlink VAR partners and local drone integrators.

### Long-term resilience

- **LLM-agnostic** — LiteLLM abstraction means we hop Gemini → Qwen → next-gen frontier model without code rewrite.
- **Transport-agnostic** — Starlink today; 5G NTN, Iridium, or ad-hoc mesh tomorrow.
- **Hardware-agnostic** — Protobuf drone contract = any MAVLink-speaking airframe.
- **Data flywheel** — Every mission log refines agent planning. Real disaster data > any competitor's synthetic training set.

### Roadmap to real hardware

- **Phase 1 (now):** Docker sim swarm, hackathon demo.
- **Phase 2 (Q3 2026):** PX4 SITL integration, one physical DJI/Autel bench test.
- **Phase 3 (Q1 2027):** Field pilot with a provincial DRRMO in the Philippines.
- **Phase 4 (2027+):** AHA Centre regional standard discussion.

---

## 6. SOCIAL IMPACT (Judging Criterion 4)

### SDG target → Beacon feature mapping

| SDG Target | How Beacon delivers |
|---|---|
| **9.1** Resilient infrastructure | Starlink + swarm autonomy keep command running when cell/fiber is destroyed |
| **9.5** Enhance scientific research & tech capability | Open protobuf contract + auditable LLM decision logs published as open research artifact |
| **3.d** Strengthen early warning & risk reduction capacity | Thermal scan + sweep patterns compress the 72h golden window; mission logs feed regional early-warning intelligence |

### Tangible outcomes

- **Lives:** Compressing survivor search by even **10%** within the 72h window — at a 22% → 30% survival delta — translates to measurable lives saved per major typhoon.
- **Operator multiplier:** One responder commands 3–5 drones vs 1-to-1 — a **3–5× force multiplier** for under-staffed DRRMOs.
- **Cost:** Drone SAR already halves mission time vs manned helicopters in documented cases (Weber County SAR); Beacon pushes that further by removing the pilot labor constraint.
- **Access for marginalized groups:** Directly helps **rural archipelagic and mountain communities** in the Philippines and Indonesia where cell coverage is thinnest and rescue teams arrive last. These are the populations traditional centralized GCS systems de-prioritize.
- **Reduced responder risk:** Drones enter collapsed structures, flooded villages, and volcanic ash zones *instead of* rescuers.

### Beyond disaster — peacetime community uplift

- **Agricultural monitoring** and illegal-logging detection between deployments.
- **Coastal erosion surveys** for climate-vulnerable coastal barangays.
- **Open-architecture friendly** — no vendor lock-in for ministries with limited budgets.

---

## 7. COMPETITIVE ADVANTAGE — ONE-SLIDE SUMMARY

> **Shield AI trains drones to fight. Anduril connects sensors to missiles. Skydio flies one drone well. DJI sells hardware.**
>
> **Beacon is the only platform that lets a non-pilot responder command a coordinated swarm in plain English, during a comms blackout, with every AI decision auditable.**
>
> **That's not a feature list — it's a category.**

---

## 8. KEY STATS TO MEMORIZE FOR Q&A

- **USD 60B** — GCS market by 2034 (22.6% CAGR)
- **USD 86.5B/year** — ASEAN's annual disaster loss average
- **72 hours** — Window where survival drops from 90% to <10%
- **191 seconds** — Drones beat ground teams to victims
- **76%** — Reduction in operator intervention with agentic UAV frameworks (arxiv.org/2509.13352)
- **USD 5.6B / USD 14B / USD 740M** — Shield AI / Anduril / Skydio war chests (all aimed elsewhere)

---

## SOURCES

**Market sizing**
- [Fortune Business Insights — UAV GCS Market](https://www.fortunebusinessinsights.com/unmanned-aerial-vehicle-uav-ground-control-stations-gcs-market-108813)
- [Allied Market Research — Public Safety Drones Market](https://www.alliedmarketresearch.com/public-safety-drones-market-A10140)
- [Market Research Future — Search and Rescue Drone Market](https://www.marketresearchfuture.com/reports/search-and-rescue-drone-market-24838)
- [IMARC Group — Malaysia Drones Market](https://www.imarcgroup.com/malaysia-drones-market)
- [Knowledge Sourcing — Malaysia Drone Market Outlook](https://www.knowledge-sourcing.com/report/malaysia-drone-market)
- [Knowledge Sourcing — Indonesia Drone Market](https://www.knowledge-sourcing.com/report/indonesia-drone-market)

**Malaysia disaster-response context**
- [Portal NADMA — Robots & drones in flood mitigation](https://www.nadma.gov.my/bi/media-en/news/848-robots-drones-used-in-flood-mitigation-study)
- [Focus Malaysia — Leveraging drones for disaster management](https://focusmalaysia.my/leveraging-drone-technology-to-enhance-malaysias-disaster-management/)
- [Vulcan Post — Malaysia drone startups in 2022 flood relief](https://vulcanpost.com/811596/malaysia-drone-companies-flood-relief-aid-efforts-2022/)
- [MDPI — Reviewing Challenges of Flood Risk Management in Malaysia](https://www.mdpi.com/2073-4441/15/13/2390)

**ASEAN disaster economics**
- [Aon — USD 65B APAC natural catastrophe loss 2023](https://www.aon.com/apac/in-the-press/asia-newsroom/2024/natural-catastrophes-caused-usd-65-billion-economic-loss-in-asia-pacific-in-2023)
- [CNBC — APAC disaster losses 2023](https://www.cnbc.com/2024/04/04/natural-disasters-caused-an-estimated-65-billion-in-losses-last-year-for-asia-pacific.html)
- [ADB — SE Asia disaster risk management](https://www.adb.org/news/features/six-ways-southeast-asia-strengthened-disaster-risk-management)
- [UN ESCAP Asia-Pacific Disaster Report](https://www.un-ilibrary.org/content/periodicals/24118176)

**Survival rate / SAR effectiveness**
- [MDPI — Indicators for Post-Disaster SAR Efficiency](https://www.mdpi.com/2071-1050/12/19/8262)
- [PubMed — Time-to-rescue analysis](https://pubmed.ncbi.nlm.nih.gov/16602260/)
- [IEEE Public Safety — How Drones Are Revolutionizing SAR](https://publicsafety.ieee.org/topics/how-drones-are-revolutionizing-search-and-rescue/)
- [Scientific American — Drones & SAR](https://www.scientificamerican.com/article/how-drones-are-revolutionizing-search-and-rescue/)

**Competitor landscape**
- [Contrary Research — Shield AI breakdown](https://research.contrary.com/company/shield-ai)
- [Fortune — Shield AI inflection point](https://fortune.com/2025/12/21/shield-ai-ukraine-defense-tech-gary-steele/)
- [Breaking Defense — RTX / Shield AI CCA autonomy](https://breakingdefense.com/2025/09/rtx-shield-ai-picked-to-give-collaborative-combat-aircraft-autonomous-capabilities/)
- [Defense One — Shield AI X-BAT](https://www.defenseone.com/business/2025/10/shield-ais-unmanned-fighter-jet-concept-pitched-drone-wingman-or-solo-aircraft/408963/)

**Agentic AI / swarm research**
- [arXiv — Agentic UAVs: LLM-Driven Autonomy (2509.13352)](https://arxiv.org/html/2509.13352v1)
- [Frontiers — Multi-agent LLM swarm intelligence](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1593017/full)
- [arXiv — Agentic AI meets Edge Computing in UAV Swarms (2601.14437)](https://arxiv.org/html/2601.14437v1)

**Starlink disaster response**
- [Starlink — Emergency Response](https://starlink.com/emergency-response)
- [Teslarati — Starlink Philippines deployment](https://www.teslarati.com/starlink-philippines-natural-disasters/)
- [Gulf News — Starlink sustains Philippine typhoon island](https://gulfnews.com/technology/starlink-keeps-typhoon-ravaged-philippine-island-online-against-all-odds-1.500288606)

**Regulation & ASEAN**
- [NDRRMC — UN-SPIDER profile](https://www.un-spider.org/philippines-national-disaster-risk-reduction-and-management-council-ndrrmc)
- [FAA BVLOS Part 108 NPRM](https://www.federalregister.gov/documents/2025/08/07/2025-14992/normalizing-unmanned-aircraft-systems-beyond-visual-line-of-sight-operations)
- [Internet Society — Drones for PH post-disaster](https://www.isocfoundation.org/story/testing-drones-for-post-disaster-operations-in-the-philippines/)
