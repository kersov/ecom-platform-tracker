

import { StatsCard } from "./StatsCard";
import { Globe, Star } from "lucide-react";
import { platformDataModel } from "../lib/PlatformData";
import React from "react";

const GoldStarIcon = React.forwardRef<SVGSVGElement, React.ComponentProps<typeof Star>>(
  (props, ref) => <Star color="#FFD700" strokeWidth={3} ref={ref} {...props} />
);
const SilverStarIcon = React.forwardRef<SVGSVGElement, React.ComponentProps<typeof Star>>(
  (props, ref) => <Star color="#C0C0C0" strokeWidth={3} ref={ref} {...props} />
);
const BronzeStarIcon = React.forwardRef<SVGSVGElement, React.ComponentProps<typeof Star>>(
  (props, ref) => <Star color="#cd7f32" strokeWidth={3} ref={ref} {...props} />
);

export const PlatformStats = () => {
  const totalSites = platformDataModel.getTotalBrands();

  return (
    <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
      <StatsCard
        title="Total Sites Tracked"
        value={totalSites.toString()}
        icon={Globe}
        trend="neutral"
      />
      <StatsCard
        title="Top Platform"
        value={(() => {
          const mostPopular = platformDataModel.getPlatformByRank(1);
          return mostPopular ? `${mostPopular.name}: ${mostPopular.count}` : "-";
        })()}
  icon={GoldStarIcon}
        trend="neutral"
      />
      <StatsCard
        title="Runner Up"
        value={(() => {
          const secondPlatform = platformDataModel.getPlatformByRank(2);
          return secondPlatform ? `${secondPlatform.name}: ${secondPlatform.count}` : "-";
        })()}
        icon={SilverStarIcon}
        trend="neutral"
      />
      <StatsCard
        title="Bronze Platform"
        value={(() => {
          const thirdPlatform = platformDataModel.getPlatformByRank(3);
          return thirdPlatform ? `${thirdPlatform.name}: ${thirdPlatform.count}` : "-";
        })()}
        icon={BronzeStarIcon}
        trend="neutral"
      />
    </div>
  );
};
