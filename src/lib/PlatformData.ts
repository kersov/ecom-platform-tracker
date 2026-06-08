// (removed duplicate getMostPopularPlatform and misplaced closing brace)
// src/lib/PlatformData.ts
// Model for e-commerce platform tracking data


import data from '../../data.json';

// Precompute ranked platform usage object
function computeRankedPlatformUsage(data: Record<string, Record<string, string>[]>) {
  const usage: Record<string, number> = {};
  let unidentifiedCount = 0;
  Object.values(data).forEach(historyArr => {
    historyArr.forEach(entry => {
      Object.values(entry).forEach(platform => {
        if (platform === "Unidentified") {
          unidentifiedCount++;
        } else {
          usage[platform] = (usage[platform] || 0) + 1;
        }
      });
    });
  });
  // Sort platforms by usage descending
  const sorted = Object.entries(usage).sort((a, b) => b[1] - a[1]);
  // Build ranked object: { '1': { name, count }, ... }
  const ranked: Record<string, { name: string; count: number }> = {};
  sorted.forEach(([name, count], idx) => {
    ranked[(idx + 1).toString()] = { name, count };
  });
  // Add 'unidentified' key
  ranked['unidentified'] = { name: 'Unidentified', count: unidentifiedCount };
  return ranked;
}

const platformUsage = computeRankedPlatformUsage(data);

export type BrandPlatformHistory = Record<string, string>[];
export type PlatformDataRaw = Record<string, BrandPlatformHistory>;

export class PlatformDataModel {
  private data: PlatformDataRaw;
  private platformUsage: Record<string, { name: string; count: number }>;

  constructor(data: PlatformDataRaw, platformUsage: Record<string, { name: string; count: number }>) {
    this.data = data;
    this.platformUsage = platformUsage;
  }

  /**
   * Returns a set of all unique platforms tracked in the data (excluding 'Unidentified').
   */
  getUniquePlatforms(): Set<string> {
    return new Set(
      Object.values(this.platformUsage)
        .filter(p => p.name !== 'Unidentified')
        .map(p => p.name)
    );
  }

  /**
   * Returns the total number of unique platforms tracked (excluding 'Unidentified').
   */
  getTotalPlatforms(): number {
    return Object.keys(this.platformUsage).filter(k => k !== 'unidentified').length;
  }

  /**
   * Returns the total number of brands tracked.
   */
  getTotalBrands(): number {
    return Object.keys(this.data).length;
  }

  /**
   * Returns the platform by rank (1 = most popular, 2 = second, ...).
   */
  getPlatformByRank(rank: number = 1): { name: string; count: number } | null {
    const key = rank.toString();
    return this.platformUsage[key] || null;
  }

  /**
   * Returns the Unidentified platform usage.
   */
  getUnidentifiedUsage(): { name: string; count: number } {
    return this.platformUsage['unidentified'];
  }

  /**
   * Builds a historical time series of how many sites run each platform on
   * every observation date, from the earliest record up to today.
   *
   * Each site's platform is forward-filled: a site keeps its last detected
   * platform until the next change, so a site with a single record counts
   * toward that platform on every date from its first observation onward.
   *
   * Returns rows shaped for a Recharts LineChart, e.g.
   *   [{ date: '2025-11-04', Shopify: 12, Magento: 3, ... }, ...]
   * alongside the list of platform names (one line each).
   */
  getPlatformTrend(today: string = new Date().toISOString().slice(0, 10)): {
    data: Array<Record<string, string | number>>;
    platforms: string[];
  } {
    // Flatten each brand into chronologically sorted { date, platform } records.
    // ISO date strings sort correctly lexicographically; sort is stable, so
    // same-day records keep their original order (last one wins as "current").
    const brands = Object.values(this.data).map(history =>
      history
        .map(entry => {
          const [date, platform] = Object.entries(entry)[0];
          return { date, platform };
        })
        .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
    );

    // X-axis: every date anything was observed, plus today so lines reach now.
    const dateSet = new Set<string>();
    const platformSet = new Set<string>();
    brands.forEach(history =>
      history.forEach(r => {
        dateSet.add(r.date);
        platformSet.add(r.platform);
      })
    );
    dateSet.add(today);
    const dates = Array.from(dateSet).sort();
    const platforms = Array.from(platformSet);

    const data = dates.map(date => {
      const row: Record<string, string | number> = { date };
      platforms.forEach(p => (row[p] = 0));
      brands.forEach(history => {
        // The site's active platform on `date` is its last record on/before it.
        // Skip sites not yet observed (first record is after `date`).
        let active: string | null = null;
        for (const r of history) {
          if (r.date <= date) active = r.platform;
          else break;
        }
        if (active !== null) row[active] = (row[active] as number) + 1;
      });
      return row;
    });

    return { data, platforms };
  }
}


// Export a default instance for convenience
export const platformDataModel = new PlatformDataModel(data as PlatformDataRaw, platformUsage);
