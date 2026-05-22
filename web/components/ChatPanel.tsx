// web/components/ChatPanel.tsx
"use client";

import type { Message } from "@/lib/roadmap-types";
import { RoadmapComposer } from "./RoadmapComposer";
import { SoftSignupWall } from "./SoftSignupWall";

interface ChatPanelProps {
  messages: Message[];
  isAnonymous: boolean;
  onSubmit: (text: string) => void;
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={
          (isUser
            ? "max-w-[85%] rounded-2xl rounded-br-md bg-brand-accent " +
              "text-white "
            : "max-w-[85%] rounded-2xl rounded-bl-md bg-brand-slate-100 " +
              "text-brand-slate-900 ") + "px-4 py-3 text-sm"
        }
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
      </div>
    </div>
  );
}

export function ChatPanel({
  messages,
  isAnonymous,
  onSubmit,
}: ChatPanelProps) {
  const composer = (
    <RoadmapComposer
      onSubmit={(text) => {
        onSubmit(text);
        return true;
      }}
    />
  );

  return (
    <div
      className={
        "flex min-h-[480px] flex-1 flex-col rounded-xl border " +
        "border-brand-slate-200 bg-white p-4 shadow-sm sm:p-6"
      }
    >
      <div className="flex-1 space-y-4 overflow-y-auto pb-4">
        {messages.length === 0 ? (
          <p className="text-sm text-brand-slate-500">
            Describe your project to start building a roadmap.
          </p>
        ) : (
          messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))
        )}
      </div>
      {isAnonymous ? (
        <SoftSignupWall>{composer}</SoftSignupWall>
      ) : (
        composer
      )}
    </div>
  );
}
