// web/components/FloatingCard.tsx
//
// The hover/focus card behind the /models Score cells and the score charts.
// It renders in a portal and positions itself against the VIEWPORT, so it is
// never clipped by the table's horizontal-scroll box or a chart's frame, and
// never runs off-screen: it opens on the preferred side of its anchor, flips
// to the other side when that has more room, and is clamped inside an 8px
// margin. It is pointer-transparent, so sweeping the mouse over it cannot
// flicker the trigger underneath, and it re-measures on scroll and resize so
// it stays attached to its anchor.
//
// HoverCard wraps an ordinary trigger (a table cell's figure): hover opens it
// for a mouse, a tap toggles it on touch, keyboard focus opens it, Escape and
// a tap elsewhere close it.
"use client";

import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

export interface AnchorRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

type Placement = "below" | "side";

const MARGIN = 8; // minimum distance from every viewport edge
const GAP = 10; // distance from the anchor

const CARD_CLASS =
  "pointer-events-none fixed z-50 max-w-[calc(100vw-16px)] rounded-lg border border-brand-slate-200 bg-white p-3.5 text-left text-[13px] font-normal normal-case leading-5 tracking-normal text-brand-slate-700 shadow-xl shadow-brand-slate-900/10 dark:border-brand-slate-600 dark:bg-brand-slate-800 dark:text-brand-slate-200 dark:shadow-black/40";

function place(
  a: AnchorRect,
  w: number,
  h: number,
  vw: number,
  vh: number,
  placement: Placement,
): { left: number; top: number } {
  const clampX = (x: number) => Math.min(Math.max(MARGIN, x), Math.max(MARGIN, vw - w - MARGIN));
  const clampY = (y: number) => Math.min(Math.max(MARGIN, y), Math.max(MARGIN, vh - h - MARGIN));
  if (placement === "side") {
    const right = a.left + a.width + GAP;
    const left = a.left - GAP - w;
    const top = clampY(a.top + a.height / 2 - h / 2);
    if (right + w <= vw - MARGIN) return { left: right, top };
    if (left >= MARGIN) return { left, top };
    // Neither side fits a card this wide (a phone): fall back to below/above.
  }
  const below = a.top + a.height + GAP;
  const above = a.top - GAP - h;
  const left = clampX(a.left + a.width / 2 - w / 2);
  if (below + h <= vh - MARGIN) return { left, top: below };
  if (above >= MARGIN) return { left, top: above };
  // Taller than the room on either side: use the roomier side, kept on screen.
  return vh - below > a.top ? { left, top: clampY(below) } : { left, top: clampY(above) };
}

export function FloatingCard({
  getAnchor,
  id,
  placement = "below",
  testId,
  children,
}: {
  // Read on every layout pass, so a scrolled page or a moved pointer re-anchors.
  getAnchor: () => AnchorRect | null;
  id?: string;
  placement?: Placement;
  testId?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const [, setTick] = useState(0);

  // Runs after EVERY render on purpose: the anchor (a moving pointer on a
  // chart line) and the card's own size (its live readout) can change on any
  // render. It sets state only when the position actually moved, so it
  // settles in one pass and cannot loop.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    const el = ref.current;
    const anchor = getAnchor();
    if (!el || !anchor) return;
    const { width, height } = el.getBoundingClientRect();
    const next = place(
      anchor,
      width,
      height,
      document.documentElement.clientWidth,
      window.innerHeight,
      placement,
    );
    if (!pos || Math.abs(pos.left - next.left) > 0.5 || Math.abs(pos.top - next.top) > 0.5) {
      setPos(next);
    }
  });

  useEffect(() => {
    const bump = () => setTick((t) => t + 1);
    window.addEventListener("scroll", bump, true);
    window.addEventListener("resize", bump);
    return () => {
      window.removeEventListener("scroll", bump, true);
      window.removeEventListener("resize", bump);
    };
  }, []);

  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      ref={ref}
      id={id}
      role="tooltip"
      data-testid={testId}
      className={CARD_CLASS}
      style={{
        left: pos?.left ?? 0,
        top: pos?.top ?? 0,
        visibility: pos ? "visible" : "hidden",
      }}
    >
      {children}
    </div>,
    document.body,
  );
}

// A focusable trigger that shows `card` on hover (mouse), tap (touch/pen), or
// keyboard focus.
export function HoverCard({
  card,
  label,
  className = "",
  triggerTestId,
  cardTestId,
  children,
}: {
  card: ReactNode;
  // Accessible name for the trigger button.
  label: string;
  className?: string;
  triggerTestId?: string;
  cardTestId?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);
  const pointer = useRef<string>("mouse");
  const id = useId();
  const getAnchor = useCallback(() => ref.current?.getBoundingClientRect() ?? null, []);

  // A tap anywhere else closes a card a tap opened.
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  return (
    <>
      <button
        ref={ref}
        type="button"
        aria-label={label}
        aria-describedby={open ? id : undefined}
        data-testid={triggerTestId}
        onPointerEnter={(e) => {
          pointer.current = e.pointerType;
          if (e.pointerType === "mouse") setOpen(true);
        }}
        onPointerLeave={(e) => {
          if (e.pointerType === "mouse") setOpen(false);
        }}
        onPointerDown={(e) => {
          pointer.current = e.pointerType;
        }}
        onClick={() => {
          if (pointer.current !== "mouse") setOpen((o) => !o);
        }}
        onFocus={(e) => {
          if (e.currentTarget.matches(":focus-visible")) setOpen(true);
        }}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
        className={
          "cursor-help rounded-sm border-b border-dotted border-brand-slate-400 outline-none focus-visible:ring-2 focus-visible:ring-brand-accent dark:border-brand-slate-500 " +
          className
        }
      >
        {children}
      </button>
      {open && (
        <FloatingCard getAnchor={getAnchor} id={id} testId={cardTestId}>
          {card}
        </FloatingCard>
      )}
    </>
  );
}
