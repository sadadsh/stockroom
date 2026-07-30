import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RunningVersionIndicator } from "./RunningVersionIndicator";

describe("RunningVersionIndicator", () => {
  it("shows the running revision and Current only with remote proof", () => {
    render(
      <RunningVersionIndicator
        data={
          {
            update_available: false,
            state: "up_to_date",
            current_revision: "123456789abc",
            target_revision: "123456789abc",
          } as never
        }
        checking={false}
        failed={false}
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
        data={
          {
            update_available: true,
            state: "update_available",
            current_revision: "111111111111",
            target_revision: "222222222222",
          } as never
        }
        checking={false}
        failed={false}
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
        data={{
          update_available: false,
          state: "up_to_date",
          current_release_id: "release-1.2.3.4",
          target_release_id: "release-1.2.3.4",
          current_revision: "release-1.2.3.4",
          target_revision: "release-1.2.3.4",
        }}
        checking={false}
        failed={false}
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
        data={undefined}
        checking
        failed={false}
        buildVersion="0.1.0+abcdef123"
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("abcdef1Checking…");
    expect(screen.queryByText("Current")).not.toBeInTheDocument();

    rerender(
      <RunningVersionIndicator
        data={{
          update_available: false,
          state: "offline",
          current_revision: "abcdef123456",
          detail: "offline",
        }}
        checking={false}
        failed={false}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("abcdef1Retrying…");
    expect(screen.queryByText("Current")).not.toBeInTheDocument();
  });
});
