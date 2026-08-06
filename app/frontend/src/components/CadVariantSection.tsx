/**
 * Query and mutation boundary between DetailPanel and the pure CAD variant selector.
 */
import { CadVariantApiError } from "../api/cadVariantClient";
import {
  useActivateCadPair,
  useCadVariantInventory,
} from "../api/cadVariantQueries";
import { Text, useText } from "../lib/copy";
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
  const loadingMessage = useText(
    "cad.variant.loading",
    "Reading retained CAD variants...",
  );
  // A written sentence, not the query's own exception appended to a prefix. The retry beside it
  // is the thing a person can actually do about it.
  const readErrorMessage = useText(
    "cad.variant.read-error",
    "The retained CAD variants could not be read.",
  );
  const staleActivationMessage = useText(
    "cad.variant.activation-stale",
    "The active CAD pair changed before this switch completed. The latest choices are loading.",
  );
  const activationErrorMessage = useText(
    "cad.variant.activation-error",
    "The CAD pair could not be switched.",
  );

  if (!enabled) return null;
  if (inventory.isPending) {
    return <VariantState message={loadingMessage} />;
  }
  if (inventory.isError) {
    return (
      <VariantState
        message={readErrorMessage}
        tone="error"
        action={
          <Button type="button" small onClick={() => void inventory.refetch()}>
            <Text id="detail.cad-variants.retry">Rerun</Text>
          </Button>
        }
      />
    );
  }

  const activationError = pairActivation.isError
    ? pairActivation.error instanceof CadVariantApiError &&
      pairActivation.error.status === 409
      ? staleActivationMessage
      : activationErrorMessage
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
          <div className={EYEBROW_DENSE}>
            <Text id="cad.variant.state-title">CAD Variants</Text>
          </div>
          <p className={`mt-1 text-2xs ${tone === "error" ? "text-err-text" : "text-t2"}`}>
            {message}
          </p>
        </div>
        {action}
      </div>
    </Card>
  );
}
