import { PlatformStats } from "@/components/PlatformStats";
import { PlatformChart } from "@/components/PlatformChart";
import { Github } from "lucide-react";
import { Button } from "@/components/ui/button";

const Index = () => {
  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border bg-card/50 backdrop-blur supports-[backdrop-filter]:bg-card/30">
        <div className="container mx-auto px-4 py-6">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-3xl font-bold text-foreground">E-commerce Platform Tracker</h1>
              <p className="mt-2 text-muted-foreground">
                Global insights into e-commerce technology trends and market share
              </p>
            </div>
            <Button variant="outline" asChild className="w-fit">
              <a
                href="https://github.com/kersov/ecom-platform-tracker"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2"
              >
                <Github className="h-5 w-5" />
                View on GitHub
              </a>
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-4 py-12">
        <div className="space-y-12">
          {/* Description */}
          <section className="rounded-lg border border-border bg-card p-6 shadow-sm">
            <p className="text-foreground leading-relaxed">
              Ecom Platform Tracker provides insights into global e-commerce technology trends by
              analyzing the usage and market share of popular platforms like{" "}
              <span className="font-semibold text-primary">Shopify</span>,{" "}
              <span className="font-semibold text-primary">Salesforce Commerce Cloud</span>,{" "}
              <span className="font-semibold text-primary">Magento</span>, and{" "}
              <span className="font-semibold text-primary">WooCommerce</span>. Our data is
              continuously updated to reflect the latest market dynamics.
            </p>
          </section>

          {/* Stats Cards */}
          <section>
            <h2 className="mb-6 text-2xl font-bold text-foreground">Platform Overview</h2>
            <PlatformStats />
          </section>

          {/* Charts */}
          <section>
            <h2 className="mb-6 text-2xl font-bold text-foreground">Analytics & Trends</h2>
            <PlatformChart />
          </section>
        </div>
      </main>

      {/* Footer */}
      <footer className="mt-20 border-t border-border bg-card/50 py-8">
        <div className="container mx-auto px-4 text-center text-sm text-muted-foreground">
          <p>
            Data updated daily · Last update: {new Date().toLocaleDateString()} · Open source on GitHub
          </p>
        </div>
      </footer>
    </div>
  );
};

export default Index;
