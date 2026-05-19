"use client";

import { ReactNode } from "react";

interface WidgetProps {
  title: string;
  /** When pinned, the parent canvas marks this widget static (no drag/resize). */
  pinned?: boolean;
  onTogglePin?: () => void;
  children: ReactNode;
}

/**
 * Shared chrome for every dashboard widget. The drag handle is the
 * header bar (react-grid-layout's draggableHandle selector targets
 * the .widget-drag-handle class). The body is scrollable so
 * arbitrarily long content fits inside the grid cell.
 */
export default function Widget({ title, pinned, onTogglePin, children }: WidgetProps) {
  return (
    <div className="h-full flex flex-col border border-zinc-200 dark:border-zinc-800 rounded bg-white dark:bg-zinc-950 shadow-sm">
      <div className="widget-drag-handle cursor-move flex items-center gap-2 px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 text-sm font-semibold select-none">
        <span className="flex-1 truncate">{title}</span>
        {onTogglePin && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onTogglePin();
            }}
            className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 px-1 py-0.5 rounded"
            title={pinned ? "Unpin (allow drag)" : "Pin (lock in place)"}
          >
            {pinned ? "📌" : "📍"}
          </button>
        )}
      </div>
      <div className="flex-1 overflow-auto p-3 text-xs">{children}</div>
    </div>
  );
}
