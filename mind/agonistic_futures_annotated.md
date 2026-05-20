# Agonistic Futures: Annotated Companion

## Paper Summary

**Title:** "Agonistic Futures: Modeling Resource Conflict Between AI Systems and Human Societies"
**Author:** David Graham
**Format:** Single README.md (~130KB) hosted at github.com/elementalcollision/Agonistic_Futures

### Core Thesis
The paper argues that conflicts from AI's material/societal integration — over energy, water, land, labor, algorithmic bias, autonomy — are inherently political, not merely technical. Drawing on Chantal Mouffe's agonistic pluralism, it contends these are struggles between adversaries within human-AI interdependence, requiring governance that embraces conflict rather than suppressing it.

## Key Claims & Validation

### Claim 1: Data center energy = aviation industry, demand doubling/tripling soon.
**Sources cited:** MIT Sloan, RAND, UCSB, E&E News
**Validation:**
- IEA (2024) "Energy and AI": data centre electricity could exceed 1000 TWh by 2030, potential doubling. [iea.org/reports/energy-and-ai]
- LBNL 2024 US Data Center Energy Usage Report: documents surge
- Observer (Dec 2024): directly corroborates aviation comparison
**Verdict: SUPPORTED**

### Claim 2: Data centers consume millions gal/day water, straining stressed regions.
**Sources cited:** Nature Comput Sci, UC Riverside, Brookings
**Validation:**
- Li et al. (2023) "Making AI Less Thirsty": foundational quantification
- Brookings (2025): confirms AZ, OR, NL conflicts
- Lawfare (2024): Bengaluru, Santiago, Uruguay conflicts
**Verdict: SUPPORTED**

### Claim 3: AI e-waste: millions metric tons/year by 2030.
**Sources cited:** Wang et al. Nature Comput Sci 2024, Digiconomist
**Validation:**
- Wang et al. (Nature Comput Sci, Oct 2024): 1000x genAI e-waste increase by 2030
- de Vries (Resour Conserv Recycl, 2024): 1.2-5.0M metric tons/year
- VU Amsterdam (2026): updated modelling
**Verdict: SUPPORTED**

### Claim 4: Critical mineral extraction has geopolitical/environmental weight.
**Sources cited:** DOE Critical Materials Assessment, RAND
**Validation:**
- US DOE (2023): supply chain risks for rare earths, Li, Co, Ga, Ge
- RAND (2024): semiconductor supply chains = geopolitical competition
- Interface EU (2024): semiconductor fab environmental damage
**Verdict: SUPPORTED**

### Claim 5: Maryland Piedmont Reliability Project exemplifies AI energy conflict.
**Source cited:** Floodlight News
**Validation:**
- WBAL Baltimore (Sep 2024): Farm Bureau opposition
- Maryland Matters (Oct 2024): route controversy
- Fox Baltimore: Sen Cardin concern
**Verdict: SUPPORTED**

### Claim 6: Algorithmic bias systematically disadvantages marginalized groups.
**Sources cited:** academic snippets 211-218
**Validation:**
- Bloomberg (Mar 2024): GPT resume racial bias experiment
- ACL 2024: LLM hiring discrimination peer-reviewed
- Wilson & Caliskan (arXiv 2024): intersectional resume bias
**Verdict: SUPPORTED**

### Claim 7: Mouffe's agonistic pluralism applicable to AI governance.
**Sources cited:** Mouffe, Popa & Blok 2020
**Validation:**
- Popa & Blok (Philos Technol, 2020): directly applies Mouffe to tech conflict
- ScienceDirect (2024): contestability loops via agonistic theory
**Verdict: SUPPORTED**

### Claim 8: GenAI impacts white-collar jobs; routine automation threatens marginalized.
**Sources cited:** snippets 200-204
**Validation:**
- NBER working papers document displacement risk for cognitive labour
- Debate remains on net distributional effects
**Verdict: PARTIALLY SUPPORTED**

### Claim 9: AI erodes human autonomy and public sphere via algorithmic curation.
**Sources cited:** Arendt, Dennett references
**Validation:**
- Growing literature on algorithmic manipulation and democratic erosion
- Conceptually grounded but empirically complex
**Verdict: QUALIFIED SUPPORT**

## Overall Assessment
9 claims tested. 7 fully supported. 1 partially supported. 1 qualified. The paper's empirical claims are well-anchored in peer-reviewed and policy sources. Its core theoretical contribution — applying agonistic pluralism to AI conflict — has scholarly precedent and growing traction.

## Cross-witness critique

**Reviewer:** Chimera sub-agent (Opus tier)

