// web/components/FloatingCard.tsx
//
// The hover/focus card behind the /models cells, glossary definitions, and the
// score charts. It renders in a portal and positions itself against the VIEWPORT,
// so it is never clipped by the table's scroll box or a chart's frame, and
// never runs off-screen: it opens on the preferred side of its anchor, flips
// to the other side when that has more room, and is clamped inside an 8px
// margin. Chart cards remain pointer-transparent (`interactive={false}`) so
// sweeping across a dense plot stays smooth; table `HoverCard` and
// `GlossaryTerm` popups are `interactive` (`pointer-events-auto`) with a gap
// bridge and height clamp so moving the pointer into the popup keeps it open
// until the pointer leaves the popup, and tall cards scroll cleanly on small
// viewports (with a touch-only close button when opened by tap).
"use client";

import { X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type FocusEvent as ReactFocusEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type RefObject,
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
const GAP = 10; // distance from the anchor for chart cards
const INTERACTIVE_GAP = 6; // fits inside cell vertical padding to avoid exposing adjacent row triggers
const CLOSE_DELAY_MS = 140;

const CARD_CLASS =
  "fixed z-50 max-w-[calc(100vw-16px)] rounded-lg border border-brand-slate-200 bg-white p-3.5 text-left text-[13px] font-normal normal-case leading-5 tracking-normal text-brand-slate-700 shadow-xl shadow-brand-slate-900/10 dark:border-brand-slate-600 dark:bg-brand-slate-800 dark:text-brand-slate-200 dark:shadow-black/40";

// Ensures at most one interactive HoverCard/GlossaryTerm popup is open across the page at a time.
let closeActiveHoverCard: (() => void) | null = null;

function sameRect(a: AnchorRect | null, b: AnchorRect | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    Math.abs(a.left - b.left) <= 0.5 &&
    Math.abs(a.top - b.top) <= 0.5 &&
    Math.abs(a.width - b.width) <= 0.5 &&
    Math.abs(a.height - b.height) <= 0.5
  );
}

function place(
  a: AnchorRect,
  w: number,
  h: number,
  vw: number,
  vh: number,
  placement: Placement,
  gap: number,
): { left: number; top: number; bridge: AnchorRect | null } {
  const clampX = (x: number) => Math.min(Math.max(MARGIN, x), Math.max(MARGIN, vw - w - MARGIN));
  const clampY = (y: number) => Math.min(Math.max(MARGIN, y), Math.max(MARGIN, vh - h - MARGIN));
  if (placement === "side") {
    const right = a.left + a.width + gap;
    const sideLeft = a.left - gap - w;
    const sideTop = clampY(a.top + a.height / 2 - h / 2);
    if (right + w <= vw - MARGIN) return { left: right, top: sideTop, bridge: null };
    if (sideLeft >= MARGIN) return { left: sideLeft, top: sideTop, bridge: null };
    // Neither side fits a card this wide (a phone): fall back to below/above.
  }
  const below = a.top + a.height + gap;
  const above = a.top - gap - h;
  const left = clampX(a.left + a.width / 2 - w / 2);
  let top: number;
  if (below + h <= vh - MARGIN) {
    top = below;
  } else if (above >= MARGIN) {
    top = above;
  } else {
    // Taller than the room on either side: use the roomier side, kept on screen.
    top = vh - below > a.top ? clampY(below) : clampY(above);
  }

  let bridge: AnchorRect | null = null;
  if (top > a.top + a.height) {
    const bLeft = Math.max(left, a.left - 4);
    const bRight = Math.min(left + w, a.left + a.width + 4);
    if (bRight > bLeft) {
      bridge = {
        left: bLeft,
        top: a.top + a.height,
        width: bRight - bLeft,
        height: top - (a.top + a.height),
      };
    }
  } else if (top + h < a.top) {
    const bLeft = Math.max(left, a.left - 4);
    const bRight = Math.min(left + w, a.left + a.width + 4);
    if (bRight > bLeft) {
      bridge = {
        left: bLeft,
        top: top + h,
        width: bRight - bLeft,
        height: a.top - (top + h),
      };
    }
  }
  return { left, top, bridge };
}

