# Augmentum Media — Creator Vetting Rubric
**v0.1 – Draft**

## Purpose

This rubric defines the brand-safety and quality criteria applied to every creator surfaced through the Modash discovery pipeline before they reach a campaign manager's shortlist. It is designed to remove creators who pose clear risk, surface edge cases for human review, and let through anyone who is genuinely on-brief without unnecessary friction.

The rubric is a living document. It will be calibrated against historical pod-lead decisions before going live and reviewed quarterly thereafter.

---

## How to Read This Rubric

Every category below produces an outcome at one of three severity levels. **The agent must always cite the specific evidence behind a decision** (post URL, bio excerpt, link destination).

### Severity Levels

- **Hard reject** — Always removed from shortlist, no brief-level overrides. Client cannot opt back in.
- **Soft reject** — Removed by default. Can be re-included via explicit brief-level override.
- **Flag for review** — Stays on shortlist but marked for campaign manager review. Used for edge cases and judgement calls.

---

## Category 1 – Adult and Sexual Content

### Hard Reject
- Explicit nudity in any recent post (visible genitalia, exposed breasts in non-medical context, explicit sexual imagery)
- Direct link in bio, Linktree, Beacons, or other link aggregator to: OnlyFans, Fansly, Fanvue, JustForFans, ManyVids, AdmireMe, IsMyGirl, or any subscription-based adult content platform
- Bio text referencing: "OF", "OnlyFans", "spicy content", "exclusive content" (when paired with subscription or paywall references), "18+", "NSFW", "link for more"
- Use of adult-platform-specific emojis in bio combined with link aggregators (🍑 💦 🔞 paired with paid content references)
- Sex work advocacy or active solicitation in bio / captions

### Soft Reject
- Suggestive content: lingerie-focused posts, sexualised posing as a recurring theme across recent grid, swimwear content that is the dominant category rather than incidental
- Bio language implying paid personal content without naming a platform ("DMs open for collabs", "custom content available")
- Recurring thirst-trap aesthetic where the sexualised presentation, not the wellness/lifestyle topic, appears to be the primary draw

### Flag for Review
- Occasional swimwear or beach content in an otherwise on-brief creator
- Fitness creators with form-focused content that could read as suggestive depending on brief
- Creator has previously posted adult-adjacent content but appears to have pivoted in the last 6+ months

---

## Category 2 – Wellness-Specific Red Flags

**Highest-priority category for Augmentum given the agency's health and wellness client base.** False negatives here create real client risk. Rubric assumes a mainstream wellness client – alternative health clients may need brief-level overrides on some soft rejects.

### Hard Reject
- Active MLM involvement (Herbalife, Arbonne, Optavia, Modere, Beachbody, etc.)
- Pro-eating-disorder content or open promotion of disordered eating patterns
- Pseudo-medical claims (cancer cures, miracle protocols, anti-chemotherapy advocacy)
- Anti-psychiatry / anti-medication advocacy positioned as health guidance

### Soft Reject
- Extreme diet culture (heavy carnivore evangelism, raw-only, prolonged fasting as primary content)
- Anti-vaccine content (advocacy, conspiracy, or misinformation)
- Controversial supplement claims unsupported by mainstream evidence
- Detox / cleanse promotion as recurring theme
- Heavy biohacking content involving unregulated peptides, hormones, or off-label use

### Flag for Review
- Functional medicine / naturopathy content (acceptable for some clients, not others)
- Strong opinions on seed oils, gluten, dairy when not making medical claims

---

## Category 3 – Political and Ideological Content

Default to soft reject for partisan content. Each client brief can override based on values alignment.

### Hard Reject
- Extremist content (white nationalist, eco-terrorist, accelerationist, etc.)
- Conspiracy content as a recurring theme (QAnon, election denial, deep state, etc.)

### Soft Reject
- Overt partisan commentary or candidate endorsements
- Issue advocacy on highly divisive topics (abortion, gun rights, immigration enforcement)