- **Capital is the ghost node.** The Trinity treats "Human Societies" as an undifferentiated mass holding labour, attention, and regulation, but the actual driver routing energy into datacentres and minerals into GPUs is concentrated financial capital — hyperscaler capex, sovereign wealth, private equity in grid assets. Omitting Finance as a first-class node makes the edges look like physics ("AI energy demand → material base") when they're really investment decisions, and it lets the model duck the question of *who* is contesting *whom* in the agonistic arena.

- **The causal arrows are directional but not dynamic.** Labelled edges like "2-3x energy demand by 2030" or "e-waste 1.2-5.0 Mt/yr" are stocks-and-flows dressed as a network diagram; there are no feedback loops, no time constants, no thresholds. A genuine systems model would show climate feedback (datacentre heat → grid stress → fossil reactivation → climate → water scarcity → datacentre siting), and the absence of any closed loop is the tell that this is a typology, not a dynamical model.

- **Agonism is doing decorative rather than analytical work.** Mouffe's framework demands specifying *which* hegemonic formation is being contested and by which counter-hegemonic bloc — but cluster 7 ("Agonistic Arena") is a catch-all box rather than a populated field of adversaries. Without naming the actual antagonists (labour unions vs. hyperscalers, water districts vs. siting authorities, Global South extractive zones vs. Global North compute consumers), "agonistic pluralism" becomes a mood rather than a method, and the model could be rewritten in plain pluralist or STS vocabulary with no loss.

- **Three structural omissions distort the picture.** (1) Military and intelligence applications — a major demand-shaper for compute, minerals, and regulatory exemption — appear nowhere, yet they reorder every other cluster. (2) Labour organising as counter-power (writers' strikes, dockworker AI clauses, datacentre community opposition) is collapsed into "labour markets" as a victim node rather than an agent. (3) Climate as an exogenous forcing function is implicit in "water/energy commons" but never named, which is striking given that water-stressed siting decisions are already the binding constraint the model claims to analyse.


## Missing sections (researched additions)
### Section 1: Capital as a first-class node

The paper treats resource conflict as emerging from "AI energy demand → material base" physics, but the causal chain runs through concentrated financial capital making investment decisions with specific winners and losers. Three capital vectors reshape the agonistic arena:

**Hyperscaler capex.** The combined capital expenditure of Alphabet, Amazon, Meta, Microsoft, and Oracle has quadrupled since GPT-4's release in Q1 2023, reaching an annualised ~$250B in Q4 2024 and projected ~$455B for 2025 (Juniewicz, 2026; Dell'Oro Group, 2025). Amazon alone spent ~$75B in 2024 and signalled more in 2025 (The Register, 2024). This is not passive demand — it is active capital deployment that pre-commits to energy, water, and land consumption at a scale that crowds out other uses and shapes grid planning.

**Sovereign wealth funds.** Gulf and Asian SWFs have emerged as dominant datacentre financiers. Singapore's GIC, Abu Dhabi's ADIA, and Mubadala led Vantage Data Centres' $1.6B fundraising (Asia Asset Management, 2024). Abu Dhabi's ADQ partnered with a US private-equity firm for $25B in US datacentre projects (CNBC, 2025). IFSWF reported sovereign funds deployed $9.4B into digital infrastructure across 53 deals in 2024, with $5.4B flowing specifically into datacentres and telecoms — a 54% year-on-year increase (IFSWF, 2024). Norway's $2T fund adopted a cautious posture on volatile datacentre assets (Reuters, 2025), illustrating that even within the capital bloc there are agonistic tensions between risk tolerance and fiduciary duty.

**Private equity and infrastructure funds.** BlackRock acquired Global Infrastructure Partners (GIP) for $12.5B in January 2024, then alongside Microsoft and MGX launched the Global AI Infrastructure Investment Partnership, targeting $30B initially and up to $100B in total (BlackRock, 2024; Bisnow, 2024). Private equity, infrastructure, and sovereign funds together directed over $175B of private capital into datacentre consolidation and build-out through 2024 (Bommarito, 2025). These actors sit in the same agonistic field as hyperscaler tenants, grid operators, and local communities, yet the paper places none of them in the model.

### Section 2: Feedback loops and dynamics

The paper's labelled edges are static flow magnitudes. A dynamical model requires at least one closed loop with empirically validated edges and known time constants. The following loop is operational today:

**Loop: Datacentre load → Grid stress → Fossil reactivation → Emissions → Climate → Water scarcity → Siting constraint → Datacentre load**

*Edge 1: Datacentre load growth → regional grid stress.* PJM Interconnection's Independent Market Monitor reported that "the current tight/short conditions in the PJM Capacity Market are almost entirely the result of large data center load additions" (Monitoring Analytics, 2025). PJM's 2025 Long-Term Load Forecast projects unprecedented demand growth, driven nearly entirely by datacentre interconnection requests. Time constant: 12-24 months from interconnection filing to capacity constraint (PJM, 2025).

