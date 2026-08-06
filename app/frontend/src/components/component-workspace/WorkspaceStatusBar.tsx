/**
 * The opened component's own status bar: what is happening to THIS component, right now.
 *
 * It is deliberately not a second copy of the application status bar at the bottom of the window.
 * That one is about the library and the build; this one is about the part on screen - whether an
 * action is in flight, how much of its specification is settled, and when its sourcing was last
 * read. No counts are repeated between the two, and no commit hash appears in either.
 */
import type { ComponentDossier } from "../../api/dossierTypes";
import { Text } from "../../lib/copy";
import { formatCount, formatTimestamp } from "../../lib/formatValue";
import { StatusText } from "../primitives";
import { conflictCount, missingCount, DOT } from "./componentIdentity";
import { totalSpecifications } from "./specificationRows";
import { latestCheck } from "./offerFacts";

/** What the bar is saying about work in flight. Exactly one of these is true at a time. */
export type WorkspaceActivity = "idle" | "refreshing" | "saving" | "deleting";

export function WorkspaceStatusBar({
  dossier,
  activity,
}: {
  dossier: ComponentDossier;
  activity: WorkspaceActivity;
}) {
  const total = totalSpecifications(dossier.specificationGroups, dossier.keySpecifications);
  const missing = missingCount(dossier);
  const conflicts = conflictCount(dossier);
  const checked = latestCheck(dossier.distributorOffers);
  const stamp = checked ? formatTimestamp(checked) : null;

  return (
    <footer
      data-dev-id="component-browser.status-bar"
      className="flex h-[22px] flex-none items-center gap-2 border-t border-line bg-band px-2"
    >
      <StatusText tone={activity === "idle" ? "neutral" : "warn"} className="flex-none">
        {activity === "refreshing" ? (
          <Text id="component-browser.status-refreshing">Refreshing sourcing</Text>
        ) : activity === "saving" ? (
          <Text id="component-browser.status-saving">Saving specification</Text>
        ) : activity === "deleting" ? (
          <Text id="component-browser.status-deleting">Deleting component</Text>
        ) : (
          <Text id="component-browser.status-ready">Idle</Text>
        )}
      </StatusText>
      {total > 0 ? (
        <span className="ui-component-metadata flex-none">
          <Text
            id="component-browser.status-specs"
            values={{ count: formatCount(total) }}
          >
            {"{count} specifications"}
          </Text>
        </span>
      ) : null}
      {missing > 0 ? (
        <span className="ui-component-metadata flex-none text-warn">
          <Text id="component-browser.status-missing" values={{ count: missing }}>
            {"{count} missing"}
          </Text>
        </span>
      ) : null}
      {conflicts > 0 ? (
        <span className="ui-component-metadata flex-none text-err-text">
          <Text id="component-browser.status-conflicts" values={{ count: conflicts }}>
            {"{count} conflicting"}
          </Text>
        </span>
      ) : null}
      {stamp ? (
        <span className="ui-component-metadata ml-auto flex-none" title={stamp.title}>
          {`${DOT} `}
          <Text id="component-browser.status-checked" values={{ when: stamp.text }}>
            {"Sourcing read {when}"}
          </Text>
        </span>
      ) : null}
    </footer>
  );
}
