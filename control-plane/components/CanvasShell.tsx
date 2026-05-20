"use client";

import { ReactNode, useEffect, useMemo, useState } from "react";
import { Responsive, WidthProvider } from "react-grid-layout";
import { useRouter } from "next/navigation";
import Icon, { IconName } from "@/components/viz/Icon";

const ResponsiveGridLayout = WidthProvider(Responsive);

/**
 * Single source of truth for the canvas.
 *
 * v4.16: design language from claude.ai/design hand-off. MLC tokens,
 * three-way theme toggle (system / paper / slate), density modes,
 * widget catalogue, view presets. react-grid-layout still does the
 * canvas math (per the designer's own caveat).
 */

export interface WidgetDef {
  id: string;
  title: string;
  eyebrow?: string;
  icon: IconName;
  chip?: { tone: "ok" | "warn" | "danger" | "info" | "mint"; text: string };
  group: "agent" | "cost" | "skills" | "federation" | "mind";
  layout: { x: number; y: number; w: number; h: number };
  /** Minimum cell footprint react-grid-layout will allow on resize. */
  minW?: number;
  minH?: number;
  defaultStatic?: boolean;
  body: ReactNode;
}

export interface ViewPreset {
  label: string;
  /** Map of widget-id → layout override. Widgets not in the map keep their default. */
  layout: Record<string, { x: number; y: number; w: number; h: number }>;
  /** Which widgets to show (others hidden). Default: show all in `layout`. */
  show?: string[];
}

type ThemePref = "system" | "light" | "slate";
type Density = "compact" | "cozy" | "spacious";

const STORAGE_LAYOUT = "chimera-canvas-layout-v14";
const STORAGE_PINS = "chimera-canvas-pinned-v14";
const STORAGE_THEME = "chimera-canvas-theme-v1";
const STORAGE_DENSITY = "chimera-canvas-density-v1";
const STORAGE_CATALOGUE = "chimera-canvas-catalogue-v1";
const STORAGE_PRESET = "chimera-canvas-preset-v1";
const STORAGE_AUTOREFRESH = "chimera-canvas-autorefresh-v1";

const AUTO_REFRESH_INTERVAL_MS = 30_000;

interface LayoutItem {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  minW?: number;
  minH?: number;
  static?: boolean;
}

interface PersistedLayouts {
  [breakpoint: string]: LayoutItem[];
}

function defaultLayout(widgets: WidgetDef[]): PersistedLayouts {
  return {
    lg: widgets.map((w) => ({
      i: w.id,
      ...w.layout,
      minW: w.minW,
      minH: w.minH,
      static: !!w.defaultStatic,
    })),
  };
}

const GROUP_LABEL: Record<WidgetDef["group"], string> = {
  agent: "Agent state",
  cost: "Cost & calls",
  skills: "Skills",
  federation: "Federation",
  mind: "Mind",
};

const GROUP_ORDER: WidgetDef["group"][] = ["agent", "cost", "skills", "federation", "mind"];