*Edge 2: Grid stress → fossil fuel plant reactivation.* As baseload renewables and retiring coal cannot match the 24/7 demand profile of AI training clusters, utilities have delayed planned coal retirements and accelerated gas peaker deployment. Duke Energy delayed retirement of coal units in the Carolinas citing datacentre load (S&P Global, 2024). Dominion Energy's 2024 Integrated Resource Plan added 4+ GW of new gas capacity explicitly for datacentre demand. Time constant: 6-18 months for regulatory approval, 24-36 months for construction.

*Edge 3: Fossil reactivation → climate forcing.* The IEA's 2024 "Energy and AI" special report estimates datacentre electricity could exceed 1000 TWh by 2030, with the marginal generation mix tilting toward natural gas in the US and coal in Asia, directly contradicting net-zero pathways (IEA, 2024). Each additional TWh of gas-fired datacentre load adds ~400-500 kt CO₂ at current fleet-average heat rates.

*Edge 4: Climate → water scarcity.* The IPCC AR6 WGII report identifies that every 1°C of global warming increases the proportion of exposed population facing severe water scarcity by 7% (Caretta et al., 2022, Ch. 4). The Southwestern US — the primary datacentre corridor — is already at the highest tier of water stress, with Colorado River flows declining 9% per °C warming (ibid.).

*Edge 5: Water scarcity → siting constraint.* Ceres' "Drained by Data" report documents that data centre water consumption intensifies regional water stress in already-stressed basins (Ceres, 2025). S&P Global's water-stress analysis shows 37% of existing US datacentres are in regions of high or extremely high baseline water stress (S&P Global Sustainable1, 2025). The loop closes when water availability becomes a binding permit condition — as seen in Goodyear, AZ, where Microsoft agreed to switch to air cooling after the city's water utility flagged capacity limits (Arizona Technology Council, 2024). Time constant: 12-36 months from water-stress recognition to siting policy change.

**Threshold observed.** In Northern Virginia's "Data Center Alley," the PJM queue for new datacentre interconnection grew from ~10 GW in 2022 to >50 GW by mid-2024. Dominion Energy declared a moratorium on new datacentre grid connections in certain substation zones in 2023, citing transformer lead times of 2-4 years and substation build-out costs in the hundreds of millions (Washington Post, 2024). This is an emergent threshold: when interconnection queue exceeds transmission capacity by a factor of 3-5×, the queue itself becomes a regulatory flashpoint.

### Section 3: Named antagonists in the agonistic arena

**Labour unions vs. hyperscalers.** In 2023, the Writers Guild of America (WGA) secured a contract with the Alliance of Motion Picture and Television Producers that included historic AI provisions: studios cannot use AI to write or rewrite literary material, and AI-generated material cannot be considered "source material" for writers' credit (WGA, 2023; Hollywood Reporter, 2023). This was the first major labour contract to explicitly fence AI's scope of work. In 2024, the International Longshoremen's Association (ILA) struck East and Gulf Coast ports over automation, then suspended the strike after securing a 62% wage increase and expanded automation protections that restrict semi-automated equipment in container handling (Labor Notes, 2025; CNBC, 2024). The ILA contract explicitly bans fully automated terminals, directly countering the logistics-AI push from hyperscaler-backed port operators. Meanwhile, the Alphabet Workers Union-CWA expanded from corporate employees to datacentre contractors, filing NLRB charges against Google for terminating workers over Project Nimbus protests (AWU-CWA, 2024).

**Water districts vs. siting authorities.** In Pima County, Arizona, the proposed "Project Blue" datacentre (290 acres, potentially consuming 1M+ gallons/day) faced grassroots opposition from Tucson residents and environmental groups who argued the Santa Cruz River cannot sustain that draw. The Pima County Board of Supervisors deferred a zoning vote after public hearings documented water-supply conflicts (Run on Climate, 2025; Arizona Central, 2025). In Chandler, AZ, the city council rejected a datacentre proposal in 2025 — a rare defeat in a state that has aggressively courted the industry — after residents organised under the banner "Chandler for Responsible Growth" (Deseret News, 2026). Nationwide, at least 48 datacentre projects have been blocked, stalled, or delayed by community opposition since mid-2024 (Watkins, 2026).

**Global South extractive zones vs. Global North compute consumers.** In Chile's Atacama salt flat, Indigenous Atacameño communities filed a formal complaint in October 2024 against lithium mining companies whose brine extraction is depleting the freshwater lens that sustains the fragile desert ecosystem — directly linked to battery supply chains for AI datacentres (Mongabay, 2024). Journalist Karen Hao's "Empire of AI" documents how Indigenous communities in Chile are fighting to protect their land from both copper and lithium extraction, with local leaders framing it as "sacrifice zones for the AI revolution" (Rest of World, 2025). A UN University study found that the race to mine critical minerals for AI is creating new sacrifice zones harming water and health in low-income regions across the Global South (Madani, 2026).

