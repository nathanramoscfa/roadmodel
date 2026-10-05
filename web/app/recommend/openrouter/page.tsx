// web/app/recommend/openrouter/page.tsx
//
// Where OpenRouter returns a visitor after "Connect OpenRouter" (the PKCE
// callback_url, lib/openrouter-connect.ts). The work happens in the browser
// (components/OpenRouterCallback.tsx): the code leaves the address bar at
// once, is exchanged for a key, and the key goes back to /recommend in memory.
import { OpenRouterCallback } from "@/components/OpenRouterCallback";

export const metadata = {
  title: "Connecting OpenRouter — roadmodel",
  robots: { index: false, follow: false },
};

export default function OpenRouterCallbackPage() {
  return (
    <section className="mx-auto max-w-xl px-6 py-16">
      <OpenRouterCallback />
    </section>
  );
}
