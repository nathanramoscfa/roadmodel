// web/app/page.tsx
import { Footer } from "@/components/Footer";
import { Hero } from "@/components/Hero";
import { RatingSystem } from "@/components/RatingSystem";
import { RunItLocally } from "@/components/RunItLocally";
import { Surfaces } from "@/components/Surfaces";
import { getCatalogStats } from "@/lib/catalog-models";

export default function HomePage() {
  // Derive the headline numbers from the live catalog so the home page tracks
  // the daily refresh instead of hard-coding counts that go stale.
  const stats = getCatalogStats();

  return (
    <>
      <Hero stats={stats} />
      <Surfaces stats={stats} />
      <RatingSystem stats={stats} />
      <RunItLocally />
      <Footer />
    </>
  );
}