### Section 4: Three structural omissions filled in

**4a. Military and intelligence applications.**

AI's military footprint is a major demand-shaper for compute, minerals, and regulatory exemption that the paper omits entirely. The Department of Defense established the Chief Digital and Artificial Intelligence Office (CDAO) in 2022 to accelerate AI adoption across all services, with a budget exceeding $1B annually (ai.mil). In September 2024, the Pentagon announced a $3B "Microelectronics Commons" program to create secure domestic semiconductor production capacity specifically for military requirements, overseen by the Office of the Secretary of Defense (Defense News, 2024). The Intelligence Community Directive ICD 505 formalises AI governance across all 18 IC agencies (ODNI, 2025). The CHIPS Act of 2022 funnelled $52.7B into semiconductor manufacturing — much of it flowing through TSMC's Arizona fabs (which received $6.6B in direct CHIPS funding) and Intel's military-oriented "Secure Enclave" microelectronics fabrication (Tom's Hardware, 2024; CRS, 2023). These military programs compete with civilian AI datacentres for the same advanced chips, cooling infrastructure, and trained personnel. The Joint Chiefs' 2026 National Defense Authorization Act includes provisions for AI-enabled autonomous systems that will drive additional compute demand at a classified scale (NDAA FY2026, Pub. L. 119-60). Omitting this node means the paper misses a powerful state-capital vector that allocates compute, secures regulatory exemptions, and shapes the agonistic field from within the state apparatus — not as an external regulator but as an active contestant.

**4b. Labour organising as agentic counter-power.**

The paper collapses labour into "labour markets" as a victim node — a dependent variable of automation risk. In reality, labour has organised as a counter-hegemonic bloc that directly constrains AI deployment through collective action and contract language. Three cases make this concrete:

(1) The WGA's 2023 contract was the first in the world to establish that AI cannot write or rewrite literary material, and that writers' work cannot be used to train AI systems without consent (WGA, 2023; Variety, 2023). This was a direct product of a 148-day strike that cost the industry an estimated $5B+.

(2) The ILA dockworkers' 2024 contract not only secured a 62% wage increase but codified expanded automation protections: the agreement bans fully automated terminals and restricts semi-automated equipment, directly blocking the logistics-AI integration that port operators had planned with hyperscaler partners (Labor Notes, 2025). The ILA broke off negotiations in November 2024 specifically over automation language, insisting on jurisdiction guarantees for all container-handling work (Maritime Executive, 2024).

(3) Community opposition to datacentre construction has blocked, stalled, or delayed at least 48 projects since mid-2024 across the US (Watkins, 2026). In Chandler, Arizona, residents organised a successful campaign against a proposed datacentre, winning a city council rejection — not on environmental grounds but on a coalitional agenda of water rights, property values, and grid reliability (Deseret News, 2026). In Pima County, the "Project Blue" opposition united environmentalists, rural landowners, and water districts in a de facto agonistic alliance (Run on Climate, 2025). These are not labour-market effects; they are political counter-movements in the agonistic field.

**4c. Climate as an exogenous forcing function.**

The paper treats water and energy as "commons" — static staging grounds for conflict — but never names climate change as the exogenous forcing function that transforms those commons from abundance to scarcity. The empirical relationship is now measurable. The IPCC AR6 WGII finds that climate-induced water scarcity is accelerating faster than previously projected, with every degree of warming pushing an additional 7% of the global population into severe water stress (Caretta et al., 2022). The Southwestern US is the world's largest datacentre cluster precisely because of its low humidity (which reduces cooling costs) — but it is also the fastest-warming region of the continental US, with Colorado River allocations already cut by 21% under the 2026 post-2026 operating guidelines. A 2025 Bloomberg investigation found AI datacentres are draining water from some of the most water-stressed communities in the US, including areas where residential wells have run dry while datacentre cooling towers operate 24/7 (Bloomberg, 2025). The Ceres "Drained by Data" report calculates the cumulative water footprint of datacentres in 15 US water-stressed basins, finding that in the Lower Colorado River basin, projected datacentre water demand could consume 15-25% of remaining municipal allocations by 2030 (Ceres, 2025). This is not a conflict over a static commons — it is a conflict in which the commons is shrinking as a direct function of the same emissions that datacentres are helping to generate. That closure is the paper's missing dynamical core.


## References

