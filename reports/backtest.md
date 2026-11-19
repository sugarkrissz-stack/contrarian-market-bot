# Contrarian event-study backtest — 2026-11-19 20:42 UTC

Entry = close of the trigger bar. Win = positive return at the horizon (trade's direction). MAE = median worst move AGAINST the trade before the horizon ends. `Stop x%` = share of trades whose adverse move reached x% at some point (daily candles use the daily low/high, so intraday order is unknown). Each trigger row is followed by a random-day baseline: if the trigger does not beat it, it is not an edge. Rows with n < 20 are marked thin. Past results, small samples, no fees or funding costs.

## A. Fear & Greed extremes (daily, UTC)

### BTC (2200 daily bars from 2020-11-10)

**LONG when F&G < 20** — 41 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 2% | Stop 3% | Stop 5% | Stop 8% | Win w/o 5% stop |
|---|---|---|---|---|---|---|---|---|---|---|
| 1d after | 41 | 49% | -0.92% | -0.05% | 2.78% | 63% | 49% | 29% | 10% | 49% |
| 1d random-day baseline | 2199 | 50% | +0.11% | +0.00% | 1.47% | 39% | 24% | 10% | 3% | 49% |
| 3d after | 41 | 59% | -0.44% | +0.54% | 4.48% | 83% | 66% | 41% | 17% | 46% |
| 3d random-day baseline | 2197 | 52% | +0.32% | +0.20% | 2.67% | 61% | 46% | 26% | 11% | 48% |
| 7d after | 40 | 58% | +0.30% | +1.62% | 6.98% | 88% | 78% | 58% | 28% | 38% |
| 7d random-day baseline | 2193 | 52% | +0.78% | +0.21% | 4.22% | 74% | 63% | 43% | 23% | 42% |
| 14d after | 40 | 48% | -0.14% | -0.63% | 7.84% | 95% | 82% | 70% | 42% | 28% |
| 14d random-day baseline | 2186 | 52% | +1.59% | +0.46% | 5.94% | 82% | 73% | 56% | 38% | 37% |
| 30d after | 40 | 52% | -0.20% | +0.25% | 8.79% | 95% | 82% | 72% | 58% | 28% |
| 30d random-day baseline | 2170 | 54% | +3.59% | +1.30% | 8.72% | 87% | 81% | 69% | 54% | 28% |

**SHORT when F&G > 80** — 25 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 2% | Stop 3% | Stop 5% | Stop 8% | Win w/o 5% stop |
|---|---|---|---|---|---|---|---|---|---|---|
| 1d after | 25 | 40% | -1.13% | -0.77% | 3.03% | 60% | 52% | 20% | 12% | 40% |
| 1d random-day baseline | 2199 | 50% | -0.11% | -0.00% | 1.44% | 38% | 23% | 10% | 3% | 49% |
| 3d after | 25 | 40% | -3.09% | -1.29% | 4.49% | 72% | 68% | 44% | 24% | 40% |
| 3d random-day baseline | 2197 | 48% | -0.32% | -0.20% | 2.74% | 62% | 46% | 27% | 11% | 46% |
| 7d after | 25 | 32% | -4.83% | -4.32% | 8.36% | 92% | 88% | 64% | 52% | 28% |
| 7d random-day baseline | 2193 | 48% | -0.78% | -0.21% | 4.34% | 75% | 63% | 44% | 26% | 41% |
| 14d after | 25 | 44% | -8.81% | -4.55% | 10.41% | 92% | 92% | 68% | 60% | 28% |
| 14d random-day baseline | 2186 | 48% | -1.59% | -0.46% | 6.52% | 84% | 77% | 60% | 42% | 32% |
| 30d after | 25 | 28% | -19.17% | -12.22% | 23.57% | 96% | 96% | 80% | 80% | 20% |
| 30d random-day baseline | 2170 | 46% | -3.59% | -1.30% | 10.65% | 90% | 86% | 75% | 62% | 23% |

**LONG setup→trigger (F&G < 20 within 5d, then close > previous day's high)** — 39 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 2% | Stop 3% | Stop 5% | Stop 8% | Win w/o 5% stop |
|---|---|---|---|---|---|---|---|---|---|---|
| 1d after | 39 | 44% | +0.42% | -0.24% | 2.15% | 51% | 36% | 13% | 3% | 44% |
| 1d random-day baseline | 2199 | 50% | +0.11% | +0.00% | 1.47% | 39% | 24% | 10% | 3% | 49% |
| 3d after | 39 | 51% | -0.02% | +0.07% | 3.87% | 77% | 67% | 36% | 8% | 46% |
| 3d random-day baseline | 2197 | 52% | +0.32% | +0.20% | 2.67% | 61% | 46% | 26% | 11% | 48% |
| 7d after | 39 | 46% | -0.63% | -0.59% | 5.03% | 82% | 77% | 54% | 33% | 31% |
| 7d random-day baseline | 2193 | 52% | +0.78% | +0.21% | 4.22% | 74% | 63% | 43% | 23% | 42% |
| 14d after | 39 | 56% | +1.01% | +1.42% | 8.11% | 87% | 82% | 67% | 51% | 31% |
| 14d random-day baseline | 2186 | 52% | +1.59% | +0.46% | 5.94% | 82% | 73% | 56% | 38% | 37% |
| 30d after | 39 | 54% | +0.13% | +0.74% | 9.22% | 90% | 85% | 74% | 59% | 23% |
| 30d random-day baseline | 2170 | 54% | +3.59% | +1.30% | 8.72% | 87% | 81% | 69% | 54% | 28% |

Structure stop (below the trigger day's low), 7d hold: n=39, median risk 4.73%, stopped out 56%, mean result -0.26R
Structure stop (below the trigger day's low), 14d hold: n=39, median risk 4.73%, stopped out 72%, mean result -0.23R

### ETH (2200 daily bars from 2020-11-10)

**LONG when F&G < 20** — 41 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 2% | Stop 3% | Stop 5% | Stop 8% | Win w/o 5% stop |
|---|---|---|---|---|---|---|---|---|---|---|
| 1d after | 41 | 49% | -1.09% | -0.01% | 3.55% | 68% | 61% | 37% | 20% | 44% |
| 1d random-day baseline | 2199 | 51% | +0.14% | +0.09% | 2.00% | 50% | 35% | 17% | 7% | 50% |
| 3d after | 41 | 46% | -1.26% | -0.80% | 6.22% | 88% | 80% | 56% | 32% | 37% |
| 3d random-day baseline | 2197 | 52% | +0.42% | +0.23% | 3.58% | 69% | 57% | 37% | 20% | 46% |
| 7d after | 40 | 45% | -0.04% | -0.81% | 8.50% | 90% | 85% | 68% | 55% | 30% |
| 7d random-day baseline | 2193 | 51% | +1.02% | +0.19% | 5.55% | 80% | 71% | 53% | 36% | 38% |
| 14d after | 40 | 48% | +0.02% | -0.76% | 10.63% | 95% | 92% | 75% | 62% | 25% |
| 14d random-day baseline | 2186 | 50% | +2.09% | +0.11% | 8.28% | 86% | 79% | 65% | 51% | 31% |
| 30d after | 40 | 58% | +2.25% | +4.52% | 11.72% | 95% | 92% | 80% | 65% | 20% |
| 30d random-day baseline | 2170 | 52% | +4.72% | +0.79% | 12.26% | 89% | 85% | 76% | 64% | 23% |

**SHORT when F&G > 80** — 25 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 2% | Stop 3% | Stop 5% | Stop 8% | Win w/o 5% stop |
|---|---|---|---|---|---|---|---|---|---|---|
| 1d after | 25 | 52% | -0.48% | +0.71% | 3.26% | 68% | 52% | 24% | 16% | 48% |
| 1d random-day baseline | 2199 | 49% | -0.14% | -0.09% | 2.00% | 50% | 34% | 15% | 6% | 48% |
| 3d after | 25 | 48% | -1.11% | -0.15% | 4.15% | 76% | 64% | 40% | 20% | 44% |
| 3d random-day baseline | 2197 | 48% | -0.42% | -0.23% | 3.63% | 71% | 57% | 38% | 20% | 44% |
| 7d after | 25 | 44% | -4.81% | -6.08% | 7.38% | 92% | 84% | 80% | 44% | 20% |
| 7d random-day baseline | 2193 | 49% | -1.02% | -0.19% | 5.89% | 80% | 71% | 57% | 38% | 36% |
| 14d after | 25 | 36% | -10.44% | -13.75% | 14.66% | 96% | 92% | 84% | 64% | 16% |
| 14d random-day baseline | 2186 | 50% | -2.09% | -0.11% | 8.61% | 86% | 80% | 67% | 52% | 29% |
| 30d after | 25 | 32% | -21.93% | -3.75% | 20.98% | 96% | 92% | 84% | 72% | 16% |
| 30d random-day baseline | 2170 | 48% | -4.72% | -0.79% | 12.97% | 91% | 86% | 78% | 65% | 21% |

**LONG setup→trigger (F&G < 20 within 5d, then close > previous day's high)** — 39 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 2% | Stop 3% | Stop 5% | Stop 8% | Win w/o 5% stop |
|---|---|---|---|---|---|---|---|---|---|---|
| 1d after | 39 | 51% | -0.10% | +0.03% | 3.32% | 64% | 51% | 26% | 10% | 46% |
| 1d random-day baseline | 2199 | 51% | +0.14% | +0.09% | 2.00% | 50% | 35% | 17% | 7% | 50% |
| 3d after | 39 | 46% | +0.26% | -0.52% | 5.31% | 82% | 69% | 54% | 18% | 38% |
| 3d random-day baseline | 2197 | 52% | +0.42% | +0.23% | 3.58% | 69% | 57% | 37% | 20% | 46% |
| 7d after | 39 | 41% | -0.36% | -2.43% | 6.72% | 90% | 82% | 59% | 38% | 31% |
| 7d random-day baseline | 2193 | 51% | +1.02% | +0.19% | 5.55% | 80% | 71% | 53% | 36% | 38% |
| 14d after | 39 | 49% | +1.32% | -0.26% | 11.01% | 92% | 82% | 67% | 62% | 33% |
| 14d random-day baseline | 2186 | 50% | +2.09% | +0.11% | 8.28% | 86% | 79% | 65% | 51% | 31% |
| 30d after | 39 | 59% | +3.79% | +4.78% | 12.24% | 97% | 87% | 72% | 72% | 26% |
| 30d random-day baseline | 2170 | 52% | +4.72% | +0.79% | 12.26% | 89% | 85% | 76% | 64% | 23% |

Structure stop (below the trigger day's low), 7d hold: n=39, median risk 6.06%, stopped out 54%, mean result -0.06R
Structure stop (below the trigger day's low), 14d hold: n=39, median risk 6.06%, stopped out 64%, mean result +0.00R

## B. Market-shock moves (1H, ~90 days) — fade or continuation?

### BTC (2200 hourly bars)

**Fade the DUMP (LONG after a sharp drop)** — 8 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 1% | Stop 2% | Stop 3% | Win w/o 2% stop |
|---|---|---|---|---|---|---|---|---|---|
| 1h after | 8 ⚠thin | 25% | -0.14% | -0.18% | 0.45% | 12% | 0% | 0% | 25% |
| 1h random-day baseline | 2199 | 49% | -0.00% | -0.00% | 0.19% | 5% | 1% | 0% | 49% |
| 4h after | 8 ⚠thin | 38% | -0.35% | -0.39% | 0.85% | 38% | 25% | 0% | 38% |
| 4h random-day baseline | 2196 | 50% | -0.02% | +0.00% | 0.41% | 20% | 4% | 1% | 50% |
| 12h after | 8 ⚠thin | 25% | -0.14% | -0.12% | 1.59% | 88% | 25% | 12% | 12% |
| 12h random-day baseline | 2188 | 49% | -0.05% | -0.01% | 0.82% | 42% | 16% | 6% | 48% |
| 24h after | 8 ⚠thin | 25% | -0.68% | -0.10% | 1.73% | 100% | 38% | 38% | 12% |
| 24h random-day baseline | 2176 | 48% | -0.13% | -0.08% | 1.28% | 59% | 29% | 15% | 45% |
| 72h after | 8 ⚠thin | 12% | -2.48% | -1.83% | 3.45% | 100% | 75% | 75% | 12% |
| 72h random-day baseline | 2128 | 40% | -0.51% | -0.72% | 2.43% | 82% | 58% | 37% | 32% |

**Fade the PUMP (SHORT after a sharp rise)** — 15 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 1% | Stop 2% | Stop 3% | Win w/o 2% stop |
|---|---|---|---|---|---|---|---|---|---|
| 1h after | 15 ⚠thin | 80% | +0.21% | +0.17% | 0.22% | 7% | 0% | 0% | 80% |
| 1h random-day baseline | 2199 | 51% | +0.00% | +0.00% | 0.18% | 3% | 1% | 0% | 51% |
| 4h after | 15 ⚠thin | 40% | -0.33% | -0.03% | 0.34% | 27% | 7% | 7% | 40% |
| 4h random-day baseline | 2196 | 50% | +0.02% | -0.00% | 0.38% | 15% | 4% | 2% | 49% |
| 12h after | 15 ⚠thin | 47% | -0.18% | -0.25% | 1.18% | 60% | 13% | 13% | 47% |
| 12h random-day baseline | 2188 | 51% | +0.05% | +0.01% | 0.69% | 33% | 12% | 5% | 50% |
| 24h after | 15 ⚠thin | 53% | +0.37% | +0.22% | 1.18% | 67% | 13% | 13% | 53% |
| 24h random-day baseline | 2176 | 52% | +0.13% | +0.08% | 0.96% | 49% | 22% | 10% | 49% |
| 72h after | 15 ⚠thin | 60% | -0.32% | +0.87% | 1.94% | 80% | 40% | 40% | 53% |
| 72h random-day baseline | 2128 | 60% | +0.51% | +0.72% | 1.81% | 71% | 45% | 29% | 46% |

**LONG after a real OI flush (contracts down >= 5%)** — 5 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 1% | Stop 2% | Stop 3% | Win w/o 2% stop |
|---|---|---|---|---|---|---|---|---|---|
| 1h after | 5 ⚠thin | 80% | +0.39% | +0.19% | 0.32% | 0% | 0% | 0% | 80% |
| 1h random-day baseline | 2199 | 49% | -0.00% | -0.00% | 0.19% | 5% | 1% | 0% | 49% |
| 4h after | 5 ⚠thin | 40% | -0.27% | -0.00% | 0.36% | 40% | 20% | 20% | 40% |
| 4h random-day baseline | 2196 | 50% | -0.02% | +0.00% | 0.41% | 20% | 4% | 1% | 50% |
| 12h after | 5 ⚠thin | 60% | -0.38% | +0.14% | 0.36% | 40% | 20% | 20% | 60% |
| 12h random-day baseline | 2188 | 49% | -0.05% | -0.01% | 0.82% | 42% | 16% | 6% | 48% |
| 24h after | 5 ⚠thin | 40% | -0.70% | -0.39% | 1.56% | 60% | 40% | 20% | 40% |
| 24h random-day baseline | 2176 | 48% | -0.13% | -0.08% | 1.28% | 59% | 29% | 15% | 45% |
| 72h after | 5 ⚠thin | 0% | -3.51% | -3.62% | 5.35% | 100% | 100% | 80% | 0% |
| 72h random-day baseline | 2128 | 40% | -0.51% | -0.72% | 2.43% | 82% | 58% | 37% | 32% |

### ETH (2200 hourly bars)

**Fade the DUMP (LONG after a sharp drop)** — 23 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 1% | Stop 2% | Stop 3% | Win w/o 2% stop |
|---|---|---|---|---|---|---|---|---|---|
| 1h after | 23 | 39% | -0.18% | -0.12% | 0.57% | 30% | 4% | 0% | 39% |
| 1h random-day baseline | 2199 | 50% | -0.01% | -0.00% | 0.25% | 8% | 2% | 1% | 50% |
| 4h after | 23 | 61% | +0.16% | +0.42% | 1.03% | 57% | 17% | 4% | 52% |
| 4h random-day baseline | 2196 | 51% | -0.04% | +0.01% | 0.54% | 28% | 9% | 4% | 51% |
| 12h after | 23 | 74% | +0.54% | +0.44% | 1.47% | 70% | 35% | 9% | 52% |
| 12h random-day baseline | 2188 | 52% | -0.12% | +0.06% | 1.03% | 52% | 28% | 14% | 50% |
| 24h after | 23 | 65% | +0.24% | +0.40% | 1.85% | 83% | 48% | 22% | 43% |
| 24h random-day baseline | 2176 | 47% | -0.25% | -0.12% | 1.67% | 66% | 44% | 27% | 42% |
| 72h after | 23 | 39% | -1.12% | -1.71% | 5.18% | 91% | 83% | 61% | 17% |
| 72h random-day baseline | 2128 | 42% | -0.88% | -0.60% | 3.24% | 86% | 70% | 53% | 26% |

**Fade the PUMP (SHORT after a sharp rise)** — 20 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 1% | Stop 2% | Stop 3% | Win w/o 2% stop |
|---|---|---|---|---|---|---|---|---|---|
| 1h after | 20 | 40% | -0.14% | -0.07% | 0.53% | 20% | 5% | 5% | 40% |
| 1h random-day baseline | 2199 | 50% | +0.01% | +0.00% | 0.25% | 7% | 1% | 0% | 50% |
| 4h after | 20 | 45% | +0.23% | -0.05% | 0.85% | 35% | 10% | 10% | 45% |
| 4h random-day baseline | 2196 | 49% | +0.04% | -0.01% | 0.52% | 25% | 6% | 2% | 49% |
| 12h after | 20 | 60% | +0.80% | +0.37% | 1.37% | 60% | 15% | 15% | 55% |
| 12h random-day baseline | 2188 | 48% | +0.12% | -0.06% | 0.93% | 47% | 21% | 10% | 46% |
| 24h after | 20 | 75% | +1.94% | +1.46% | 1.49% | 70% | 30% | 15% | 65% |
| 24h random-day baseline | 2176 | 53% | +0.25% | +0.12% | 1.36% | 61% | 34% | 18% | 46% |
| 72h after | 20 | 70% | +1.05% | +1.47% | 1.72% | 70% | 40% | 35% | 60% |
| 72h random-day baseline | 2128 | 58% | +0.88% | +0.60% | 2.65% | 78% | 61% | 44% | 36% |

**LONG after a real OI flush (contracts down >= 5%)** — 8 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 1% | Stop 2% | Stop 3% | Win w/o 2% stop |
|---|---|---|---|---|---|---|---|---|---|
| 1h after | 8 ⚠thin | 62% | +0.03% | +0.07% | 0.48% | 25% | 0% | 0% | 62% |
| 1h random-day baseline | 2199 | 50% | -0.01% | -0.00% | 0.25% | 8% | 2% | 1% | 50% |
| 4h after | 7 ⚠thin | 100% | +0.74% | +0.62% | 0.43% | 29% | 0% | 0% | 100% |
| 4h random-day baseline | 2196 | 51% | -0.04% | +0.01% | 0.54% | 28% | 9% | 4% | 51% |
| 12h after | 7 ⚠thin | 57% | +0.39% | +0.02% | 0.93% | 43% | 29% | 0% | 57% |
| 12h random-day baseline | 2188 | 52% | -0.12% | +0.06% | 1.03% | 52% | 28% | 14% | 50% |
| 24h after | 7 ⚠thin | 57% | +0.07% | +0.12% | 2.05% | 71% | 57% | 0% | 43% |
| 24h random-day baseline | 2176 | 47% | -0.25% | -0.12% | 1.67% | 66% | 44% | 27% | 42% |
| 72h after | 7 ⚠thin | 57% | +0.35% | +0.43% | 2.05% | 71% | 57% | 29% | 43% |
| 72h random-day baseline | 2128 | 42% | -0.88% | -0.60% | 3.24% | 86% | 70% | 53% | 26% |

_Reading it: if 'Fade the DUMP' has a negative mean, the dump CONTINUED — chasing the move would have beaten fading it._

## C. Funding dislocations (1H candles, ~3 months of OKX funding history)

### BTC (277 funding settlements)

**LONG when funding APR <= -8% (current)** — 0 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 1% | Stop 2% | Stop 3% | Win w/o 2% stop |
|---|---|---|---|---|---|---|---|---|---|
| 4h after | 0 | — | — | — | — | — | — | — | — |
| 4h random-day baseline | 2396 | 51% | +0.00% | +0.01% | 0.38% | 19% | 4% | 1% | 51% |
| 12h after | 0 | — | — | — | — | — | — | — | — |
| 12h random-day baseline | 2388 | 50% | +0.01% | +0.01% | 0.74% | 40% | 15% | 5% | 49% |
| 24h after | 0 | — | — | — | — | — | — | — | — |
| 24h random-day baseline | 2376 | 49% | +0.02% | -0.02% | 1.19% | 56% | 27% | 14% | 47% |
| 72h after | 0 | — | — | — | — | — | — | — | — |
| 72h random-day baseline | 2328 | 43% | +0.11% | -0.51% | 2.21% | 78% | 54% | 34% | 35% |

**LONG when funding APR <= -5.475% (Gemini's relaxed rule)** — 1 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 1% | Stop 2% | Stop 3% | Win w/o 2% stop |
|---|---|---|---|---|---|---|---|---|---|
| 4h after | 1 ⚠thin | 100% | +1.08% | +1.08% | 0.11% | 0% | 0% | 0% | 100% |
| 4h random-day baseline | 2396 | 51% | +0.00% | +0.01% | 0.38% | 19% | 4% | 1% | 51% |
| 12h after | 1 ⚠thin | 100% | +0.70% | +0.70% | 0.69% | 0% | 0% | 0% | 100% |
| 12h random-day baseline | 2388 | 50% | +0.01% | +0.01% | 0.74% | 40% | 15% | 5% | 49% |
| 24h after | 1 ⚠thin | 0% | -2.07% | -2.07% | 3.14% | 100% | 100% | 100% | 0% |
| 24h random-day baseline | 2376 | 49% | +0.02% | -0.02% | 1.19% | 56% | 27% | 14% | 47% |
| 72h after | 1 ⚠thin | 0% | -5.25% | -5.25% | 9.66% | 100% | 100% | 100% | 0% |
| 72h random-day baseline | 2328 | 43% | +0.11% | -0.51% | 2.21% | 78% | 54% | 34% | 35% |

**SHORT when funding APR >= 27.375%** — 0 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 1% | Stop 2% | Stop 3% | Win w/o 2% stop |
|---|---|---|---|---|---|---|---|---|---|
| 4h after | 0 | — | — | — | — | — | — | — | — |
| 4h random-day baseline | 2396 | 49% | -0.00% | -0.01% | 0.36% | 14% | 4% | 2% | 49% |
| 12h after | 0 | — | — | — | — | — | — | — | — |
| 12h random-day baseline | 2388 | 50% | -0.01% | -0.01% | 0.69% | 33% | 12% | 5% | 49% |
| 24h after | 0 | — | — | — | — | — | — | — | — |
| 24h random-day baseline | 2376 | 51% | -0.02% | +0.02% | 0.98% | 49% | 22% | 11% | 48% |
| 72h after | 0 | — | — | — | — | — | — | — | — |
| 72h random-day baseline | 2328 | 57% | -0.11% | +0.51% | 1.87% | 72% | 47% | 31% | 44% |

### ETH (277 funding settlements)

**LONG when funding APR <= -8% (current)** — 6 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 1% | Stop 2% | Stop 3% | Win w/o 2% stop |
|---|---|---|---|---|---|---|---|---|---|
| 4h after | 6 ⚠thin | 67% | +0.76% | +0.35% | 0.58% | 17% | 17% | 17% | 50% |
| 4h random-day baseline | 2396 | 52% | -0.00% | +0.02% | 0.50% | 27% | 9% | 4% | 51% |
| 12h after | 6 ⚠thin | 67% | +0.43% | +0.11% | 1.27% | 83% | 33% | 17% | 50% |
| 12h random-day baseline | 2388 | 53% | -0.01% | +0.07% | 0.98% | 49% | 26% | 13% | 51% |
| 24h after | 6 ⚠thin | 67% | +0.44% | +0.32% | 1.74% | 83% | 50% | 33% | 33% |
| 24h random-day baseline | 2376 | 49% | -0.01% | -0.04% | 1.46% | 63% | 40% | 25% | 44% |
| 72h after | 6 ⚠thin | 67% | -0.18% | +1.28% | 2.35% | 83% | 50% | 50% | 50% |
| 72h random-day baseline | 2328 | 46% | +0.01% | -0.31% | 2.85% | 81% | 64% | 48% | 31% |

**LONG when funding APR <= -5.475% (Gemini's relaxed rule)** — 10 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 1% | Stop 2% | Stop 3% | Win w/o 2% stop |
|---|---|---|---|---|---|---|---|---|---|
| 4h after | 10 ⚠thin | 70% | +0.63% | +0.67% | 0.46% | 30% | 10% | 10% | 60% |
| 4h random-day baseline | 2396 | 52% | -0.00% | +0.02% | 0.50% | 27% | 9% | 4% | 51% |
| 12h after | 10 ⚠thin | 90% | +0.74% | +0.59% | 1.09% | 60% | 20% | 10% | 80% |
| 12h random-day baseline | 2388 | 53% | -0.01% | +0.07% | 0.98% | 49% | 26% | 13% | 51% |
| 24h after | 10 ⚠thin | 80% | +0.85% | +0.49% | 1.51% | 70% | 30% | 20% | 60% |
| 24h random-day baseline | 2376 | 49% | -0.01% | -0.04% | 1.46% | 63% | 40% | 25% | 44% |
| 72h after | 9 ⚠thin | 56% | -0.25% | +0.41% | 3.30% | 67% | 56% | 56% | 44% |
| 72h random-day baseline | 2328 | 46% | +0.01% | -0.31% | 2.85% | 81% | 64% | 48% | 31% |

**SHORT when funding APR >= 27.375%** — 0 episode(s)

| Horizon | n | Win | Mean | Median | Median MAE | Stop 1% | Stop 2% | Stop 3% | Win w/o 2% stop |
|---|---|---|---|---|---|---|---|---|---|
| 4h after | 0 | — | — | — | — | — | — | — | — |
| 4h random-day baseline | 2396 | 48% | +0.00% | -0.02% | 0.51% | 24% | 6% | 3% | 48% |
| 12h after | 0 | — | — | — | — | — | — | — | — |
| 12h random-day baseline | 2388 | 47% | +0.01% | -0.07% | 0.92% | 46% | 20% | 10% | 46% |
| 24h after | 0 | — | — | — | — | — | — | — | — |
| 24h random-day baseline | 2376 | 51% | +0.01% | +0.04% | 1.34% | 60% | 34% | 18% | 44% |
| 72h after | 0 | — | — | — | — | — | — | — | — |
| 72h random-day baseline | 2328 | 54% | -0.01% | +0.31% | 2.60% | 78% | 61% | 44% | 35% |


##[group]Run if [ -f reports/backtest.md ]; then cat reports/backtest.md >> "$GITHUB_STEP_SUMMARY"; fi
[36;1mif [ -f reports/backtest.md ]; then cat reports/backtest.md >> "$GITHUB_STEP_SUMMARY"; fi[0m
shell: /usr/bin/bash -e {0}
env:
  pythonLocation: /opt/hostedtoolcache/Python/3.11.18/x64
  PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.11.18/x64/lib/pkgconfig
  Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.18/x64
  Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.18/x64
  Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.18/x64
  LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.11.18/x64/lib
##[endgroup]
##[group]Run actions/upload-artifact@v4
with:
  name: backtest-report
  path: reports/backtest.md
  if-no-files-found: warn
  compression-level: 6
  overwrite: false
  include-hidden-files: false
env:
  pythonLocation: /opt/hostedtoolcache/Python/3.11.18/x64
  PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.11.18/x64/lib/pkgconfig
  Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.18/x64
  Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.18/x64
  Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.18/x64
  LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.11.18/x64/lib
##[endgroup]
(node:2302) [DEP0040] DeprecationWarning: The `punycode` module is deprecated. Please use a userland alternative instead.
(Use `node --trace-deprecation ...` to show where the warning was created)
With the provided path, there will be 1 file uploaded
Artifact name is valid!
Root directory input is valid!
Beginning upload of artifact content to blob storage
(node:2302) [DEP0169] DeprecationWarning: `url.parse()` behavior is not standardized and prone to errors that have security implications. Use the WHATWG URL API instead. CVEs are not issued for `url.parse()` vulnerabilities.
Uploaded bytes 3932
Finished uploading artifact content to blob storage!
SHA256 digest of uploaded artifact zip is 1f67704cd3efe9c29c1d839f9b737b458c529f0110e3729e809b7016da0938de
Finalizing artifact upload
Artifact backtest-report.zip successfully finalized. Artifact ID 14572706729
Artifact backtest-report has been successfully uploaded! Final size is 3932 bytes. Artifact ID is 14572706729
Artifact download URL: https://github.com/sugarkrissz-stack/contrarian-market-bot/actions/runs/44611158306/artifacts/14572706729
Post job cleanup.
Cache hit occurred on the primary key setup-python-Linux-x64-26.04-Ubuntu-python-3.11.18-pip-8fb3857668e0b6b0562a3f7a1ac1f02ce98d055ddb8f740555d3c4393b5dcf7f, not saving cache.
(node:2314) [DEP0040] DeprecationWarning: The `punycode` module is deprecated. Please use a userland alternative instead.
(Use `node --trace-deprecation ...` to show where the warning was created)
Post job cleanup.
[command]/usr/bin/git version
git version 2.56.1
Temporarily overriding HOME='/home/runner/work/_temp/c3ded594-b541-4817-ba7c-564a102fcc0d' before making global git config changes
Adding repository directory to the temporary git global config as a safe directory
[command]/usr/bin/git config --global --add safe.directory /home/runner/work/contrarian-market-bot/contrarian-market-bot
[command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
[command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
[command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
http.https://github.com/.extraheader
[command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
[command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
[command]/usr/bin/git config --local --name-only --get-regexp ^includeIf\.gitdir:
[command]/usr/bin/git submodule foreach --recursive git config --local --show-origin --name-only --get-regexp remote.origin.url
Cleaning up orphan processes
##[warning]Node.js 20 is deprecated. The following actions target Node.js 20 but are being forced to run on Node.js 24: actions/checkout@v4, actions/setup-python@v5, actions/upload-artifact@v4. For more information see: https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/
