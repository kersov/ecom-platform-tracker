# Ecom Platform Tracker

See the platform usage results on the [website](https://kersov.github.io/ecom-platform-tracker/).

Tracks and visualizes global trends in e-commerce platform usage across regions, industries, and time.

Ecom Platform Tracker provides insights into global e-commerce technology trends by analyzing the usage and market share of popular platforms (like Shopify, SFCC, Magento, and WooCommerce)

---

## 📊 What It Does

- Scans a list of websites daily
- Detects which e-commerce engine each site uses
- Saves results in structured JSON files with historical snapshots
- Updates the data automatically through GitHub Actions

---

## ⚙️ Run Locally

You can run the tracker locally either with **Docker** (recommended) or with **Python**.

### 🐳 Option 1: Using Docker

```bash
# Clone the repository
git clone https://github.com/kersov/ecom-platform-tracker.git

# Build the Docker image
docker build -t ecom-platform-tracker .

# Run the tracker
docker run --rm -v $(pwd):/app ecom-platform-tracker
```