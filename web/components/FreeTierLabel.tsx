// web/components/FreeTierLabel.tsx
import Link from "next/link";

interface FreeTierLabelProps {
  label: string;
}

export function FreeTierLabel({ label }: FreeTierLabelProps) {
  return (
    <p className="text-sm">
      <Link
        href="/pricing"
        className="font-medium text-brand-accent underline-offset-2 hover:underline"
      >
        {label}
      </Link>
    </p>
  );
}
