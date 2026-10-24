# web-landing-ab_pricing

Two self-hosted landing-page variants for a **web design / copy A/B conversion**
experiment. Persona agent runtime: `application/shared-web-playwright`.

## Services

| Service | URL (compose network) | Design |
|---|---|---|
| `web-a` | `http://web-a` | **Variant A** — value / savings framing, compact single-column layout, plain CTA ("Get started free") |
| `web-b` | `http://web-b` | **Variant B** — premium / outcome framing, hero + testimonial + highlighted "Most popular" plan card, trial CTA ("Start your free trial") |

Both variants offer the **identical product and prices** (Free $0 / Pro $10 /
Business $20). Only the **copy framing and layout** differ, so any conversion
delta isolates the design effect rather than a price or content confound.

## Objective conversion signal

The signup CTA on each page links to `/signup`. Each nginx writes requests to a
real per-service log file (not the image's stdout symlink):

- `web-a` → `/var/log/site/web-a.access.log`
- `web-b` → `/var/log/site/web-b.access.log`

The task collects each file as an artifact from its service, so a `GET /signup`
there is server-side proof that the persona actually converted — independent of
the persona's self-report.

Static pages are baked into each image (`COPY site/`) rather than bind-mounted,
so the environment works in DinD / remote compose providers.
