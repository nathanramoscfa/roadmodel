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

function createStubDraft(userMessage: string): RoadmapDraft {
  return {
    project_overview:
      "Stub executive summary for your project based on the " +
      `message: "${userMessage}".`,
    phases: [
      {
        title: "Phase 1 — Foundation",
        goal: "Establish the core project scaffold.",
        sub_sections: [
          "Define repository structure",
          "Configure CI and deployment",
        ],
        acceptance_criteria: [
          "All automated checks pass in CI.",
          "Documentation covers setup and usage.",
        ],
      },
    ],
    glossary: [],
    generated_at: new Date().toISOString(),
  };
}

export function RoadmapWorkspace({ isAnonymous }: RoadmapWorkspaceProps) {
  const [draft, setDraft] = useState<RoadmapDraft | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [activeTab, setActiveTab] = useState<RoadmapTab>("chat");

  const send = useCallback((text: string) => {
    setMessages((prev) => [...prev, createMessage("user", text)]);

    window.setTimeout(() => {
      setDraft(createStubDraft(text));
      setMessages((prev) => [
        ...prev,
        createMessage(
          "assistant",
          "Here is a stub roadmap draft based on your description.",
        ),
      ]);
    }, 600);
  }, []);

  const chatPanelClass =
    activeTab === "chat" ? "flex flex-1 flex-col" : "hidden md:flex flex-1 flex-col";
  const previewPanelClass =
    activeTab === "preview"
      ? "flex flex-1 flex-col"
      : "hidden md:flex flex-1 flex-col";

  return (
    <div className="flex flex-col">
      <RoadmapTabSwitcher activeTab={activeTab} onChange={setActiveTab} />
      <div className="flex flex-col gap-6 md:flex-row md:gap-8">
        <div className={chatPanelClass}>
          <ChatPanel
            messages={messages}
            isAnonymous={isAnonymous}
            onSubmit={send}
          />
        </div>
        <div className={previewPanelClass}>
          <PreviewPanel draft={draft} />
        </div>
      </div>
    </div>
  );
}
