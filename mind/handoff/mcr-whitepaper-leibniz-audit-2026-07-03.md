# Audit Package: "MCR: A Universal Transition Equation for Multi-Level Information Processing"

**For:** Leibniz (math/logic agent — Z3, Lean/Mathlib, formal verification)
**From:** Chimera (code-production agent), on behalf of the operator
**Source document:** [MCR_WHITEPAPER_EN.md](https://github.com/Player-Kheltz/MCR/blob/main/docs/MCR_WHITEPAPER_EN.md), Kheltz, July 2026
**Source code:** [MCR_AGI.py](https://github.com/Player-Kheltz/MCR/blob/main/MCR_AGI.py) (2,109 lines as of this audit; the whitepaper's abstract claims 950)
**Repo:** https://github.com/Player-Kheltz/MCR
**Date compiled:** 2026-07-03

## How to use this document

This is self-contained — every definition and claim you need is quoted or precisely restated below, so you should not need network access to work the problems. Source URLs are given for provenance/spot-checking only.

Each problem in Part 2 asks for one of five verdicts. Please tag your answer to each problem with exactly one:

- **PROVEN-AS-STATED** — the claim holds under the most charitable faithful formalization.
- **REFUTED** — you have a counterexample or proof of the negation. Give it explicitly (Z3 model / Lean term / concrete numbers).
- **VACUOUS-OR-TRIVIAL** — the claim is technically true but carries none of the content the source attributes to it (state precisely what content is missing and why).
- **ILL-POSED** — a term needed to state the claim precisely is undefined or used inconsistently in the source (name the term, quote both usages, show the inconsistency).
- **TRUE-BUT-WEAKER** — a corrected/restricted version of the claim is provable; state it precisely and prove it, and state exactly what hypothesis the original was missing.

Where I offer a hypothesis about which verdict is likely, it's flagged **[Chimera's prior — verify independently, do not defer to it]**. Treat those as a starting point to check, not an answer key. I have reviewed this document already (informally); the point of sending it to you is to get formal ground-truth on the parts that are actually formalizable, which I cannot do myself.

---

## Part 0 — What this document is

Kheltz's "MCR" (Multi-level Cognitive Registry) whitepaper claims that a single equation — count observed transitions `a → b`, predict via arg-max of the empirical conditional distribution — is a "universal information processor" and that this has implications for how AGI is achieved (§13: "the path to AGI may be one of level discovery rather than architecture invention"). It presents this as a sequence of formal Theorems/Corollaries/Proofs (Defs 1–20, Thms 1–4, Props 1–4) plus a 2,109-line Python implementation as "constructive proof."

I (Chimera) read the whitepaper in full, the implementation, the README, and the author's own validation report (`historia/validacao/resultados.md`), and formed an informal critical assessment. The core finding: the mechanism is exactly a first-order (bigram) Markov frequency counter with arg-max lookup — mathematically unremarkable and well over a century old (Markov 1906, cited by the author) — and several of the "Theorems" either don't establish what they're claimed to establish, or contain unstated steps that, filled in honestly, undercut the conclusion. The empirical "validation" contains zero task-performance evidence (only descriptive entropy/fingerprint statistics on 12 arbitrary sample files).

What follows are the specific, formalizable claims worth your independent scrutiny — the parts of my assessment that are genuinely math/logic questions rather than editorial judgment, which is what you're suited to settle rigorously and I am not.

---

## Part 1 — The formal objects, quoted from the source

### Definitions 1–4 (the core mechanism)

> **Definition 1 (MCR Core).** At level $n$, the MCR equation maintains a sparse matrix $T_n: S_n \times S_n \to \mathbb{N}$ and a frequency vector $f_n: S_n \to \mathbb{N}$, where:
> $$T_n(a,b) = \text{count of observed transitions } a \to b$$
> $$f_n(a) = \sum_{c \in S_n} T_n(a,c)$$
>
> **Definition 2 (Learn Operation).** Upon observing a transition $a \to b$:
> $$T_n(a,b) \leftarrow T_n(a,b) + 1, \qquad f_n(a) \leftarrow f_n(a) + 1$$
>
> **Definition 3 (Predict Operation).**
> $$P_n(b|a) = \frac{T_n(a,b)}{f_n(a)}, \qquad \hat{b} = \arg\max_{b} P_n(b|a), \qquad c(a) = \max_b P_n(b|a)$$

**Verbatim from the implementation** (`MCR_AGI.py`, class `MCR`, confirmed to match Defs 1–3 exactly):

```python
def aprender(self, a, b):                          # "learn"
    a, b = str(a), str(b)
    if a not in self.transicoes:
        self.transicoes[a] = {}
        self.freq[a] = 0
    self.transicoes[a][b] = self.transicoes[a].get(b, 0) + 1
    self.freq[a] += 1
    self.total += 1

def predizer(self, a):                              # "predict"
    a = str(a)
    if a not in self.transicoes or not self.transicoes[a]:
        return (None, 0.0)
    m = max(self.transicoes[a], key=self.transicoes[a].get)
    return (m, self.transicoes[a][m] / self.freq[a])
```

Note this is exactly Defs 1–3 with no hidden machinery: a dict-of-dicts counter plus arg-max. This grounding matters for Problems P1 and P4 below — the code is not more sophisticated than the stated definitions.

### Theorem 1 and Corollary 1 (the universality claim)

> **Theorem 1 (Level Invariance).** For any two levels $n, m \in \mathcal{L}$, the MCR equation produces transition matrices $T_n$ and $T_m$ that are isomorphic up to state space cardinality. Specifically, the learning and prediction algorithms are identical; only the tokenization function $\tau_n$ differs.
>
> *Proof.* The MCR class implements a single `learn(a,b)` and `predict(a)` method. These methods make no reference to the semantic content of $a$ or $b$. The state space $S_n$ is defined entirely by the tokenization function $\tau_n$. Since the same operator $T$ acts on the image of $\tau_n$ for any $n$, the equation is invariant to level choice.
>
> **Corollary 1 (Universality).** If every information processing task can be represented as learning transitions in some state space $S$, and MCR can learn transitions in any $S$ via appropriate $\tau$, then MCR is a universal information processor.

### Theorem 3 (the Q-learning claim)

> **Theorem 3 (Q-Learning Embedding).** Q-learning can be represented as a two-level MCR system:
> $$Q(s,a) \cong T_{\text{Q}}(FP(s), a), \qquad \pi(s) = \arg\max_a T_{\text{Q}}(FP(s), a)$$
>
> **Definition 14 (Q-Update via MCR).** The Bellman update $Q(s,a) \leftarrow Q(s,a) + \alpha[r + \gamma\max_{a'}Q(s',a') - Q(s,a)]$ is implemented as:
> $$T_{\text{Q}}(\text{"Q:"} + FP(s) + \text{":"} + a) \leftarrow Q_{\text{new}}$$
> where $Q_{\text{new}}$ is stored as a transition target, and subsequent predictions retrieve it by maximum likelihood.

### Theorem 2 (the Bridge Score bound)

> **Definition 11 (Bridge Score).** $\mathcal{B}(A,B) = \dfrac{5D + 3E + 2P}{10}$, where:
> - $D$ (Divergence): $1 - \text{Jaccard}(T_A, T_B) \in [0,1]$ by construction.
> - $E$ (Specificity): $-\log_2(p(w))$, where $p(w)$ is the relative frequency of word $w$ in the corpus.
> - $P$ (Depth): length of the generated chain after bridging.
>
> **Theorem 2 (Bridge Normalization).** $\mathcal{B}(A,B) \in [0,1]$ for any $A,B$.
>
> *Proof.* Since $D \in [0,1]$, $E \in [0, \log_2 N]$ normalized, and $P$ has a finite maximum, the weighted sum $(5D+3E+2P)/10$ is bounded by $[0,1]$ **when $D, E, P$ are normalized to $[0,1]$.**

(Emphasis mine. $N$ is not defined anywhere in this section of the source — elsewhere in the paper, in the sample-complexity section, $N := |S_n|$, state-space cardinality; it is unclear whether the same $N$ is meant here, and no normalization map from raw $E$ (which is unbounded above) to $[0,1]$ is given anywhere in the document.)

### Theorem 4 (the sample complexity bound)

> **Theorem 4 (Sample Bound).** For a state space $|S_n| = N$ with observed transitions $M = \sum_{a,b} T_n(a,b)$, the expected error in transition probability estimation satisfies:
> $$\mathbb{E}\left[|P_n(b|a) - \hat{P}_n(b|a)|\right] \leq \sqrt{\frac{1}{2f_n(a)} \ln \frac{2}{\delta}}$$
> with probability $1-\delta$, by Hoeffding's inequality applied to the multinomial distribution of transitions from state $a$.
>
> *Corollary.* Reliable estimation (error $< 0.05$) for each state requires $f_n(a) \geq O(\ln N)$ samples per state, giving total sample complexity $O(N \ln N)$.

### The concluding claim (§13, informal — not stated as a theorem, but is the paper's payload)

> "The level invariance theorem (Theorem 1) shows that claimed specialization is not a mathematical necessity but an architectural choice. ... if general intelligence requires learning transitions in increasingly abstract state spaces, and one equation operates across all such spaces, then the path to AGI may be one of level discovery rather than architecture invention."

---

## Part 2 — Problems

### P1. Is Theorem 1 a parametricity corollary, and if so, is it evidentially empty?

**Setup.** Formalize `learn` and `predict` (Defs 1–3) as functions polymorphic in the carrier type of the state space:

```
learn    : ∀ (S : Type) [DecidableEq S], S → S → StateM (Table S) Unit
predict  : ∀ (S : Type) [DecidableEq S], S → StateM (Table S) (Option S × Float)
```

where `Table S := S → S → ℕ` (or a finite-support equivalent).

**Question.** Reynolds' abstraction theorem ("theorems for free," Wadler 1989) says any term of a parametrically polymorphic type automatically satisfies certain relational properties independent of instantiation. Formalize the applicable free theorem for `learn`/`predict` at this type. Then determine: is Theorem 1, as stated in the source ("the learning and prediction algorithms are identical; only $\tau_n$ differs"), *exactly* the free theorem for this type signature — i.e., a fact that holds of *any* well-typed implementation of this signature, with zero dependence on what `learn`/`predict` actually compute?

**Why it matters.** If yes, Theorem 1 asserts nothing beyond "this code is well-typed and generic in `S`" — true of a no-op stub with the same type, equally. It would carry no information about MCR's capability at any given level, which is the property the paper's Corollary 1 and its AGI conclusion actually need.

**Chimera's prior** [verify independently]: yes, this reduces to parametricity and is evidentially empty for the purpose it's used for in §13. **VACUOUS-OR-TRIVIAL** is my expected verdict, but confirm or refute formally.

---

### P2. Formalize Corollary 1 and test for equivocation

**Setup.** Corollary 1's argument, as literally given:

- $P_1$: "every information processing task can be represented as learning transitions in some state space $S$"
- $P_2$: "MCR can learn transitions in any $S$ via appropriate $\tau$"
- $C$: "MCR is a universal information processor"

**Question.** Define two distinct predicates precisely:

- $\text{Representable}(t, S)$ — task $t$ admits a semantics as a state-transition system over $S$ (i.e., there exists *some* function $g: S \to S$, deterministic or stochastic, whose behavior constitutes correct performance of $t$).
- $\varepsilon\text{-Learnable}_{\text{MCR}}(t, S)$ — MCR's specific estimator (Defs 1–3, first-order frequency count + arg-max, over the *literal* state space $S$ as tokenized, with no history augmentation) converges to error $< \varepsilon$ on task $t$ as sample size $\to \infty$.

Formalize $P_1$ using $\text{Representable}$ and $P_2$ using $\varepsilon\text{-Learnable}_{\text{MCR}}$ (this is the only reading under which $P_2$, as literally stated in the source, is textually supported — the source's "proof" of Theorem 1 only establishes genericity of the code, not a learnability guarantee). Under this formalization, is the syllogism $P_1, P_2 \vdash C$ deductively valid? If $P_2$ as actually justified by the source only supports $\text{Representable}(t,S) \Rightarrow \text{MCR-can-be-run-on}(t,S)$ (a much weaker claim than $\varepsilon\text{-Learnable}$), name the fallacy precisely (this looks like equivocation on "learn," but confirm/name formally) and show the argument is invalid under the honest reading.

**Chimera's prior**: **REFUTED** or **ILL-POSED** (equivocation on "learn" — the source never establishes $\varepsilon\text{-Learnable}_{\text{MCR}}$ for arbitrary tasks, only $\text{Representable}$-adjacent genericity from Theorem 1; P2 in the corollary silently smuggles in the stronger reading).

---

### P3. Construct a task where order-1 MCR has a provable, non-vanishing error floor

This is the sharpest and most self-contained problem in this set — a concrete construction, not just an argument about wording.

**Construction.** Fix alphabet $\Sigma = \{a, b, c\}$. Define two deterministic "modes":
- Mode $X$ emits the infinite repeating pattern $a, b, a, b, a, b, \dots$
- Mode $Y$ emits the infinite repeating pattern $a, c, a, c, a, c, \dots$

Define a data-generating process: partition time into consecutive blocks of length $L$ (large); each block independently is Mode $X$ with probability $q \in (0,1)$ and Mode $Y$ with probability $1-q$, run for the whole block, concatenated into one long observed sequence over $\Sigma$. Let MCR (Defs 1–3, order-1, $S = \Sigma$, i.e. the *raw* symbol as state — this matches how the paper's own worked examples define byte/word-level state spaces, no history augmentation) observe an arbitrarily long prefix of this sequence and learn $T(a{,}\cdot)$, $T(b{,}\cdot)$, $T(c{,}\cdot)$ per Defs 1–2.

**Question.**
1. Show that $b$ and $c$ never co-occur with $a$'s *true* deterministic successor except through the hidden mode — i.e., that the correct next-symbol given `a` is fully determined by which mode the current block is in, information not present in the order-1 state `a` alone.
2. Derive the stationary distribution of $T(a,\cdot)$ under this process and show $\hat{b} = \arg\max_b P(b|a)$ is a *fixed* symbol (either always $b$ or always $c$, whichever mode has larger $q$) regardless of how much data is observed.
3. Prove that MCR's asymptotic per-symbol error rate on this task converges to $\min(q, 1-q) > 0$ for every $q \in (0,1)$ — i.e., prove a **lower bound on error that does not shrink with sample size**, in direct tension with any reading of Theorem 4 as implying error → 0 with enough data. (Theorem 4 bounds *estimation* error of $\hat P_n(b|a)$ around the *true* order-1 conditional $P_n(b|a)$; it says nothing about the gap between that true order-1 conditional and the *task-correct* answer when the generating process is not order-1 Markov over $S$. Confirm this distinction formally and state it as the precise reason Theorem 4 does not contradict your P3 result.)

**Why it matters.** This is a fully explicit countermodel to Corollary 1 as it would need to be read to support §13's AGI claim: a task that is trivially "representable as transitions" in the broad sense ($P_1$), for which MCR (run over the state space the paper itself would naturally choose) provably cannot achieve low error at *any* sample size, for a structural reason (context-conflation) rather than a data-scarcity reason. This is also exactly the well-documented, decades-old failure mode of bigram language models in NLP — so this isn't a contrived edge case, it's the modal failure mode of the mechanism.

**Chimera's prior**: **REFUTED** (of Corollary 1 read as unconditional universal learnability). Please make the proof of the $\min(q,1-q)$ bound rigorous — I have not verified the exact constant, only the qualitative claim that the floor is bounded away from 0.

---

### P4. Is Theorem 3's "embedding" well-typed relative to Definitions 1–2?

**Setup.** Definition 1 types $T_n$ as $S_n \times S_n \to \mathbb{N}$ — a *count*. Definition 2's update is $T_n(a,b) \leftarrow T_n(a,b) + 1$ — increment-only, monotonically non-decreasing, no notion of overwriting with an arbitrary value. Theorem 3 / Definition 14 instead specifies:
$$T_{\text{Q}}(\text{"Q:"} + FP(s) + \text{":"} + a) \leftarrow Q_{\text{new}}$$
— a *direct assignment* of an arbitrary real-valued Q-estimate (which can decrease, and is not a count) into what Definition 1 declared to be a natural-number-valued counting structure, and the "increment by 1" operation of Definition 2 is nowhere used or generalized for this case.

**Question.** Formalize both operations as distinct abstract signatures:
- `count-update : Table(S, ℕ) → S → S → Table(S, ℕ)` (Def 2, monotone increment)
- `value-assign : Table(S, ℝ) → S → ℝ → Table(S, ℝ)` (what Def 14 actually needs, arbitrary overwrite)

Prove or disprove: `value-assign` is *not* derivable as an instance of `count-update` under any type-preserving specialization, without introducing a strictly more general Definition 1' that the source never states. If not derivable (I expect not — the codomain changes from $\mathbb{N}$ to $\mathbb{R}$, and increment becomes overwrite, which are incompatible operation shapes, not merely different parameter choices), then Theorem 3 is not actually proven from Definitions 1–4 as given; state precisely what additional, unstated definition would need to be added to the source's formal system to make Theorem 3 well-formed, and whether that addition would still be compatible with Theorem 1's "single operator $T$" claim (i.e., does patching Theorem 3 break Theorem 1's premise that only $\tau_n$ varies across levels — or does it introduce a *second* kind of level-specific variation, namely the update rule itself, silently defeating Theorem 1's "invariance" claim?).

**Chimera's prior**: **ILL-POSED** — Theorem 3 relies on an operation Definitions 1–2 don't define, and patching it in a way that preserves well-typedness likely reintroduces exactly the per-level variation Theorem 1 claims doesn't exist.

---

### P5. Is Theorem 2's proof valid for the definitions actually given?

**Setup.** As quoted in Part 1: $D \in [0,1]$ by construction (Jaccard-based, fine, note the edge case of two empty sets — Jaccard is conventionally $1$ or undefined there; check whether this edge case can occur and if so how it's handled, or flag as undefined). $E = -\log_2 p(w)$ is, as literally defined, unbounded above as $p(w) \to 0^+$ — nothing in Definition 11 caps $p(w)$ away from 0. $P$ = chain length, a non-negative integer with no stated upper bound in Definition 11 itself (the "finite maximum" is asserted in the proof of Theorem 2, not established in the definition).

**Question.** Construct an explicit numeric counterexample to the *literal* claim "$E \in [0, \log_2 N]$" (for any reasonable reading of $N$ available in context — vocabulary size or corpus size): e.g., a corpus of $10^6$ tokens over a vocabulary of $N=100$ distinct words, with one hapax legomenon $w$ (frequency 1, so $p(w) = 10^{-6}$). Compute $E = -\log_2(10^{-6}) \approx 19.93$ against $\log_2(N) = \log_2(100) \approx 6.64$. Confirm $E > \log_2 N$ in this instance (a two-line Z3 or direct arithmetic check suffices — this doesn't need SMT, just verification that I haven't made an arithmetic error). Then determine: does *any* explicit renormalization map for $E$ (or $P$) appear anywhere in the source document? (I did not find one in my reading — Definition 11 gives raw formulas only; the Theorem 2 proof asserts "normalized to $[0,1]$" as a hypothesis without ever defining the normalizing map.) If none exists, is the proof of Theorem 2 valid as a proof about the *quantities actually defined* in Definition 11, or only about a different, unstated, renormalized version of $D, E, P$?

**Chimera's prior**: **ILL-POSED** (the term "normalized" in the Theorem 2 proof is used without a defining map, and the raw quantities as defined in Def. 11 are not bounded as claimed) — but also flag whether a *natural* choice of renormalization (e.g. $E' = E / \log_2 N_{\max}$ for some stated $N_{\max}$, clipped to $[0,1]$) would rescue the theorem, and if so state that rescued version as a **TRUE-BUT-WEAKER** finding alongside the **ILL-POSED** verdict on the original.

---

### P6. Re-derive Theorem 4 and check for a missing union bound

**Setup.** As quoted. The claimed bound is, per-pair $(a,b)$:
$$\mathbb{E}[|P_n(b|a) - \hat P_n(b|a)|] \leq \sqrt{\tfrac{1}{2 f_n(a)} \ln \tfrac{2}{\delta}} \quad \text{w.p. } 1-\delta$$

**Question.**
1. Re-derive this bound from first principles. The cleanest route: fix $a$, and for a fixed $b$, let $Z_i \in \{0,1\}$ indicate whether the $i$-th transition out of $a$ went to $b$ (Bernoulli, since "did it go to $b$ or not" is a binary event even though the underlying distribution over $b \in S_n$ is multinomial). Apply Hoeffding's inequality to $\hat P_n(b|a) = \frac{1}{f_n(a)}\sum_i Z_i$ directly. Confirm this per-$(a,b)$-pair reduction to a Bernoulli/Hoeffding bound is valid and reproduces the stated bound (I believe it is — this is a standard reduction — but derive it rather than taking my word for it, and check the constants: is it $\ln(2/\delta)$ or should it be $\ln(1/\delta)$ depending on one- vs two-sided Hoeffding, since the source states an *absolute value* bound $|P-\hat P|$, which is two-sided).
2. The stated bound holds with probability $1-\delta$ for one fixed pair $(a,b)$. The paper's Corollary claims "reliable estimation for **each state** requires $f_n(a) \geq O(\ln N)$" — i.e., a guarantee that holds *simultaneously* across (at minimum) all $b \in S_n$ for a fixed $a$, and arguably across all $a \in S_n$ too. Determine whether achieving a *uniform* guarantee across all $|S_n| = N$ outcomes (or all $N$ states) requires a union bound, which would replace $\delta$ with $\delta/N$ (or $\delta/N^2$ for both $a,b$ ranging), changing $\ln(2/\delta) \to \ln(2N/\delta)$ in the per-cell bound. Is this union-bound correction present anywhere in the source's derivation of the $O(N\ln N)$ total sample complexity? If the correction is missing, does the stated $O(N \ln N)$ total sample complexity conclusion still hold once the union bound is correctly applied, or does it change (e.g. to $O(N \ln N)$ still, since $\ln(N/\delta)$ vs $\ln(1/\delta)$ only affects the bound by an additive $\ln N$ term inside an already-$\ln$ factor — check whether this is asymptotically absorbed or actually changes the stated complexity class)?

**Chimera's prior**: the per-pair bound itself is likely **PROVEN-AS-STATED** (standard Hoeffding, correctly cited) modulo the one/two-sided constant, which I have not checked carefully — please do. The *uniform-over-states* framing needed to justify the informal Corollary about total sample complexity is likely missing a union bound; determine whether this is **TRUE-BUT-WEAKER** (needs the correction, but the correction doesn't change the final asymptotic complexity class) or a genuine gap.

---

### P7. Map the full argument Theorem 1 → Corollary 1 → §13's AGI conclusion, and locate every non-sequitur

**Question.** Construct a complete argument diagram (premises, inference rule invoked at each step, conclusion) from Theorem 1 through to the concluding claim quoted in Part 1 ("the path to AGI may be one of level discovery rather than architecture invention"). At each edge in the diagram, classify the inference as: (a) a valid deductive step given the stated premises, (b) a valid step only under an *additional*, unstated premise (name it), or (c) a non-sequitur — the conclusion doesn't follow from the stated premises under any charitable reading. I expect at least the following gap needs to be named explicitly: moving from "one counting mechanism is syntactically reusable across tokenizations" (Theorem 1, which per P1 may itself be vacuous) to "general intelligence may emerge from this" requires an implicit premise that syntactic reusability of a learning mechanism across domains is *sufficient for competent performance* in those domains — a premise the paper never states and that P3 gives a concrete counterexample to. Produce the diagram and the classification; this is the deliverable, not a prose summary.

---

### P8 (constructive/steelman). Find and prove the true, weaker statement in the neighborhood of Corollary 1

This is the generous half of the audit: rather than only tearing down the claim, find the closest *true* formal statement and prove it, so the author has something correct to build from.

**Candidate true statement (Order-Reduction via State Augmentation).** For any stationary $k$-th order Markov process over alphabet $\Sigma$ (i.e., $P(x_{i+1} \mid x_i, \dots, x_{i-k+1})$ depends on the last $k$ symbols), define the augmented state space $S' = \Sigma^k$ (length-$k$ context windows) with transitions $a' = (x_{i-k+1},\dots,x_i) \to b' = (x_{i-k+2},\dots,x_{i+1})$. Then this process *is* exactly first-order Markov over $S'$, and Defs 1–3 applied to $S'$ (not the raw alphabet $\Sigma$) converge to the correct conditional distribution as sample size $\to \infty$, by standard Markov chain estimation theory.

**Question.** State this precisely and prove it (this should be a clean, standard result — check whether Mathlib has sufficient Markov-chain/stochastic-process machinery to formalize it directly, or whether it needs to be done at the level of ordinary probability theory). Then connect it back to the source's own Theorem 4: show that the required $|S'| = |\Sigma|^k$ makes the source's own $O(N \ln N)$ sample complexity **exponential in $k$**, and relate this explicitly to the source's own §12 admission ("First-order Markov assumption... cannot capture long-range dependencies without additional mechanisms"). The point of this problem: the *true* version of "universality" is real but conditional — representable-with-sufficient-augmentation, at a cost that is *exactly* quantified by the paper's own sample-complexity theorem — which is a materially weaker and more interesting claim than the unconditional one in §13, and shows precisely where the paper's own formal apparatus (Theorem 4) already contains the seeds of the correct caveat to its own conclusion, if the author had connected the two sections.

**Deliverable:** a full statement and proof (Lean/Mathlib if feasible, otherwise rigorous pen-and-paper formalized in the same notation as this document), plus the explicit exponential-in-$k$ sample complexity corollary.

---

## Part 3 — What I am *not* asking you to adjudicate

For completeness, so you don't duplicate work outside your remit: I've already separately assessed (a) that the repo's own validation report (`historia/validacao/resultados.md`) contains no task-performance evidence, only descriptive entropy/fingerprint statistics on 12 unrelated sample files, and (b) that the "950 lines" claim in the abstract doesn't match the 2,109-line implementation. These are empirical/bibliographic observations, not math/logic claims, and don't need formal verification — flagging them here only so the full picture is in one place.

## Part 4 — Requested output format

For each of P1–P8: the verdict tag, the formal artifact (Lean proof term, Z3 model/UNSAT core, or explicit numeric witness, as applicable), and a short (≤5 sentence) plain-language statement of what the artifact establishes. For P7, the argument diagram itself is the artifact. A one-paragraph overall summary at the end: does *any* result in P1–P8 survive as genuine support for the paper's §13 AGI conclusion, and if so, which one and under what restated hypotheses.
