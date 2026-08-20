import { useRefreshSourcing } from "../api/queries";
import { Text, useCopyFormatter } from "../lib/copy";
import { Button } from "./primitives";

export function ExistingPartRecovery({
  partId,
  mpn,
  onOpen,
}: {
  partId: string;
  mpn: string;
  onOpen: (partId: string) => void;
}) {
  const refresh = useRefreshSourcing(partId);
  const alreadyExists = useCopyFormatter(
    "ingest.conflict-existing",
    "{mpn} exists in Components.",
  );

  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-control border border-warn/40 bg-warn/[0.08] px-3 py-2.5"
    >
      <span className="text-sm font-medium text-t1">{alreadyExists({ mpn })}</span>
      <span className="text-xs text-t3">
        <Text id="ingest.conflict-guidance">
          Open the existing component, or refresh its retained source evidence with intent.
        </Text>
      </span>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => onOpen(partId)}>
          <Text id="ingest.conflict-open">Open Component</Text>
        </Button>
        <Button
          onClick={() => void refresh.run()}
          disabled={refresh.status === "running"}
        >
          {refresh.status === "running" ? (
            <Text id="ingest.conflict-refreshing">Refreshing...</Text>
          ) : (
            <Text id="ingest.conflict-refresh">Refresh Evidence</Text>
          )}
        </Button>
      </div>
      <span aria-live="polite" className="text-xs text-t3">
        {refresh.status === "done" ? (
          <Text id="ingest.conflict-refreshed">Evidence refreshed.</Text>
        ) : refresh.status === "error" ? (
          refresh.error
        ) : null}
      </span>
    </div>
  );
}