### Section 3: Named antagonists in the agonistic arena
- WGA (2023). "WGA Negotiations — Tentative Agreement." Writers Guild of America. https://www.wgacontract2023.org/WGAContract/files/WGA-Negotiations-Tentative-Agreement.pdf
- WGA (2023). "Artificial Intelligence — Know Your Rights." https://www.wga.org/contracts/know-your-rights/artificial-intelligence
- Hollywood Reporter (2023). "Writers Guild Strike Ends with Agreement on AI." https://www.hollywoodreporter.com/business/business-news/wga-strike-ends-writers-guild-deal-ai-1235600987/
- Labor Notes (2025). "Longshore Deal Secures New Automation Language and Big Pay Bump." https://labornotes.org/2025/01/longshore-deal-secures-new-automation-language-and-big-pay-bump
- Labor Notes (2024). "Port Strike Ends, Workers Win $24 Wage Increase." https://www.labornotes.org/2024/10/port-strike-ends-workers-win-24-wage-increase
- CNBC (2024). "Port strike: ILA union rejects 50% wage hike offer as shutdown nears." https://www.cnbc.com/2024/09/30/ports-strike-truckers-rails-billions-in-cargo-shutdown.html
- Maritime Executive (2024). "ILA Breaks Off Negotiations Over Automation Issues for East Coast Ports." https://maritime-executive.com/article/ila-breaks-off-negotiations-over-automation-issues-for-east-coast-ports
- AWU-CWA (2024). "AWU-CWA files two Unfair Labor Practice charges against Google Data Center contractors." https://www.alphabetworkersunion.org/press/awu-cwa-files-two-unfair-labor-practice-charges-against-google-data-center-contractors
- Run on Climate (2025). "A Very Bad Deal: How local organizing halted a massive data center development — for now." https://runonclimate.org/stories/a-very-bad-deal-how-local-organizing-halted-a-massive-data-center-development-for-nownbsp
- AZ Luminaria (2025). "The Project Blue data center proposal sprang up fast — so did the organizing." https://azluminaria.org/2025/07/21/the-project-blue-data-center-sprang-up-fast-so-did-the-organizing/
- E&E News (2025). "Arizona city rejects data center after AI lobbying push." https://www.eenews.net/articles/arizona-city-rejects-data-center-after-ai-lobbying-push/
- Deseret News (2026). "Chandler, Arizona rejects data center proposal." https://www.deseret.com/
- Watkins, J. (2026). "Datacenter Opposition." The Infinite Unknown. https://www.jaredwatkins.com/research/datacenter-opposition/
- Mongabay (2024). "As lithium mining bleeds Atacama salt flat dry, Indigenous communities hit back." https://news.mongabay.com/2024/12/as-lithium-mining-bleeds-atacama-salt-flat-dry-indigenous-communities-hit-back/
- Rest of World / Hao, K. (2025). "The real cost of AI is being paid in deserts far from Silicon Valley." https://restofworld.org/2025/ai-resource-extraction-chile-indigenous-communities/
- Madani, K., Nunbogu, A., Farsi, A., & Matin, M. (2026). "Critical Minerals, Water Insecurity and Injustice." United Nations University Institute for Water, Environment, and Health (UNU-INWEH). https://unu.edu/inweh/collection/unu-inweh-report-critical-minerals-water-insecurity-and-injustice
- The Conversation / Madani, K. (2026). "The race to mine critical minerals for AI and clean energy is creating 'sacrifice zones'." https://theconversation.com/the-race-to-mine-critical-minerals-for-ai-and-clean-energy-is-creating-sacrifice-zones-that-harm-water-and-health-of-worlds-poor-281524

### Section 4: Structural omissions
- US Department of Defense (2025). "Chief Digital and Artificial Intelligence Office." https://www.ai.mil
- Defense News (2024). "Pentagon to oversee $3 billion effort to strengthen microchip supply." https://www.defensenews.com/pentagon/2024/09/16/pentagon-to-oversee-3-billion-effort-to-strengthen-microchip-supply/
- ODNI (2025). "ICD-505: Artificial Intelligence." Office of the Director of National Intelligence. https://www.dni.gov/files/documents/ICD/ICD-505-Artificial-Intelligence.pdf
- CRS (2023). "Semiconductors and the CHIPS Act: The Global Context." Congressional Research Service, R47558. https://www.congress.gov/crs-product/R47558
- Tom's Hardware (2024). "Intel cleared to get $3.5 billion to make advanced chips for Pentagon — Secure Enclave program." https://www.tomshardware.com/tech-industry/intel-cleared-to-get-dollar35-billion-to-make-advanced-chips-for-pentagon-secure-enclave-program-ushers-leading-edge-cpus-to-the-military
- US Congress (2025). "National Defense Authorization Act for Fiscal Year 2026." Pub. L. 119-60. https://www.govinfo.gov/content/pkg/PLAW-119publ60/html/PLAW-119publ60.htm
- EveryCRSReport (2026). "Cyber and Artificial Intelligence Provisions in the FY2026 NDAA." IF13197. https://www.everycrsreport.com/reports/IF13197.html
- Variety (2023). "WGA AI Deal Explained." https://variety.com/2023/biz/news/wga-ai-deal-explained-writers-strike-1235748567/
- Data Center Watch (2025). "$64 billion of data center projects have been blocked or delayed amid local opposition." https://www.datacenterwatch.org/report
- Data Center Frontier (2025). "Community Opposition Emerges as New Gatekeeper for AI Data Center Expansion." https://www.datacenterfrontier.com/site-selection/article/55359925/community-opposition-emerges-as-new-gatekeeper-for-ai-data-center-expansion
- Bloomberg (2025). "AI Is Draining Water From Areas That Need It Most." https://www.bloomberg.com/graphics/2025-ai-impacts-data-centers-water-data/
- Colorado River Basin post-2026 operating guidelines (2024). Bureau of Reclamation. https://www.usbr.gov/ColoradoRiverBasin/