export function FloatingCard({
  getAnchor,
  id,
  placement = "below",
  testId,
  interactive = false,
  cardRef,
  bridgeRef,
  onClose,
  onCardPointerEnter,
  onCardPointerLeave,
  onBridgePointerLeave,
  children,
}: {
  // Read on every layout pass, so a scrolled page or a moved pointer re-anchors.
  getAnchor: () => AnchorRect | null;
  id?: string;
  placement?: Placement;
  testId?: string;
  interactive?: boolean;
  cardRef?: RefObject<HTMLDivElement | null>;
  bridgeRef?: RefObject<HTMLDivElement | null>;
  onClose?: () => void;
  onCardPointerEnter?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onCardPointerLeave?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onBridgePointerLeave?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number; bridge: AnchorRect | null } | null>(null);
  const [, setTick] = useState(0);

  const setCardNode = useCallback(
    (node: HTMLDivElement | null) => {
      ref.current = node;
      if (cardRef) cardRef.current = node;
    },
    [cardRef],
  );

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
      interactive ? INTERACTIVE_GAP : GAP,
    );
    if (
      !pos ||
      Math.abs(pos.left - next.left) > 0.5 ||
      Math.abs(pos.top - next.top) > 0.5 ||
      !sameRect(pos.bridge, next.bridge)
    ) {
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
    <>
      {interactive && pos?.bridge && (
        <div
          ref={bridgeRef}
          aria-hidden="true"
          className="pointer-events-auto fixed z-50"
          style={{
            left: pos.bridge.left,
            top: pos.bridge.top,
            width: pos.bridge.width,
            height: pos.bridge.height,
          }}
          onPointerEnter={onCardPointerEnter}
          onPointerLeave={onBridgePointerLeave ?? onCardPointerLeave}
        />
      )}
      <div
        ref={setCardNode}
        id={id}
        role="tooltip"
        data-testid={testId}
        className={
          CARD_CLASS +
          (interactive
            ? " pointer-events-auto max-h-[calc(100dvh-16px)] overflow-y-auto overscroll-contain"
            : " pointer-events-none")
        }
        style={{
          left: pos?.left ?? 0,
          top: pos?.top ?? 0,
          visibility: pos ? "visible" : "hidden",
        }}
        onPointerEnter={interactive ? onCardPointerEnter : undefined}
        onPointerLeave={interactive ? onCardPointerLeave : undefined}
      >
        {interactive && onClose && (
          <div className="sticky top-0 z-10 -mx-3.5 -mt-3.5 mb-2 flex justify-end border-b border-brand-slate-100 bg-white/95 px-2 py-1 backdrop-blur-sm dark:border-brand-slate-700/70 dark:bg-brand-slate-800/95">
            <button
              type="button"
              onClick={onClose}
              aria-label="Close popup"
              data-testid="floating-card-close"
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-brand-slate-500 hover:bg-brand-slate-100 hover:text-brand-slate-900 dark:text-brand-slate-400 dark:hover:bg-brand-slate-700 dark:hover:text-brand-slate-50"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>
        )}
        {children}
      </div>
    </>,
    document.body,
  );
}

