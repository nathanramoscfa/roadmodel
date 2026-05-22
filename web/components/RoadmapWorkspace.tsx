// web/components/RoadmapWorkspace.tsx
"use client";

import { useCallback, useState } from "react";
import type { Message, RoadmapDraft } from "@/lib/roadmap-types";
import { ChatPanel } from "./ChatPanel";
import { PreviewPanel } from "./PreviewPanel";
import {
  RoadmapTabSwitcher,
  type RoadmapTab,
} from "./RoadmapTabSwitcher";

interface RoadmapWorkspaceProps {
  isAnonymous: boolean;
}

function createMessage(role: Message["role"], content: string): Message {
  return {
    id: crypto.randomUUID(),
    role,
    content,
    created_at: new Date().toISOString(),
  };
}

type StreamEvent =
  | { type: "message_delta"; delta: string }
  | { type: "roadmap_draft"; draft: RoadmapDraft }
  | { type: "message_complete"; content?: string }
  | { type: "error"; error?: string; message?: string };

function parseSseEvents(buffer: string): {
  events: StreamEvent[];
  rest: string;
} {
  const events: StreamEvent[] = [];
  let rest = buffer;
  while (true) {
    const boundary = rest.indexOf("\n\n");
    if (boundary === -1) {
      break;
    }
    const raw = rest.slice(0, boundary);
    rest = rest.slice(boundary + 2);
    const dataLine = raw
      .split("\n")
      .find((line) => line.startsWith("data:"));
    if (!dataLine) {
      continue;
    }
    const payload = dataLine.replace(/^data:\s*/, "").trim();
    if (!payload) {
      continue;
    }
    try {
      events.push(JSON.parse(payload) as StreamEvent);
    } catch {
      // Malformed chunk; skip — the downstream message_complete
      // event still finalizes the assistant bubble.
    }
  }
  return { events, rest };
}

export function RoadmapWorkspace({ isAnonymous }: RoadmapWorkspaceProps) {
  const [draft, setDraft] = useState<RoadmapDraft | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [activeTab, setActiveTab] = useState<RoadmapTab>("chat");
  const [sessionExpired, setSessionExpired] = useState(false);

  const send = useCallback(
    async (text: string) => {
      const userMessage = createMessage("user", text);
      const assistantMessage = createMessage("assistant", "");
      const conversationSoFar = [...messages, userMessage];
      setMessages([...conversationSoFar, assistantMessage]);

      let response: Response;
      try {
        response = await fetch("/api/roadmap", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: conversationSoFar }),
        });
      } catch {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessage.id
              ? {
                  ...m,
                  content:
                    "We hit a network error reaching the roadmap engine. " +
                    "Try again in a moment.",
                }
              : m,
          ),
        );
        return;
      }

      if (response.status === 401) {
        setSessionExpired(true);
        setMessages((prev) =>
          prev.filter((m) => m.id !== assistantMessage.id),
        );
        return;
      }

      if (!response.ok || !response.body) {
        const message =
          response.status === 429
            ? "You've reached your roadmap limit. Try again later."
            : "The roadmap engine is unavailable. Try again in a moment.";
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessage.id ? { ...m, content: message } : m,
          ),
        );
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          const { events, rest } = parseSseEvents(buffer);
          buffer = rest;
          for (const event of events) {
            if (event.type === "message_delta") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMessage.id
                    ? { ...m, content: m.content + event.delta }
                    : m,
                ),
              );
            } else if (event.type === "roadmap_draft") {
              setDraft(event.draft);
            } else if (event.type === "message_complete") {
              if (event.content) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMessage.id
                      ? { ...m, content: event.content ?? m.content }
                      : m,
                  ),
                );
              }
            } else if (event.type === "error") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMessage.id
                    ? {
                        ...m,
                        content:
                          event.message ??
                          "The roadmap engine returned an error.",
                      }
                    : m,
                ),
              );
            }
          }
        }
      } catch {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessage.id && m.content.length === 0
              ? {
                  ...m,
                  content:
                    "The roadmap stream was interrupted. Try again in " +
                    "a moment.",
                }
              : m,
          ),
        );
      }
    },
    [messages],
  );

  const sendSync = useCallback(
    (text: string) => {
      void send(text);
    },
    [send],
  );

  const chatPanelClass =
    activeTab === "chat" ? "flex flex-1 flex-col" : "hidden md:flex flex-1 flex-col";
  const previewPanelClass =
    activeTab === "preview"
      ? "flex flex-1 flex-col"
      : "hidden md:flex flex-1 flex-col";

  // Once a 401 surfaces mid-stream, downgrade to anonymous so the
  // SoftSignupWall renders on the next composer submit; the wall
  // also captures the user's draft text so they don't lose it.
  const effectiveAnonymous = isAnonymous || sessionExpired;

  return (
    <div className="flex flex-col">
      <RoadmapTabSwitcher activeTab={activeTab} onChange={setActiveTab} />
      <div className="flex flex-col gap-6 md:flex-row md:gap-8">
        <div className={chatPanelClass}>
          <ChatPanel
            messages={messages}
            isAnonymous={effectiveAnonymous}
            onSubmit={sendSync}
          />
        </div>
        <div className={previewPanelClass}>
          <PreviewPanel draft={draft} />
        </div>
      </div>
    </div>
  );
}
