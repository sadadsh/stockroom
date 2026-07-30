export type ProjectInspectorFact = {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
};

export function ProjectInspectorFacts({
  items,
  className = "mt-4",
}: {
  items: ProjectInspectorFact[];
  className?: string;
}) {
  return (
    <dl className={`${className} border-y border-line`}>
      {items.map((item, index) => (
        <div
          key={item.label}
          className={`grid grid-cols-[4.5rem_minmax(0,1fr)] items-start gap-3 py-2.5 ${
            index ? "border-t border-line" : ""
          }`}
        >
          <dt className="text-xs text-t3">{item.label}</dt>
          <dd
            className={`min-w-0 break-words text-right text-xs font-medium text-t1 ${
              item.mono ? "font-mono tabular-nums" : ""
            }`}
          >
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