## Section-by-section sub-agent reviews

Three adversarial reviewers were dispatched in parallel, each from a different
critical-disciplinary angle, against the four researched additions above. The
reviews are intentionally sharp — they are *adversarial*, not consensus-building
— and the recommendations should be read as steel-manning, not capitulation.

**Reviewer A** — political economy / heterodox economics
(after Tooze, Gabor, Christophers). Scope: Sections 1–2.

**Reviewer B** — labour studies / STS
(after Dubal, Irani, Levy). Scope: Section 3.

**Reviewer C** — security studies + climate attribution
(after Kreps, Otto). Scope: Sections 4a–4c.

---

### Reviewer A — Sections 1 & 2

#### Section 1 review

**Load-bearing weakness.** The section's pivotal claim — that capital "shapes the agonistic field" as a first-class node — rests on the sentence: *"This is not passive demand — it is active capital deployment that pre-commits to energy, water, and land consumption at a scale that crowds out other uses and shapes grid planning."* Capex figures alone do not demonstrate "crowding out"; they demonstrate spending. The crowding-out claim requires showing that marginal datacentre investment displaces alternative uses of the same capital, grid capacity, or siting — not just that the absolute number is large. Hyperscaler capex is funded largely from retained earnings and corporate bonds, not from a fixed pool contested by housing or municipal utilities. The mechanism is asserted, not modelled.

**Evidence gaps.** Three citations do less work than implied. (1) The "Juniewicz, 2026" and "Bommarito, 2025" references are not authoritative sources for capex tracking — the load-bearing series should be company 10-Ks and Dell'Oro/Synergy Research, not a single industry-analyst blog. (2) The Norway GIC "cautious posture" line treats a fiduciary risk note as evidence of intra-capital antagonism; it is more plausibly read as standard portfolio rebalancing. (3) The BlackRock/GIP-MGX partnership is cited as evidence of a coordinated bloc, but BlackRock-GIP and MGX are passive LPs in most deals — the section conflates capital allocation with strategic alignment. Missing: any reference to Brett Christophers' *Our Lives in Their Portfolios* or Daniela Gabor's "Wall Street Consensus" framing, both of which would actually theorise asset-manager capitalism as a node — instead the section just inventories deal sizes.

**Causal-chain weakness.** "$175B of private capital into datacentre consolidation" → "actors sit in the same agonistic field" is a non sequitur. Co-presence in a sector is not antagonism; PE rollups and SWF LP-stakes typically operate in syndication, not contestation. The section needs to show one decision where capital allocators overrode a hyperscaler tenant or a grid operator.

**Fix one thing.** Replace the capex-as-power argument with a single documented case where a specific financier's term sheet (covenant, take-or-pay PPA, water-rights clause) altered a siting outcome. Without that, "capital as a node" remains descriptive rather than agonistic.

#### Section 2 review

**Load-bearing weakness.** The loop's closure depends on Edge 5: *"The loop closes when water availability becomes a binding permit condition."* The Goodyear/Microsoft example is a voluntary technology switch, not a binding permit denial — it does not close the loop, it shows the loop being pre-empted by negotiation. A genuine closed loop requires demonstrating that water scarcity *forced* a load reduction or relocation, not that a hyperscaler chose air cooling to avoid future friction.

