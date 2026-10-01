# -*- coding: utf-8 -*-
"""Cost model for the Permits pipeline. Stated assumptions, no hidden constants.

Rates: Anthropic first-party, per MTok, as of 2026-06-24. Re-verify before quoting.
Batch API = 50% off both directions. Cache reads = 0.1x input.
"""

RATE = {                      # (input, output) $ per MTok
    'opus5':   (5.0, 25.0),
    'sonnet5': (2.0, 10.0),
    'haiku45': (1.0, 5.0),
}
BATCH = 0.5
CACHE_READ = 0.1


def call(model, fresh_in, cached_in, out, batch=True):
    """Cost of one call in dollars."""
    ri, ro = RATE[model]
    c = (fresh_in * ri + cached_in * ri * CACHE_READ + out * ro) / 1e6
    return c * (BATCH if batch else 1.0)


# ---- assumptions, all editable in one place -------------------------------
PREFIX = 4000      # stable synthesis prefix: schema + work-class ontology + few-shots
PAGE = 3000        # one permit page AFTER stripping scripts/styles/attrs (~30k raw)
SYNTH_OUT = 2000   # emitted extractor
EXTRACT_OUT = 500  # one structured permit record

synth = call('sonnet5', PAGE, PREFIX, SYNTH_OUT)
extract = call('haiku45', PAGE, 0, EXTRACT_OUT)
synth_opus = call('opus5', PAGE, PREFIX, SYNTH_OUT)

print('unit costs (batched, cached)')
print('  synthesis  (Sonnet 5) : $%.4f' % synth)
print('  synthesis  (Opus 5)   : $%.4f' % synth_opus)
print('  fallback extract (Haiku 4.5) : $%.5f' % extract)
print()

# ---- what the October decision gate actually needs -------------------------
print('=' * 64)
print('A. WORK REQUIRED FOR THE OCTOBER DECISION GATE (steps 0-2 + writeup)')
print('=' * 64)
items = [
    ('Spike A: classify 30 portals (1 synth each, some retries)', 30 * 2, synth),
    ('Spike C: template collision over saved HTML (offline, no LLM)', 0, 0.0),
    ('Spike B: reconcile 6 jurisdictions x 12 months', 6 * 12, extract),
    ('Step 2: golden set, ~1,000 records LLM-assisted', 1000, extract),
    ('Step 1: extractor synthesis for 6 pilot jurisdictions', 6 * 3, synth),
    ('Step 1: extract ~5,000 permits across 6 pilots @ FALLBACK', 5000, extract),
]
FALLBACK = 0.05   # share of pages the synthesized extractor cannot handle
gate = 0.0
for label, n, unit in items:
    c = n * unit * (FALLBACK if 'FALLBACK' in label else 1.0)
    gate += c
    print('  %-56s $%6.2f' % (label[:56], c))
print('  %-56s $%6.2f' % ('TOTAL (gate)', gate))
print('  %-56s $%6.2f' % ('  +100% contingency for reruns/mistakes', gate * 2))
print()

# ---- what a national crawl would cost --------------------------------------
print('=' * 64)
print('B. NATIONAL SCALE (NOT needed by October)')
print('=' * 64)
OFFICES = 20069
BUCKET1 = 180
crawl_offices = OFFICES - BUCKET1
for amort in (1, 5, 20):
    n_synth = crawl_offices / float(amort)
    c = n_synth * synth
    print('  synthesis for %5d offices, 1 template per %2d offices : $%8.2f'
          % (crawl_offices, amort, c))
PERMITS = 1_400_000
for frac in (0.02, 0.10, 0.30):
    print('  fallback extraction on %4.0f%% of %sM permits/yr        : $%8.2f'
          % (frac * 100, PERMITS // 1_000_000, PERMITS * frac * extract))
print()
print('=' * 64)
print('VERDICT vs a $40 cap')
print('=' * 64)
print('  gate @ fallback=5%%, x2 contingency      : $%.2f' % (gate * 2))
print()
print('  SENSITIVITY -- gate cost vs fallback fraction (x2 contingency):')
for f in (0.02, 0.05, 0.10, 0.25, 0.50, 1.00):
    base = sum(n * u * (f if 'FALLBACK' in label else 1.0)
               for label, n, u in items)
    flag = 'OVER CAP' if base * 2 > 40 else ''
    print('    fallback %5.0f%% -> $%7.2f  %s' % (f * 100, base * 2, flag))
print()
print('  National crawl : does NOT fit under $40; separate decision')
