interface Props {
  current: number;
  recent?: number | null;
}

export default function TierLadder({ current, recent = null }: Props) {
  return (
    <div className="ladder" aria-label={`Tier T${current}`}>
      {[0, 1, 2, 3, 4, 5].map((n) => {
        let state: "empty" | "filled" | "current" | "recent" = "empty";
        if (n < current) state = "filled";
        if (n === current) state = "current";
        if (recent != null && n === recent && n !== current) state = "recent";
        const h = 6 + n * 3;
        return (
          <div
            key={n}
            className="ladder__rung"
            data-state={state}
            style={{ height: `${h}px` }}
          />
        );
      })}
    </div>
  );
}