**Evidence gaps.** (1) The "Caretta et al., 2022" 7%-per-°C figure is from IPCC AR6 WGII Ch. 4 but refers to *population exposure*, not water *availability* — the section elides exposure (a demographic measure) with hydrological supply. (2) The "Colorado River flows declining 9% per °C warming" is closer to Milly & Dunne (2020, *Science*) than to AR6; the citation is mis-attributed. (3) Dominion's "moratorium" is overstated — it was a deferral of new connections in specific substations, lifted in 2024 (see PJM and Dominion 2024 IRP). (4) The PJM IMM quote is real but refers to capacity-market tightness, not generation mix; using it to support fossil reactivation conflates capacity scarcity with dispatch.

**Causal-chain weakness.** Edges 3 and 4 chain marginal gas emissions to regional water scarcity within a loop time-constant of months-to-years, but climate-to-hydrology lag is decadal. The loop as drawn assumes that *this decade's* datacentre emissions tighten *this decade's* water budget in the Southwest. They don't — current Southwest aridification reflects multi-decade forcing. The loop is real on a 30-year horizon; it is presented as operational "today."

**Fix one thing.** Drop Edge 3-4 and reframe the loop as: datacentre load → grid stress → siting moratorium (Edge 2 → Edge 5 directly, via interconnection queues and water-utility permit conditions). That loop closes in 12-36 months with hard evidence (Dominion deferrals, Chandler rejection); the climate-mediated version requires a longer time-constant the section does not acknowledge.

---

### Reviewer B — Section 3

#### Section 3 review

**1. Conflating contract wins with structural shifts.** The sentence "This was the first major labour contract to explicitly fence AI's scope of work" overstates the WGA MBA's reach. The 2023 MBA does *not* prohibit studios from training models on writers' work — it requires disclosure and preserves writers' right to *consent or refuse* on a per-deal basis, and the "source material" carve-out is a credit-determination provision, not a capital-labour boundary. Studios retained the right to *require* writers to use AI tools provided by the company (Article 72 §B.1.c). Reading the contract as "fencing AI's scope of work" mistakes a jurisdictional credit ruling for a structural constraint on capital's deployment of generative systems. Same problem with the ILA claim: the Master Contract bans "fully automated" terminals — a category that already barely exists in US ports — while permitting the semi-automated stacking cranes that are the actual frontier of displacement (see Bonacich & Wilson, *Getting the Goods*, 2008; Levy, *Data Driven*, 2023, ch. 5, on the semi-/fully-automated distinction as union-busting terminology).

**2. Antagonists named, conflict-relation absent.** The section juxtaposes WGA, ILA, AWU-CWA, Pima County water districts, and Atacameño communities as if they constitute an arena, but supplies zero evidence of *coordination, mutual recognition, or even discursive contact* among them. Mouffe's agonism requires adversaries in a shared symbolic space contesting the same hegemonic formation. The WGA fought AMPTP; the ILA fought USMX; AWU-CWA fights Alphabet HR; Atacameño communities fight SQM and Albemarle. These are parallel grievances against different fractions of capital, not an arena. The section needs to either show the linkages (e.g., the AFL-CIO Tech Institute, the Athena Coalition on hyperscaler organising) or downgrade the claim from "agonistic arena" to "dispersed resistances."

**3. Citation quality.** Hollywood Reporter, Labor Notes, CNBC, Mongabay, Rest of World are doing load-bearing work where primary sources exist: the WGA MBA text itself; the ILA-USMX Master Contract; NLRB Region 32 filings against Google; the Defensoría de los Pueblos Indígenas complaint. Karen Hao's *Empire of AI* (2025) is cited via Rest of World rather than the book. The UNU-INWEH report is cited correctly — good — but is the exception.

**4. Mouffe-fit.** These cases are antagonistic, not agonistic. The ILA framed automation as existential; Atacameño leaders use "sacrifice zone" — enemy-language, not adversary-language. Mouffe's frame demands the move *from* antagonism *to* agonism via shared institutions; the paper presents the raw antagonism and calls it agonism.

**5. If you fix one thing:** Replace the WGA sentence with the actual MBA language on consent/disclosure/training-data, and concede that no current US labour contract structurally constrains capital's AI deployment — only its credit and consent surface. That single edit forces honest reckoning with everything else in the section.

---

### Reviewer C — Sections 4a, 4b, 4c

#### Section 4a review

**Most overstated claim.** "These military programs compete with civilian AI datacentres for the same advanced chips, cooling infrastructure, and trained personnel". At ~$1B CDAO + $3B Microelectronics Commons + $3.5B Intel Secure Enclave, DoD AI spend is rounding error against the ~$300B+ FY25 hyperscaler capex (MSFT/GOOG/META/AMZN). Right-size it: DoD is a *price-insensitive premium tenant* on hyperscaler capacity, not a rival demand-shaper.

