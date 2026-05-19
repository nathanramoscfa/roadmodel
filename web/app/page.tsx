// web/app/page.tsx
import { Footer } from "@/components/Footer";
import { Hero } from "@/components/Hero";
import { HowItWorks } from "@/components/HowItWorks";
import { PricingTeaser } from "@/components/PricingTeaser";

export default function HomePage() {
  return (
    <>
      <Hero />
      <HowItWorks />
      <PricingTeaser />
      <Footer />
    </>
  );
}
