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
}


// Export a default instance for convenience
export const platformDataModel = new PlatformDataModel(data as PlatformDataRaw, platformUsage);
