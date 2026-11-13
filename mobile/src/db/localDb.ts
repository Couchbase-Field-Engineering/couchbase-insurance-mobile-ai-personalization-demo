import type { ActionRequest, ActivityItem, Catalog, ChatDoc, ContextDoc, FeedDoc, MemberGuide, Profile, SyncState } from '../types';

/**
 * The app's local database. Two implementations with the same contract:
 *
 * - `couchbase-lite` (cblDb.native.ts): the real thing. An on-device Couchbase
 *   Lite database (scope `ins`, same collections as the server) kept in sync
 *   by a continuous push/pull replicator against Sync Gateway. Everything
 *   renders from here, so the app works with no connectivity at all.
 * - `preview` (previewDb.ts): a browser/Expo Go stand-in for demos without a
 *   device build - an in-memory store that polls the backend's REST
 *   `/api/sync/pull` and pushes requests with `/api/sync/push`. Same document
 *   ids and shapes.
 */
export const SCOPE = 'ins';
export const COLLECTIONS = ['profiles', 'feed', 'activity', 'requests', 'chat', 'context_cache', 'catalog'] as const;
export type CollectionName = (typeof COLLECTIONS)[number];

export const CONTEXT_KEYS = [
  'emergency', 'roadside', 'claim', 'telematics', 'billing', 'documents', 'coverage', 'wellness', 'account', 'handoff', 'general',
].flatMap((i) => [i, `playbook_${i}`]);

export type Snapshot = {
  profile: Profile | null;
  feed: FeedDoc | null;
  activity: { items: ActivityItem[] } | null;
  requests: ActionRequest[];
  chat: ChatDoc | null;
  catalog: Catalog | null;
  /** Member Care Guide reference data. Null on a phone without a health or pet plan: Sync Gateway never sends it. */
  memberGuide: MemberGuide | null;
  contexts: Record<string, ContextDoc>;
};

export const EMPTY: Snapshot = { profile: null, feed: null, activity: null, requests: [], chat: null, catalog: null, memberGuide: null, contexts: {} };

export type SyncSession = {
  token: string;
  userId: string;
  sg: { session_id: string; cookie_name: string; url: string | null; db: string } | null;
};

export interface LocalDb {
  readonly engine: SyncState['engine'];
  open(userId: string): Promise<void>;
  read(): Promise<Snapshot>;
  saveRequest(req: ActionRequest): Promise<void>;
  startSync(session: SyncSession): Promise<void>;
  setPaused(paused: boolean): Promise<void>;
  onChange(cb: () => void): () => void;
  onSyncState(cb: (s: SyncState) => void): () => void;
  location(): string | null;
  close(): Promise<void>;
}

export const ids = {
  profile: (u: string) => `profile::${u}`,
  feed: (u: string) => `feed::${u}`,
  activity: (u: string) => `activity::${u}`,
  chat: (u: string) => `chat::${u}`,
  ctx: (u: string, k: string) => `ctx::${u}::${k}`,
  catalog: 'catalog::v1',
  memberGuide: 'wellness::v1',
};

/** Build a Snapshot from a by-id getter + the user's requests. */
export async function buildSnapshot(
  userId: string,
  get: (col: CollectionName, id: string) => Promise<Record<string, unknown> | null>,
  requests: ActionRequest[],
): Promise<Snapshot> {
  const contexts: Record<string, ContextDoc> = {};
  for (const k of CONTEXT_KEYS) {
    const d = await get('context_cache', ids.ctx(userId, k));
    if (d) contexts[k] = d as unknown as ContextDoc;
  }
  return {
    profile: (await get('profiles', ids.profile(userId))) as unknown as Profile | null,
    feed: (await get('feed', ids.feed(userId))) as unknown as FeedDoc | null,
    activity: (await get('activity', ids.activity(userId))) as unknown as Snapshot['activity'],
    chat: (await get('chat', ids.chat(userId))) as unknown as ChatDoc | null,
    catalog: (await get('catalog', ids.catalog)) as unknown as Catalog | null,
    memberGuide: (await get('catalog', ids.memberGuide)) as unknown as MemberGuide | null,
    contexts,
    requests: [...requests].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
  };
}

type Listener<T> = (v: T) => void;
export class Emitter<T> {
  private ls = new Set<Listener<T>>();
  on(l: Listener<T>) {
    this.ls.add(l);
    return () => {
      this.ls.delete(l);
    };
  }
  emit(v: T) {
    this.ls.forEach((l) => {
      try {
        l(v);
      } catch {
        /* listener errors never break sync */
      }
    });
  }
}
