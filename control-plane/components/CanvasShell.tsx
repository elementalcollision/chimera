"use client";

import { ReactNode, useEffect, useMemo, useState } from "react";
import { Responsive, WidthProvider } from "react-grid-layout";
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
  defaultStatic?: boolean;
  body: ReactNode;
}

type ThemePref = "system" | "light" | "slate";
type Density = "compact" | "cozy" | "spacious";

const STORAGE_LAYOUT = "chimera-canvas-layout-v3";
const STORAGE_PINS = "chimera-canvas-pinned-v3";
const STORAGE_THEME = "chimera-canvas-theme-v1";
const STORAGE_DENSITY = "chimera-canvas-density-v1";
const STORAGE_CATALOGUE = "chimera-canvas-catalogue-v1";

interface PersistedLayouts {
  [breakpoint: string]: { i: string; x: number; y: number; w: number; h: number; static?: boolean }[];
}

function defaultLayout(widgets: WidgetDef[]): PersistedLayouts {
  return {
    lg: widgets.map((w) => ({ i: w.id, ...w.layout, static: !!w.defaultStatic })),
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

export default function CanvasShell({ widgets }: { widgets: WidgetDef[] }) {
  const [layouts, setLayouts] = useState<PersistedLayouts | null>(null);
  const [pinned, setPinned] = useState<Record<string, boolean>>({});
  const [theme, setTheme] = useState<ThemePref>("system");
  const [density, setDensity] = useState<Density>("cozy");
  const [showCatalogue, setShowCatalogue] = useState(true);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [tweaksOpen, setTweaksOpen] = useState(false);
  const resolvedTheme = useResolvedTheme(theme);

  // Load persisted state from localStorage on mount.
  useEffect(() => {
    try {
      const rawL = localStorage.getItem(STORAGE_LAYOUT);
      const rawP = localStorage.getItem(STORAGE_PINS);
      const rawT = localStorage.getItem(STORAGE_THEME);
      const rawD = localStorage.getItem(STORAGE_DENSITY);
      const rawC = localStorage.getItem(STORAGE_CATALOGUE);
      setLayouts(rawL ? JSON.parse(rawL) : defaultLayout(widgets));
      setPinned(rawP ? JSON.parse(rawP) : Object.fromEntries(widgets.map((w) => [w.id, !!w.defaultStatic])));
      if (rawT === "system" || rawT === "light" || rawT === "slate") setTheme(rawT);
      if (rawD === "compact" || rawD === "cozy" || rawD === "spacious") setDensity(rawD);
      if (rawC != null) setShowCatalogue(rawC === "1");
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
    setLayouts(all);
    try {
      localStorage.setItem(STORAGE_LAYOUT, JSON.stringify(all));
    } catch { /* */ }
  };

  const togglePin = (id: string) => {
    setPinned((p) => {
      const next = { ...p, [id]: !p[id] };
      try { localStorage.setItem(STORAGE_PINS, JSON.stringify(next)); } catch { /* */ }
      return next;
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
  };

  const resetLayout = () => {
    if (!confirm("Reset canvas to default layout?")) return;
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

  const groupedCatalogue = useMemo(() => {
    const buckets: Record<WidgetDef["group"], WidgetDef[]> = {
      agent: [], cost: [], skills: [], federation: [], mind: [],
    };
    for (const w of widgets) buckets[w.group].push(w);
    return buckets;
  }, [widgets]);

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

        <div className="topbar__actions">
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
            cols={{ lg: 12, md: 12, sm: 6, xs: 4 }}
            rowHeight={48}
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
                    <div className="tile__menu">
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
