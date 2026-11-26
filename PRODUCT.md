# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
1. **Used-bike buyers (primary, biggest search demand).** Deciding which model and which year to buy. They want to know what breaks on that bike, at roughly what mileage, which years had recalls or problem clusters, and what to check before handing over cash. They read whole pages, which suits a display-ad model.
2. **Current owners.** Something is wrong, or they want to know what is coming. They want to know whether their issue is a known pattern or a one-off, what usually fails next at their mileage, and whether an open recall covers it.
3. **Riders comparing models.** Choosing between two bikes (e.g. MT-07 vs SV650) and wanting each one's repair and recall record side by side instead of forum opinions.

## Product Purpose
motorcycleproblems.com helps riders know what is likely to go wrong with a specific bike, and when, before it costs them money. Success: a rider finds their exact model and leaves knowing what fails, at what mileage, and what to check.

## Positioning
Nobody else answers "what actually breaks on this bike, and at what mileage" from data. Bikes are not rated on opinion: the site combines official recall, complaint and inspection records with an owner-submitted repair log, and labels each figure by what it measures. Competitors (motodealer.co.uk network) only republish UK MOT pass rates, with merged models and no recalls or complaints.

## Operating Context
Visitors arrive mostly from search ("[model] problems", "[model] reliability", "[model] [year] recall") on phone or desktop, often while looking at a listing. Model pages (one per model, ~5,000) are being prepared from the catalogue and are not built yet. The existing live site holds the owner repair-log form and US complaint pages at /complaints/.

## Capabilities and Constraints
- Data (verified 2026-11-26): 21.4 million UK MOT inspections (2005-2025) on 3.24 million individual motorcycles; 15,995 NHTSA owner complaints (US, safety-related); recalls from the US (NHTSA, with makers' recall documents), UK (DVSA), Canada, Japan (MLIT) and the EU (Safety Gate); 5,003 models from 316 brands; owner repair log (part failed + mileage).
- Every figure must be labelled by what it measures (inspection failure, owner complaint, recall, owner repair) and its source and country. NHTSA complaints are US-only, owner-submitted, safety-related; never merged with owner-log counts.
- Primary action: model search ("check a bike before you buy"). Until model pages exist the search is a mock-up.
- Static HTML/CSS/JS on Cloudflare Pages; no framework.
- Revenue model: display ads on long-read model pages (landing page itself should stay clean).

## Brand Commitments
- Name/domain: motorcycleproblems.com.
- Voice: plain, factual, no hype, no opinion ratings. Never use em dashes in copy (owner preference).

## Evidence on Hand
- Real aggregate figures above (data/catalog.sqlite, data/mot/mot.sqlite, data/nhtsa/motorcycles.sqlite on the WD drive).
- Real per-model numbers can be quoted from the catalogue (e.g. MOT failure rates, US complaint counts, recall campaigns).
- No testimonials, press, user counts or reviews exist. Do not fabricate any.

## Product Principles
1. Data, not opinion: every claim traces to a named record type and source.
2. Label what each number measures; never blend sources into one score.
3. Specific beats general: the exact model, years and mileage.
4. Useful before the purchase: lead with what to check, not with a verdict.
5. Keep models apart: never merge different bikes to make numbers bigger.
