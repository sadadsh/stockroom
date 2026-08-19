import type { ReactNode } from "react";
import type { CaptureDownloadProgress } from "../../api/types";
import { Text, useText } from "../../lib/copy";
import { Icon } from "../Icon";

interface ProviderCaptureGuideProps {
  providerLabel: string;
  preparing?: boolean;
  ready?: boolean;
  requiredFiles?: string[];
  progress?: CaptureDownloadProgress | null;
  navigationError?: string;
  attachmentCount?: number;
  message?: string | null;
}

function joinRequirements(requiredFiles: string[]): string {
  if (requiredFiles.length <= 1) return requiredFiles[0] ?? "the required CAD files";
  if (requiredFiles.length === 2) return requiredFiles.join(" and ");
  return `${requiredFiles.slice(0, -1).join(", ")}, and ${requiredFiles[requiredFiles.length - 1]}`;
}

function downloadPercent(progress: CaptureDownloadProgress): number | null {
  const active = progress.files.find((file) => file.state === "in_progress");
  if (!active || active.total_bytes <= 0) return null;
  return Math.min(100, Math.round((active.bytes_received / active.total_bytes) * 100));
}

export function ProviderCaptureGuide({
  providerLabel,
  preparing = false,
  ready = false,
  requiredFiles = [],
  progress = null,
  navigationError = "",
  attachmentCount = 0,
  message = null,
}: ProviderCaptureGuideProps) {
  const progressLabel = useText("component-browser.capture-guide.progress-label", "Download progress");
  const interrupted = progress?.files.find((file) => file.state === "interrupted") ?? null;
  const active = progress?.files.find((file) => file.state === "in_progress") ?? null;
  const found = progress?.files.filter((file) => file.state === "completed").length ?? 0;
  const percent = progress ? downloadPercent(progress) : null;

  let iconId: "status.info" | "action.download" | "status.warn" | "detail.ready-check" = "status.info";
  let iconTone = "text-t3";
  let surfaceTone = "bg-band";
  let title: ReactNode;
  let detail: ReactNode;

  if (attachmentCount > 0) {
    iconId = "detail.ready-check";
    iconTone = "text-ok-text";
    surfaceTone = "bg-ok/10";
    title = <Text id="component-browser.capture-guide.attachments-ready">Files ready to attach</Text>;
    detail = (
      <Text id="component-browser.capture-guide.attachments-detail" values={{ count: attachmentCount }}>
        {"Review and commit {count} verified attachments."}
      </Text>
    );
  } else if (navigationError) {
    iconId = "status.warn";
    iconTone = "text-warn-text";
    surfaceTone = "bg-warn/10";
    title = <Text id="component-browser.capture-guide.navigation-error">Provider page could not load</Text>;
    detail = navigationError;
  } else if (interrupted) {
    iconId = "status.warn";
    iconTone = "text-warn-text";
    surfaceTone = "bg-warn/10";
    title = <Text id="component-browser.capture-guide.interrupted">Download interrupted</Text>;
    detail = (
      <Text id="component-browser.capture-guide.interrupted-detail" values={{ file: interrupted.name }}>
        {"Download {file} again from the provider page."}
      </Text>
    );
  } else if (active) {
    iconId = "action.download";
    iconTone = "text-acc";
    surfaceTone = "bg-acc/10";
    title = (
      <Text id="component-browser.capture-guide.receiving" values={{ file: active.name }}>
        {"Receiving {file}"}
      </Text>
    );
    detail = percent === null
      ? <Text id="component-browser.capture-guide.receiving-detail">Stockroom is saving this file.</Text>
      : <Text id="component-browser.capture-guide.receiving-percent" values={{ percent }}>{"{percent}%"}</Text>;
  } else if (found > 0) {
    iconId = "detail.ready-check";
    iconTone = "text-ok-text";
    surfaceTone = "bg-ok/10";
    title = found === 1
      ? <Text id="component-browser.capture-guide.found-one">1 file found</Text>
      : <Text id="component-browser.capture-guide.found-many" values={{ count: found }}>{"{count} files found"}</Text>;
    detail = (
      <Text id="component-browser.capture-guide.checking">Checking the files and preparing attachments.</Text>
    );
  } else if (message) {
    title = message;
    detail = null;
  } else if (preparing) {
    iconId = "action.download";
    iconTone = "text-acc";
    surfaceTone = "bg-acc/10";
    title = message ?? (
      <Text id="component-browser.capture-guide.opening" values={{ provider: providerLabel }}>
        {"Opening {provider}"}
      </Text>
    );
    detail = <Text id="component-browser.capture-guide.opening-detail">The provider page will appear here.</Text>;
  } else if (ready) {
    iconId = "action.download";
    iconTone = "text-acc";
    surfaceTone = "bg-acc/10";
    title = (
      <>
        <Text id="component-browser.capture-guide.download">Download</Text>{" "}
        {joinRequirements(requiredFiles)}
      </>
    );
    detail = <Text id="component-browser.capture-guide.automatic">Stockroom finds files in the background.</Text>;
  } else {
    title = message ?? <Text id="component-browser.capture-guide.choose">Choose a provider above</Text>;
    detail = <Text id="component-browser.capture-guide.choose-detail">Its page opens here. Download the files Stockroom asks for.</Text>;
  }

  return (
    <aside
      data-testid="provider-capture-guide"
      role="status"
      aria-live="polite"
      className={`flex min-h-[44px] flex-none items-center gap-2 border-b border-line px-3 ${surfaceTone}`}
    >
      <Icon id={iconId} className={`h-4 w-4 flex-none ${iconTone}`} />
      <p className="min-w-0 flex-1 truncate text-xs text-t1">
        <strong className="font-semibold">{title}</strong>
        {detail ? <span className="ml-2 text-t3">{detail}</span> : null}
      </p>
      {active && percent !== null ? (
        <progress
          aria-label={progressLabel}
          className="h-1.5 w-28 accent-accent"
          max={100}
          value={percent}
        />
      ) : null}
    </aside>
  );
}
