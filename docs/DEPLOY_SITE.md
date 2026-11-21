# Deploying the showcase site (`site/`)

The site is static: no build step, no functions, no third-party requests. Any static host works.
Live at https://study-guide-pipeline.vercel.app (Vercel project `study-guide-pipeline`, first deployed 2026-11-21).
The project is not linked to Git: nothing deploys on push. Each deploy is a manual CLI run, after the owner's yes.

## Before every deploy
```
py tests/test_site.py        # must print RESULT PASS
```
The gate checks links, the self-only CSP and security headers in `site/vercel.json`, size budgets, and a leak
scan of every served file, and prints the request count of one cold page view (currently 20 requests, 447 kB;
at the Hobby cap of 1,000,000 edge requests a month that is about 50,000 cold page views).

## Redeploy (manual)
```
py tests/test_site.py                                   # RESULT PASS first
cp -r site <temp>/study-guide-pipeline && cd <temp>/study-guide-pipeline
vercel link --yes --project study-guide-pipeline
vercel deploy --prod
```
Deploy from a copy so the CLI's `.vercel/` folder never lands in `site/`.

Current protection (set 2026-11-21, read back from the firewall API): a 300 requests/minute per-IP rate-limit
rule, bot protection in challenge mode, Vercel Authentication on every non-production URL. Command-line clients
such as `curl` get a 429 challenge; browsers load normally. If a link preview fails on some platform, that
platform's fetcher is being challenged: check the firewall log before loosening anything.

One exception, added 2026-11-21: a bypass rule, placed after the rate limit, lets a `GET` of `/` and `/og.png`
through when the user agent matches a link-preview fetcher (WhatsApp, LinkedInBot, facebookexternalhit,
Twitterbot, Slackbot, TelegramBot, Discordbot), because these cannot pass a challenge. LinkedIn's "add a link"
failed to load a preview before the rule and loaded the title and image after it. Checked with that user agent: `/` and `/og.png` answer 200, `/app.js` and a `POST`
still get 429. The user agent can be spoofed, so the rule covers only those two cached files and the per-IP
limit still applies. Delete the rule if the firewall log shows it being abused.

Usage alerts (checked 2026-11-21): the team is on Hobby, which has no usage-alert or spend-management setting
(Spend Management is Pro only), and the team's notification page has no usage category to switch on. The
watch is manual: Team > Usage. On 2026-11-21 the whole team had used about 1,400 CDN requests and 105 MB of
transfer in the previous 30 days, against 1,000,000 requests and 100 GB.

## First-time setup on Vercel (project root = `site/`)
1. Import the GitHub repository, set **Root Directory** to `site`, framework preset **Other**, no build command.
2. Firewall, before the first production deploy: one per-IP rate-limit rule, bot protection on, a saved
   deny-all rule kept ready as the kill switch.
3. Deployment Protection (Vercel Authentication) on preview deployments.
4. After the deploy: open the usage dashboard, confirm the headers with `curl -I`, and turn usage alerts on.
5. Then set the repository's homepage to the production URL and add it to the README.

## Also fine
GitHub Pages or Cloudflare Pages serve the same folder. `vercel.json` headers do not apply there: Cloudflare
Pages needs the same rules in a `_headers` file, and GitHub Pages cannot set a CSP header at all.

## What is public in `site/img/`
Seven page images of generated notes from one guide. No exam paper, receipt, instructor name or shared-drive
link is in them (checked against the local redaction list by the gate). The fonts in `site/fonts/` are subsets
of Latin Modern under the GUST Font License.
