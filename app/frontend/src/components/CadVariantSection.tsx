/**
 * Query and mutation boundary between DetailPanel and the pure CAD variant selector.
 */
import { CadVariantApiError } from "../api/cadVariantClient";
import {
  useActivateCadPair,
  useCadVariantInventory,
} from "../api/cadVariantQueries";
import { Text } from "../lib/copy";
import { Button, Card, EYEBROW_DENSE } from "./primitives";
import { CadVariantSelector } from "./CadVariantSelector";

export function CadVariantSection({
  partId,
  enabled,
}: {
  partId: string;
  enabled: boolean;
}) {
  const inventory = useCadVariantInventory(partId, enabled);
  const pairActivation = useActivateCadPair(partId);

  if (!enabled) return null;
  if (inventory.isPending) {
    return <VariantState message="Reading retained CAD variants..." />;
  }
  if (inventory.isError) {
    return (
      <VariantState
        message={`Could not read CAD variants. ${inventory.error.message}`}
        tone="error"
        action={
          <Button type="button" small onClick={() => void inventory.refetch()}>
            <Text id="detail.cad-variants.retry">Try Again</Text>
          </Button>
        }
      />
    );
  }

  const activationError = pairActivation.isError
    ? pairActivation.error instanceof CadVariantApiError &&
      pairActivation.error.status === 409
      ? "The active CAD pair changed before this switch completed. The latest choices are loading."
      : `Could not switch the CAD pair. ${pairActivation.error.message}`
    : null;

  return (
    <CadVariantSelector
      inventories={inventory.data?.inventories ?? []}
      pairs={inventory.data?.pairs ?? []}
      supplementary={inventory.data?.supplementary ?? []}
      activatingPair={
        pairActivation.isPending
          ? {
              kicadVariantId: pairActivation.variables.kicadVariantId,
              altiumVariantId: pairActivation.variables.altiumVariantId,
            }
          : null
      }
      activationError={activationError}
      onActivatePair={(selection) => pairActivation.mutate(selection)}
    />
  );
}

function VariantState({
  message,
  tone = "normal",
  action,
}: {
  message: string;
  tone?: "normal" | "error";
  action?: React.ReactNode;
}) {
  return (
    <Card role={tone === "error" ? "alert" : "status"} className="px-3 py-2.5">
      <div className="flex min-w-0 items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className={EYEBROW_DENSE}>CAD Variants</div>
          <p className={`mt-1 text-2xs ${tone === "error" ? "text-err" : "text-t2"}`}>
            {message}
          </p>
        </div>
        {action}
      </div>
    </Card>
  );
}
