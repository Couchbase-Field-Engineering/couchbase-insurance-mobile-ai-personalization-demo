import * as Crypto from 'expo-crypto';

/**
 * 16 hex chars for a request id. `crypto.randomUUID()` only exists in secure
 * contexts (https or localhost), so the web build opened over plain http on a
 * LAN or public IP has to fall back to getRandomValues, which is available
 * everywhere.
 */
function requestId(): string {
  try {
    return Crypto.randomUUID().replace(/-/g, '').slice(0, 16);
  } catch {
    try {
      return Array.from(Crypto.getRandomBytes(8), (b) => b.toString(16).padStart(2, '0')).join('');
    } catch {
      return (Date.now().toString(16) + Math.random().toString(16).slice(2)).slice(0, 16);
    }
  }
}
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api, ApiError, type LoginResponse } from '../api';
import { createLocalDb } from '../db/engine';
import { EMPTY, type LocalDb, type Snapshot } from '../db/localDb';
import { answerOffline } from '../features/assistant/offline';
import { useAuth } from '../session/AuthContext';
import type { ActionRequest, ChatMessage, SyncState } from '../types';

type Ctx = {
  snap: Snapshot;
  sync: SyncState;
  offline: boolean;
  setOffline: (v: boolean) => void;
  dbLocation: string | null;
  /** Queue an action (offline-first): a `requests` doc in the local DB, pushed by the replicator. */
  request: (tool: string, args: Record<string, unknown>, title: string) => Promise<ActionRequest>;
  ask: (message: string) => Promise<void>;
  /** A question queued by a card or screen ("Ask about it"); the Chat tab sends it when it opens. */
  queuedAsk: string | null;
  queueAsk: (message: string | null) => void;
  thinking: boolean;
  liveChat: ChatMessage[];
  refresh: () => Promise<void>;
};

const DataContext = createContext<Ctx | null>(null);
export const SESSION_EXPIRED = 'session-expired';
const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');

export function DataProvider({ children }: { children: React.ReactNode }) {
  const { session, renew, expire } = useAuth();
  const dbRef = useRef<LocalDb | null>(null);
  // The app token in use: the stored one until /api/auth/refresh renews it.
  const tokenRef = useRef<string | null>(null);
  const [snap, setSnap] = useState<Snapshot>(EMPTY);
  const [sync, setSync] = useState<SyncState>({ engine: 'preview', status: 'stopped', lastSyncAt: null, pendingPush: 0 });
  const [offline, setOfflineState] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [liveChat, setLiveChat] = useState<ChatMessage[]>([]);
  const [dbLocation, setDbLocation] = useState<string | null>(null);
  const [queuedAsk, queueAsk] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (dbRef.current) setSnap(await dbRef.current.read());
  }, []);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    const db = createLocalDb();
    dbRef.current = db;
    const offs: (() => void)[] = [];
    void (async () => {
      await db.open(session.user_id);
      if (cancelled) return;
      setDbLocation(db.location());
      offs.push(db.onChange(() => void reload()));
      offs.push(db.onSyncState(setSync));
      await reload(); // whatever is already on the device renders immediately
      let sg = session.sync_gateway;
      tokenRef.current = session.token;
      try {
        // Fresh app token + Sync Gateway session when there is connectivity
        // (sliding expiry); offline, the stored ones are used.
        const r = await api<Pick<LoginResponse, 'token' | 'sync_gateway'>>('/api/auth/refresh', { token: session.token, method: 'POST', timeoutMs: 6000 });
        sg = r.sync_gateway ?? sg;
        if (r.token) tokenRef.current = r.token;
        await renew({ token: r.token, sync_gateway: r.sync_gateway });
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          // Not "offline": the backend no longer accepts this session.
          await expire();
          return;
        }
        /* offline at launch - fine */
      }
      if (cancelled) return;
      await db.startSync({ token: tokenRef.current ?? session.token, userId: session.user_id, sg });
    })();
    return () => {
      cancelled = true;
      offs.forEach((f) => f());
      void db.close();
      dbRef.current = null;
      setSnap(EMPTY);
      setLiveChat([]);
      setSync((st) => ({ ...st, status: 'stopped', detail: undefined }));
    };
  }, [session, reload, renew, expire]);

  // The sync loop reports a rejected session the same way.
  useEffect(() => {
    if (sync.status === 'error' && sync.detail === SESSION_EXPIRED) void expire();
  }, [sync.status, sync.detail, expire]);

  const setOffline = useCallback((v: boolean) => {
    setOfflineState(v);
    void dbRef.current?.setPaused(v);
  }, []);

  const request = useCallback(
    async (tool: string, args: Record<string, unknown>, title: string) => {
      if (!session || !dbRef.current) throw new Error('Not signed in');
      const req: ActionRequest = {
        _id: `req::${session.user_id}::${requestId()}`,
        type: 'request',
        user_id: session.user_id,
        tool,
        args,
        title,
        status: 'pending',
        created_at: nowIso(),
      };
      await dbRef.current.saveRequest(req);
      await reload();
      return req;
    },
    [session, reload],
  );

  const ask = useCallback(
    async (message: string) => {
      if (!session) return;
      const userMsg: ChatMessage = { id: `l${Date.now()}`, role: 'user', text: message, at: nowIso() };
      setLiveChat((c) => [...c, userMsg]);
      setThinking(true);
      try {
        if (offline) throw new ApiError('offline', 0);
        const r = await api<any>('/api/chat', { token: tokenRef.current ?? session.token, body: { message, session_id: `app-${session.user_id}` }, timeoutMs: 45000 });
        setLiveChat((c) => [
          ...c,
          { id: `r${Date.now()}`, role: 'assistant', text: r.reply, at: nowIso(), intent: r.intent, area: r.area, actions: r.actions,
            context: r.context, llm: r.llm, sources: r.sources, restricted: r.restricted },
        ]);
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          void expire();
          return;
        }
        // No connectivity: answer from Couchbase Lite (context cache, FAQ, earlier answers).
        const local = answerOffline(message, snap);
        setLiveChat((c) => [...c, { id: `o${Date.now()}`, role: 'assistant', at: nowIso(), ...local }]);
        void e;
      } finally {
        setThinking(false);
      }
    },
    [session, offline, snap, expire],
  );

  return (
    <DataContext.Provider value={{ snap, sync, offline, setOffline, dbLocation, request, ask, queuedAsk, queueAsk, thinking, liveChat, refresh: reload }}>
      {children}
    </DataContext.Provider>
  );
}

export function useData(): Ctx {
  const c = useContext(DataContext);
  if (!c) throw new Error('useData outside DataProvider');
  return c;
}