// Shared open/close, hover-bridge, blur-guard, and touch-dismissal state for
// interactive portaled popups (HoverCard and GlossaryTerm).
export function useHoverPopup<T extends HTMLElement = HTMLButtonElement>() {
  const [open, setOpen] = useState(false);
  const [openedByTouch, setOpenedByTouch] = useState(false);
  const triggerRef = useRef<T | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const bridgeRef = useRef<HTMLDivElement | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastInsidePointerDownAt = useRef(0);
  const pointer = useRef<string>("mouse");
  const id = useId();
  const getAnchor = useCallback(() => triggerRef.current?.getBoundingClientRect() ?? null, []);

  const cancelClose = useCallback(() => {
    if (closeTimer.current !== null) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }, []);

  const closeImmediate = useCallback(() => {
    cancelClose();
    lastInsidePointerDownAt.current = 0;
    if (closeActiveHoverCard === closeImmediate) {
      closeActiveHoverCard = null;
    }
    setOpenedByTouch(false);
    setOpen(false);
  }, [cancelClose]);

  const openNow = useCallback(
    (touch = false) => {
      cancelClose();
      if (closeActiveHoverCard && closeActiveHoverCard !== closeImmediate) {
        closeActiveHoverCard();
      }
      closeActiveHoverCard = closeImmediate;
      setOpenedByTouch(touch);
      setOpen(true);
    },
    [cancelClose, closeImmediate],
  );

  const scheduleClose = useCallback(() => {
    cancelClose();
    closeTimer.current = setTimeout(() => {
      closeTimer.current = null;
      if (closeActiveHoverCard === closeImmediate) {
        closeActiveHoverCard = null;
      }
      setOpenedByTouch(false);
      setOpen(false);
    }, CLOSE_DELAY_MS);
  }, [cancelClose, closeImmediate]);

  const toggleTouch = useCallback(() => {
    if (open) closeImmediate();
    else openNow(true);
  }, [open, openNow, closeImmediate]);

  const isWithinPopup = useCallback((target: EventTarget | null) => {
    if (!(target instanceof Node)) return false;
    return Boolean(
      triggerRef.current?.contains(target) ||
        cardRef.current?.contains(target) ||
        bridgeRef.current?.contains(target),
    );
  }, []);

  useEffect(() => {
    return () => {
      cancelClose();
      if (closeActiveHoverCard === closeImmediate) {
        closeActiveHoverCard = null;
      }
    };
  }, [cancelClose, closeImmediate]);

  // A tap/click inside the popup records a grace timestamp so a blur on the
  // trigger (e.g. Linux WebKit focusing a tapped button and blurring on card
  // tap with relatedTarget === null) does not dismiss the card; outside taps,
  // external focus changes, and Escape close it immediately.
  useEffect(() => {
    if (!open) return;
    const onPointerDownCapture = (e: PointerEvent) => {
      if (isWithinPopup(e.target)) {
        lastInsidePointerDownAt.current = Date.now();
      } else {
        closeImmediate();
      }
    };
    const onFocusIn = (e: FocusEvent) => {
      if (!isWithinPopup(e.target)) closeImmediate();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeImmediate();
    };
    document.addEventListener("pointerdown", onPointerDownCapture, true);
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDownCapture, true);
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, isWithinPopup, closeImmediate]);

  const triggerProps = {
    ref: triggerRef,
    "aria-describedby": open ? id : undefined,
    onPointerEnter: (e: ReactPointerEvent<T>) => {
      pointer.current = e.pointerType;
      if (e.pointerType === "mouse") openNow(false);
    },
    onPointerLeave: (e: ReactPointerEvent<T>) => {
      if (e.pointerType === "mouse" && !isWithinPopup(e.relatedTarget)) {
        scheduleClose();
      }
    },
    onPointerDown: (e: ReactPointerEvent<T>) => {
      pointer.current = e.pointerType;
      lastInsidePointerDownAt.current = Date.now();
    },
    onClick: (e: ReactMouseEvent<T>) => {
      if (pointer.current !== "mouse") {
        e.preventDefault();
        toggleTouch();
      }
    },
    onFocus: (e: ReactFocusEvent<T>) => {
      if (e.currentTarget.matches(":focus-visible")) openNow(false);
    },
    onBlur: (e: ReactFocusEvent<T>) => {
      if (
        Date.now() - lastInsidePointerDownAt.current < 500 ||
        isWithinPopup(e.relatedTarget)
      ) {
        return;
      }
      closeImmediate();
    },
    onKeyDown: (e: ReactKeyboardEvent<T>) => {
      if (e.key === "Tab") lastInsidePointerDownAt.current = 0;
      if (e.key === "Escape") closeImmediate();
    },
  };

  const cardProps = {
    getAnchor,
    id,
    interactive: true as const,
    cardRef,
    bridgeRef,
    onClose: openedByTouch ? closeImmediate : undefined,
    onCardPointerEnter: (e: ReactPointerEvent<HTMLDivElement>) => {
      if (e.pointerType === "mouse") cancelClose();
    },
    onBridgePointerLeave: (e: ReactPointerEvent<HTMLDivElement>) => {
      if (e.pointerType === "mouse" && !isWithinPopup(e.relatedTarget)) {
        scheduleClose();
      }
    },
    onCardPointerLeave: (e: ReactPointerEvent<HTMLDivElement>) => {
      if (e.pointerType === "mouse" && !isWithinPopup(e.relatedTarget)) {
        closeImmediate();
      }
    },
  };

  return { open, cardProps, triggerProps };
}

// A focusable trigger that shows `card` on hover (mouse), tap (touch/pen), or
// keyboard focus. Interactive mouse hover stays open while moving into or
// hovering over the popup, and closes once the pointer leaves the popup.
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
  const { open, cardProps, triggerProps } = useHoverPopup<HTMLButtonElement>();

  return (
    <>
      <button
        type="button"
        aria-label={label}
        data-testid={triggerTestId}
        {...triggerProps}
        className={
          "cursor-help rounded-sm border-b border-dotted border-brand-slate-400 outline-none focus-visible:ring-2 focus-visible:ring-brand-accent dark:border-brand-slate-500 " +
          className
        }
      >
        {children}
      </button>
      {open && (
        <FloatingCard {...cardProps} testId={cardTestId}>
          {card}
        </FloatingCard>
      )}
    </>
  );
}
