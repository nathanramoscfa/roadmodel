// web/lib/conversations.ts
//
// Phase 4 Step 5 persistence layer for /api/roadmap, /history, and
// the /roadmap/[conversation_id] re-hydration path. Two backends:
//
//   - Supabase server client (default). Uses the user's session
//     cookie, so RLS enforces auth.uid() = user_id on every read
//     and write. Authoring code does NOT pass user_id filters
//     defensively; RLS is the single source of truth.
//   - In-memory store (E2E mode only). Mirrors the e2eProfiles
//     pattern in web/lib/profile.ts so Playwright fixtures can
//     seed conversations without standing up a Postgres.
//
// The shape returned by both backends matches the
// roadmap-types.ts ConversationSummary / ConversationDetail
// contracts so callers don't branch on backend.

import { randomUUID } from "node:crypto";

import { createSupabaseServerClient } from "./auth";
import { isE2eAuthEnabled } from "./e2e-mode";
import type {
  ConversationDetail,
  ConversationSummary,
  Message,
  RoadmapDraft,
} from "./roadmap-types";

const DEFAULT_CONVERSATION_TITLE = "Untitled roadmap";
const SNIPPET_MAX_CHARS = 140;

interface ConversationRow {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

interface MessageRow {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

interface RoadmapRow {
  id: string;
  conversation_id: string;
  user_id: string;
  draft: RoadmapDraft;
  generated_at: string;
}

// ---------------------------------------------------------------
// E2E in-memory store
// ---------------------------------------------------------------

const e2eConversations = new Map<string, ConversationRow>();
const e2eMessages = new Map<string, MessageRow[]>();
const e2eRoadmaps = new Map<string, RoadmapRow>();

export function e2eClearConversations(userId?: string): void {
  // When no userId is passed, clear everything. With a userId, only
  // rows owned by that user are removed — used by /api/test/e2e-reset
  // so concurrent Playwright workers running OTHER specs don't
  // clobber seeds belonging to history.spec's distinct uid.
  if (!userId) {
    e2eConversations.clear();
    e2eMessages.clear();
    e2eRoadmaps.clear();
    return;
  }
  for (const [id, row] of e2eConversations) {
    if (row.user_id === userId) {
      e2eConversations.delete(id);
      e2eMessages.delete(id);
    }
  }
  for (const [conversationId, row] of e2eRoadmaps) {
    if (row.user_id === userId) {
      e2eRoadmaps.delete(conversationId);
    }
  }
}

export function e2eSeedConversation(args: {
  userId: string;
  title?: string;
  updatedAt?: string;
  messages?: Array<Pick<MessageRow, "role" | "content">>;
  draft?: RoadmapDraft;
}): ConversationRow {
  const now = new Date().toISOString();
  const conversation: ConversationRow = {
    id: randomUUID(),
    user_id: args.userId,
    title: args.title ?? DEFAULT_CONVERSATION_TITLE,
    created_at: now,
    updated_at: args.updatedAt ?? now,
  };
  e2eConversations.set(conversation.id, conversation);
  const rows: MessageRow[] = (args.messages ?? []).map((m, idx) => ({
    id: randomUUID(),
    conversation_id: conversation.id,
    role: m.role,
    content: m.content,
    created_at: new Date(Date.now() + idx).toISOString(),
  }));
  e2eMessages.set(conversation.id, rows);
  if (args.draft) {
    e2eRoadmaps.set(conversation.id, {
      id: randomUUID(),
      conversation_id: conversation.id,
      user_id: args.userId,
      draft: args.draft,
      generated_at: now,
    });
  }
  return conversation;
}

// ---------------------------------------------------------------
// Helpers shared across backends
// ---------------------------------------------------------------

function snippetFromMessages(rows: MessageRow[]): string {
  if (rows.length === 0) {
    return "";
  }
  const last = rows[rows.length - 1];
  const text = last.content.replace(/\s+/g, " ").trim();
  return text.length > SNIPPET_MAX_CHARS
    ? text.slice(0, SNIPPET_MAX_CHARS - 1) + "…"
    : text;
}

function toSummary(
  conversation: ConversationRow,
  messages: MessageRow[],
): ConversationSummary {
  return {
    id: conversation.id,
    title: conversation.title,
    updated_at: conversation.updated_at,
    last_message_snippet: snippetFromMessages(messages),
  };
}

function mapMessageRow(row: MessageRow): Message {
  return {
    id: row.id,
    role: row.role,
    content: row.content,
    created_at: row.created_at,
  };
}

// ---------------------------------------------------------------
// Public API
// ---------------------------------------------------------------

export async function createConversation(args: {
  userId: string;
  title?: string;
}): Promise<{ id: string; title: string }> {
  if (isE2eAuthEnabled()) {
    const now = new Date().toISOString();
    const row: ConversationRow = {
      id: randomUUID(),
      user_id: args.userId,
      title: args.title ?? DEFAULT_CONVERSATION_TITLE,
      created_at: now,
      updated_at: now,
    };
    e2eConversations.set(row.id, row);
    e2eMessages.set(row.id, []);
    return { id: row.id, title: row.title };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("conversations")
    .insert({
      user_id: args.userId,
      title: args.title ?? DEFAULT_CONVERSATION_TITLE,
    })
    .select("id, title")
    .single();
  if (error || !data) {
    throw new Error(`conversation_insert_failed: ${error?.message ?? "unknown"}`);
  }
  return { id: String(data.id), title: String(data.title) };
}

export async function listConversationsForUser(
  userId: string,
): Promise<ConversationSummary[]> {
  if (isE2eAuthEnabled()) {
    const rows = Array.from(e2eConversations.values())
      .filter((c) => c.user_id === userId)
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    return rows.map((c) => toSummary(c, e2eMessages.get(c.id) ?? []));
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("conversations")
    .select("id, title, updated_at, messages(content, created_at)")
    .order("updated_at", { ascending: false })
    .limit(200);
  if (error || !data) {
    return [];
  }
  type Row = {
    id: string;
    title: string;
    updated_at: string;
    messages: Array<{ content: string; created_at: string }> | null;
  };
  return (data as Row[]).map((row) => {
    const messages = (row.messages ?? [])
      .slice()
      .sort((a, b) => a.created_at.localeCompare(b.created_at));
    const last = messages.length > 0 ? messages[messages.length - 1] : null;
    const text = last ? last.content.replace(/\s+/g, " ").trim() : "";
    const snippet =
      text.length > SNIPPET_MAX_CHARS
        ? text.slice(0, SNIPPET_MAX_CHARS - 1) + "…"
        : text;
    return {
      id: row.id,
      title: row.title,
      updated_at: row.updated_at,
      last_message_snippet: snippet,
    };
  });
}

export async function getConversationDetail(
  conversationId: string,
  userId: string,
): Promise<ConversationDetail | null> {
  if (isE2eAuthEnabled()) {
    const conversation = e2eConversations.get(conversationId);
    if (!conversation || conversation.user_id !== userId) {
      return null;
    }
    const messages = (e2eMessages.get(conversationId) ?? [])
      .slice()
      .sort((a, b) => a.created_at.localeCompare(b.created_at))
      .map(mapMessageRow);
    const roadmap = e2eRoadmaps.get(conversationId) ?? null;
    return {
      id: conversation.id,
      title: conversation.title,
      created_at: conversation.created_at,
      updated_at: conversation.updated_at,
      messages,
      draft: roadmap?.draft ?? null,
      roadmap_id: roadmap?.id ?? null,
    };
  }
  const supabase = await createSupabaseServerClient();
  const { data: convoRow, error: convoErr } = await supabase
    .from("conversations")
    .select("id, title, created_at, updated_at")
    .eq("id", conversationId)
    .maybeSingle();
  if (convoErr || !convoRow) {
    return null;
  }
  const { data: messageRows } = await supabase
    .from("messages")
    .select("id, role, content, created_at")
    .eq("conversation_id", conversationId)
    .order("created_at", { ascending: true });
  const { data: roadmapRow } = await supabase
    .from("roadmaps")
    .select("id, draft")
    .eq("conversation_id", conversationId)
    .maybeSingle();
  return {
    id: String(convoRow.id),
    title: String(convoRow.title),
    created_at: String(convoRow.created_at),
    updated_at: String(convoRow.updated_at),
    messages: (messageRows ?? []).map((row) => ({
      id: String(row.id),
      role: row.role as "user" | "assistant",
      content: String(row.content),
      created_at: String(row.created_at),
    })),
    draft: roadmapRow ? (roadmapRow.draft as RoadmapDraft) : null,
    roadmap_id: roadmapRow ? String(roadmapRow.id) : null,
  };
}

export async function insertMessage(args: {
  conversationId: string;
  userId: string;
  role: "user" | "assistant";
  content: string;
}): Promise<void> {
  if (isE2eAuthEnabled()) {
    const conversation = e2eConversations.get(args.conversationId);
    if (!conversation || conversation.user_id !== args.userId) {
      return;
    }
    const rows = e2eMessages.get(args.conversationId) ?? [];
    rows.push({
      id: randomUUID(),
      conversation_id: args.conversationId,
      role: args.role,
      content: args.content,
      created_at: new Date().toISOString(),
    });
    e2eMessages.set(args.conversationId, rows);
    conversation.updated_at = new Date().toISOString();
    return;
  }
  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.from("messages").insert({
    conversation_id: args.conversationId,
    role: args.role,
    content: args.content,
  });
  if (error) {
    console.error("message_insert_failed", error);
  }
}

export async function upsertRoadmap(args: {
  conversationId: string;
  userId: string;
  draft: RoadmapDraft;
}): Promise<{ id: string } | null> {
  if (isE2eAuthEnabled()) {
    const conversation = e2eConversations.get(args.conversationId);
    if (!conversation || conversation.user_id !== args.userId) {
      return null;
    }
    const existing = e2eRoadmaps.get(args.conversationId);
    const row: RoadmapRow = existing
      ? { ...existing, draft: args.draft, generated_at: new Date().toISOString() }
      : {
          id: randomUUID(),
          conversation_id: args.conversationId,
          user_id: args.userId,
          draft: args.draft,
          generated_at: new Date().toISOString(),
        };
    e2eRoadmaps.set(args.conversationId, row);
    return { id: row.id };
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("roadmaps")
    .upsert(
      {
        conversation_id: args.conversationId,
        user_id: args.userId,
        draft: args.draft,
        generated_at: new Date().toISOString(),
      },
      { onConflict: "conversation_id" },
    )
    .select("id")
    .single();
  if (error || !data) {
    console.error("roadmap_upsert_failed", error);
    return null;
  }
  return { id: String(data.id) };
}

export async function updateConversationTitle(args: {
  conversationId: string;
  userId: string;
  title: string;
}): Promise<void> {
  const title = args.title.trim();
  if (!title) {
    return;
  }
  if (isE2eAuthEnabled()) {
    const conversation = e2eConversations.get(args.conversationId);
    if (!conversation || conversation.user_id !== args.userId) {
      return;
    }
    conversation.title = title;
    conversation.updated_at = new Date().toISOString();
    return;
  }
  const supabase = await createSupabaseServerClient();
  const { error } = await supabase
    .from("conversations")
    .update({ title })
    .eq("id", args.conversationId);
  if (error) {
    console.error("conversation_title_update_failed", error);
  }
}

export async function getRoadmapById(
  roadmapId: string,
  userId: string,
): Promise<RoadmapRow | null> {
  if (isE2eAuthEnabled()) {
    for (const row of e2eRoadmaps.values()) {
      if (row.id === roadmapId && row.user_id === userId) {
        return row;
      }
    }
    return null;
  }
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase
    .from("roadmaps")
    .select("id, conversation_id, user_id, draft, generated_at")
    .eq("id", roadmapId)
    .maybeSingle();
  if (error || !data) {
    return null;
  }
  return {
    id: String(data.id),
    conversation_id: String(data.conversation_id),
    user_id: String(data.user_id),
    draft: data.draft as RoadmapDraft,
    generated_at: String(data.generated_at),
  };
}
