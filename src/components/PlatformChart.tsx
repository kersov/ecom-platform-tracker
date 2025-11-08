import { Card } from "@/components/ui/card";
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from "recharts";
import { platformDataModel } from "../lib/PlatformData";

// Generate chart data from real platform usage
const CHART_COLORS = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
  "hsl(var(--chart-6))",
];

const getPlatformChartData = () => {
  // Get all platforms including 'Unidentified', keep original order
  return Object.entries(platformDataModel["platformUsage"])
    .map(([key, p], idx) => ({
      name: key === "unidentified" ? "Unidentified" : p.name,
      value: p.count,
      color: CHART_COLORS[idx % CHART_COLORS.length],
    }));
};

const PLATFORM_DATA = getPlatformChartData();


export const PlatformChart = () => {
  return (
    <div className="grid gap-6 md:grid-cols-1">
      <Card className="p-6">
        <h3 className="mb-6 text-lg font-semibold text-foreground">Market Share Distribution</h3>
        <ResponsiveContainer width="100%" height={300}>
          <PieChart>
            <Pie
              data={PLATFORM_DATA}
              cx="50%"
              cy="50%"
              labelLine={true}
              label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
              outerRadius={80}
              fill="#8884d8"
              dataKey="value"
              minAngle={10} // Prevents very small slices from having overlapping labels
              paddingAngle={2} // Adds space between slices
            >
              {PLATFORM_DATA.map((entry) => (
                <Cell key={entry.name} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );
};