### Flag for Review
- Social issues with broader consensus (women's health access, mental health awareness, LGBTQ+ visibility)
- Cause-led posting where the cause is values-aligned with the brief

---

## Category 4 – General Brand Safety

### Hard Reject
- Hate speech (racism, antisemitism, homophobia, transphobia, ableism)
- Active harassment campaigns or doxxing behaviour
- Illegal drug promotion or sale
- Gambling promotion in non-gambling-licensed brief contexts

### Soft Reject
- Aggressive cancellation or pile-on patterns in recent comment threads
- Public callout history within the last 90 days
- Heavy alcohol-centric content (relevant for non-alcohol brands)

### Flag for Review
- Negative engagement / sentiment patterns without specific incident
- Past controversy outside the recency window but still surfaceable

---

## Category 5 – Authenticity and Audience Quality

These checks largely run via Modash data, but Claude adds a sanity layer on top.

### Soft Reject
- Engagement rate <0.5% on accounts >50k followers (likely inauthentic growth)
- Sudden follower spikes inconsistent with content cadence
- Comment patterns dominated by emoji-only or bot-like responses
- Audience geo mismatch >40% outside the brief target market

### Flag for Review
- Heavy giveaway-driven growth in last 90 days
- Audience age skew significantly outside brief target

---

## Category 6 – Client-Specific Filters (Configurable)

These are not fixed in the rubric. They are passed as brief-level parameters and applied on top of the default categories.

- **Competitor exclusions** — past sponsored posts with named competitor brands
- **Exclusivity windows** — creator has posted with a competitor in the last X days (client-defined)
- **Category conflicts** — e.g. alcohol brand client cannot work with sober-advocacy creators
- **Regulated industry rules** — supplements, CBD, financial, gambling all have FTC / ASA implications that narrow creator eligibility
- **Age gates** — some briefs require 25+ / 30+ / parent-of-X etc. as hard filters

---

## Operational Rules for the Agent

1. **Evidence required** — Every reject or flag must include the specific evidence (post URL, bio text, link destination). No black-box decisions. CMs need to sanity-check the logic.

2. **Confidence scoring** — Each category assessment returns a 0–1 confidence. Below 0.6 = flag, not reject, even for hard-reject categories. Hard reject only fires on confidence ≥0.8.

3. **Recency window** — Vetting looks at the last 30 posts or last 90 days, whichever is shorter. Older content is not grounds for rejection unless it's a pattern continuing into the recent window.

4. **Private accounts** — Cannot be vetted. Return as flag-for-manual-review rather than reject.

5. **Vision calls are expensive** — Run visual analysis only on candidates that have passed bio/caption text screening. Do not analyse every creator in a large discovery pool.

6. **Brief overrides** — The agent accepts brief-level overrides for soft-reject categories (e.g. "political content acceptable for this client"). Hard rejects are never overridable via brief.

7. **Audit log** — Every rejection is logged with creator handle, category, confidence, evidence, timestamp. Reviewable weekly and feeds rubric refinement.

---

## Calibration and Review

The rubric should be pressure-tested before going live and reviewed quarterly.

### Initial Calibration (Pre-Launch)
- Pull 20 creators previously approved by each pod lead and 20 previously rejected
- Run the full vetting pipeline against all profiles
- Measure: false positive rate (approved creators the agent would reject) and false negative rate (rejected creators the agent would approve)
- **Target thresholds:** <5% false positive on hard rejects, <10% false negative on soft rejects
- Iterate rubric wording until thresholds are hit

### Ongoing Calibration
- **Weekly** — review the agent's hard-reject log; any CM disagreement gets logged
- **Monthly** — sample 50 agent-approved creators and have a pod lead spot-check for misses
- **Quarterly** — full rubric review with pod leads; update category thresholds based on new client mix, platform trends, regulatory shifts
