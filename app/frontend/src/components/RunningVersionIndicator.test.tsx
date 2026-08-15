import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { UpdateCheck } from "../api/types";
import { deriveUpdateStanding } from "../lib/updateStanding";
import { RunningVersionIndicator } from "./RunningVersionIndicator";

// The indicator takes the DERIVED standing now (the clocks that bound it live in
// `useUpdateStanding`, not in a status readout), so each case states the same inputs it always
// did and hands the result over. A build version WITHOUT an embedded revision keeps these cases
// about the standing: a bundle that carries no revision cannot disagree with the backend, so the
// stale-frontend rule stays out of the way of everything else being asserted here.
const BUILD = "0.1.0";
function viewOf(data: UpdateCheck | undefined, checking = false, failed = false) {
  return deriveUpdateStanding({ data, checking, failed, buildVersion: BUILD });
}

describe("RunningVersionIndicator", () => {
  it("shows the running revision and Current only with remote proof", () => {
    render(
      <RunningVersionIndicator
        view={viewOf({
          update_available: false,
          state: "up_to_date",
          current_revision: "123456789abc",
          target_revision: "123456789abc",
        })}
        buildVersion={BUILD}
      />,
    );

    expect(
      screen.getByRole("status", {
        name: "running revision 1234567, Current",
      }),
    ).toBeInTheDocument();
  });

  it("shows both current and target revisions when an update is available", () => {
    render(
      <RunningVersionIndicator
        view={viewOf({
          update_available: true,
          state: "update_available",
          current_revision: "111111111111",
          target_revision: "222222222222",
        })}
        buildVersion={BUILD}
      />,
    );

    expect(
      screen.getByRole("status", {
        name: "running revision 1111111, Update Available, target revision 2222222",
      }),
    ).toHaveTextContent("r1111111→2222222Update Available");
  });

  it("shows a packaged release as its full version and Current", () => {
    render(
      <RunningVersionIndicator
        view={viewOf({
          update_available: false,
          state: "up_to_date",
          current_release_id: "release-1.2.3.4",
          target_release_id: "release-1.2.3.4",
          current_revision: "release-1.2.3.4",
          target_revision: "release-1.2.3.4",
        })}
        buildVersion={BUILD}
      />,
    );

    const status = screen.getByRole("status", {
      name: "running version 1.2.3.4, Current",
    });
    expect(status).toHaveTextContent("v1.2.3.4Current");
    expect(status).not.toHaveTextContent("release-");
  });

  it("uses the compiled version while checking and never guesses Current", () => {
    const { rerender } = render(
      <RunningVersionIndicator
        view={viewOf(undefined, true)}
        buildVersion="0.1.0+abcdef123"
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("abcdef1Checking…");
    expect(screen.queryByText("Current")).not.toBeInTheDocument();

    rerender(
      <RunningVersionIndicator
        view={viewOf({
          update_available: false,
          state: "offline",
          current_revision: "abcdef123456",
          detail: "offline",
        })}
        buildVersion={BUILD}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("abcdef1Rerunning…");
    expect(screen.queryByText("Current")).not.toBeInTheDocument();
  });

  it("names a frontend that never reloaded instead of reporting the backend's revision as running", () => {
    // C8: the bundle is what is EXECUTING. When the backend has moved on and this window has not,
    // showing the backend's revision beside "Current" is the app confidently reporting code it is
    // not running. Both identities are on screen, and the standing says which way to resolve it.
    const data = {
      update_available: false,
      state: "up_to_date",
      current_revision: "222222222222",
      target_revision: "222222222222",
    } as UpdateCheck;
    render(
      <RunningVersionIndicator
        view={deriveUpdateStanding({
          data,
          checking: false,
          failed: false,
          buildVersion: "0.1.0+1111111",
        })}
        buildVersion="0.1.0+1111111"
      />,
    );

    const status = screen.getByRole("status", {
      name: "running revision 1111111, Restart Required, backend revision 2222222",
    });
    expect(status).toHaveTextContent("r1111111→2222222Restart Required");
    expect(status).not.toHaveTextContent("Current");
  });

  it("gives a blocked convergence a tone of its own", () => {
    // C9: the dot's last two ternary arms both returned "neutral", so blocked rendered exactly
    // like a healthy adoption. Blocked is the app's err tone, the same one every other surface
    // spends on a state that needs a hand.
    const { container, rerender } = render(
      <RunningVersionIndicator
        view={viewOf({
          update_available: false,
          state: "failed",
          convergence_phase: "failed",
          current_revision: "111111111111",
          detail: "adoption did not complete",
        })}
        buildVersion={BUILD}
      />,
    );
    expect(container.querySelector(".bg-err")).not.toBeNull();
    expect(screen.getByText("Blocked")).toHaveClass("text-err-text");

    rerender(
      <RunningVersionIndicator
        view={viewOf({
          update_available: false,
          state: "offline",
          current_revision: "111111111111",
        })}
        buildVersion={BUILD}
      />,
    );
    // Retrying is not the same fact as blocked, and it is not the same fact as healthy either.
    expect(container.querySelector(".text-warn svg")).not.toBeNull();
    expect(container.querySelector(".bg-err")).toBeNull();
  });
});
