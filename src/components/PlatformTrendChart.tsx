import { Card } from "@/components/ui/card";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Legend,
  Tooltip,
} from "recharts";
import { platformDataModel } from "../lib/PlatformData";

// A distinct color per platform line. The first five reuse the theme's chart
// vars; the rest are explicit hues so ~9 platforms stay distinguishable.
const LINE_COLORS = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
  "hsl(280 65% 60%)",
  "hsl(330 75% 60%)",
  "hsl(25 85% 55%)",
  "hsl(95 50% 50%)",
  "hsl(0 0% 60%)",
];

const { data: TREND_DATA, platforms: PLATFORMS } = platformDataModel.getPlatformTrend();

export const PlatformTrendChart = () => {
  return (
    <div className="grid gap-6 md:grid-cols-1">
      <Card className="p-6">
        <h3 className="mb-1 text-lg font-semibold text-foreground">
          Platform Adoption Over Time
        </h3>
        <p className="mb-6 text-sm text-muted-foreground">
          Number of tracked sites running each platform on each date. Each site keeps its
          last detected platform until the next change.
        </p>
        <ResponsiveContainer width="100%" height={360}>
          <LineChart data={TREND_DATA} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }}
              minTickGap={24}
            />
            <YAxis
              allowDecimals={false}
              tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: "0.5rem",
              }}
            />
            <Legend />
            {PLATFORMS.map((platform, idx) => (
              <Line
                key={platform}
                type="monotone"
                dataKey={platform}
                stroke={LINE_COLORS[idx % LINE_COLORS.length]}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );
};