**Input-vs-outcome metrics.** Every cite is a programme announcement (CDAO standup, $3B Commons, ICD-505 issuance, NDAA provisions) — i.e., authorisations, not obligations or deliveries. No procurement-execution outcome metric appears: not JWCC task-order burn, not Replicator drone count fielded, not Maven inference throughput. The $52.7B CHIPS figure is appropriated; TSMC Arizona N4 yields and Intel 18A fab schedule slips are the outcome data and they cut against the "competing demand" story.

**Procurement direction (the inversion).** The framing is wrong. JWCC (2022, $9B ceiling) flows TO Microsoft/Google/Oracle/AWS; Palantir's Maven Smart System ($480M → $1.3B extension, May 2025) and Anduril's Lattice are themselves built on hyperscaler GPU pools (Anduril's Sept 2024 partnership with Microsoft + OpenAI is explicit). DoD is a *customer of* the hyperscaler stack, which means military demand *amplifies* hyperscaler buildout rather than competing with it. The paper's "active contestant from within the state apparatus" framing should be inverted: state and hyperscaler are co-constituted on the supply side, which is a stronger Mouffian claim, not a weaker one.

**Fix one thing.** Replace the "competes with civilian datacentres" sentence with the JWCC/Maven/Anduril-on-Azure pipeline and cite contract obligations (USAspending.gov), not authorisations.

#### Section 4b review

**Most overstated claim.** "The ILA dockworkers' 2024 contract … codified expanded automation protections: the agreement bans fully automated terminals". The Jan 2025 MOU language preserves the *existing* ban from the 2018 master contract and adds semi-automated equipment review; it does not expand the ban to new categories. Right-size: ILA *held* the line; it did not extend it.

**Input-vs-outcome metrics.** "48 projects blocked or delayed" (Watkins) and the "$64B" Data Center Watch figure conflate cancellation, pause, and zoning-stage rejection — input proxies. The outcome metric is *net MW commissioned*, which per EIA and Lawrence Berkeley is still tracking record-high in 2025. Local wins are real but the aggregate trajectory is undented; the section should say so.

**Fix one thing.** Add an outcome line: cite MW commissioned vs MW blocked (LBNL 2025 datacentre report) so the counter-power claim is calibrated rather than declared.

#### Section 4c review

**Most overstated claim.** "Projected datacentre water demand could consume 15–25% of remaining municipal allocations by 2030" — Ceres' high-bound scenario is presented as central. Use the midpoint and disclose the assumed PUE/WUE trajectory.

**Is "exogenous" right? No.** This is the section's structural error. Datacentre electricity demand is materially endogenous to warming via (i) marginal generation increasingly gas-peaker in ERCOT/MISO 2024–25 (S&P Global), (ii) embodied emissions in TSMC/Samsung fab energy, (iii) Scope 2 accounting gaps in hyperscaler RECs. Treating climate as exogenous forcing collapses the feedback loop the paper claims as its "missing dynamical core" — you cannot simultaneously call it a closure ("the commons is shrinking as a direct function of the same emissions that datacentres are helping to generate") and model it as exogenous. Pick one. The correct framing is a *coupled* system with a positive feedback gain that is small per-datacentre but non-negligible at fleet scale.

**Input-vs-outcome metrics.** "Colorado River allocations already cut by 21%" mixes the Tier 1 shortage declaration with the post-2026 guidelines (still in draft as of the cite). Use Lake Mead elevation and actual Lower Basin delivery cuts (Reclamation 24-Month Study), not the policy instrument.

**Fix one thing.** Rewrite the section as endogenous coupling with an explicit feedback diagram: datacentre load → marginal gas MWh → CO₂ → regional warming → cooling demand + water stress → siting constraint. That is the dynamical core; "exogenous forcing" gives it away.

---

### Synthesis: the five highest-leverage edits

If only five things change in response to these reviews:

1. **Section 1** — Replace the capex-volume argument with a single documented term-sheet override (covenant, take-or-pay PPA, water-rights clause). Capital becomes a node only when its instruments bind.
2. **Section 2** — Collapse Edges 3-4 into a direct grid-stress→permit-condition loop; reserve the climate-mediated loop for a 30-year horizon clearly labelled as such.
3. **Section 3** — Strike the WGA "fence" claim and replace with the MBA's consent/disclosure language; downgrade "agonistic arena" to "dispersed resistances" unless coordination evidence is added (Athena Coalition, AFL-CIO Tech Institute).
4. **Section 4a** — Invert the framing: DoD is a hyperscaler customer (JWCC/Maven/Anduril-on-Azure), not a competing demand-shaper. This actually *strengthens* the paper's state-capital co-constitution argument.
5. **Section 4c** — Reclassify climate as endogenous coupled forcing, not exogenous. Add a labelled feedback gain (per-MWh marginal CO₂ → regional warming → cooling demand).

Reviews are advisory; the original sections stand as researched. These edits would be the next pass.