function useResolvedTheme(pref: ThemePref) {
  const [resolved, setResolved] = useState<"light" | "slate">(() => {
    if (pref === "slate" || pref === "light") return pref;
    if (typeof window === "undefined") return "light";
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "slate" : "light";
  });
  useEffect(() => {
    if (pref === "slate" || pref === "light") {
      setResolved(pref);
      return;
    }
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => setResolved(mq.matches ? "slate" : "light");
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [pref]);
  return resolved;
}

export default function CanvasShell({
  widgets,
  presets = {},
}: {
  widgets: WidgetDef[];
  presets?: Record<string, ViewPreset>;
}) {
  const [layouts, setLayouts] = useState<PersistedLayouts | null>(null);
  const [pinned, setPinned] = useState<Record<string, boolean>>({});
  const [theme, setTheme] = useState<ThemePref>("system");
  const [density, setDensity] = useState<Density>("cozy");
  const [showCatalogue, setShowCatalogue] = useState(true);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [tweaksOpen, setTweaksOpen] = useState(false);
  const [preset, setPresetState] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const resolvedTheme = useResolvedTheme(theme);
  const router = useRouter();

  // Load persisted state from localStorage on mount.
  useEffect(() => {
    try {
      const rawL = localStorage.getItem(STORAGE_LAYOUT);
      const rawP = localStorage.getItem(STORAGE_PINS);
      const rawT = localStorage.getItem(STORAGE_THEME);
      const rawD = localStorage.getItem(STORAGE_DENSITY);
      const rawC = localStorage.getItem(STORAGE_CATALOGUE);
      const rawPreset = localStorage.getItem(STORAGE_PRESET);
      const rawAuto = localStorage.getItem(STORAGE_AUTOREFRESH);
      setLayouts(rawL ? JSON.parse(rawL) : defaultLayout(widgets));
      setPinned(rawP ? JSON.parse(rawP) : Object.fromEntries(widgets.map((w) => [w.id, !!w.defaultStatic])));
      if (rawT === "system" || rawT === "light" || rawT === "slate") setTheme(rawT);
      if (rawD === "compact" || rawD === "cozy" || rawD === "spacious") setDensity(rawD);
      if (rawC != null) setShowCatalogue(rawC === "1");
      if (rawPreset && rawPreset in presets) setPresetState(rawPreset);
      if (rawAuto === "1") setAutoRefresh(true);
    } catch {
      setLayouts(defaultLayout(widgets));
      setPinned(Object.fromEntries(widgets.map((w) => [w.id, !!w.defaultStatic])));
    }
  }, [widgets]);

  useEffect(() => {
    try { localStorage.setItem(STORAGE_THEME, theme); } catch { /* */ }
  }, [theme]);
  useEffect(() => {
    try { localStorage.setItem(STORAGE_DENSITY, density); } catch { /* */ }
  }, [density]);
  useEffect(() => {
    try { localStorage.setItem(STORAGE_CATALOGUE, showCatalogue ? "1" : "0"); } catch { /* */ }
  }, [showCatalogue]);
  useEffect(() => {
    try {
      if (preset) localStorage.setItem(STORAGE_PRESET, preset);
      else localStorage.removeItem(STORAGE_PRESET);
    } catch { /* */ }
  }, [preset]);
  useEffect(() => {
    try { localStorage.setItem(STORAGE_AUTOREFRESH, autoRefresh ? "1" : "0"); } catch { /* */ }
  }, [autoRefresh]);

  // Auto-refresh: every AUTO_REFRESH_INTERVAL_MS, soft-refresh the
  // RSC payload so widgets pick up new data without losing layout.
  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(() => router.refresh(), AUTO_REFRESH_INTERVAL_MS);
    return () => clearInterval(t);
  }, [autoRefresh, router]);

  const visibleWidgets = useMemo(
    () => widgets.filter((w) => !hidden.has(w.id)),
    [widgets, hidden],
  );

  const renderLayouts = useMemo(() => {
    if (!layouts) return null;
    const out: PersistedLayouts = {};
    for (const [bp, arr] of Object.entries(layouts)) {
      out[bp] = arr
        .filter((it) => !hidden.has(it.i))
        .map((it) => ({ ...it, static: !!pinned[it.i] }));
    }
    return out;
  }, [layouts, pinned, hidden]);

  const groupedCatalogue = useMemo(() => {
    const buckets: Record<WidgetDef["group"], WidgetDef[]> = {
      agent: [], cost: [], skills: [], federation: [], mind: [],
    };
    for (const w of widgets) buckets[w.group].push(w);
    return buckets;
  }, [widgets]);

  if (!layouts || !renderLayouts) {
    return (
      <div className="app">
        <div style={{ padding: 24, color: "var(--fg-3)" }}>Loading canvas…</div>
      </div>
    );
  }

  const onLayoutChange = (
    _: unknown,
    all: PersistedLayouts,
  ) => {
    // v4.36 fix: react-grid-layout's callback only carries the currently
    // VISIBLE items, so naively persisting it drops any hidden widget's
    // layout entry. Next time the user re-adds the widget from the
    // catalogue, RGL has no record and falls back to a 1×1 default tile
    // (the "chip" bug). Merge: keep entries for hidden ids from the
    // previous layouts, replace entries for visible ids with the
    // callback's fresh values.
    setLayouts((curr) => {
      const merged: PersistedLayouts = {};
      const bps = new Set([
        ...Object.keys(all || {}),
        ...Object.keys(curr || {}),
      ]);
      for (const bp of bps) {
        const fresh = (all && all[bp]) || [];
        const prior = (curr && curr[bp]) || [];
        const freshIds = new Set(fresh.map((it) => it.i));
        const hiddenEntries = prior.filter(
          (it) => !freshIds.has(it.i) && hidden.has(it.i),
        );
        merged[bp] = [...fresh, ...hiddenEntries];
      }
      try {
        localStorage.setItem(STORAGE_LAYOUT, JSON.stringify(merged));
      } catch { /* */ }
      return merged;
    });
  };

  const togglePin = (id: string) => {
    setPinned((p) => {
      const next = { ...p, [id]: !p[id] };
      try { localStorage.setItem(STORAGE_PINS, JSON.stringify(next)); } catch { /* */ }
      return next;
    });
    setLayouts((curr) => {
      if (!curr) return curr;
      const out: PersistedLayouts = {};
      for (const [bp, arr] of Object.entries(curr)) {
        out[bp] = arr.map((it) =>
          it.i === id ? { ...it, static: !it.static } : it,
        );
      }
      try { localStorage.setItem(STORAGE_LAYOUT, JSON.stringify(out)); } catch { /* */ }
      return out;
    });
  };

  const removeWidget = (id: string) => {
    setHidden((h) => new Set(h).add(id));
  };

  const addWidget = (id: string) => {
    setHidden((h) => {
      const next = new Set(h);
      next.delete(id);
      return next;
    });
    // v4.36 fix: if the layout was previously persisted WITHOUT this
    // widget (pre-fix corruption, or user added a brand-new widget def),
    // restore its default layout entry so RGL doesn't fall back to a
    // 1×1 chip. No-op when an entry already exists.
    const def = widgets.find((w) => w.id === id);
    if (!def) return;
    setLayouts((curr) => {
      if (!curr) return curr;
      const next: PersistedLayouts = {};
      let mutated = false;
      for (const [bp, arr] of Object.entries(curr)) {
        if (arr.some((it) => it.i === id)) {
          next[bp] = arr;
          continue;
        }
        mutated = true;
        next[bp] = [
          ...arr,
          {
            i: def.id,
            ...def.layout,
            minW: def.minW,
            minH: def.minH,
            static: !!pinned[def.id],
          },
        ];
      }
      if (!mutated) return curr;
      try {
        localStorage.setItem(STORAGE_LAYOUT, JSON.stringify(next));
      } catch { /* */ }
      return next;
    });
  };

  const applyPreset = (key: string) => {
    const p = presets[key];
    if (!p) return;
    setPresetState(key);
    const visible = new Set(p.show ?? Object.keys(p.layout));
    setHidden(new Set(widgets.filter((w) => !visible.has(w.id)).map((w) => w.id)));
    const next: PersistedLayouts = {
      lg: widgets
        .filter((w) => visible.has(w.id))
        .map((w) => {
          const ov = p.layout[w.id] ?? w.layout;
          return {
            i: w.id,
            ...ov,
            minW: w.minW,
            minH: w.minH,
            static: !!pinned[w.id],
          };
        }),
    };
    setLayouts(next);
    try { localStorage.setItem(STORAGE_LAYOUT, JSON.stringify(next)); } catch { /* */ }
  };

  const resetLayout = () => {
    if (!confirm("Reset canvas to default layout?")) return;
    setPresetState(null);
    const fresh = defaultLayout(widgets);
    const freshPins = Object.fromEntries(widgets.map((w) => [w.id, !!w.defaultStatic]));
    setLayouts(fresh);
    setPinned(freshPins);
    setHidden(new Set());
    try {
      localStorage.setItem(STORAGE_LAYOUT, JSON.stringify(fresh));
      localStorage.setItem(STORAGE_PINS, JSON.stringify(freshPins));
    } catch { /* */ }
  };

  const cycleTheme = () => {
    setTheme((t) => (t === "system" ? "light" : t === "light" ? "slate" : "system"));
  };

  const themeIcon: IconName = theme === "system" ? "layout" : resolvedTheme === "slate" ? "sun" : "moon";
  const nextTheme = theme === "system" ? "light" : theme === "light" ? "slate" : "system";

  return (
    <div className="app" data-theme={resolvedTheme} data-density={density}>
      <header className="topbar">
        <div className="brand">
          <span className="brand__dot" />
          <span>Chimera</span>
          <span
            style={{
              color: "var(--fg-3)",
              fontFamily: "var(--font-sans)",
              fontSize: 12,
              fontStyle: "italic",
              marginLeft: 4,
            }}
          >
            control plane
          </span>
        </div>

        <div className="topbar__spacer" />

        {Object.keys(presets).length > 0 && (
          <div className="topbar__presets" aria-label="View presets">
            {Object.entries(presets).map(([key, p]) => (
              <button
                key={key}
                className="topbar__preset"
                data-active={preset === key ? "true" : "false"}
                onClick={() => applyPreset(key)}
                title={`Apply ${p.label} view`}
              >
                {p.label}
              </button>
            ))}
          </div>
        )}

        <div className="topbar__spacer" />

        <div className="topbar__actions">
          {autoRefresh && (
            <span
              className="pill"
              data-tone="ok"
              title={`Auto-refreshing every ${AUTO_REFRESH_INTERVAL_MS / 1000}s`}
            >
              <span className="pill__dot" /> live
            </span>
          )}
          <button className="ghostbtn" onClick={resetLayout} title="Reset canvas to default">
            <Icon name="rotate" size={13} /> Reset
          </button>
          <button
            className="iconbtn"
            onClick={cycleTheme}
            title={`Theme: ${theme === "system" ? `auto (${resolvedTheme})` : theme} — next: ${nextTheme}`}
          >
            <Icon name={themeIcon} size={15} />
          </button>
          <button
            className="iconbtn"
            data-active={tweaksOpen ? "true" : "false"}
            onClick={() => setTweaksOpen((v) => !v)}
            title="Open tweaks"
          >
            <Icon name="edit" size={15} />
          </button>
        </div>
      </header>

      <div
        className="app__main"
        style={{ gridTemplateColumns: showCatalogue ? undefined : "1fr" }}
      >
        {showCatalogue && (
          <aside className="sidebar">
            <div className="sidebar__section">
              <div className="sidebar__title">Widget catalogue</div>
            </div>
            {GROUP_ORDER.map((g) => (
              <div key={g} className="sidebar__section">
                <div className="sidebar__title">{GROUP_LABEL[g]}</div>
                {groupedCatalogue[g].map((w) => {
                  const on = !hidden.has(w.id);
                  return (
                    <div
                      key={w.id}
                      className="cat-item"
                      data-on={on ? "true" : "false"}
                      onClick={() => (on ? removeWidget(w.id) : addWidget(w.id))}
                      title={on ? "Hide from canvas" : "Add to canvas"}
                    >
                      <span className="cat-item__icon">
                        <Icon name={w.icon} size={15} />
                      </span>
                      <span className="cat-item__label">{w.title}</span>
                      {!on && (
                        <span className="cat-item__add">
                          <Icon name="plus" size={13} />
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
          </aside>
        )}

        <div className="canvas">
          <ResponsiveGridLayout
            className="layout"
            layouts={renderLayouts}
            breakpoints={{ lg: 1200, md: 960, sm: 720, xs: 480 }}
            cols={{ lg: 12, md: 12, sm: 12, xs: 12 }}
            rowHeight={56}
            draggableHandle=".tile__header"
            onLayoutChange={onLayoutChange}
            margin={[12, 12]}
            compactType="vertical"
          >
            {visibleWidgets.map((w) => (
              <div key={w.id}>
                <div
                  className="tile"
                  data-pinned={pinned[w.id] ? "true" : "false"}
                >
                  <div className="tile__header">
                    {w.eyebrow && <span className="tile__eyebrow">{w.eyebrow}</span>}
                    <span className="tile__title">{w.title}</span>
                    {w.chip && (
                      <span className="tile__chip" data-tone={w.chip.tone}>
                        {w.chip.text}
                      </span>
                    )}
                    <div
                      className="tile__menu"
                      onMouseDown={(e) => e.stopPropagation()}
                      onTouchStart={(e) => e.stopPropagation()}
                    >
                      <button
                        className="iconbtn"
                        data-active={pinned[w.id] ? "true" : "false"}
                        onClick={(e) => {
                          e.stopPropagation();
                          togglePin(w.id);
                        }}
                        title={pinned[w.id] ? "Unpin" : "Pin"}
                      >
                        <Icon name="pin" size={13} />
                      </button>
                      <button
                        className="iconbtn"
                        onClick={(e) => {
                          e.stopPropagation();
                          removeWidget(w.id);
                        }}
                        title="Remove from canvas"
                      >
                        <Icon name="x" size={13} />
                      </button>
                    </div>
                  </div>
                  <div className="tile__body">{w.body}</div>
                </div>
              </div>
            ))}
          </ResponsiveGridLayout>
        </div>
      </div>

      {tweaksOpen && (
        <div
          style={{
            position: "fixed",
            top: 56,
            right: 16,
            width: 280,
            background: "var(--bg-1)",
            border: "1px solid var(--border-1)",
            borderRadius: "var(--radius-lg)",
            boxShadow: "var(--shadow-3)",
            padding: 16,
            zIndex: 20,
            display: "grid",
            gap: 14,
          }}
        >
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span className="label">Tweaks</span>
            <span
              style={{ marginLeft: "auto", cursor: "pointer" }}
              className="iconbtn"
              onClick={() => setTweaksOpen(false)}
            >
              <Icon name="x" size={13} />
            </span>
          </div>
          <TweaksSegmented
            label="Theme"
            value={theme}
            onChange={(v) => setTheme(v as ThemePref)}
            options={[
              { value: "system", label: "Auto" },
              { value: "light", label: "Paper" },
              { value: "slate", label: "Slate" },
            ]}
          />
          <TweaksSegmented
            label="Density"
            value={density}
            onChange={(v) => setDensity(v as Density)}
            options={[
              { value: "compact", label: "Compact" },
              { value: "cozy", label: "Cozy" },
              { value: "spacious", label: "Roomy" },
            ]}
          />
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 12,
              color: "var(--fg-2)",
            }}
          >
            <input
              type="checkbox"
              checked={showCatalogue}
              onChange={(e) => setShowCatalogue(e.target.checked)}
            />
            Show widget catalogue
          </label>
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 12,
              color: "var(--fg-2)",
            }}
          >
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Auto-refresh every {AUTO_REFRESH_INTERVAL_MS / 1000}s
          </label>
        </div>
      )}
    </div>
  );
}

function TweaksSegmented({
  label, value, onChange, options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <span className="label">{label}</span>
      <div className="topbar__presets" style={{ alignSelf: "start" }}>
        {options.map((o) => (
          <button
            key={o.value}
            className="topbar__preset"
            data-active={value === o.value ? "true" : "false"}
            onClick={() => onChange(o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
