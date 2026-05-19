"use client";

import { ReactNode, useEffect, useMemo, useState } from "react";
import { Responsive, WidthProvider } from "react-grid-layout";
import Widget from "./widgets/Widget";
import "react-grid-layout/css/styles.css";

const ResponsiveGridLayout = WidthProvider(Responsive);

/**
 * Single source of truth for the canvas. Each widget definition is
 * a (id, title, defaultLayout, render-fn) tuple. Page-level SSR
 * pre-fetches data; this client component just hangs widgets in the
 * grid and persists per-user layout to localStorage.
 *
 * Static-pinning: clicking the 📍 icon on a widget header flips it
 * into static mode so the grid won't move or resize it. Useful for
 * always-on-top tiles like Status.
 */

export interface WidgetDef {
  id: string;
  title: string;
  /** Default grid placement: { x, y, w, h } in 12-col units. */
  layout: { x: number; y: number; w: number; h: number };
  defaultStatic?: boolean;
  /** Pre-rendered server JSX. Functions can't cross the
   *  server→client boundary in Next.js app router. */
  body: ReactNode;
}

const STORAGE_KEY = "chimera-canvas-layout-v1";
const PIN_KEY = "chimera-canvas-pinned-v1";

interface PersistedState {
  layouts: Record<string, { i: string; x: number; y: number; w: number; h: number; static?: boolean }[]>;
  pinned: Record<string, boolean>;
}

function defaultPersisted(widgets: WidgetDef[]): PersistedState {
  return {
    layouts: {
      lg: widgets.map((w) => ({ i: w.id, ...w.layout, static: !!w.defaultStatic })),
    },
    pinned: Object.fromEntries(widgets.map((w) => [w.id, !!w.defaultStatic])),
  };
}

export default function CanvasShell({ widgets }: { widgets: WidgetDef[] }) {
  const [state, setState] = useState<PersistedState | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      const pinRaw = localStorage.getItem(PIN_KEY);
      if (raw) {
        const layouts = JSON.parse(raw);
        const pinned = pinRaw ? JSON.parse(pinRaw) : {};
        setState({ layouts, pinned });
        return;
      }
    } catch {
      // fall through
    }
    setState(defaultPersisted(widgets));
  }, [widgets]);

  const layouts = useMemo(() => {
    if (!state) return null;
    // Apply pinned flags to layout items so react-grid-layout marks them static.
    const out: Record<string, { i: string; x: number; y: number; w: number; h: number; static?: boolean }[]> = {};
    for (const [bp, arr] of Object.entries(state.layouts)) {
      out[bp] = arr.map((it) => ({ ...it, static: !!state.pinned[it.i] }));
    }
    return out;
  }, [state]);

  if (!state || !layouts) {
    return <p className="p-6 text-zinc-500">Loading canvas…</p>;
  }

  const onLayoutChange = (
    _: unknown,
    allLayouts: Record<string, { i: string; x: number; y: number; w: number; h: number; static?: boolean }[]>,
  ) => {
    setState((s) => (s ? { ...s, layouts: allLayouts } : s));
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(allLayouts));
    } catch {
      // localStorage may be full / disabled — ignore
    }
  };

  const togglePin = (id: string) => {
    setState((s) => {
      if (!s) return s;
      const next = { ...s.pinned, [id]: !s.pinned[id] };
      try {
        localStorage.setItem(PIN_KEY, JSON.stringify(next));
      } catch {
        // ignore
      }
      return { ...s, pinned: next };
    });
  };

  const resetLayout = () => {
    if (!confirm("Reset canvas to default layout?")) return;
    const fresh = defaultPersisted(widgets);
    setState(fresh);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(fresh.layouts));
      localStorage.setItem(PIN_KEY, JSON.stringify(fresh.pinned));
    } catch {
      // ignore
    }
  };

  return (
    <div>
      <div className="flex justify-end px-4 py-2 border-b border-zinc-200 dark:border-zinc-800">
        <button
          onClick={resetLayout}
          className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 px-2 py-1 rounded border border-zinc-300 dark:border-zinc-700"
        >
          Reset canvas
        </button>
      </div>
      <ResponsiveGridLayout
        className="layout"
        layouts={layouts}
        breakpoints={{ lg: 1200, md: 960, sm: 720, xs: 480 }}
        cols={{ lg: 12, md: 12, sm: 6, xs: 4 }}
        rowHeight={48}
        draggableHandle=".widget-drag-handle"
        onLayoutChange={onLayoutChange}
        margin={[12, 12]}
        compactType="vertical"
      >
        {widgets.map((w) => (
          <div key={w.id}>
            <Widget
              title={w.title}
              pinned={!!state.pinned[w.id]}
              onTogglePin={() => togglePin(w.id)}
            >
              {w.body}
            </Widget>
          </div>
        ))}
      </ResponsiveGridLayout>
    </div>
  );
}
